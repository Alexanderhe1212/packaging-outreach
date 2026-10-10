"""邮箱空间：用量报告 + 本地存档。服务器上超过 N 天的邮件先完整保存到本地（.eml，含图片和附件），
核对文件写好之后才从服务器删除，释放空间。只有用户在设置里开启后才会执行删除；dry_run 只统计。

存档位置：<数据目录>/accounts/<账号>/archive/<文件夹>/<年-月>/<日期>_<对方>_<主题>.eml
"""
import base64
import email.policy
import re
import time
from datetime import datetime, timedelta
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime

from . import config, store

KINDS = {  # folder role -> IMAP special-use flag + common names (Tencent Exmail, Gmail, Outlook, Aliyun, NetEase)
    'sent': ('\\Sent', ('sent messages', 'sent', 'sent items', '已发送', '已发邮件', '[gmail]/sent mail')),
    'trash': ('\\Trash', ('deleted messages', 'trash', 'deleted items', '已删除', '[gmail]/trash')),
    'junk': ('\\Junk', ('junk', 'spam', '垃圾邮件', '垃圾箱', 'junk e-mail', '[gmail]/spam')),
    'inbox': (None, ('inbox',)),
}


def utf7_decode(name):
    """IMAP modified UTF-7 (RFC 3501) -> str, e.g. '&XfJT0ZAB-' -> '已发送'."""
    def dec(m):
        s = m.group(1)
        if not s:
            return '&'
        s = s.replace(',', '/')
        return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-16-be')
    return re.sub(r'&([^-]*)-', dec, name)


def list_folders(c):
    out = []
    typ, data = c.list()
    for line in data or []:
        if not isinstance(line, bytes):
            continue
        m = re.match(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', line)
        if not m:
            continue
        raw = m.group('name').decode('utf-8', 'replace').strip()
        raw = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
        out.append({'raw': raw, 'name': utf7_decode(raw), 'flags': m.group('flags').decode().lower()})
    return out


def role(folder):
    for kind, (flag, names) in KINDS.items():
        if (flag and flag.lower() in folder['flags']) or folder['name'].lower() in names:
            return kind
    return ''


def _q(raw):
    return '"%s"' % raw.replace('\\', '\\\\').replace('"', '\\"')


def report(acc):
    """Quota and per-folder message counts / sizes (read-only)."""
    from .mailer import imap_connect
    c = imap_connect(acc, timeout=180)
    try:
        used = limit = None
        try:
            if 'QUOTA' not in c.capabilities:  # e.g. Tencent Exmail: the command hangs instead of failing
                raise LookupError('no quota support')
            typ, data = c.getquotaroot('INBOX')
            m = re.search(rb'STORAGE (\d+) (\d+)', b' '.join(x if isinstance(x, bytes) else b' '.join(x) for x in data[1] or []))
            if m:
                used, limit = int(m.group(1)) * 1024, int(m.group(2)) * 1024
        except Exception:
            pass
        folders = []
        for f in list_folders(c):
            if '\\noselect' in f['flags']:
                continue
            try:
                typ, data = c.select(_q(f['raw']), readonly=True)
                n = int(data[0]) if typ == 'OK' and data and data[0] else 0
                size = 0
                for start in range(1, n + 1, 2000):  # sizes in batches: big folders stay responsive
                    typ, sizes = c.fetch('%d:%d' % (start, min(n, start + 1999)), '(RFC822.SIZE)')
                    size += sum(int(x) for x in re.findall(rb'RFC822\.SIZE (\d+)', b' '.join(s if isinstance(s, bytes) else s[0] for s in sizes or [])))
                folders.append({'name': f['name'], 'role': role(f), 'messages': n, 'bytes': size})
            except Exception:
                continue
        if used is None:
            used = sum(f['bytes'] for f in folders)
        if not limit and acc.get('mailbox_limit_gb'):
            limit = int(float(acc['mailbox_limit_gb']) * 1073741824)
        r = {'used': used, 'limit': limit, 'folders': sorted(folders, key=lambda x: -x['bytes']), 'at': time.time()}
        store.put('mailbox_' + acc['id'], r)
        return r
    finally:
        try:
            c.logout()
        except Exception:
            pass


def _safe(s, n=40):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', s or '').strip()
    return re.sub(r'\s+', '_', s)[:n] or 'no-subject'


def archive_dir(acc_id):
    d = config.data_dir() / 'accounts' / acc_id / 'archive'
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_raw(acc, folder_name, raw):
    msg = BytesParser(policy=email.policy.default).parsebytes(raw, headersonly=True)
    try:
        when = parsedate_to_datetime(str(msg.get('Date')))
    except Exception:
        when = datetime.now()
    peer = parseaddr(str(msg.get('To' if 'sent' in folder_name.lower() or '发' in folder_name else 'From', '')))[1] or 'unknown'
    folder = archive_dir(acc['id']) / _safe(folder_name, 30) / when.strftime('%Y-%m')
    folder.mkdir(parents=True, exist_ok=True)
    base = '%s_%s_%s' % (when.strftime('%Y%m%d-%H%M'), _safe(peer, 40), _safe(str(msg.get('Subject', '')), 50))
    path = folder / (base + '.eml')
    n = 1
    while path.exists():
        if path.stat().st_size == len(raw):
            return path  # already archived earlier
        n += 1
        path = folder / ('%s_%d.eml' % (base, n))
    path.write_bytes(raw)
    if path.stat().st_size != len(raw):
        raise IOError('archive write incomplete: %s' % path)
    return path


def run(acc, days=None, kinds=None, limit=300, dry_run=False):
    """Archive messages older than `days` from the chosen folder roles, then delete them on the server (unless dry_run)."""
    from .mailer import imap_connect
    cfg = acc.get('mail_archive') or {}
    days = int(days if days is not None else cfg.get('days', 7))
    kinds = kinds or cfg.get('folders') or ['sent', 'trash']
    before = (datetime.now() - timedelta(days=days)).strftime('%d-%b-%Y')
    c = imap_connect(acc, timeout=180)
    out = {'days': days, 'dry_run': dry_run, 'folders': [], 'archived': 0, 'bytes': 0}
    try:
        for f in list_folders(c):
            if role(f) not in kinds or '\\noselect' in f['flags']:
                continue
            typ, _ = c.select(_q(f['raw']), readonly=dry_run)
            if typ != 'OK':
                continue
            typ, data = c.uid('search', None, 'BEFORE', before)
            uids = (data[0].split() if typ == 'OK' and data and data[0] else [])[:limit]
            done, size = [], 0
            for uid in uids:
                if dry_run:
                    typ, d = c.uid('fetch', uid, '(RFC822.SIZE)')
                    m = re.search(rb'RFC822\.SIZE (\d+)', b' '.join(x if isinstance(x, bytes) else x[0] for x in d or []))
                    size += int(m.group(1)) if m else 0
                    done.append(uid)
                    continue
                typ, d = c.uid('fetch', uid, '(BODY.PEEK[])')
                raw = next((x[1] for x in d or [] if isinstance(x, tuple)), None)
                if not raw:
                    continue
                save_raw(acc, f['name'], raw)  # raises if the local copy is not complete -> nothing deleted
                done.append(uid)
                size += len(raw)
            if done and not dry_run:
                for i in range(0, len(done), 100):
                    c.uid('store', b','.join(done[i:i + 100]).decode(), '+FLAGS', '(\\Deleted)')
                c.expunge()
            out['folders'].append({'name': f['name'], 'role': role(f), 'messages': len(done), 'bytes': size})
            out['archived'] += len(done)
            out['bytes'] += size
        if not dry_run:
            store.put('archive_last_' + acc['id'], {'at': time.time(), **out})
        return out
    finally:
        try:
            c.logout()
        except Exception:
            pass


def due(acc):
    """Scheduled run: once a day when the user enabled it for this account."""
    cfg = acc.get('mail_archive') or {}
    if not cfg.get('enabled'):
        return False
    last = (store.get('archive_last_' + acc['id']) or {}).get('at', 0)
    return time.time() - last > 23 * 3600

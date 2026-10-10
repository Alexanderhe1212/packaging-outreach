"""邮件：组装（正文 → A/B 图 → WhatsApp 链接 → 签名 → 退订）、SMTP 发送、IMAP 识别回复/退订/退信、同线程跟进。"""
import base64
import email.policy
import html
import imaplib
import re
import smtplib
import ssl
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate, parseaddr
from urllib.parse import urlencode

from . import config, store

OPT_OUT = "Not relevant? Just reply \"no thanks\" and I won't email again."


class MailAuthError(RuntimeError):
    pass


def password(acc):
    pw = config.secrets()['passwords'].get(acc['id'])
    if pw:
        return pw
    svc = acc.get('keychain_service')
    if svc:  # reuse the Keychain item created by the old app (macOS asks once; choose "Always Allow")
        try:
            r = subprocess.run(['security', 'find-generic-password', '-s', svc, '-a', acc['sender'], '-w'],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    raise MailAuthError('没有邮箱密码/授权码：在 设置 → 账号 填写 %s 的授权码' % acc['sender'])


def smtp_connect(acc):
    host, port = acc['smtp']['host'], int(acc['smtp'].get('port', 465))
    ctx = ssl.create_default_context()
    if port == 465:
        c = smtplib.SMTP_SSL(host, port, timeout=60, context=ctx)
    else:
        c = smtplib.SMTP(host, port, timeout=60)
        c.starttls(context=ctx)
    try:
        c.login(acc.get('login') or acc['sender'], password(acc))
    except smtplib.SMTPAuthenticationError:
        raise MailAuthError('邮箱登录失败：授权码错误或已失效（%s）' % acc['sender'])
    return c


def imap_connect(acc):
    c = imaplib.IMAP4_SSL(acc['imap']['host'], int(acc['imap'].get('port', 993)), ssl_context=ssl.create_default_context(),
                          timeout=30)
    try:
        c.login(acc.get('login') or acc['sender'], password(acc))
    except imaplib.IMAP4.error:
        raise MailAuthError('收件箱登录失败：授权码错误或未开启 IMAP（%s）' % acc['sender'])
    return c


def test_login(acc):
    s = smtp_connect(acc)
    s.quit()
    i = imap_connect(acc)
    i.logout()
    return acc['sender'] + ' 发信和收信登录都正常'


# ---------------- signature ----------------
def signature_text(acc):
    return (acc.get('signature') or '%s\n%s\n%s' % (acc.get('contact_name', ''), acc.get('company_name', ''), acc['sender'])).strip()


_sig_cache = {}


def signature_image(acc):
    path = acc.get('signature_image')
    if not path:
        return None
    if path not in _sig_cache:
        try:
            from .pipeline import to_jpeg
            _sig_cache[path] = to_jpeg(config.resolve(path).read_bytes(), 1200, 88)
        except Exception:
            _sig_cache[path] = None
    return _sig_cache[path]


def wa_link(acc, company, option=None):
    text = "Hi %s, I'd like to discuss %s for %s." % (acc.get('contact_name', ''), ('concept ' + option) if option else 'your ideas', company)
    return 'https://wa.me/%s?%s' % (re.sub(r'\D', '', acc.get('whatsapp', '')), urlencode({'text': text}))


# ---------------- build ----------------
def _base_msg(acc, to, subject, message_id=None):
    msg = EmailMessage(policy=email.policy.SMTP)
    msg['From'] = formataddr((acc.get('from_name') or acc.get('company_name') or acc['sender'], acc['sender']))
    msg['To'] = to
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = message_id or '<%s@%s>' % (uuid.uuid4(), acc['sender'].split('@')[1])
    msg['List-Unsubscribe'] = '<mailto:%s?subject=unsubscribe>' % acc['sender']
    return msg


def build(acc, lead, image_bytes):
    company = lead['data'].get('prospect', {}).get('customer_brand') or lead['company']
    body, sig, sig_img = lead['body'], signature_text(acc), signature_image(acc)
    opt_out = '' if 'no thanks' in sig.lower() else OPT_OUT
    has_wa = bool(acc.get('whatsapp'))
    links = [('A', wa_link(acc, company, 'A')), ('B', wa_link(acc, company, 'B'))] if has_wa else []
    E = html.escape
    paras = ''.join('<p style="margin:0 0 14px">%s</p>' % E(x).replace('\n', '<br>') for x in body.split('\n\n'))
    parts = ['<div style="max-width:620px;font:15px/1.6 -apple-system,Segoe UI,Arial,sans-serif;color:#222">', paras]
    if image_bytes:
        parts.append('<img src="cid:concept" width="620" alt="Concepts A and B for %s" '
                     'style="display:block;width:100%%;max-width:620px;height:auto;border-radius:6px;margin:6px 0 14px">' % E(company))
        if links:
            parts.append('<p style="margin:0 0 16px">' + ' &nbsp;·&nbsp; '.join(
                '<a href="%s" style="color:#1f8a70;font-weight:600;text-decoration:none">Discuss concept %s on WhatsApp &rarr;</a>'
                % (E(u, quote=True), k) for k, u in links) + '</p>')
    parts.append('<p style="margin:0 0 6px">Best regards,</p>')
    parts.append('<p style="margin:0 0 10px;color:#444;font-size:14px">%s</p>' % E(sig).replace('\n', '<br>'))
    if sig_img:
        parts.append('<img src="cid:signature" width="560" alt="%s" style="display:block;width:100%%;max-width:560px;height:auto">'
                     % E(acc.get('company_name', '')))
    if opt_out:
        parts.append('<p style="margin:14px 0 0;color:#999;font-size:12px">%s</p>' % E(opt_out))
    parts.append('</div>')
    markup = '<!doctype html><html><head><meta charset="utf-8"></head><body>%s</body></html>' % ''.join(parts)
    plain = body + '\n\n'
    if image_bytes and links:
        plain += '\n'.join('Discuss concept %s on WhatsApp: %s' % (k, u) for k, u in links) + '\n\n'
    plain += 'Best regards,\n' + sig + ('\n\n' + opt_out if opt_out else '')

    msg = _base_msg(acc, lead['email'], lead['subject'], lead.get('message_id') or None)
    msg.set_content(plain)
    msg.add_alternative(markup, subtype='html')
    htmlpart = msg.get_payload()[1]
    if image_bytes:
        htmlpart.add_related(image_bytes, maintype='image', subtype='jpeg' if image_bytes[:2] == b'\xff\xd8' else 'png',
                             cid='<concept>', filename='concepts.jpg')
    if sig_img:
        htmlpart.add_related(sig_img, maintype='image', subtype='jpeg', cid='<signature>', filename='signature.jpg')
    return msg


def build_followup(acc, lead, profile):
    p = lead['data'].get('prospect', {})
    tpl = profile.get('followup', {}).get('body') or 'Hi {brand} team,\n\nJust following up on the two ideas for {product}. Would A or B be worth a quote?'
    body = tpl.format(brand=p.get('customer_brand') or lead['company'], product=p.get('product_name') or 'your product',
                      contact=acc.get('contact_name', ''))
    subject = lead['subject'] if lead['subject'].lower().startswith('re:') else 'Re: ' + lead['subject']
    msg = _base_msg(acc, lead['email'], subject)
    msg['In-Reply-To'] = lead['message_id']
    msg['References'] = lead['message_id']
    msg.set_content(body + '\n\nBest regards,\n' + signature_text(acc))
    return msg


def preview_html(acc, lead, image_bytes):
    msg = build(acc, lead, image_bytes)
    markup = msg.get_payload()[1].get_payload()[0].get_content()
    if image_bytes:
        markup = markup.replace('cid:concept', 'data:image/jpeg;base64,' + base64.b64encode(image_bytes).decode())
    sig = signature_image(acc)
    if sig:
        markup = markup.replace('cid:signature', 'data:image/jpeg;base64,' + base64.b64encode(sig).decode())
    head = ('<div style="font:13px -apple-system,Arial;color:#666;border-bottom:1px solid #eee;padding:0 0 10px;margin:0 0 14px">'
            '<b>From:</b> %s<br><b>To:</b> %s<br><b>Subject:</b> %s</div>') % (
        html.escape(str(msg['From'])), html.escape(lead['email']), html.escape(lead['subject']))
    return markup.replace('<body>', '<body style="margin:16px;background:#fff">' + head, 1)


# ---------------- send ----------------
def send(acc, msg):
    """Returns (result, note); result is 'sent' | 'bounced' | 'unknown' | 'retry'. Never resends once DATA has started."""
    rcpt = parseaddr(str(msg['To']))[1]
    stage, client = 'connect', None
    try:
        client = smtp_connect(acc)
        stage = 'mail'
        client.mail(acc['sender'])
        code, resp = client.rcpt(rcpt)
        if code >= 500:
            return 'bounced', 'RCPT %s %s' % (code, resp[:120])
        if code >= 400:
            return 'retry', 'RCPT %s' % code
        stage = 'data'
        code, resp = client.data(msg.as_bytes())
        if code == 250:
            return 'sent', ''
        return ('bounced' if code >= 500 else 'unknown'), 'DATA %s' % code
    except MailAuthError:
        raise
    except Exception as e:
        return ('unknown' if stage == 'data' else 'retry'), '%s at %s' % (type(e).__name__, stage)
    finally:
        if client:
            try:
                client.quit()
            except Exception:
                pass


def save_eml(name, msg, account=''):
    d = config.data_dir() / 'accounts' / account / 'sent' if account else config.data_dir() / 'sent'
    d.mkdir(parents=True, exist_ok=True)
    (d / ('%s.eml' % name)).write_bytes(msg.as_bytes())


# ---------------- inbox ----------------
STOP_WORDS = ('unsubscribe', 'no thanks', 'no thank you', 'not interested', 'remove me', 'stop emailing', 'do not contact',
              "don't contact", 'take me off', 'not relevant', 'please stop', 'kein interesse', 'pas intéressé',
              '退订', '不需要', '不感兴趣')
BOUNCE_FROM = re.compile(r'(?i)mailer-daemon|postmaster|mail delivery')
BOUNCE_SUBJ = re.compile(r'(?i)undeliver|delivery status|delivery fail|returned mail|failure notice|退信|无法投递')
AUTO_SUBJ = re.compile(r'(?i)automatic reply|auto.?reply|out of (the )?office|自动回复|abwesenheit|absence|réponse automatique')


def fresh_text(msg):
    texts = []
    for part in msg.walk():
        if part.get_content_type() == 'text/plain':
            try:
                texts.append(part.get_content())
            except Exception:
                pass
    if not texts:
        for part in msg.walk():
            if part.get_content_type() == 'text/html':
                try:
                    texts.append(re.sub(r'<[^>]+>', ' ', part.get_content()))
                except Exception:
                    pass
    fresh = []
    for line in '\n'.join(texts).splitlines():
        if re.match(r'(?i)^\s*(on .+wrote:|from:|发件人[:：]|-+ ?original message|在 .+写道|am .+schrieb)', line):
            break
        if not line.lstrip().startswith('>'):
            fresh.append(line)
    return '\n'.join(fresh).strip()


def sync_inbox(acc):
    """Mark replies / opt-outs / bounces for this account's sent leads. Read-only (BODY.PEEK, readonly select)."""
    aid = acc['id']
    sent = {r['email']: r['id'] for r in store.q(
        "SELECT id,email FROM leads WHERE account=? AND status IN ('sent','unknown','replied')", (aid,))}
    if not sent:
        return {'checked': 0}
    c = imap_connect(acc)
    found = 0
    try:
        c.select('INBOX', readonly=True)
        last = int(store.get('imap_uid_' + aid, 0) or 0)
        if last:
            typ, data = c.uid('search', None, 'UID', '%d:*' % (last + 1))
        else:  # first sync: only mail that arrived after this app's first send
            first = store.q('SELECT min(sent_at) t FROM leads WHERE account=? AND sent_at IS NOT NULL', (aid,), one=True)['t'] or time.time()
            typ, data = c.uid('search', None, 'SINCE', (datetime.fromtimestamp(first) - timedelta(days=1)).strftime('%d-%b-%Y'))
        uids = [int(u) for u in (data[0].split() if typ == 'OK' and data and data[0] else []) if int(u) > last][-500:]
        wanted = []
        for i in range(0, len(uids), 100):  # headers only, 100 at a time; bodies only for replies and bounces
            typ, parts = c.uid('fetch', ','.join(map(str, uids[i:i + 100])), '(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')
            for part in parts or []:
                if not isinstance(part, tuple):
                    continue
                m = re.search(rb'UID (\d+)', part[0])
                head = BytesParser(policy=email.policy.default).parsebytes(part[1])
                frm, subj = str(head.get('From', '')), str(head.get('Subject', ''))
                if m and (parseaddr(frm)[1].lower() in sent or BOUNCE_FROM.search(frm) or BOUNCE_SUBJ.search(subj)):
                    wanted.append(int(m.group(1)))
        for uid in wanted:
            typ, parts = c.uid('fetch', str(uid), '(BODY.PEEK[]<0.200000>)')
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = BytesParser(policy=email.policy.default).parsebytes(raw)
            sender = parseaddr(str(msg.get('From', '')))[1].lower()
            subject = str(msg.get('Subject', ''))
            if BOUNCE_FROM.search(str(msg.get('From', ''))) or BOUNCE_SUBJ.search(subject):
                body = raw.decode('utf-8', 'replace').lower()
                for addr, lid in sent.items():
                    if addr in body:
                        store.update(lid, status='bounced', error='退信: ' + subject[:120])
                        store.suppress(addr, 'bounce', aid, subject[:120])
                        found += 1
                continue
            if sender not in sent or AUTO_SUBJ.search(subject) or str(msg.get('Auto-Submitted', 'no')).lower() not in ('no', ''):
                continue
            text = fresh_text(msg)
            lid = sent[sender]
            if any(w in text.lower()[:600] for w in STOP_WORDS):
                store.update(lid, status='unsubscribed', reply_at=time.time(), reply_excerpt=text[:2000])
                store.suppress(sender, 'unsubscribe', aid, 'reply')
            else:
                store.update(lid, status='replied', reply_at=time.time(), reply_excerpt=text[:2000])
                store.suppress(sender, 'reply', aid, 'conversation')
            found += 1
        if uids:
            store.put('imap_uid_' + aid, max(uids))
        return {'checked': len(uids), 'events': found}
    finally:
        try:
            c.logout()
        except Exception:
            pass

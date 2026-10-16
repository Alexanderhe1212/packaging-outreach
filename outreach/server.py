"""本机 HTTP 服务：界面 + JSON API（同一套 API 也给 CLI、Skill 和其他 Agent 调用）。只监听 127.0.0.1。"""
import base64
import json
import os
import sys
import threading
import time
import uuid
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import VERSION, archive, config, legacy, llm, mailer, pipeline, store, updater, web
from .worker import AccountWorker

WORKERS = {}
UI = config.ROOT / 'ui' / 'index.html'


def sync_workers():
    ids = [a['id'] for a in config.load()['accounts']]
    for aid in ids:
        if aid not in WORKERS or not WORKERS[aid].is_alive():
            WORKERS[aid] = AccountWorker(aid)
            WORKERS[aid].start()
    for aid in list(WORKERS):
        if aid not in ids:
            WORKERS.pop(aid).stopped = True


def worker(aid):
    if aid not in WORKERS:
        raise KeyError('账号不存在：%s' % aid)
    return WORKERS[aid]


# ---------------- GET ----------------
def legacy_running(ports):
    import socket
    alive = []
    for port in ports:
        with socket.socket() as sock:
            sock.settimeout(0.15)
            if sock.connect_ex(('127.0.0.1', int(port))) == 0:
                alive.append(port)
    return alive


def api_state(_q):
    cfg = config.load()
    sec = config.secrets()
    accounts = []
    for a in cfg['accounts']:
        w = WORKERS.get(a['id'])
        accounts.append(dict(id=a['id'], name=a.get('name') or a['id'], sender=a['sender'], profile=a.get('profile', 'packaging'),
                             paused=w.paused if w else True, activity=w.activity if w else '', error=w.error if w else '',
                             stats=store.stats(a['id']), auto_send=a.get('auto_send', True), daily_limit=int(a.get('daily_limit') or 0),
                             color=a.get('color', ''), mailbox=store.get('mailbox_' + a['id']),
                             archive=store.get('archive_last_' + a['id'])))
    conns = cfg['connections']
    ready = all(sec['keys'].get(s.get('connection')) or conns.get(s.get('connection'), {}).get('preset') == 'codex'
                for s in cfg['stages'].values())
    return dict(version=VERSION, accounts=accounts, api_ready=ready, daily_limit_total=int(cfg.get('daily_limit_total') or 0), legacy=store.get('legacy_imported'),
                data_dir=str(config.data_dir()), legacy_running=legacy_running(cfg.get('legacy', {}).get('ports', [])))


def api_leads(qs):
    g = lambda k, d='': qs.get(k, [d])[0]
    return store.list_leads(g('account') or None, g('status') or None, int(g('limit', '100')), int(g('offset', '0')), g('q'))


def api_lead(lid):
    lead = store.lead(int(lid))
    if not lead:
        raise KeyError('not found')
    lead['has_image'] = bool(lead.get('image') and Path(lead['image']).exists())
    lead.pop('image', None)
    lead['usage'] = store.q('SELECT stage,model,input,output,cached,images,searches,cost FROM usage WHERE lead=?', (lead['id'],))
    return lead


def api_settings_get(_q):
    cfg = config.load()
    sec = config.secrets()
    return dict(connections=cfg['connections'], stages=cfg['stages'], accounts=cfg['accounts'],
                api_presets=cfg['api_presets'], mail_presets=cfg['mail_presets'], inbox_check_minutes=cfg.get('inbox_check_minutes', 10),
                daily_limit_total=int(cfg.get('daily_limit_total') or 0), cross_account_dedupe=True,
                has_key={k: bool(sec['keys'].get(k)) for k in cfg['connections']},
                has_password={a['id']: bool(sec['passwords'].get(a['id'])) or bool(a.get('keychain_service')) for a in cfg['accounts']},
                profiles=config.profiles(), version=VERSION)


# ---------------- POST ----------------
def control(data, paused):
    for aid in ([data['account']] if data.get('account') else list(WORKERS)):
        worker(aid).set_paused(paused)
        store.audit('account_paused' if paused else 'account_started',aid,origin=data.get('_origin'),result='paused' if paused else 'running')
    return {'ok': True}


def api_add(data):
    aid = data['account']
    config.account(aid)
    urls = [u.strip() for u in str(data.get('urls') or data.get('url') or '').replace(',', '\n').splitlines() if u.strip()]
    if not urls:
        raise ValueError('请填写客户官网')
    ids, skipped = [], []
    for u in urls:
        email = (data.get('email') or '').strip().lower() if len(urls) == 1 else ''
        if '@' in u and '.' in u and ' ' not in u and '/' not in u:  # a bare email: website = its domain
            email, u = u.lower(), u.split('@')[1]
        dom = web.host(u)
        if store.blocked(email, dom, aid) and not data.get('force'):
            skipped.append(dom)
            continue
        lid=store.claim_prospect(aid,dict(company=dom,domain=dom,email=email),source='manual',
                                 manual={'url':u if '//' in u else 'https://'+u,'email':email})
        if lid: ids.append(lid)
        else: skipped.append(dom)
    worker(aid).wake.set()
    return {'ids': ids, 'skipped': skipped}


def api_send(data):
    lead = store.lead(int(data['id']))
    result = worker(lead['account']).send(lead, manual=True, origin=data.get('_origin',{'source':'api_internal'}))
    messages={'changed':'草稿已更新，请重新审核','interval':'发送间隔尚未到，请稍后审核发送','paused':'账号已暂停','daily_limit':'今日发送额度已满',
              'total_limit':'今日总发送额度已满','not_ready':'当前状态不可发送','duplicate':'重复公司或邮箱，已阻止',
              'suppressed':'已退订、退信或回复，已阻止','claimed':'另一条记录已认领此客户','sending':'该账号有发送事务进行中',
              'cooldown':'最近联系未满7天','reply_context_required':'客户已回复，需先核实对话','customer_paused':'客户已暂停联系','future_contact':'尚未到约定联系时间','unknown':'历史发送结果待核实','outside_hours':'当前不在发送时段','already_contacted':'已联系，禁止重复发送','account_mismatch':'账号不匹配'}
    if result not in ('sent','unknown','bounced','retry','blocked'):
        raise ValueError(messages.get(result,result))
    return {'result': result, 'lead': api_lead(lead['id'])}


def record_mutation(fn):
    @wraps(fn)
    def wrapped(data):
        with store._lock:
            return fn(data)
    return wrapped


@record_mutation
def api_skip(data):
    lid=int(data['id'])
    if store.lead(lid)['status'] in ('sending','sent','unknown','replied','bounced','unsubscribed','writing','researching','imaging'):
        raise ValueError('已发送或待核实记录不可跳过')
    store.update(lid, status='skipped')
    return {'ok': True}


@record_mutation
def api_edit(data):
    lead = store.lead(int(data['id']))
    if lead['status'] in ('sent', 'sending', 'unknown', 'replied', 'bounced', 'unsubscribed'):
        raise ValueError('已发送的邮件不能修改')
    store.update(lead['id'], subject=data.get('subject', lead['subject']).strip(), body=data.get('body', lead['body']).strip())
    return api_lead(lead['id'])


@record_mutation
def api_redo(data):
    lead = store.lead(int(data['id']))
    if lead['status'] in ('sent', 'sending', 'unknown', 'bounced', 'unsubscribed', 'replied', 'imaging', 'writing', 'researching'):
        raise ValueError('当前状态不能重做')
    d = lead['data']
    d.pop('image_prompt', None)
    if data.get('what') != 'image':
        d.pop('plan', None)
    store.update(lead['id'], status='queued', data=d, error='', image='')
    worker(lead['account']).wake.set()
    return {'ok': True}


def api_settings_post(data):
    patch = {k: data[k] for k in ('connections', 'stages', 'inbox_check_minutes', 'daily_limit_total', 'cross_account_dedupe') if k in data}
    if 'accounts' in data:
        seen = set()
        for a in data['accounts']:
            a['id'] = ''.join(ch for ch in (a.get('id') or a.get('name') or 'acc') if ch.isalnum() or ch in '-_')[:24] or 'acc'
            if a['id'] in seen:
                raise ValueError('账号代号重复：' + a['id'])
            seen.add(a['id'])
        patch['accounts'] = data['accounts']
    patch['cross_account_dedupe']=True
    if patch:
        config.save(patch)
    config.save_secrets(keys=data.get('keys'), passwords=data.get('passwords'))
    sync_workers()
    for w in WORKERS.values():
        w.wake.set()
    return api_settings_get(None)


def api_profile(data):
    p = data['profile']
    if not p.get('id'):
        raise ValueError('方案需要 id')
    config.save_profile(p)
    return {'profiles': config.profiles()}


def api_signature(data):
    aid = data['account']
    raw = base64.b64decode(data['data'].split(',', 1)[-1])
    if not web.is_image(raw):
        raise ValueError('请上传 PNG / JPG 图片')
    path = config.data_dir() / ('signature-%s.jpg' % aid)
    path.write_bytes(pipeline.to_jpeg(raw, 760, 72, keep_below=60000))
    accs = config.load()['accounts']
    for a in accs:
        if a['id'] == aid:
            a['signature_image'] = path.name
    config.save({'accounts': accs})
    mailer._sig_cache.clear()
    return {'ok': True}


def api_mailbox(qs):
    aid = qs.get('account', [''])[0]
    if qs.get('refresh', [''])[0]:
        return archive.report(config.account(aid))
    return store.get('mailbox_' + aid) or archive.report(config.account(aid))


def api_archive(data):
    acc = config.account(data['account'])
    r = archive.run(acc, data.get('days'), data.get('folders'), limit=int(data.get('limit', 300)), dry_run=bool(data.get('dry_run', True)))
    if not r['dry_run']:
        archive.report(acc)
    return r


def api_open_folder(data):
    d = config.data_dir() / 'accounts' / data['account'] / data.get('kind', 'archive')
    d.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        import subprocess
        subprocess.Popen(['open', str(d)])
    return {'path': str(d)}


def local_file(path):
    """Serve files from the data folder only (sent .eml, concept images, saved replies, archive)."""
    p = Path(path).resolve()
    root = config.data_dir().resolve()
    if root not in p.parents or not p.is_file():
        raise KeyError('file not available')
    return p


def api_import(data):
    n = legacy.import_csv(data.get('csv', ''))
    return {'imported': n}


def api_update_apply(_data):
    r = updater.apply()
    threading.Timer(1.0, restart).start()
    return r


def restart():
    store.close()
    os.execv(sys.executable, [sys.executable] + sys.argv)


def api_quit(_data):
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {'ok': True}


GET = {'/api/audit': lambda qs: {'items': store.q('SELECT * FROM audit ORDER BY id DESC LIMIT 100')}, '/api/state': api_state, '/api/mailbox': api_mailbox, '/api/leads': api_leads, '/api/settings': api_settings_get,
       '/api/usage': lambda qs: store.usage_summary(int(qs.get('days', ['7'])[0])),
       '/api/update/check': lambda _q: updater.check(), '/api/ping': lambda _q: {'ok': True, 'version': VERSION}}
POST = {'/api/start': lambda d: control(d, False), '/api/pause': lambda d: control(d, True), '/api/add': api_add,
        '/api/send': api_send, '/api/skip': api_skip, '/api/edit': api_edit, '/api/redo': api_redo,
        '/api/settings': api_settings_post, '/api/profile': api_profile, '/api/signature': api_signature,
        '/api/import-csv': api_import, '/api/archive': api_archive, '/api/open-folder': api_open_folder,
        '/api/test-api': lambda d: llm.test_connection(d['connection']),
        '/api/test-mail': lambda d: {'ok': True, 'message': mailer.test_login(config.account(d['account']))},
        '/api/update/apply': api_update_apply, '/api/quit': api_quit}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, code=200, ctype='application/json; charset=utf-8'):
        if not isinstance(body, (bytes, str)):
            body = json.dumps(body, ensure_ascii=False, default=str)
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def local(self):  # Host check blocks DNS-rebinding pages from talking to the local API
        return self.headers.get('Host', '').rsplit(':', 1)[0] in ('127.0.0.1', 'localhost')

    def do_GET(self):
        if not self.local():
            return self.reply({'error': 'local only'}, 403)
        u = urlsplit(self.path)
        try:
            if u.path in ('/', '/index.html'):
                return self.reply(UI.read_bytes(), ctype='text/html; charset=utf-8')
            if u.path in GET:
                return self.reply(GET[u.path](parse_qs(u.query)))
            if u.path.startswith('/api/lead/'):
                return self.reply(api_lead(u.path.rsplit('/', 1)[1]))
            if u.path == '/file':
                p = local_file(parse_qs(u.query).get('path', [''])[0])
                ctype = {'.eml': 'message/rfc822', '.jpg': 'image/jpeg', '.png': 'image/png'}.get(p.suffix.lower(), 'application/octet-stream')
                body = p.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                if p.suffix.lower() == '.eml':
                    from urllib.parse import quote
                    self.send_header('Content-Disposition', "attachment; filename*=UTF-8''%s" % quote(p.name))
                self.end_headers()
                return self.wfile.write(body)
            if u.path.startswith('/image/'):
                lead = store.lead(int(u.path.rsplit('/', 1)[1]))
                return self.reply(Path(lead['image']).read_bytes(), ctype='image/jpeg')
            if u.path.startswith('/preview/'):
                lead = store.lead(int(u.path.rsplit('/', 1)[1]))
                img = Path(lead['image']).read_bytes() if lead.get('image') and Path(lead['image']).exists() else None
                return self.reply(mailer.preview_html(config.account(lead['account']), lead, img), ctype='text/html; charset=utf-8')
            self.reply({'error': 'not found'}, 404)
        except Exception as e:
            self.reply({'error': str(e)}, 400)

    def do_POST(self):
        if not self.local():
            return self.reply({'error': 'local only'}, 403)
        # JSON content type forces a CORS preflight, so ordinary web pages cannot trigger actions (CSRF).
        if 'application/json' not in self.headers.get('Content-Type', ''):
            return self.reply({'error': 'json only'}, 415)
        try:
            n = int(self.headers.get('Content-Length', '0'))
            data = json.loads(self.rfile.read(n) or b'{}') if n else {}
            fn = POST.get(urlsplit(self.path).path)
            if not fn:
                return self.reply({'error': 'not found'}, 404)
            label=self.headers.get('X-Outreach-Source','api')
            if label not in ('ui','cli','review-agent'): label='api'
            data['_origin']={'source':label,'request_id':uuid.uuid4().hex,'peer':self.client_address[0]}
            self.reply(fn(data))
        except Exception as e:
            self.reply({'error': str(e)}, 400)


def serve(port, open_window=True):
    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except OSError:
        return None
    store.db()
    store.reset_interrupted()
    try:
        print('导入旧版名单：', legacy.run(), flush=True)
    except Exception as e:
        print('旧版名单导入跳过：', e, flush=True)
    sync_workers()
    return server


def wait_ready(port, seconds=10):
    import urllib.request
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % port, timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False

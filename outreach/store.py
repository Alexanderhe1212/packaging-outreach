"""单一 SQLite 数据库，所有账号共用，便于跨账号去重。放在数据目录（不在 iCloud / Git 里）。"""
import json
import sqlite3
import threading
import re
import unicodedata
import uuid
import time
from datetime import datetime, timedelta, timezone

from . import config

_lock = threading.RLock()
_conn = None
BJ = timezone(timedelta(hours=8))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'auto',
  company TEXT DEFAULT '', domain TEXT DEFAULT '', email TEXT DEFAULT '',
  data TEXT NOT NULL DEFAULT '{}', subject TEXT DEFAULT '', body TEXT DEFAULT '',
  image TEXT DEFAULT '', message_id TEXT DEFAULT '', error TEXT DEFAULT '',
  tries INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
  created_at REAL, updated_at REAL, sent_at REAL, reply_at REAL, reply_excerpt TEXT DEFAULT '',
  followup_at REAL, followups INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS leads_acc_status ON leads(account,status);
CREATE INDEX IF NOT EXISTS leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS leads_email ON leads(email);
CREATE TABLE IF NOT EXISTS candidates(domain TEXT PRIMARY KEY, account TEXT, brand TEXT, note TEXT,
  status TEXT NOT NULL DEFAULT 'new', reason TEXT DEFAULT '', created_at REAL);
CREATE TABLE IF NOT EXISTS suppress(value TEXT PRIMARY KEY, kind TEXT, account TEXT, note TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, account TEXT, lead INTEGER,
  stage TEXT, model TEXT, input INTEGER, output INTEGER, cached INTEGER, images INTEGER, searches INTEGER, cost REAL);
CREATE INDEX IF NOT EXISTS usage_day ON usage(day);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS send_attempts(
 id TEXT PRIMARY KEY, lead INTEGER, account TEXT, started REAL, finished REAL,
 result TEXT, message_id TEXT, source TEXT, request_id TEXT, peer TEXT, followup INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, event TEXT, account TEXT, lead INTEGER,
 source TEXT, request_id TEXT, peer TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS identity_claims(key TEXT PRIMARY KEY, lead INTEGER);

'''
ACTIVE = ('queued', 'researching', 'writing', 'imaging')
CONTACTED = ('sent', 'unknown', 'replied', 'bounced', 'unsubscribed')
_current_lead = threading.local()


def db():
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(str(config.data_dir() / 'outreach.db'), timeout=30, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute('PRAGMA journal_mode=WAL')
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def close():
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def q(sql, args=(), one=False):
    with _lock:
        rows = db().execute(sql, args).fetchall()
        return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]


def x(sql, args=()):
    with _lock:
        c = db()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def today():
    return datetime.now(BJ).strftime('%Y-%m-%d')


# ---------- key/value ----------
def get(key, default=None):
    r = q('SELECT value FROM kv WHERE key=?', (key,), one=True)
    return json.loads(r['value']) if r else default


def put(key, value):
    x('INSERT OR REPLACE INTO kv VALUES(?,?)', (key, json.dumps(value)))


# ---------- leads ----------
def lead(lid):
    r = q('SELECT * FROM leads WHERE id=?', (lid,), one=True)
    if r:
        r['data'] = json.loads(r['data'] or '{}')
    return r


def add_lead(account, status, source='auto', **f):
    now = time.time()
    data = json.dumps(f.pop('data', {}), ensure_ascii=False)
    return x('INSERT INTO leads(account,status,source,company,domain,email,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
             (account, status, source, f.get('company', ''), f.get('domain', '').lower(), f.get('email', '').lower(), data, now, now))


def update(lid, **f):
    if 'data' in f:
        f['data'] = json.dumps(f['data'], ensure_ascii=False)
    f['updated_at'] = time.time()
    keys = list(f)
    x('UPDATE leads SET ' + ','.join(k + '=?' for k in keys) + ' WHERE id=?', [f[k] for k in keys] + [lid])


def next_lead(account, statuses):
    marks = ','.join('?' for _ in statuses)
    r = q('SELECT id FROM leads WHERE account=? AND status IN (' + marks + ') ORDER BY id LIMIT 1', [account] + list(statuses), one=True)
    return lead(r['id']) if r else None


def count(account, status):
    return q('SELECT count(*) n FROM leads WHERE account=? AND status=?', (account, status), one=True)['n']


def day_start():
    return datetime.now(BJ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def sent_today(account):
    return q('SELECT count(*) n FROM leads WHERE account=? AND sent_at>=?', (account, day_start()), one=True)['n'] + \
        (get('followups_%s_%s' % (account, today()), 0) or 0)


def list_leads(account=None, status=None, limit=100, offset=0, search=''):
    where, args = ' WHERE 1=1', []
    if account:
        where += ' AND account=?'
        args.append(account)
    if status:
        where += ' AND status IN (' + ','.join('?' for _ in status.split(',')) + ')'
        args += status.split(',')
    if search:
        where += ' AND (company LIKE ? OR domain LIKE ? OR email LIKE ? OR subject LIKE ?)'
        args += ['%' + search + '%'] * 4
    total = q('SELECT count(*) n FROM leads' + where, args, one=True)['n']
    items = q('SELECT id,account,status,source,company,domain,email,subject,error,cost,tokens,created_at,updated_at,sent_at,'
              'reply_at,followups FROM leads' + where + ' ORDER BY COALESCE(reply_at,0) DESC, updated_at DESC LIMIT ? OFFSET ?',
              args + [limit, offset])
    return {'items': items, 'total': total}


def reset_interrupted():
    """After a restart, half-finished leads go back to the queue (finished parts are kept in data)."""
    with _lock:
        x("UPDATE leads SET status='unknown', sent_at=COALESCE(sent_at,updated_at), error='进程中断：发送状态需人工核实，禁止自动重试' WHERE status='sending'")
        x("UPDATE send_attempts SET result='unknown',finished=? WHERE result='sending'", (time.time(),))
        x("UPDATE leads SET status='queued' WHERE status IN ('researching','writing','imaging')")
        x("UPDATE candidates SET status='new' WHERE status='researching'")


# ---------- candidates (cheap list of domains to crawl) ----------
def add_candidates(account, items):
    added = 0
    with _lock:
        for item in items:
            from .web import root_domain
            d = root_domain((item.get('domain') or '').lower().strip())
            if not d or '.' not in d or blocked(domain=d, account=account):
                continue
            c = db()
            cur = c.execute('INSERT OR IGNORE INTO candidates(domain,account,brand,note,created_at) VALUES(?,?,?,?,?)',
                            (d, account, str(item.get('brand', ''))[:120], json.dumps({k:str(item.get(k,''))[:1500] for k in ('brand','domain','product_url','match_reason','signal_type','signal_source','note')}, ensure_ascii=False), time.time()))
            added += cur.rowcount
            c.commit()
    return added


def next_candidate(account):
    return q("SELECT * FROM candidates WHERE account=? AND status='new' ORDER BY created_at LIMIT 1", (account,), one=True)


def claim_candidate(account):
    with _lock:
        c = db()
        c.execute('BEGIN IMMEDIATE')
        try:
            r = c.execute("SELECT * FROM candidates WHERE account=? AND status='new' ORDER BY created_at LIMIT 1", (account,)).fetchone()
            if r:
                c.execute("UPDATE candidates SET status='researching' WHERE domain=?", (r['domain'],))
            c.commit()
            return dict(r) if r else None
        except Exception:
            c.rollback()
            raise


def mark_candidate(domain, status, reason=''):
    x('UPDATE candidates SET status=?, reason=? WHERE domain=?', (status, reason[:200], domain))


def recent_candidate_domains(account, limit=40):
    return [r['domain'] for r in q('SELECT domain FROM candidates WHERE account=? ORDER BY created_at DESC LIMIT ?', (account, limit))]


# ---------- dedupe / suppression ----------
def suppress(value, kind, account='', note=''):
    if value:
        x('INSERT OR REPLACE INTO suppress VALUES(?,?,?,?,?)', (value.lower(), kind, account, note[:300], time.time()))


def shared():
    """Accounts are fully separate unless the user turns on the cross-account lock in settings."""
    return bool(config.load().get('cross_account_dedupe', False))


def _scope(account):
    if not account or shared():
        return '', []
    return ' AND account IN (?, \'\')', [account]


def blocked(email='', domain='', account=''):
    """True when this address/company was already contacted by this account (or by any account if the lock is on),
    is being prepared, or opted out. Entries imported without an account (CSV / constraints) apply to every account."""
    from .web import root_domain
    vals = [v.lower() for v in (email, domain, root_domain(domain) if domain else '') if v]
    if not vals:
        return False
    extra, args = _scope(account)
    marks = ','.join('?' for _ in vals)
    if q('SELECT 1 FROM suppress WHERE value IN (' + marks + ')' + extra + ' LIMIT 1', vals + args):
        return True
    lextra = ' AND account=?' if account and not shared() else ''
    largs = [account] if lextra else []
    if domain and q("SELECT 1 FROM leads WHERE domain IN (?,?) AND status NOT IN ('skipped','failed')" + lextra + " LIMIT 1",
                    [domain.lower(), root_domain(domain)] + largs):
        return True
    if email and q("SELECT 1 FROM leads WHERE email=? AND status NOT IN ('skipped','failed')" + lextra + " LIMIT 1",
                   [email.lower()] + largs):
        return True
    return False


def hard_blocked(email, account=''):
    """Opt-out / bounce / reply / unresolved-unknown only (a manual lead may override ordinary dedupe)."""
    extra, args = _scope(account)
    return bool(q("SELECT 1 FROM suppress WHERE value=? AND kind IN ('unsubscribe','bounce','hard_reject','unknown','reply')"
                  + extra + " LIMIT 1", [(email or '').lower()] + args))


def recent_structures(account, limit=10):
    """Box structures this account proposed recently, newest first (used to keep concepts varied)."""
    out = []
    for r in q("SELECT data FROM leads WHERE account=? AND data LIKE '%\"plan\"%' ORDER BY id DESC LIMIT ?", (account, limit)):
        plan = json.loads(r['data']).get('plan') or {}
        for k in ('a', 'b'):
            v = (plan.get(k) or {}).get('structure') or (plan.get(k) or {}).get('name')
            if v and v not in out:
                out.append(v)
    return out


# ---------- usage & cost ----------
def set_current_lead(lid):
    _current_lead.id = lid


def estimate_cost(model, inp, out, cached=0, images=0, searches=0, quality=''):
    cfg = config.load()
    name = model.split('/')[-1].split(':')[0]
    if not name or name.startswith('codex'):
        return 0.0  # Codex / ChatGPT subscription: no per-call charge, tokens are still recorded
    cost = 0.0
    price = cfg.get('pricing_usd_per_million', {}).get(name)
    if price:
        cost += ((inp - cached) * price[0] + cached * price[0] * 0.25 + out * price[1]) / 1e6
    if images:
        cost += images * cfg.get('pricing_usd_per_image', {}).get('%s:%s' % (name, quality or 'medium'), 0.06)
    cost += searches * 0.01
    return round(cost, 5)


def add_usage(account, stage, model, inp=0, out=0, cached=0, images=0, searches=0, quality=''):
    lid = getattr(_current_lead, 'id', None)
    cost = estimate_cost(model, inp, out, cached, images, searches, quality)
    x('INSERT INTO usage(ts,day,account,lead,stage,model,input,output,cached,images,searches,cost) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      (time.time(), today(), account, lid, stage, model, inp, out, cached, images, searches, cost))
    if lid:
        x('UPDATE leads SET cost=cost+?, tokens=tokens+? WHERE id=?', (cost, inp + out, lid))


def usage_summary(days=7):
    since = (datetime.now(BJ) - timedelta(days=days - 1)).strftime('%Y-%m-%d')
    rows = q('SELECT day, stage, sum(input) input, sum(output) output, sum(cached) cached, sum(images) images, '
             'sum(searches) searches, sum(cost) cost, count(*) calls FROM usage WHERE day>=? GROUP BY day, stage ORDER BY day', (since,))
    prepared = q("SELECT count(*) n, avg(tokens) tokens, avg(cost) cost FROM leads WHERE status IN ('ready','sent','unknown','replied') "
                 "AND tokens>0 AND created_at>=?", (time.time() - days * 86400,), one=True)
    return {'rows': rows, 'per_email': prepared}


def stats(account):
    rows = q('SELECT status,count(*) n FROM leads WHERE account=? GROUP BY status', (account,))
    s = {r['status']: r['n'] for r in rows}
    s['sent_today'] = sent_today(account)
    s['candidates'] = q("SELECT count(*) n FROM candidates WHERE account=? AND status='new'", (account,), one=True)['n']
    c = q('SELECT sum(cost) c, sum(input+output) t FROM usage WHERE account=? AND day=?', (account, today()), one=True)
    s['cost_today'] = round(c['c'] or 0, 3)
    s['tokens_today'] = c['t'] or 0
    return s


# Shared final gate. Transactions contain only local decisions, never network I/O.
def identity_keys(email='', domain='', company=''):
    from .web import root_domain
    keys = set()
    if email:
        keys.add('email:' + email.strip().casefold())
    if domain:
        keys.add('domain:' + root_domain(domain.strip().lower()))
    name = re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', company).casefold())
    if name:
        keys.add('company:' + name)
    return keys


def _audit(c, event, account, lid, origin, result):
    origin = origin or {}
    # Only bounded operational metadata. Never headers, prompts, body or credentials.
    c.execute('INSERT INTO audit(ts,event,account,lead,source,request_id,peer,result) VALUES(?,?,?,?,?,?,?,?)',
              (time.time(), event, account, lid, str(origin.get('source', 'internal'))[:40],
               str(origin.get('request_id', ''))[:40], str(origin.get('peer', ''))[:45], str(result)[:100]))


def audit(event, account='', lid=None, origin=None, result=''):
    with _lock:
        c = db(); _audit(c, event, account, lid, origin, result); c.commit()


def _conflict(c, row, preparation=False):
    keys = identity_keys(row['email'], row['domain'], row['company'])
    vals = {row['email'].strip().lower(), row['domain'].strip().lower()}
    vals.update(k[7:] for k in keys if k.startswith('domain:'))
    # Safety suppression always applies across accounts, including old per-account rows.
    if any(r['value'].strip().lower() in vals for r in c.execute('SELECT value FROM suppress')):
        return 'suppressed'
    for other in c.execute("SELECT id,email,domain,company,status,reply_at,message_id FROM leads WHERE id<>? AND status NOT IN ('skipped','failed')", (row['id'],)):
        if not (identity_keys(other['email'], other['domain'], other['company']) & keys):
            continue
        # Earlier queued prospect owns an alias; a previously contacted prospect always wins.
        if preparation or other['id'] < row['id'] or other['message_id'] or other['reply_at'] or other['status'] in ('sending','unknown','sent','replied','bounced','unsubscribed'):
            return 'duplicate'
    for key in keys:
        owner = c.execute('SELECT lead FROM identity_claims WHERE key=?', (key,)).fetchone()
        if owner and owner['lead'] != row['id']:
            r = c.execute('SELECT status FROM leads WHERE id=?', (owner['lead'],)).fetchone()
            if r and r['status'] not in ('failed', 'skipped'):
                return 'claimed'
    return ''


def claim_prospect(account, prospect, source='auto', lid=None, manual=None):
    """Atomic brand/email/domain ownership after research, including redirects/aliases."""
    with _lock:
        c = db(); c.execute('BEGIN IMMEDIATE')
        try:
            row = dict(id=lid or -1, email=prospect.get('email',''), domain=prospect.get('domain',''), company=prospect.get('company',''))
            reason = _conflict(c, row, preparation=True)
            if reason:
                c.rollback(); return None
            now=time.time()
            if lid is None:
                data={'prospect':prospect} if not manual else {'manual':manual}
                cur=c.execute('INSERT INTO leads(account,status,source,company,domain,email,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (account,'queued' if manual else 'writing',source,row['company'],row['domain'].lower(),row['email'].lower(),json.dumps(data,ensure_ascii=False),now,now))
                lid=cur.lastrowid
            for key in identity_keys(row['email'],row['domain'],row['company']):
                c.execute('INSERT OR REPLACE INTO identity_claims VALUES(?,?)',(key,lid))
            c.commit();return lid
        except Exception:
            c.rollback();raise


def reserve_send(lid, acc, message_id, origin=None, followup=False, expected=None):
    with _lock:
        c=db();c.execute('BEGIN IMMEDIATE')
        try:
            row=c.execute('SELECT * FROM leads WHERE id=?',(lid,)).fetchone()
            reason=''
            if not row or row['account']!=acc['id']:reason='account_mismatch'
            elif row['status'] != ('sent' if followup else 'ready'):reason='not_ready'
            elif row['reply_at'] or (row['message_id'] and not followup):reason='already_contacted'
            elif followup and (row['followups'] or not acc.get('followup_enabled',False)):reason='followup_disabled'
            if not reason and expected and any(row[k]!=expected.get(k) for k in ('email','subject','body','image')):reason='changed'
            if not reason:reason=_conflict(c,row)
            def val(k,d=None):
                r=c.execute('SELECT value FROM kv WHERE key=?',(k,)).fetchone();return json.loads(r['value']) if r else d
            now=time.time()
            if not reason and val('paused_'+acc['id'],True):reason='paused'
            if not reason and c.execute("SELECT 1 FROM send_attempts WHERE account=? AND result='sending'",(acc['id'],)).fetchone():reason='sending'
            if not reason and now<float(val('next_send_'+acc['id'],0)):reason='interval'
            hours=acc.get('send_hours_beijing')
            if not reason and hours:
                h=datetime.now(BJ).hour;start,end=hours
                if not (start<=h<end if start<end else h>=start or h<end):reason='outside_hours'
            cfg=config.load()
            def used(aid=None):
                scope=' AND account=?' if aid else '';args=[day_start()]+([aid] if aid else [])
                n=c.execute('SELECT count(*) n FROM leads WHERE sent_at>=?'+scope,args).fetchone()['n']
                ids=[aid] if aid else [a['id'] for a in cfg['accounts']]
                n+=sum(val('followups_%s_%s'%(a,today()),0) for a in ids)
                n+=c.execute("SELECT count(*) n FROM send_attempts WHERE result='sending'"+scope,([aid] if aid else [])).fetchone()['n']
                return n
            if not reason and acc.get('daily_limit') and used(acc['id'])>=int(acc['daily_limit']):reason='daily_limit'
            if not reason and cfg.get('daily_limit_total') and used()>=int(cfg['daily_limit_total']):reason='total_limit'
            if reason:
                _audit(c,'send_denied',acc['id'],lid,origin,reason);c.commit();return None,reason
            token=uuid.uuid4().hex;origin=origin or {}
            c.execute('INSERT INTO send_attempts(id,lead,account,started,result,message_id,source,request_id,peer,followup) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (token,lid,acc['id'],now,'sending',message_id,str(origin.get('source','internal'))[:40],str(origin.get('request_id',''))[:40],str(origin.get('peer',''))[:45],int(followup)))
            c.execute("UPDATE leads SET status='sending',message_id=?,updated_at=? WHERE id=?",(message_id,now,lid))
            for key in identity_keys(row['email'],row['domain'],row['company']):c.execute('INSERT OR REPLACE INTO identity_claims VALUES(?,?)',(key,lid))
            _audit(c,'send_reserved',acc['id'],lid,origin,'sending');c.commit();return token,''
        except Exception:
            c.rollback();raise


def transport_allowed(token):
    with _lock:
        c=db();a=c.execute('SELECT * FROM send_attempts WHERE id=?',(token,)).fetchone()
        if not a or a['result']!='sending':return False
        row=c.execute('SELECT * FROM leads WHERE id=?',(a['lead'],)).fetchone()
        return bool(row and row['status']=='sending' and not row['reply_at'] and not _conflict(c,row) and not get('paused_'+a['account'],True))


def finish_send(token,result,note,next_at):
    with _lock:
        c=db();c.execute('BEGIN IMMEDIATE')
        try:
            a=c.execute('SELECT * FROM send_attempts WHERE id=?',(token,)).fetchone()
            if not a or a['result']!='sending':c.rollback();return
            row=c.execute('SELECT * FROM leads WHERE id=?',(a['lead'],)).fetchone();now=time.time()
            if result not in ('sent','unknown','bounced','retry','blocked','auth_error'):result='unknown'
            status=result if result in ('sent','unknown','bounced') else ('sent' if a['followup'] else 'ready')
            if result=='blocked':status='skipped'
            # An inbox event arriving during transport must never be overwritten.
            if row['status'] in ('replied','unsubscribed','bounced'):status=row['status']
            sent_at=row['sent_at'];mid=row['message_id'];tries=row['tries']
            if result in ('sent','unknown') and not a['followup']:sent_at=now
            if result in ('retry','auth_error','blocked') and not a['followup']:mid=''
            if result=='retry':
                tries+=1
                if tries>=3 and not a['followup']:status='failed'
            c.execute('UPDATE leads SET status=?,sent_at=?,message_id=?,tries=?,error=?,updated_at=? WHERE id=?',
                      (status,sent_at,mid,tries,note[:300],now,a['lead']))
            if a['followup'] and result in ('sent','unknown','bounced'):
                c.execute('UPDATE leads SET followups=1,followup_at=? WHERE id=?',(now,a['lead']))
                key='followups_%s_%s'%(a['account'],today());v=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
                c.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,json.dumps((json.loads(v['value']) if v else 0)+1)))
            if result in ('unknown','bounced'):
                c.execute('INSERT OR REPLACE INTO suppress VALUES(?,?,?,?,?)',(row['email'].lower(),result,a['account'],note[:300],now))
            if result in ('sent','unknown','retry','bounced'):
                c.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',('next_send_'+a['account'],json.dumps(next_at)))
            c.execute('UPDATE send_attempts SET result=?,finished=? WHERE id=?',(result,now,token))
            _audit(c,'send_finished',a['account'],a['lead'],dict(source=a['source'],request_id=a['request_id'],peer=a['peer']),result)
            c.commit()
        except Exception:
            c.rollback();raise

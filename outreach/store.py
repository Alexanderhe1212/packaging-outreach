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
CREATE TABLE IF NOT EXISTS stage_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT, lead INTEGER,
 stage TEXT, started REAL, finished REAL, duration REAL, outcome TEXT, error_type TEXT);
CREATE INDEX IF NOT EXISTS stage_runs_account ON stage_runs(account,started);
CREATE TABLE IF NOT EXISTS crawl_retries(domain TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0, next_at REAL, reason TEXT);

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
            columns = {r[1] for r in _conn.execute('PRAGMA table_info(usage)')}
            if 'run_id' not in columns:
                _conn.execute('ALTER TABLE usage ADD COLUMN run_id INTEGER')
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
    if f.get('status') in ('failed', 'unknown'):
        from . import problems
        problems.overview()


def next_lead(account, statuses):
    marks = ','.join('?' for _ in statuses)
    r = q("SELECT id FROM leads WHERE account=? AND status IN (" + marks + ") AND (status != 'queued' OR COALESCE(json_extract(data, '$.research_retry_at'), 0) <= ?) ORDER BY id LIMIT 1", [account] + list(statuses) + [time.time()], one=True)
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
              "reply_at,followups,COALESCE(json_extract(data,'$.research_retry_at'),0) AS research_retry_at FROM leads" + where + ' ORDER BY COALESCE(reply_at,0) DESC, updated_at DESC LIMIT ? OFFSET ?',
              args + [limit, offset])
    return {'items': items, 'total': total}


def reset_interrupted():
    """After a restart, half-finished leads go back to the queue (finished parts are kept in data)."""
    with _lock:
        x("UPDATE leads SET status='unknown', sent_at=COALESCE(sent_at,updated_at), error='进程中断：发送状态需人工核实，禁止自动重试' WHERE status='sending'")
        x("UPDATE send_attempts SET result='unknown',finished=? WHERE result='sending'", (time.time(),))
        x("UPDATE leads SET status='queued' WHERE status IN ('researching','writing','imaging')")
        x("UPDATE candidates SET status='new' WHERE status='researching'")
        x("UPDATE stage_runs SET outcome='interrupted',finished=? WHERE outcome='running'", (time.time(),))


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
            fields = ('brand','domain','product_url','match_reason','signal_type','signal_source','note','opportunity_tier','project_name','evidence_quote','published_at','checked_at','procurement_status','missing_information','buyer_role','requested_product','quantity','specifications','arrival_requirement','open_window_evidence','capability_status','source_url','verification','policy_hash')
            tier = item.get('opportunity_tier')
            state = 'backlog' if tier in ('B','C') or item.get('capability_status') == 'needs_confirmation' else 'new'
            cur = c.execute('INSERT OR IGNORE INTO candidates(domain,account,brand,note,created_at,status) VALUES(?,?,?,?,?,?)',
                            (d, account, str(item.get('brand', ''))[:120], json.dumps({k:str(item.get(k,''))[:1500] for k in fields}, ensure_ascii=False), time.time(), state))
            inserted=cur.rowcount
            if not inserted:
                existing=c.execute('SELECT status FROM candidates WHERE domain=?',(d,)).fetchone()
                if existing and existing['status'] not in ('new','researching','retry_wait','retry_exhausted'):
                    c.execute('UPDATE candidates SET account=?,brand=?,note=?,created_at=?,status=?,reason=? WHERE domain=?',
                        (account,str(item.get('brand',''))[:120],json.dumps({k:str(item.get(k,''))[:1500] for k in fields},ensure_ascii=False),time.time(),state,'refreshed source after eligibility check',d))
                    inserted=1
            added += inserted if state == 'new' else 0
            c.commit()
    return added


def next_candidate(account):
    return q("SELECT * FROM candidates WHERE account=? AND status='new' ORDER BY created_at LIMIT 1", (account,), one=True)


def claim_candidate(account):
    with _lock:
        c = db()
        c.execute('BEGIN IMMEDIATE')
        try:
            c.execute("UPDATE candidates SET status='new' WHERE account=? AND status='retry_wait' AND domain IN (SELECT domain FROM crawl_retries WHERE next_at<=?)", (account,time.time()))
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
    if COOLDOWN_SECONDS <= 0:
        return []
    return [r['domain'] for r in q('SELECT domain FROM candidates WHERE created_at>? ORDER BY created_at DESC LIMIT ?', (time.time()-COOLDOWN_SECONDS, limit))]


# ---------- dedupe / suppression ----------
def suppress(value, kind, account='', note=''):
    if value:
        x('INSERT OR REPLACE INTO suppress VALUES(?,?,?,?,?)', (value.lower(), kind, account, note[:300], time.time()))


COOLDOWN_SECONDS = 0  # Keep automatic recycling of sent records disabled.
CONTACT_COOLDOWN_SECONDS = 7 * 24 * 60 * 60  # Sending safety spans every account.


def shared():
    """The rolling contact window and safety exclusions always span all accounts."""
    return True


def _scope(account):
    return '', []


def blocked(email='', domain='', account=''):
    if not email and not domain:
        return False
    with _lock:
        return bool(_conflict(db(), dict(id=-1,email=email,domain=domain,company=''), preparation=True))


def hard_blocked(email, account=''):
    # Replies require context review; elapsed time never overrides exclusions.
    return bool(q('SELECT 1 FROM suppress WHERE lower(trim(value))=? LIMIT 1', [(email or '').strip().lower()]))


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
    usage_id = x('INSERT INTO usage(ts,day,account,lead,stage,model,input,output,cached,images,searches,cost) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      (time.time(), today(), account, lid, stage, model, inp, out, cached, images, searches, cost))
    x('UPDATE usage SET run_id=? WHERE id=?', (getattr(_current_lead, 'run_id', None), usage_id))
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
    s['sent_today'] = sent_today(account)  # quota semantics unchanged
    s.update(delivery_stats(account))
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


def _data(row):
    value = dict(row).get('data') or '{}'
    return value if isinstance(value,dict) else json.loads(value)


def last_contact(c, row):
    row = dict(row)
    attempt = c.execute("SELECT MAX(finished) ts FROM send_attempts WHERE lead=? AND result='sent'", (row['id'],)).fetchone()
    return max(float(row.get('sent_at') or 0), float(row.get('followup_at') or 0), float(attempt['ts'] or 0))


def _record_hold(c, row, now):
    row = dict(row)
    data = _data(row)
    policy = data.get('contact_policy') or {}
    if policy.get('paused') or data.get('customer_paused'):
        return 'customer_paused'
    until = policy.get('recontact_after') or data.get('recontact_after')
    if until:
        try:
            when = float(until)
        except (ValueError,TypeError):
            try: when = datetime.fromisoformat(str(until).replace('Z','+00:00')).timestamp()
            except (ValueError,TypeError): return 'future_contact'
        if now < when: return 'future_contact'
    if row.get('status') in ('unknown','bounced','unsubscribed','rejected'):
        return 'suppressed'
    if row.get('reply_at') or row.get('status') == 'replied':
        return 'reply_context_required'
    if c.execute("SELECT 1 FROM send_attempts WHERE lead=? AND result='unknown' LIMIT 1", (row['id'],)).fetchone():
        return 'unknown'
    contacted = last_contact(c,row)
    if contacted and now - contacted < CONTACT_COOLDOWN_SECONDS:
        return 'cooldown'
    if row.get('status') == 'sent' and not contacted:
        return 'history_time_unknown'
    return ''


def _conflict(c, row, preparation=False):
    row = dict(row);now=time.time()
    keys = identity_keys(row['email'], row['domain'], row['company'])
    vals = {row['email'].strip().casefold(), row['domain'].strip().casefold()}
    vals.update(k[7:] for k in keys if k.startswith('domain:'))
    for entry in c.execute('SELECT value FROM suppress'):
        value=entry['value'].strip().casefold()
        skeys=identity_keys(email=value) if '@' in value else identity_keys(domain=value,company=value)
        if value in vals or keys & skeys: return 'suppressed'
    own=c.execute('SELECT * FROM leads WHERE id=?',(row['id'],)).fetchone()
    if own:
        reason=_record_hold(c,own,now)
        if reason:return reason
    active=set(ACTIVE) | {'ready','sending','radar_review'}
    for other in c.execute('SELECT * FROM leads WHERE id<>?', (row['id'],)):
        if not (identity_keys(other['email'],other['domain'],other['company']) & keys):continue
        reason=_record_hold(c,other,now)
        if reason:return reason
        if other['status'] in active and (preparation or other['id'] < row['id'] or other['status']=='sending'):
            return 'duplicate'
    for key in keys:
        owner=c.execute('SELECT lead FROM identity_claims WHERE key=?',(key,)).fetchone()
        if not owner or owner['lead']==row['id']:continue
        other=c.execute('SELECT * FROM leads WHERE id=?',(owner['lead'],)).fetchone()
        if other:
            reason=_record_hold(c,other,now)
            if reason:return reason
            if other['status'] in active:return 'claimed'
    return ''


def queue_recontact(account):
    """Create one fresh draft from verified facts; never rewrite sent history or reuse its email."""
    # With no contact cooldown, auto-recycling sent rows would produce an endless
    # immediate resend loop. Recontact instead enters via discovery/manual import.
    if COOLDOWN_SECONDS <= 0:
        return None
    import copy
    with _lock:
        c=db();c.execute('BEGIN IMMEDIATE')
        try:
            candidates=c.execute("SELECT * FROM leads WHERE account=? AND status='sent' ORDER BY sent_at DESC",(account,)).fetchall()
            profile=config.profile(config.account(account).get('profile','packaging'))
            recent_reviews=[_data(r).get('prior_contact',{}).get('lead_id') for r in c.execute("SELECT data FROM leads WHERE source='recontact' AND created_at>?",(time.time()-COOLDOWN_SECONDS,))]
            for old in candidates:
                if old['id'] in recent_reviews:continue
                if _record_hold(c,old,time.time()):continue
                data=_data(old);prospect=data.get('prospect') or {}
                if not prospect.get('email_verified'):continue
                if profile.get('discovery_rules') and (prospect.get('discovery_evidence') or {}).get('opportunity_tier') not in ('A+','A'):continue
                row=dict(id=-1,email=old['email'],domain=old['domain'],company=old['company'])
                if _conflict(c,row,preparation=True):continue
                now=time.time();prospect=copy.deepcopy(prospect)
                prior={'lead_id':old['id'],'sent_at':last_contact(c,old),'subject':old['subject'],'body':old['body'][:2000]}
                prospect['prior_contact']=prior
                fresh={'prospect':prospect,'prior_contact':prior,'revalidate_opportunity':True}
                cur=c.execute('INSERT INTO leads(account,status,source,company,domain,email,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (account,'queued','recontact',old['company'],old['domain'],old['email'],json.dumps(fresh,ensure_ascii=False),now,now))
                lid=cur.lastrowid
                for key in identity_keys(old['email'],old['domain'],old['company']):c.execute('INSERT OR REPLACE INTO identity_claims VALUES(?,?)',(key,lid))
                _audit(c,'recontact_queued',account,lid,{'source':'scheduler'},'verified_facts_reused')
                c.commit();return lid
            c.commit();return None
        except Exception:
            c.rollback();raise


def claim_prospect(account, prospect, source='auto', lid=None, manual=None, hold=False):
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
                    (account,'radar_review' if hold else ('queued' if manual else 'writing'),source,row['company'],row['domain'].lower(),row['email'].lower(),json.dumps(data,ensure_ascii=False),now,now))
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


def defer_candidate(domain, error):
    """At most three deferred rounds; fresh discovery cannot reset this budget."""
    from . import web
    with _lock:
        prev = q('SELECT attempts FROM crawl_retries WHERE domain=?', (domain,), one=True)
        cause = web.transient_failure(error)
        tries = (prev['attempts'] if prev else 0) + (0 if isinstance(cause, web.DeferredFetch) else 1)
        delay = (max(1, web.retry_after(cause)) if isinstance(cause, web.DeferredFetch) else
                 max(min(300 * 2 ** max(0, tries-1), 3600) * (1 + __import__('random').uniform(0, .25)), web.retry_after(cause)))
        exhausted = tries >= 3
        reason = '临时官网错误：%s；%s' % (web.web_error_label(cause), '重试额度耗尽，需人工核实' if exhausted else '延后第 %d/3 轮重试' % tries)
        x('INSERT OR REPLACE INTO crawl_retries VALUES(?,?,?,?)', (domain, tries, time.time()+delay, reason))
        mark_candidate(domain, 'retry_exhausted' if exhausted else 'retry_wait', reason)


def delivery_stats(account):
    """Transport acceptance is based on attempts, never lead state or imported sent_at."""
    start = day_start()
    r = q("SELECT count(*) total, sum(CASE WHEN finished>=? THEN 1 ELSE 0 END) today, max(finished) last FROM send_attempts WHERE account=? AND result='sent'", (start,account), one=True)
    result = dict(accepted_total=r['total'], accepted_today=r['today'] or 0, last_accepted_at=r['last'])
    for state in ('unknown','retry','bounced','auth_error'):
        result[state+'_attempts_today'] = q('SELECT count(*) n FROM send_attempts WHERE account=? AND result=? AND started>=?', (account,state,start), one=True)['n']
    result['retry_candidates'] = q("SELECT count(*) n FROM candidates WHERE account=? AND status='retry_wait'", (account,), one=True)['n']
    result['exhausted_candidates'] = q("SELECT count(*) n FROM candidates WHERE account=? AND status='retry_exhausted'", (account,), one=True)['n']
    # Classification is descriptive only; no change to eligibility or sending policy.
    result['signals'] = q("SELECT CASE WHEN json_extract(data,'$.prospect.purchase_signal')='confirmed_procurement' THEN 'confirmed_procurement' WHEN json_extract(data,'$.prospect.purchase_signal')='fit_inference' THEN 'fit_inference' ELSE 'unclassified' END signal,count(*) n FROM leads WHERE account=? GROUP BY signal", (account,))
    return result


def operation_report(days=7):
    since = time.time()-max(1,min(days,90))*86400
    timing = q("SELECT account,stage,count(*) runs,sum(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) failures,sum(CASE WHEN outcome='interrupted' THEN 1 ELSE 0 END) interrupted,count(duration) measured,avg(duration) avg_seconds,max(duration) max_seconds FROM stage_runs WHERE started>=? AND outcome!='running' GROUP BY account,stage", (since,))
    usage = q('SELECT account,stage,model,count(*) calls,sum(input) input,sum(output) output,sum(cached) cached,sum(images) images,sum(cost) recorded_cost FROM usage WHERE ts>=? GROUP BY account,stage,model', (since,))
    prices = config.load().get('pricing_usd_per_million', {})
    for row in usage:
        model = row['model'] or ''
        row['cost_status'] = 'subscription' if model.startswith('codex:') else ('estimated' if model.split('/')[-1] in prices else 'unpriced')
        row['estimated_cost'] = row['recorded_cost'] if row['cost_status']=='estimated' else None
        row['tokens_status'] = 'reported' if (row['input'] or row['output']) else 'not_reported_or_zero'
        row.pop('recorded_cost',None)
    return dict(days=days,timing=timing,usage=usage,as_of=time.time(),duration_note='耗时仅包含升级后的实测记录；历史未记录，不补算。',cost_note='订阅调用未折算金额；估算不等于账单。')

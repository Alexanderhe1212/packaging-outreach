"""单一 SQLite 数据库，所有账号共用，便于跨账号去重。放在数据目录（不在 iCloud / Git 里）。"""
import json
import sqlite3
import threading
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
    x("UPDATE leads SET status='queued' WHERE status IN ('researching','writing','imaging')")


# ---------- candidates (cheap list of domains to crawl) ----------
def add_candidates(account, items):
    added = 0
    for c in items:
        d = (c.get('domain') or '').lower().strip()
        if d.startswith('www.'):
            d = d[4:]
        if not d or '.' not in d or blocked(domain=d):
            continue
        if q('SELECT 1 FROM candidates WHERE domain=?', (d,)):
            continue
        x('INSERT INTO candidates(domain,account,brand,note,created_at) VALUES(?,?,?,?,?)',
          (d, account, str(c.get('brand', ''))[:80], str(c.get('note', ''))[:200], time.time()))
        added += 1
    return added


def next_candidate(account):
    return q("SELECT * FROM candidates WHERE account=? AND status='new' ORDER BY created_at LIMIT 1", (account,), one=True)


def mark_candidate(domain, status, reason=''):
    x('UPDATE candidates SET status=?, reason=? WHERE domain=?', (status, reason[:200], domain))


def recent_candidate_domains(limit=40):
    return [r['domain'] for r in q('SELECT domain FROM candidates ORDER BY created_at DESC LIMIT ?', (limit,))]


# ---------- dedupe / suppression ----------
def suppress(value, kind, account='', note=''):
    if value:
        x('INSERT OR REPLACE INTO suppress VALUES(?,?,?,?,?)', (value.lower(), kind, account, note[:300], time.time()))


def blocked(email='', domain=''):
    """True when this address/company was already contacted (by any account), is being prepared, or opted out."""
    from .web import root_domain
    vals = [v.lower() for v in (email, domain, root_domain(domain) if domain else '') if v]
    if not vals:
        return False
    marks = ','.join('?' for _ in vals)
    if q('SELECT 1 FROM suppress WHERE value IN (' + marks + ') LIMIT 1', vals):
        return True
    if domain and q("SELECT 1 FROM leads WHERE domain IN (?,?) AND status NOT IN ('skipped','failed') LIMIT 1",
                    (domain.lower(), root_domain(domain))):
        return True
    if email and q("SELECT 1 FROM leads WHERE email=? AND status NOT IN ('skipped','failed') LIMIT 1", (email.lower(),)):
        return True
    return False


def hard_blocked(email):
    """Opt-out / bounce / reply / unresolved-unknown only (a manual lead may override ordinary dedupe)."""
    return bool(q("SELECT 1 FROM suppress WHERE value=? AND kind IN ('unsubscribe','bounce','hard_reject','unknown','reply') LIMIT 1",
                  ((email or '').lower(),)))


# ---------- usage & cost ----------
def set_current_lead(lid):
    _current_lead.id = lid


def estimate_cost(model, inp, out, cached=0, images=0, searches=0, quality=''):
    cfg = config.load()
    name = model.split('/')[-1].split(':')[0]
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

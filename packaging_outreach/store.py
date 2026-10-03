"""Durable per-stage claims, per-company first contact, and immutable send attempts."""
import contextlib,json,sqlite3,time,uuid
from pathlib import Path

class Store:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'workflow.sqlite3'
        with self.db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,brand TEXT,company_key TEXT,recipient TEXT,stage TEXT,state TEXT,payload TEXT,updated REAL,next_at REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,job_id TEXT,stage TEXT,state TEXT,output TEXT,started REAL,ended REAL);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,job_id TEXT UNIQUE,company_key TEXT,recipient TEXT,message_id TEXT,result TEXT,stage TEXT,mime_sha TEXT,updated REAL);
            CREATE TABLE IF NOT EXISTS traces(attempt_id TEXT,stage TEXT,detail TEXT,at REAL);
            CREATE TABLE IF NOT EXISTS events(recipient TEXT,kind TEXT,evidence TEXT,at REAL,UNIQUE(recipient,kind,evidence));
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS followups(job_id TEXT PRIMARY KEY,source_attempt TEXT,evidence TEXT);
            INSERT OR IGNORE INTO settings VALUES('paused','true');
            ''')
    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def setting(self,key,value=None):
        with self.db() as c:
            if value is not None:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,str(value)))
            row=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return row[0] if row else None
    def acquire(self,owner):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT value FROM settings WHERE key='worker'").fetchone();old=json.loads(r[0]) if r else {}
            if old.get('owner')!=owner and old.get('at',0)>time.time()-20:raise RuntimeError('Another worker owns this workspace')
            # Stale work is uncertain, never automatically regenerate or resubmit it.
            c.execute("UPDATE jobs SET state='unknown' WHERE state='running'")
            c.execute("UPDATE runs SET state='unknown' WHERE state='running'")
            c.execute("UPDATE attempts SET result='unknown' WHERE result='in_progress'")
            c.execute("INSERT OR REPLACE INTO settings VALUES('worker',?)",(json.dumps({'owner':owner,'at':time.time()}),))
    def heartbeat(self,owner):
        with self.db() as c:
            old=json.loads(c.execute("SELECT value FROM settings WHERE key='worker'").fetchone()[0])
            if old['owner']!=owner:raise RuntimeError('Worker ownership changed')
            c.execute("UPDATE settings SET value=? WHERE key='worker'",(json.dumps({'owner':owner,'at':time.time()}),))
    def release(self,owner):
        with self.db() as c:
            row=c.execute("SELECT value FROM settings WHERE key='worker'").fetchone()
            if row and json.loads(row[0])['owner']==owner:c.execute("DELETE FROM settings WHERE key='worker'")
    def add(self,brand,payload,stage='research',followup_of=None,evidence=None):
        from .sources import host
        company_key=host(payload['company_url']) if payload.get('company_url') else ''
        recipient=payload.get('recipient','').lower();jid=str(uuid.uuid4())
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if company_key and not followup_of and c.execute('SELECT 1 FROM jobs WHERE company_key=?',(company_key,)).fetchone():return None
            if recipient and c.execute("SELECT 1 FROM events WHERE recipient=? AND kind IN ('unsubscribe','hard_reject','reply')",(recipient,)).fetchone():raise ValueError('Recipient requires a conversation decision')
            if followup_of:
                source=c.execute("SELECT a.id,j.brand FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE a.id=? AND a.company_key=? AND a.result='accepted'",(followup_of,company_key)).fetchone()
                if not source or source['brand']!=brand or not evidence:raise ValueError('Follow-up needs an accepted same-brand source and explicit new-value evidence')
                c.execute('INSERT INTO followups VALUES(?,?,?)',(jid,followup_of,evidence))
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,0)',(jid,brand,company_key,recipient,stage,'queued',json.dumps(payload,ensure_ascii=False),time.time()))
        return jid
    def get(self,jid):
        with self.db() as c:r=dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        r['payload']=json.loads(r['payload']);return r
    def queue(self):
        with self.db() as c:return [dict(x) for x in c.execute("SELECT id,brand,stage FROM jobs WHERE state='queued' AND next_at<=? ORDER BY updated",(time.time(),))]
    def claim(self,jid):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':return False
            return c.execute("UPDATE jobs SET state='running',updated=? WHERE id=? AND state='queued'",(time.time(),jid)).rowcount==1
    def advance(self,jid,stage,payload,state='queued'):
        with self.db() as c:c.execute('UPDATE jobs SET stage=?,state=?,payload=?,updated=?,next_at=0 WHERE id=?',(stage,state,json.dumps(payload,ensure_ascii=False),time.time(),jid))
    def fail(self,jid,state,error,delay=0):
        job=self.get(jid);p=job['payload'];p['last_error']=error
        with self.db() as c:c.execute('UPDATE jobs SET state=?,payload=?,next_at=?,updated=? WHERE id=?',(state,json.dumps(p,ensure_ascii=False),time.time()+delay,time.time(),jid))
    def cached_call(self,jid,stage,fn):
        rid=str(uuid.uuid5(uuid.NAMESPACE_URL,jid+':'+stage))
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT state,output FROM runs WHERE id=?',(rid,)).fetchone()
            if r:
                if r['state']=='complete':return json.loads(r['output'])
                if r['state']!='retryable':raise RuntimeError('Unresolved API request '+rid+'; do not repeat blindly')
            c.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,NULL)',(rid,jid,stage,'running',None,time.time()))
        try:
            result=fn(rid)
            with self.db() as c:c.execute("UPDATE runs SET state='complete',output=?,ended=? WHERE id=?",(json.dumps(result,ensure_ascii=False),time.time(),rid))
            return result
        except Exception as e:
            from .providers import RetryLater,ProviderRejected
            state='retryable' if isinstance(e,RetryLater) else 'blocked' if isinstance(e,ProviderRejected) else 'unknown'
            with self.db() as c:c.execute('UPDATE runs SET state=?,ended=? WHERE id=?',(state,time.time(),rid))
            raise
    def event(self,recipient,kind,evidence):
        if kind not in ('unsubscribe','hard_reject','reply'):raise ValueError('Invalid event')
        with self.db() as c:c.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',(recipient.lower(),kind,evidence,time.time()))
    def trace(self,aid,stage,detail):
        with self.db() as c:
            c.execute('INSERT INTO traces VALUES(?,?,?,?)',(aid,stage,json.dumps(detail),time.time()))
            c.execute('UPDATE attempts SET stage=?,result=coalesce(?,result),updated=? WHERE id=?',(stage,detail.get('result'),time.time(),aid))
    def claim_send(self,job,mid,sha):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]=='true':raise ValueError('Paused')
            if c.execute('SELECT 1 FROM attempts WHERE job_id=?',(job['id'],)).fetchone():raise ValueError('Job already submitted')
            if c.execute('SELECT 1 FROM events WHERE recipient=?',(job['recipient'],)).fetchone():raise ValueError('Reply, refusal or unsubscribe requires reconciliation')
            previous=c.execute("SELECT id,result FROM attempts WHERE company_key=? AND result IN ('accepted','unknown','in_progress')",(job['company_key'],)).fetchall()
            permit=c.execute('SELECT source_attempt FROM followups WHERE job_id=?',(job['id'],)).fetchone()
            if any(r['result']!='accepted' for r in previous) or (previous and not permit):raise ValueError('Company already contacted or outcome unknown')
            aid=str(uuid.uuid4());c.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)',(aid,job['id'],job['company_key'],job['recipient'],mid,'in_progress','claimed',sha,time.time()))
            return aid
    def status(self):
        with self.db() as c:
            return {'paused':self.setting('paused')!='false','jobs':[dict(r) for r in c.execute('SELECT id,brand,company_key,recipient,stage,state,updated FROM jobs ORDER BY updated DESC')],'attempts':[dict(r) for r in c.execute('SELECT * FROM attempts ORDER BY updated DESC')],'events':[dict(r) for r in c.execute('SELECT * FROM events ORDER BY at DESC')]}

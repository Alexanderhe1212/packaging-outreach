"""Private, append-only contact observations; no outreach integration."""
import csv
import io
import json
import os
import sqlite3
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

FIELDS=('id','website','name','title','email','mobile','whatsapp','sources','evidence_by_field','verified_at','saved_at','mobile_verified_personal','whatsapp_verified_personal','email_status','procurement_authority_confirmed','qualified','qualification_mode','source_job_id','contact_id','contact_kind','company','fit_reason','fit_source','batch_id')

def store_path():
    return Path(os.environ.get('USER_RADAR_CUSTOMER_DB',str(Path.home()/'Library/Application Support/UserRadar/customers.sqlite3')))

@contextmanager
def connection():
    path=store_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(str(path),timeout=15)
    os.chmod(str(path),0o600)
    db.execute('CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS history (sequence INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL)')
    try:
        with db:yield db
    finally:db.close()

def save(contact):
    host=(urlsplit(contact['website']).hostname or '').lower().removeprefix('www.')
    identifier=hashlib.sha256(('\0'.join((host,contact['name'].strip().casefold(),contact['email'].strip().casefold()))).encode()).hexdigest()[:32]
    now=datetime.now(timezone.utc).isoformat()
    item={k:contact.get(k,'') for k in FIELDS};item.update(id=identifier,saved_at=now)
    observed=json.dumps(item,ensure_ascii=False,sort_keys=True)
    with connection() as db:
        old=db.execute('SELECT payload FROM customers WHERE id=?',(identifier,)).fetchone()
        # A later observation lacking optional channels cannot erase a previously
        # sourced observation. History retains both snapshots and conflicting data.
        if old:
            prior=json.loads(old[0])
            if not item.get('title') and prior.get('title'):item['title']=prior['title']
            for field in ('mobile','whatsapp'):
                if not item[field] and prior.get(field):
                    item[field]=prior[field]
                    item.setdefault('evidence_by_field',{})[('phone' if field=='mobile' else field)]=prior.get('evidence_by_field',{}).get(('phone' if field=='mobile' else field),[])
            item['mobile_verified_personal']=bool(item['mobile'])
            item['whatsapp_verified_personal']=bool(item['whatsapp'])
            item['sources']=list(dict.fromkeys(prior.get('sources',[])+item.get('sources',[])))
        raw=json.dumps(item,ensure_ascii=False,sort_keys=True)
        db.execute('INSERT INTO history (customer_id,observed_at,payload) VALUES (?,?,?)',(identifier,now,observed))
        db.execute('INSERT OR REPLACE INTO customers (id,payload) VALUES (?,?)',(identifier,raw))
    return {'customer':item,'created':old is None}

def customers():
    with connection() as db:return [json.loads(row[0]) for row in db.execute('SELECT payload FROM customers ORDER BY rowid DESC')]

def export_csv():
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['官网','姓名','职位','邮箱','本人手机','本人WhatsApp','来源','核实时间','联系方式类型','公司'])
    def safe(value):
        text=str(value or '')
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    for p in customers():
        writer.writerow([safe(v) for v in (p['website'],p['name'],p['title'],p['email'],p['mobile'],'; '.join(w.get('url','') for w in p['whatsapp']),'; '.join(p['sources']),p['verified_at'],p.get('contact_kind') or 'person',p.get('company',''))])
    return ('\ufeff'+out.getvalue()).encode('utf-8')

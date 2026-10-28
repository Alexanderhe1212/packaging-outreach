"""Shared source evidence and content-addressed raster assets; no outbound calls."""
import hashlib,json,re,sqlite3,struct,time,zlib
from pathlib import Path
from urllib.parse import urlsplit
from .features import data_root,option
TTL={'signal':7,'product':14,'image':14,'email':30,'contact':30,'page':14,'prospect':14,'blocked':30}
def root():
 p=data_root()/'evidence';p.mkdir(parents=True,exist_ok=True);return p
def company_key(value):
 p=urlsplit(value if '://' in value else 'https://'+value)
 if not p.hostname or p.username or p.password:raise ValueError('invalid company URL')
 return p.hostname.lower().rstrip('.').removeprefix('www.').encode('idna').decode('ascii')
def connect():
 c=sqlite3.connect(str(root()/'evidence.sqlite3'),timeout=15)
 c.execute('CREATE TABLE IF NOT EXISTS evidence(company_key TEXT,kind TEXT,item_key TEXT,payload TEXT,source_url TEXT,quote TEXT,confidence REAL,fetched_at REAL,http_status INTEGER,expires_at REAL,PRIMARY KEY(company_key,kind,item_key))')
 return c
def put(domain,kind,payload,source_url,quote='',confidence=1.0,now=None,key='',http_status=200):
 now=time.time() if now is None else now
 p=urlsplit(source_url)
 if p.scheme not in ('https','http') or p.username or p.password or not p.hostname:raise ValueError('public source URL required')
 ttl=float(option('evidence_ttl_days',{}).get(kind,TTL.get(kind,14)))*86400
 if not 0<ttl<=365*86400:raise ValueError('invalid TTL')
 c=connect()
 try:
  with c:c.execute('INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?)',(company_key(domain),kind,key,json.dumps(payload),source_url,str(quote)[:8000],max(0,min(1,float(confidence))),now,http_status,now+ttl))
 finally:c.close()
def get(domain,kind,key='',now=None):
 c=connect();c.row_factory=sqlite3.Row
 try:
  row=c.execute('SELECT * FROM evidence WHERE company_key=? AND kind=? AND item_key=? AND expires_at>? AND http_status=200',(company_key(domain),kind,key,time.time() if now is None else now)).fetchone()
  if not row:return None
  result=dict(row);result['payload']=json.loads(result['payload']);return result
 finally:c.close()
def image_info(raw):
 if not isinstance(raw,bytes) or not 32<=len(raw)<=15*1024*1024:raise ValueError('image size outside limit')
 if raw.startswith(b'\x89PNG\r\n\x1a\n'):
  pos=8;w=h=None;ended=False
  while pos+12<=len(raw):
   n=struct.unpack('!I',raw[pos:pos+4])[0];kind=raw[pos+4:pos+8];end=pos+8+n
   if end+4>len(raw) or zlib.crc32(raw[pos+4:end])&0xffffffff!=struct.unpack('!I',raw[end:end+4])[0]:raise ValueError('invalid PNG')
   if kind==b'IHDR':
    if n!=13:raise ValueError('invalid PNG header')
    w,h=struct.unpack('!II',raw[pos+8:pos+16])
   pos=end+4
   if kind==b'IEND':ended=True;break
  if not ended or pos!=len(raw):raise ValueError('invalid PNG end')
  mime='image/png'
 elif raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'):
  pos=2;w=h=None
  while pos+4<len(raw):
   if raw[pos]!=255:break
   marker=raw[pos+1];pos+=2
   if marker in (0xd8,0xd9):continue
   n=int.from_bytes(raw[pos:pos+2],'big')
   if n<2 or pos+n>len(raw):raise ValueError('invalid JPEG')
   if marker in (0xc0,0xc1,0xc2):
    if n<7:raise ValueError('invalid JPEG header')
    h,w=struct.unpack('!HH',raw[pos+3:pos+7]);break
   pos+=n
  mime='image/jpeg'
 else:raise ValueError('only verified PNG/JPEG raster images supported; SVG rejected')
 if not w or not h or max(w,h)>4096 or w*h>16000000:raise ValueError('image dimensions outside limit')
 return {'mime':mime,'bytes':len(raw),'width':w,'height':h}
def save_asset(raw,source_url,now=None):
 info=image_info(raw);p=urlsplit(source_url)
 if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:raise ValueError('invalid image source')
 digest=hashlib.sha256(raw).hexdigest();folder=root()/'assets';folder.mkdir(exist_ok=True)
 path=folder/digest
 if path.is_symlink():raise ValueError('symlink asset rejected')
 if not path.exists():
  import os
  fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as f:f.write(raw)
 return dict(info,sha256=digest,source_url=source_url,verified_at=time.time() if now is None else now)
def read_asset(ref):
 digest=ref.get('sha256','')
 if not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid asset reference')
 folder=(root()/'assets').resolve();path=folder/digest
 if path.is_symlink() or path.resolve().parent!=folder:raise ValueError('unsafe asset path')
 raw=path.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('asset hash mismatch')
 info=image_info(raw)
 if any(ref.get(k)!=v for k,v in info.items()):raise ValueError('asset metadata mismatch')
 return raw
def save_prospect(p,photo,now=None):
 if not p.get('email_verified') or not p.get('product_name') or not p.get('product_url'):raise ValueError('incomplete evidence')
 value=dict(p);ref=save_asset(photo,p.get('product_image_url') or p['product_url'],now)
 value['product_asset']=ref
 domain=p['domain'];source=p.get('email_source') or p['website']
 put(domain,'email',{'email':p['email']},source,p.get('recipient_source_context') or p['email'],now=now)
 put(domain,'product',{'name':p['product_name'],'url':p['product_url']},p['product_url'],p.get('product_description',''),now=now)
 put(domain,'image',ref,ref['source_url'],now=now)
 put(domain,'prospect',value,p['website'],p.get('site_description',''),now=now)
 return value
def load_prospect(url,email_hint='',now=None):
 row=get(url,'prospect',now=now)
 if not row:return None
 p=row['payload'];e=get(url,'email',now=now);product=get(url,'product',now=now);img=get(url,'image',now=now)
 if not all((e,product,img)) or not p.get('email_verified'):return None
 if (email_hint and email_hint.casefold()!=p['email'].casefold()) or e['payload']['email']!=p['email']:return None
 if product['payload']['url']!=p['product_url']:return None
 # A user-selected product page must never silently reuse another product.
 requested=urlsplit(url if '://' in url else 'https://'+url)
 if requested.path.strip('/') and url.rstrip('/') not in (p.get('website','').rstrip('/'),p['product_url'].rstrip('/')):return None
 return p,read_asset(img['payload'])

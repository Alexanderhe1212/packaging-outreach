"""Exercise the existing worker with fictional boundary adapters. Never sends SMTP."""
import argparse,json,os,tempfile,time,struct,zlib
from contextlib import ExitStack
from unittest.mock import patch
from . import config,store,radar,pipeline,web,llm,mailer
from .worker import AccountWorker

def sample_png():
 def chunk(k,v):return struct.pack('!I',len(v))+k+v+struct.pack('!I',zlib.crc32(k+v)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xdd\xaa\x88'*128)*128))+chunk(b'IEND',b'')

def run_mock(count=20):
 # Refuse accidental execution against an installed database, including direct Python calls.
 root=config.data_dir().resolve()
 if 'Application Support' in root.parts or not os.environ.get('OUTREACH_DATA'):raise ValueError('dry-run requires an explicit isolated data directory')
 import importlib.util
 source=config.ROOT/'userradar/customer_store.py'
 import sys
 if str(source.parent) not in sys.path:sys.path.insert(0,str(source.parent))
 spec=importlib.util.spec_from_file_location('dryrun_customer_store',source);cs=importlib.util.module_from_spec(spec);spec.loader.exec_module(cs)
 acc={'id':'MOCK','sender':'sender@mock.invalid','company_name':'Mock Packaging','signature':'Mock Packaging','profile':'packaging','auto_send':False}
 rows=[];started=time.monotonic();photo=sample_png()
 prof=config.profile('packaging');prof=dict(prof,image={'enabled':True})
 def model(_self,system,user,**kwargs):
  if 'Extract the real person' in system:return {'name':'','email':'','quote':''}
  if 'Review this packaging' in system:return {'approved':True,'reason':'synthetic fixture'}
  return {'subject':'Packaging for your candle','body':'Hi there,\n\nYour published candle range uses glass jars. If protection during gifting is a priority, a fitted paper insert could help. We are Mock Packaging and make custom gift boxes. Would a sample of the proposed structure be useful?', 'a':{'name':'Folding carton','structure':'carton','visual':'fitted insert'},'b':{'name':'Rigid box','structure':'rigid','visual':'fitted insert'}}
 with ExitStack() as stack:
  stack.enter_context(patch.object(config,'account',return_value=acc));stack.enter_context(patch.object(config,'profile',return_value=prof))
  stack.enter_context(patch.object(config,'load',return_value={'accounts':[acc]}))
  stack.enter_context(patch.object(llm.Stage,'__init__',lambda self,stage,account='',cfg=None:None));stack.enter_context(patch.object(llm.Stage,'json',model));stack.enter_context(patch.object(llm.Stage,'image',return_value=photo))
  stack.enter_context(patch.object(mailer,'send',side_effect=AssertionError('SMTP forbidden in dry-run')))
  stack.enter_context(patch.object(web,'product_image',return_value=(photo,'https://mock.invalid/product.png')))
  stack.enter_context(patch.object(web,'page',return_value=('<html>Public company contact</html>','https://mock.invalid/contact')))
  worker=AccountWorker('MOCK');store.put('paused_MOCK',False)
  for i in range(count):
   tick=time.monotonic();domain='fixture%02d.invalid'%i;url='https://'+domain
   contact={'id':domain,'website':url,'name':'','email':'sales@'+domain,'contact_kind':'company_public','company':'Fixture %02d'%i,'sources':[url+'/contact']}
   store.event(None,'verify','completed','MOCK_PUBLIC_EVIDENCE','MOCK')
   with patch.dict(os.environ,USER_RADAR_CUSTOMER_DB=str(root/'mock-customers.sqlite3')):
    saved=cs.save(dict(contact,whatsapp=[],evidence_by_field={}))
   contact['id']=saved['customer']['id']
   store.event(None,'save','completed','MOCK_CONTACT_SAVED','MOCK')
   with patch.object(radar,'contacts',return_value=[contact]):ids=radar.import_contacts({'account':'MOCK','contact_ids':[contact['id']]},held=False)['ids']
   if not ids:rows.append({'company':domain,'result':'protected'});continue
   lid=ids[0];store.event(lid,'handoff','completed','MOCK_HANDOFF','MOCK')
   prospect={'company':contact['company'],'domain':domain,'website':url,'email':contact['email'],'email_verified':True,'email_source':'','product_name':'Glass candle','product_url':url+'/candle','product_image_url':url+'/product.png','category':'candles','description':'Glass candle for gifting'}
   with patch.object(web,'crawl',return_value=prospect):worker.process(store.lead(lid),None)
   lead=store.lead(lid);result=worker.send(lead,dry_run=True) if lead['status']=='ready' else lead['error']
   rows.append({'company':domain,'lead_id':lid,'result':result,'duration_ms':round((time.monotonic()-tick)*1000,2)})
 return {'mode':'mock','companies':rows,'ready':sum(r['result']=='dry_run_ready' for r in rows),'seconds':round(time.monotonic()-started,3),'smtp_attempts':len(store.q('SELECT * FROM send_attempts'))}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--live-read',action='store_true',default=False);ap.add_argument('--url');ap.add_argument('--count',type=int,default=20);args=ap.parse_args()
 if args.live_read:
  # Explicit opt-in entrypoint; deliberately never imports/starts workers here.
  if not args.url:ap.error('--live-read requires --url')
  if not os.environ.get('OUTREACH_DATA') or 'Application Support' in config.data_dir().resolve().parts:ap.error('use an isolated OUTREACH_DATA')
  result=web.crawl(args.url)
  print(json.dumps({'mode':'live-read','prospect':result,'image_generation':False,'sending':False},ensure_ascii=False));return
 with tempfile.TemporaryDirectory(prefix='pipeline-dryrun-') as tmp:
  os.environ['OUTREACH_DATA']=tmp;store.close();print(json.dumps(run_mock(args.count),ensure_ascii=False));store.close()
if __name__=='__main__':main()

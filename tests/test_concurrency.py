import os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from email.message import EmailMessage
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from outreach import store,config,mailer,server,llm
from outreach.worker import AccountWorker
class SafetyTests(unittest.TestCase):
 def setUp(self):
  self.old=os.environ.get('OUTREACH_DATA');self.tmp=tempfile.TemporaryDirectory();os.environ['OUTREACH_DATA']=self.tmp.name;store.close()
  config.save({'cross_account_dedupe':True,'accounts':[dict(id=a,sender=a.lower()+'@supplier.test',profile='packaging',daily_limit=30,send_interval_minutes=[4,9],auto_send=False,followup_enabled=False) for a in ['MTT','GUKA']]})
  self.ws={a:AccountWorker(a) for a in ['MTT','GUKA']}
  for w in self.ws.values():w.set_paused(False)
  self.calls=[]
 def tearDown(self):
  for w in self.ws.values():w.stopped=True;w.wake.set()
  for w in self.ws.values():
   if w.is_alive():w.join(3)
  store.close()
  if self.old is None:os.environ.pop('OUTREACH_DATA',None)
  else:os.environ['OUTREACH_DATA']=self.old
  self.tmp.cleanup()
 def lead(self,a='MTT',domain='brand.test',company='Brand'):
  i=store.add_lead(a,'ready',company=company,email='hello@'+domain,domain=domain,data={'prospect':{'product_name':'Serum','product_url':'https://brand.test/products/serum'}});store.update(i,subject='Packaging',body='Concept');return store.lead(i)
 def build(self,acc,lead,img=None):
  m=EmailMessage();m['Message-ID']='<%s-%s@test>'%(lead['id'],time.time_ns());m['From']=acc['sender'];m['To']=lead['email'];m.set_content('test');return m
 def transport(self,a,m,before_data=None):
  if before_data and not before_data():return 'blocked','changed'
  self.calls.append((a['id'],str(m['To'])));return 'sent',''
 def mocks(self):return patch.multiple(mailer,build=self.build,send=self.transport,save_eml=lambda *a,**k:None)
 def test_atomic_company_claim(self):
  bar=threading.Barrier(2);out=[]
  def run(a):bar.wait();out.append(store.claim_prospect(a,dict(company='BRAND & Co',domain='www.brand.test',email=' Hello@Brand.test ')))
  ts=[threading.Thread(target=run,args=(a,)) for a in self.ws];[t.start() for t in ts];[t.join() for t in ts];self.assertEqual(sum(x is not None for x in out),1)
 def test_duplicate_racing_send(self):
  a=self.lead();b=self.lead('GUKA','www.brand.test');bar=threading.Barrier(2);out=[]
  def run(l):bar.wait();out.append(self.ws[l['account']].send(l,manual=True))
  with self.mocks():
   ts=[threading.Thread(target=run,args=(l,)) for l in [a,b]];[t.start() for t in ts];[t.join() for t in ts]
  self.assertEqual(len(self.calls),1);self.assertIn('sent',out)
 def test_interval_quota_and_api(self):
  a=self.lead();b=self.lead(domain='other.test',company='Other');w=self.ws['MTT']
  with self.mocks(),patch.dict(server.WORKERS,self.ws,clear=True):
   self.assertEqual(w.send(a,manual=True),'sent')
   with self.assertRaises(ValueError):server.api_send({'id':b['id'],'_origin':{'source':'ui','request_id':'test'}})
   self.assertEqual(w.send(b),'interval');store.put('next_send_MTT',0);cfg=config.load();cfg['accounts'][0]['daily_limit']=1;config.save({'accounts':cfg['accounts']});self.assertEqual(w.send(b,manual=True),'daily_limit')
  self.assertEqual(len(self.calls),1);self.assertTrue(store.q("select 1 from audit where source='ui' and result='interval'"))
 def test_cross_account_suppression(self):
  for kind in ['unsubscribe','bounce','reply','unknown']:
   l=self.lead(domain=kind+'.test',company=kind);store.suppress(l['email'],kind,'GUKA')
   with self.mocks():self.assertEqual(self.ws['MTT'].send(l,manual=True),'suppressed')
  self.assertFalse(self.calls)
 def test_unknown_after_acceptance_no_retry(self):
  l=self.lead()
  def uncertain(a,m,before_data=None):self.calls.append(a['id']);raise TimeoutError()
  with self.mocks(),patch.object(mailer,'send',uncertain):
   self.assertEqual(self.ws['MTT'].send(l,manual=True),'unknown');self.assertEqual(self.ws['MTT'].send(l,manual=True),'not_ready')
  self.assertEqual(len(self.calls),1)
 def test_search_timeout_other_account_continues(self):
  entered=threading.Event();release=threading.Event();other=threading.Event()
  def discover(a,p):
   if a['id']=='MTT':entered.set();release.wait(2);raise llm.AIError('simulated timeout')
   other.set();return 0
  with patch('outreach.pipeline.discover',discover),patch.object(AccountWorker,'check_inbox',lambda s:None):
   self.ws['MTT'].start();self.assertTrue(entered.wait(1));self.ws['GUKA'].start();self.assertTrue(other.wait(1));release.set()
 def test_hung_send_other_account_continues(self):
  a=self.lead();b=self.lead('GUKA','other.test','Other');entered=threading.Event();release=threading.Event()
  def transport(acc,msg,before_data=None):
   if acc['id']=='MTT':entered.set();release.wait(2)
   return self.transport(acc,msg,before_data)
  with self.mocks(),patch.object(mailer,'send',transport):
   t=threading.Thread(target=lambda:self.ws['MTT'].send(a,manual=True));t.start();self.assertTrue(entered.wait(1));self.assertEqual(self.ws['GUKA'].send(b,manual=True),'sent');release.set();t.join(2)
  self.assertEqual(len(self.calls),2)
 def test_auth_no_fallback(self):
  l=self.lead()
  def auth(a,m,before_data=None):self.calls.append(a['id']);raise mailer.MailAuthError('auth')
  with self.mocks(),patch.object(mailer,'send',auth):
   with self.assertRaises(mailer.MailAuthError):self.ws['MTT'].send(l,manual=True)
  self.assertEqual(self.calls,['MTT']);self.assertTrue(self.ws['MTT'].paused)
 def test_new_suppression_before_data(self):
  l=self.lead()
  def trans(a,m,before_data=None):store.suppress(l['email'],'unsubscribe','GUKA');return self.transport(a,m,before_data)
  with self.mocks(),patch.object(mailer,'send',trans):self.assertEqual(self.ws['MTT'].send(l,manual=True),'blocked')
  self.assertFalse(self.calls)
 def test_restart_no_retry(self):
  l=self.lead();token,r=store.reserve_send(l['id'],config.account('MTT'),'<test@test>');self.assertTrue(token);store.reset_interrupted();self.assertEqual(store.lead(l['id'])['status'],'unknown')
  with self.mocks():self.assertEqual(self.ws['MTT'].send(l,manual=True),'not_ready')
 def test_retry_and_bounce_respect_full_interval(self):
  a=self.lead();b=self.lead(domain='second.test',company='Second')
  for result in ['retry','bounced']:
   store.update(a['id'],status='ready',message_id='',sent_at=None);store.put('next_send_MTT',0)
   with self.mocks(),patch.object(mailer,'send',lambda *args,**kw:(result,'test')):
    self.assertEqual(self.ws['MTT'].send(a,manual=True),result)
   self.assertGreaterEqual(store.get('next_send_MTT')-time.time(),239)
   with self.mocks():self.assertEqual(self.ws['MTT'].send(b,manual=True),'interval')
 def test_total_quota_reserves_inflight(self):
  config.save({'daily_limit_total':1});a=self.lead();b=self.lead('GUKA','other.test','Other')
  token,_=store.reserve_send(a['id'],config.account('MTT'),'<one@test>');self.assertTrue(token)
  with self.mocks():self.assertEqual(self.ws['GUKA'].send(b,manual=True),'total_limit')
 def test_inflight_mutations_blocked(self):
  l=self.lead();store.update(l['id'],status='sending')
  for fn in [server.api_skip,server.api_redo,server.api_edit]:
   with self.assertRaises(ValueError):fn({'id':l['id']})
 def test_mailer_data_timeout_no_second_transmission(self):
  l=self.lead();calls=[]
  class SMTP:
   def mail(s,x):return 250,b'ok'
   def rcpt(s,x):return 250,b'ok'
   def data(s,x):calls.append(x);raise TimeoutError()
   def quit(s):pass
  with patch.object(mailer,'smtp_connect',lambda a:SMTP()),patch.object(mailer,'build',self.build),patch.object(mailer,'save_eml',lambda *a,**k:None):
   self.assertEqual(self.ws['MTT'].send(l,manual=True),'unknown')
   self.assertEqual(self.ws['MTT'].send(l,manual=True),'not_ready')
  self.assertEqual(len(calls),1)
if __name__=='__main__':unittest.main()

"""Shared rolling 7x24-hour gates, verified-history reuse and unlimited quota."""
import json,os,tempfile,threading,time,unittest
from unittest.mock import patch
from outreach import config,store,server,mailer,pipeline
from outreach.worker import AccountWorker

class CooldownTests(unittest.TestCase):
 def setUp(self):
  self.old=os.environ.get('OUTREACH_DATA');self.tmp=tempfile.TemporaryDirectory();os.environ['OUTREACH_DATA']=self.tmp.name;store.close()
  config.save({'cross_account_dedupe':False,'daily_limit_total':0,'accounts':[{'id':a,'sender':a.lower()+'@supplier.test','profile':'packaging','daily_limit':0,'send_interval_minutes':[4,9],'auto_send':False,'followup_enabled':True} for a in ['MTT','GUKA']]})
  for a in ['MTT','GUKA']:store.put('paused_'+a,False)
  self.now=1800000000.;self.clock=patch.object(store.time,'time',return_value=self.now);self.clock.start()
 def tearDown(self):
  self.clock.stop();store.close()
  if self.old is None:os.environ.pop('OUTREACH_DATA',None)
  else:os.environ['OUTREACH_DATA']=self.old
  self.tmp.cleanup()
 def old_lead(self,age,status='sent'):
  p={'company':'Brand & Co','customer_brand':'Brand & Co','email':'hello@brand.test','domain':'brand.test','email_verified':True,'product_name':'Serum','product_url':'https://brand.test/products/serum','discovery_evidence':{'opportunity_tier':'A'}}
  lid=store.add_lead('MTT',status,company=p['company'],email=p['email'],domain=p['domain'],data={'prospect':p})
  store.update(lid,sent_at=self.now-age,message_id='<old@test>',subject='Previous subject',body='Previous body')
  for k in store.identity_keys(p['email'],p['domain'],p['company']):store.x('INSERT OR REPLACE INTO identity_claims VALUES(?,?)',(k,lid))
  return lid
 def fresh(self,account='GUKA'):
  lid=store.add_lead(account,'ready',company='BRAND & CO',email='hello@brand.test',domain='www.brand.test');store.update(lid,subject='New project question',body='New useful angle');return lid
 def reserve(self,lid,account='GUKA',followup=False):return store.reserve_send(lid,config.account(account),'<new@test>',followup=followup)
 def test_six_days_23_hours_blocked_all_accounts(self):
  self.old_lead(7*86400-3600);self.assertTrue(store.blocked(' HELLO@brand.test ','www.brand.test','GUKA'));self.assertEqual(self.reserve(self.fresh())[1],'cooldown')
 def test_exact_seven_days_releases_old_claims(self):
  old=self.old_lead(7*86400);self.assertFalse(store.blocked('hello@brand.test','brand.test','GUKA'));token,reason=self.reserve(self.fresh());self.assertTrue(token,reason);self.assertEqual(store.lead(old)['status'],'sent')
 def test_more_than_seven_days_allowed(self):
  self.old_lead(8*86400);self.assertTrue(self.reserve(self.fresh())[0])
 def test_latest_send_wins_over_older_contact(self):
  self.old_lead(9*86400);self.old_lead(86400);self.assertEqual(self.reserve(self.fresh())[1],'cooldown')
 def test_followup_uses_same_window_and_resets_clock(self):
  old=self.old_lead(6*86400);self.assertEqual(self.reserve(old,'MTT',True)[1],'cooldown')
  store.update(old,sent_at=self.now-7*86400);token,r=self.reserve(old,'MTT',True);self.assertTrue(token,r);store.finish_send(token,'sent','',self.now+300)
  self.assertEqual(self.reserve(self.fresh())[1],'cooldown')
 def test_atomic_cross_account_after_window(self):
  self.old_lead(8*86400);a=self.fresh('MTT');b=self.fresh();bar=threading.Barrier(2);results=[]
  def go(lid,account):bar.wait();results.append(self.reserve(lid,account))
  ts=[threading.Thread(target=go,args=(a,'MTT')),threading.Thread(target=go,args=(b,'GUKA'))]
  for t in ts:t.start()
  for t in ts:t.join(3)
  self.assertEqual(sum(bool(x[0]) for x in results),1)
 def test_unsubscribe_refusal_bounce_unknown_never_expire(self):
  for kind in ['unsubscribe','hard_reject','bounce','bounced','unknown']:
   with self.subTest(kind=kind):
    store.suppress('hello@brand.test',kind,'MTT');self.assertEqual(self.reserve(self.fresh())[1],'suppressed');store.x('DELETE FROM suppress')
    store.x("UPDATE leads SET status='skipped'")
 def test_unknown_attempt_survives_status_change(self):
  old=self.old_lead(9*86400,'unknown');store.update(old,status='skipped')
  store.x("INSERT INTO send_attempts(id,lead,account,result,started) VALUES(?,?,?,?,?)",('unknown-id',old,'MTT','unknown',self.now-9*86400))
  self.assertEqual(self.reserve(self.fresh())[1],'unknown')
 def test_customer_pause_future_contact_and_reply(self):
  old=self.old_lead(9*86400);fresh=self.fresh();d=store.lead(old)['data'];d['contact_policy']={'paused':True};store.update(old,data=d);self.assertEqual(self.reserve(fresh)[1],'customer_paused')
  d['contact_policy']={'recontact_after':self.now+86400};store.update(old,data=d);self.assertEqual(self.reserve(fresh)[1],'future_contact')
  d['contact_policy']={'recontact_after':self.now-1};store.update(old,data=d);store.update(old,reply_at=self.now-86400);self.assertEqual(self.reserve(fresh)[1],'reply_context_required')
 def test_unlimited_not_fake_large_number(self):
  for i in range(35):
   lid=store.add_lead('GUKA','sent',company='Other '+str(i),email='x@other%d.test'%i,domain='other%d.test'%i);store.update(lid,sent_at=self.now-30)
  self.assertEqual(config.account('GUKA')['daily_limit'],0);self.assertTrue(self.reserve(self.fresh())[0])
 def test_pre_data_rechecks_new_suppression(self):
  old=self.old_lead(8*86400);token,r=self.reserve(self.fresh());self.assertTrue(store.transport_allowed(token));store.suppress('brand.test','unsubscribe');self.assertFalse(store.transport_allowed(token))
 def test_history_reused_once_without_rewriting_sent_record(self):
  old=self.old_lead(8*86400);before=store.lead(old);new=store.queue_recontact('MTT');self.assertIsNotNone(new)
  fresh=store.lead(new);self.assertEqual(fresh['status'],'queued');self.assertEqual(fresh['subject'],'');self.assertEqual(fresh['data']['prospect']['prior_contact']['body'],'Previous body');self.assertEqual(store.lead(old),before);self.assertIsNone(store.queue_recontact('MTT'))
  store.update(new,status='backlog');self.assertIsNone(store.queue_recontact('MTT'),'do not re-research the same failed evidence every loop')
 def test_candidate_can_return_after_window(self):
  old=self.old_lead(8*86400);store.x("INSERT INTO candidates(domain,account,status,created_at) VALUES(?,?,?,?)",('brand.test','MTT','used',self.now-8*86400))
  self.assertEqual(store.add_candidates('GUKA',[{'domain':'brand.test','brand':'Brand & Co','opportunity_tier':'A'}]),1);self.assertEqual(store.claim_candidate('GUKA')['domain'],'brand.test')
 def test_immediate_api_cannot_bypass_window(self):
  self.old_lead(6*86400);lid=self.fresh();w=AccountWorker('GUKA')
  with patch.dict(server.WORKERS,{'GUKA':w},clear=True),patch.object(mailer,'build',return_value={'Message-ID':'<x@test>'}),patch.object(mailer,'send') as send:
   with self.assertRaisesRegex(ValueError,'7天'):server.api_send({'id':lid})
   send.assert_not_called()
 def test_same_body_rejected(self):
  p={'prior_contact':{'body':'Hello, same previous body that should not be sent again.'}}
  plan={'subject':'Hello','body':p['prior_contact']['body']*3}
  p['prior_contact']['body']=plan['body']
  with patch.object(pipeline,'writer_prompts',return_value=('system','user')),patch.object(pipeline.llm,'Stage') as stage:
   stage.return_value.json.return_value=plan
   with self.assertRaisesRegex(ValueError,'原文'):pipeline.write(config.account('GUKA'),{},p,None)

 def test_retry_obeys_interval_without_erasing_prior_send(self):
  old=self.old_lead(8*86400);fresh=self.fresh();before=store.lead(old)
  token,reason=self.reserve(fresh);self.assertTrue(token,reason);store.finish_send(token,'retry','temporary refusal',self.now+300)
  self.assertEqual(self.reserve(fresh)[1],'interval');self.assertEqual(store.lead(old),before)
  store.put('next_send_GUKA',self.now);self.assertTrue(self.reserve(fresh)[0])
 def test_scheduler_cannot_bypass_window(self):
  self.old_lead(6*86400);self.fresh();cfg=config.load();cfg['accounts'][1]['auto_send']=True;config.save({'accounts':cfg['accounts']});w=AccountWorker('GUKA')
  with patch.object(mailer,'build',return_value={'Message-ID':'<scheduler@test>'}),patch.object(mailer,'send') as send:
   w.step(block=False);send.assert_not_called()
  self.assertEqual(store.q("select result from audit order by id desc limit 1",one=True)['result'],'cooldown')
 def test_expired_company_claim_race(self):
  self.old_lead(8*86400);bar=threading.Barrier(2);results=[]
  def claim(a):
   bar.wait();results.append(store.claim_prospect(a,{'company':'BRAND & CO','domain':'brand.test','email':'hello@brand.test'}))
  ts=[threading.Thread(target=claim,args=(a,)) for a in ['MTT','GUKA']]
  for t in ts:t.start()
  for t in ts:t.join(3)
  self.assertEqual(sum(x is not None for x in results),1)

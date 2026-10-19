import json,time,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_bridge import BridgeTest,store,config
from outreach import radar,prospect_filter,worker,mailer,web,recommendation
from radar_automation import recheck_queue

class FlowRecovery(BridgeTest):
 def test_rate_wait_does_not_consume_ai_capacity(self):
  for i in range(12):store.add_lead('A','queued',data={'research_retry_at':time.time()+3600})
  store.add_lead('A','queued',data={'research_retry_at':time.time()-10})
  store.add_lead('A','queued');store.add_lead('A','ready')
  stats=store.stats('A');self.assertEqual(stats['deferred_research'],12);self.assertEqual(stats['actionable_pending'],2);self.assertEqual(stats['due_research_retries'],1)
 def failed(self):
  return store.add_lead('A','failed',source='user_radar',domain='example.com',email='old@example.com',data={'research_retry_at':time.time()+3600})
 def test_handoff_preserves_retry_deadline_and_account(self):
  lid=self.failed();before=store.lead(lid)['data']['research_retry_at']
  r=radar.recheck_handoff({'lead_id':lid,'contact_id':'person'})
  lead=store.lead(lid);self.assertEqual(r['status'],'queued');self.assertEqual(lead['account'],'A');self.assertEqual(lead['data']['manual']['email'],'jane@example.com');self.assertEqual(lead['data']['research_retry_at'],before)
  self.assertEqual(radar.recheck_handoff({'lead_id':lid,'contact_id':'person'})['status'],'already_active')
 def test_protected_history_cannot_be_requeued(self):
  for status in ('sent','unknown','bounced','replied','unsubscribed'):
   lid=self.failed();store.update(lid,status=status)
   self.assertEqual(radar.recheck_handoff({'lead_id':lid,'contact_id':'person'})['status'],'protected')
   self.assertEqual(store.lead(lid)['status'],status)
 def test_recheck_domain_cannot_change(self):
  lid=self.failed();store.update(lid,domain='other.test')
  with self.assertRaises(ValueError):radar.recheck_handoff({'lead_id':lid,'contact_id':'person'})
 def test_machinery_blocked_before_mail_transport(self):
  lid=store.add_lead('A','ready',data={'prospect':{'company':'Example Packaging Machinery'}})
  with patch.object(mailer,'build') as build:
   self.assertEqual(worker.AccountWorker('A').send(store.lead(lid)),'non_target_business')
  build.assert_not_called();self.assertEqual(store.lead(lid)['status'],'skipped')

class Classification(unittest.TestCase):
 def test_explicit_equipment_supplier_excluded(self):
  self.assertTrue(prospect_filter.reason('Example','We manufacture filling and packaging machines for cosmetics.'))
 def test_consumer_brand_using_machines_retained(self):
  self.assertFalse(prospect_filter.reason('Example Skincare','We make skincare. Our filling machines package our own serum.'))
 def test_nail_drills_are_consumer_products(self):
  self.assertFalse(prospect_filter.reason('Example Beauty','Manufacturer of nail drills and beauty appliances.'))

class RecheckQueue(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'queue.json'
 def tearDown(self):self.temp.cleanup()
 def write(self,items):self.path.write_text(json.dumps({'items':items}))
 def read(self):return json.loads(self.path.read_text())['items']
 def test_done_saved_before_handoff_then_next_query(self):
  self.write([{'id':1,'status':'researching','job':{'id':'j'}},{'id':2,'status':'pending','website':'https://brand.test'}])
  calls=[]
  def fetch(route,data=None):
   calls.append(route)
   return {'id':'new'} if data else {'status':'done','report':{'emails':[]}}
  def save(*_):calls.append('save');return {'contact_ids':['c'],'emails':['x@brand.test']}
  def handoff(*_):calls.append('handoff');return {'status':'queued'}
  recheck_queue.step(self.path,fetch,save,handoff);self.assertEqual(self.read()[0]['status'],'completed_handoff');self.assertEqual(calls[-1],'handoff')
  recheck_queue.step(self.path,fetch,save,handoff);self.assertEqual(calls[-1],'/api/research-start');self.assertEqual(calls.count('save'),1)
 def test_existing_active_handoff_does_not_block_remaining_sites(self):
  self.write([{'id':1,'status':'saved_waiting','saved_contact_ids':['c']},{'id':2,'status':'pending','website':'https://brand.test'}])
  result=recheck_queue.step(self.path,lambda *a:{'id':'new'},lambda *a:None,lambda *a:{'status':'already_active'})
  self.assertEqual(result['id'],2);self.assertEqual(self.read()[0]['status'],'saved_waiting')
 def test_network_poll_failure_does_not_restart_job(self):
  self.write([{'id':1,'status':'researching','job':{'id':'j'}}])
  def fetch(*_):raise TimeoutError()
  with self.assertRaises(TimeoutError):recheck_queue.step(self.path,fetch,None,None)
  self.assertEqual(self.read()[0]['job']['id'],'j')
 def test_no_email_result_finishes_without_handoff(self):
  self.write([{'id':1,'status':'researching','job':{'id':'j'}}])
  def handoff(*_):raise AssertionError('must not hand off empty report')
  recheck_queue.step(self.path,lambda *a:{'status':'done','report':{}},lambda *a:{'contact_ids':[]},handoff)
  self.assertEqual(self.read()[0]['status'],'completed_no_email')

 def test_interrupted_start_requires_review_without_duplicate_query(self):
  self.write([{'id':1,'status':'starting'}])
  def fetch(*_):raise AssertionError('must not restart an ambiguous job')
  result=recheck_queue.step(self.path,fetch,None,None)
  self.assertEqual(result['status'],'review_required')
  self.assertEqual(self.read()[0]['status'],'completed_review_required')

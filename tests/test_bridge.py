import os,sys,tempfile,unittest
from unittest.mock import patch
from outreach import radar,store,config
class BridgeTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,OUTREACH_DATA=self.tmp.name);self.env.start();store.close()
  config.save({'accounts':[{'id':'A'},{'id':'B'}]})
  store.put('paused_A',False);store.put('paused_B',False)
  self.rows=[dict(id='person',website='https://example.com/',name='Jane Smith',email='jane@example.com',company='Example',qualified=True,sources=['https://example.com/contact']),dict(id='shared',website='https://example.com/',name='',email='info@example.com',company='Example',contact_kind='company_public',sources=['https://example.com/contact'])]
  self.mock=patch.object(radar,'contacts',return_value=self.rows);self.mock.start()
 def tearDown(self):self.mock.stop();store.close();self.env.stop();self.tmp.cleanup()
 def test_held_and_named_priority(self):
  r=radar.import_contacts({'account':'A','contact_ids':['shared','person']});self.assertEqual(len(r['ids']),1)
  p=store.lead(r['ids'][0]);self.assertEqual(p['status'],'radar_review');self.assertEqual(p['email'],'jane@example.com');self.assertIsNone(store.next_lead('A',('queued',)))
 def test_cross_account_duplicate(self):
  radar.import_contacts({'account':'A','contact_ids':['person']})
  self.assertEqual(radar.import_contacts({'account':'B','contact_ids':['shared']})['ids'],[])
 def test_wrong_account_cannot_release(self):
  ids=radar.import_contacts({'account':'A','contact_ids':['person']})['ids']
  with self.assertRaises(ValueError):radar.release({'account':'B','ids':ids})
 def test_release_uses_standard_pipeline(self):
  ids=radar.import_contacts({'account':'A','contact_ids':['person']})['ids'];radar.release({'account':'A','ids':ids})
  p=store.next_lead('A',('queued',));self.assertEqual(p['data']['manual']['email'],'jane@example.com');self.assertEqual(p['data']['manual']['radar']['name'],'Jane Smith')
 def test_suppression_after_import_blocks_release(self):
  ids=radar.import_contacts({'account':'A','contact_ids':['person']})['ids']
  store.x('INSERT INTO suppress(value,kind) VALUES(?,?)',('example.com','unsubscribe'))
  self.assertEqual(radar.release({'account':'A','ids':ids})['ids'],[])
 def test_auto_off_and_account_isolated(self):
  self.assertIsNone(radar.pull_one('A'));radar.configure({'account':'A','enabled':True});self.assertIsNone(radar.pull_one('B'))
  p=radar.pull_one('A');self.assertEqual(p['status'],'queued');self.assertIsNone(radar.pull_one('A'))
 def test_seven_day_history_still_blocks_import(self):
  import time
  lid=store.add_lead('B','sent',company='Example',domain='example.com',email='old@example.com')
  store.update(lid,sent_at=time.time()-6*86400,message_id='<fixture@test>')
  self.assertEqual(radar.import_contacts({'account':'A','contact_ids':['person']})['ids'],[])
  self.assertEqual(store.lead(lid)['status'],'sent')
 def test_held_contact_cannot_reserve_send(self):
  ids=radar.import_contacts({'account':'A','contact_ids':['person']})['ids']
  token,reason=store.reserve_send(ids[0],config.account('A'),'<fixture@test>')
  self.assertIsNone(token);self.assertEqual(reason,'not_ready')
 def test_random_assignment_is_stable_and_unique(self):
  radar.configure({'account':'A','accounts':['A','B'],'mode':'shared_random','enabled':True})
  with patch.object(radar.random,'choice',return_value='B'):
   self.assertIsNone(radar.pull_one('A'))
  p=radar.pull_one('B');self.assertEqual(p['account'],'B')
  self.assertIsNone(radar.pull_one('A'));self.assertEqual(len(store.q("SELECT id FROM leads")),1)
 def test_paused_account_not_randomly_selected(self):
  store.put('paused_B',True);radar.configure({'account':'A','accounts':['A','B'],'mode':'shared_random','enabled':True})
  self.assertEqual(radar.pull_one('A')['account'],'A')
 def test_missing_id_rejected(self):
  with self.assertRaises(ValueError):radar.import_contacts({'account':'A','contact_ids':['invented']})
if __name__=='__main__':unittest.main()

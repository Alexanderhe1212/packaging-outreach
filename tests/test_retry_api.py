import sys,unittest,copy,threading
from unittest.mock import patch,Mock
from outreach import server
class Retry(unittest.TestCase):
 def test_research_retry_discards_stale_prospect_keeps_evidence(self):
  lead=dict(id=1,account='test',status='failed',email='info@brand.test',error='lookup failed',data={'manual':{'email':'info@brand.test','url':'https://brand.test','radar':{'sources':['https://brand.test/contact']}},'prospect':{'stale':True},'plan':{}},sent_at=None,message_id='')
  with patch.object(server.store,'lead',return_value=lead),patch.object(server.store,'hard_blocked',return_value=False),patch.object(server.store,'update') as update,patch.object(server,'worker',return_value=Mock()):
   server.api_redo({'id':1,'what':'research'})
   d=update.call_args.kwargs['data'];self.assertNotIn('prospect',d);self.assertEqual(d['manual']['email'],'');self.assertTrue(d['manual']['radar']['sources']);self.assertEqual(d['retry_history'][-1]['error'],'lookup failed')
 def test_historical_sent_cannot_retry_even_failed_status(self):
  lead=dict(id=1,account='test',status='failed',email='info@brand.test',data={},sent_at=123,message_id='id')
  with patch.object(server.store,'lead',return_value=lead),patch.object(server.store,'update'),patch.object(server,'worker',return_value=Mock()):
   with self.assertRaises(ValueError):server.api_redo({'id':1,'what':'research'})
if __name__=='__main__':unittest.main()

import unittest,time
from unittest.mock import patch
import test_bridge
from outreach import store,radar
class OptionalContacts(unittest.TestCase):
 setUp=test_bridge.BridgeTest.setUp
 tearDown=test_bridge.BridgeTest.tearDown
 def test_accepted_history_does_not_expire_into_resend(self):
  lid=store.add_lead('A','sent',company='Fiction',domain='fiction.invalid',email='sales@fiction.invalid')
  store.update(lid,sent_at=time.time()-40*86400,message_id='<one>')
  self.assertTrue(store.blocked('sales@fiction.invalid','fiction.invalid','B'))
 def test_second_contact_is_explicit_same_account_and_stops_on_reply(self):
  lid=store.add_lead('A','sent',company='Fiction',domain='fiction.invalid',email='sales@fiction.invalid')
  store.update(lid,sent_at=time.time()-10*86400,message_id='<one>')
  p=dict(id='buyer',name='Jane Smith',qualified=True,website='https://fiction.invalid',email='jane@fiction.invalid')
  radar.upgrade_contact(store.lead(lid),p)
  self.assertIsNone(radar.queue_second_contact('A'))
  with patch('pipeline_core.features.settings',return_value={'second_contact':True}):
   self.assertIsNone(radar.queue_second_contact('B'))
   child=radar.queue_second_contact('A');self.assertEqual(child['account'],'A')
   self.assertEqual(child['data']['second_contact_parent_id'],lid)
   self.assertIsNone(radar.queue_second_contact('A'))
   store.update(lid,status='replied',reply_at=time.time())
   self.assertTrue(store._conflict(store.db(),store.lead(child['id'])))

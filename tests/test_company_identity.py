import sqlite3,unittest
class Identity(unittest.TestCase):
 def test_alias_migration_is_idempotent_and_owner_is_fixed(self):
  from pipeline_core.identity import register
  db=sqlite3.connect(':memory:')
  self.assertEqual(register(db,'https://www.Fiction.invalid','old','MTT'),'old')
  self.assertEqual(register(db,'fiction.invalid','new','GUKA'),'old')
  register(db,'fiction.invalid','new','MTT')
  self.assertEqual(db.execute('select count(*) from companies').fetchone()[0],1)
  self.assertEqual(db.execute('select account from companies').fetchone()[0],'MTT')
  self.assertEqual(db.execute('select count(*) from contact_aliases').fetchone()[0],2)
 def test_role_mailboxes_are_not_named_buyers(self):
  from pipeline_core.identity import email_quality
  self.assertEqual(email_quality('press@fiction.invalid',lambda d:['mx.invalid'])['role'],'excluded')
  self.assertEqual(email_quality('sales@fiction.invalid',lambda d:['mx.invalid'])['role'],'generic_company')
  self.assertEqual(email_quality('someone@fiction.invalid',lambda d:[])['status'],'invalid')

import test_bridge
from outreach import store,radar
class Upgrade(unittest.TestCase):
 setUp=test_bridge.BridgeTest.setUp
 tearDown=test_bridge.BridgeTest.tearDown
 def test_upgrade_preserves_company_account_and_blocks_after_sent(self):
  lid=store.add_lead('A','queued',source='user_radar',company='Fiction',domain='fiction.invalid',email='sales@fiction.invalid',data={'manual':{'radar':{'contact_kind':'company_public'}}})
  p={'id':'new-contact','name':'Jane Smith','qualified':True,'website':'https://fiction.invalid','email':'jane@fiction.invalid','contact_kind':'person'}
  self.assertTrue(radar.upgrade_contact(store.lead(lid),p))
  self.assertEqual(store.lead(lid)['account'],'A');self.assertEqual(store.lead(lid)['email'],p['email'])
  self.assertEqual(store.q('select count(*) n from leads',one=True)['n'],1)
  store.update(lid,status='sent',sent_at=100,message_id='<old>')
  self.assertFalse(radar.upgrade_contact(store.lead(lid),dict(p,email='new@fiction.invalid')))

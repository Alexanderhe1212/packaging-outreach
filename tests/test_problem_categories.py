import sys,time,gzip
from unittest.mock import patch
from test_bridge import BridgeTest,store
from outreach import problems,web

class ProblemCategoryTests(BridgeTest):
 def test_waiting_is_retained_separately_from_attention(self):
  lead={'id':1,'company':'Brand','account':'A','email':'info@brand.test','status':'queued','error':'官网限流等待','next_check_at':time.time()+600}
  log=problems.reconcile({'1':{'first_seen':1,'reason':'old','state':'open'}},[lead],time.time())
  self.assertEqual(problems.category(log['1'],time.time()),'waiting')
  self.assertEqual(log['1']['next_check_at'],lead['next_check_at']);self.assertEqual(log['1']['state'],'retrying')
 def test_unknown_needs_review_and_protected_records_remain_visible(self):
  self.assertEqual(problems.category({'state':'open','status':'unknown'},time.time()),'attention')
  self.assertEqual(problems.category({'state':'open','status':'bounced'},time.time()),'protected')
  self.assertEqual(problems.category({'state':'open','status':'failed','reason':'重复或已抑制客户'},time.time()),'protected')
 def test_lead_list_exposes_retry_deadline_without_private_payload(self):
  lid=store.add_lead('A','queued',data={'research_retry_at':12345,'private':'not exposed'})
  row=store.list_leads()['items'][0]
  self.assertEqual(row['research_retry_at'],12345);self.assertNotIn('data',row)
 def test_gzip_html_is_decoded_before_email_verification(self):
  raw=gzip.compress(b'<p>Business enquiries: sales@brand.test</p>')
  with patch.object(web,'get',return_value=(raw,'https://brand.test/contact','text/html; charset=utf-8')):
   self.assertEqual(web.verify_email('sales@brand.test','https://brand.test/contact','https://brand.test/'),'https://brand.test/contact')

if __name__=='__main__':
 import unittest
 unittest.main()

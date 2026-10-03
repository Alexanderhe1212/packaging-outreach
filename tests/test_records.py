import json,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from packaging_outreach.store import Store
from packaging_outreach.mail import mailbox_test,verify_mailbox_test,connection_fingerprint
from packaging_outreach.config import example
from unittest.mock import patch
from fixture_png import png

class RecordTests(unittest.TestCase):
 def job(self,s,brand='brand-a',domain='brand.example',followup=None):
  jid=s.add(brand,{'company_url':'https://'+domain,'recipient':'trade@'+domain},'send',followup,'A new product proposal' if followup else None);return s.get(jid)
 def test_only_one_concurrent_company_submission(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d);s.setting('paused','false');job=self.job(s)
   def claim(n):
    try:return s.claim_send(job,'<'+str(n)+'@example.test>','sha')
    except ValueError:return None
   with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(claim,range(4)))
   self.assertEqual(sum(x is not None for x in result),1)
 def test_optout_and_unknown_survive_restart(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d);s.setting('paused','false');job=self.job(s);aid=s.claim_send(job,'<1@example.test>','sha');s.trace(aid,'final_ack_wait',{});s.acquire('new-process')
   self.assertEqual(s.status()['attempts'][0]['result'],'unknown');s.event(job['recipient'],'unsubscribe','Actual request')
   with self.assertRaises(ValueError):s.claim_send(job,'<2@example.test>','sha')
 def test_value_followup_is_explicit_and_same_brand(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d);s.setting('paused','false');job=self.job(s);aid=s.claim_send(job,'<1@example.test>','sha');s.trace(aid,'final_ack',{'result':'accepted'})
   with self.assertRaises(ValueError):self.job(s,'brand-b',followup=aid)
   nextjob=self.job(s,followup=aid);self.assertTrue(s.claim_send(nextjob,'<2@example.test>','sha2'))
 def test_worker_exclusion_and_pause_claim(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d);s.acquire('a')
   with self.assertRaises(RuntimeError):Store(d).acquire('b')
   job=self.job(s);self.assertFalse(s.claim(job['id']));s.release('a')
 def test_mailbox_proof_needs_actual_image_receipt_and_can_recheck_without_resend(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d);brand=example()['brands'][0]
   with patch('packaging_outreach.mail.secret',return_value='fixture'),patch('packaging_outreach.mail.transport.send_once',return_value={'result':'accepted','stage':'final_ack','code':250}) as send,patch('packaging_outreach.mail.transport.verify_imap',return_value={'received':False}) as receive:
    self.assertFalse(mailbox_test(s,brand,png())['verified']);self.assertIsNone(s.setting('mail_verified:'+brand['id']))
    receive.return_value={'received':True,'image_hashes_match':True};self.assertTrue(verify_mailbox_test(s,brand)['verified']);self.assertEqual(send.call_count,1)
    changed=dict(brand,sender='changed@example.test')
    with self.assertRaises(ValueError):verify_mailbox_test(s,changed)

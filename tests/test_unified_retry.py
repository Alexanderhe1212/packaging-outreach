import unittest,urllib.error
class Retry(unittest.TestCase):
 def test_429_budget_retry_after_and_deferred(self):
  from pipeline_core.retry_policy import decide
  e=urllib.error.HTTPError('https://fixture.invalid',429,'limited',{'Retry-After':'900'},None)
  r=decide(e,0,now=100);self.assertEqual(r['retry_count'],1);self.assertEqual(r['next_retry_at'],1000);self.assertEqual(r['reason_code'],'RATE_LIMITED')
  self.assertEqual(decide(e,6,now=100)['reason_code'],'RETRY_EXHAUSTED')
  r=decide(e,6,now=100,deferred=True,deadline=5000);self.assertEqual(r['retry_count'],6);self.assertEqual(r['next_retry_at'],5000)
 def test_network_has_three_attempts_unknown_post_never_restarted(self):
  from pipeline_core.retry_policy import decide
  self.assertEqual(decide(TimeoutError(),3,now=100)['action'],'review')
  self.assertEqual(decide('POST_UNKNOWN',0,now=100)['action'],'review')
  self.assertEqual(decide('JOB_EXPIRED',0,now=100)['action'],'review')
 def test_403_contact_and_image_have_distinct_actions(self):
  from pipeline_core.retry_policy import decide
  self.assertEqual(decide('BLOCKED',0,now=100)['action'],'review')
  self.assertEqual(decide('NO_PUBLIC_EMAIL',0,now=100)['action'],'contacts')
  self.assertEqual(decide('IMAGE_QC_FAILED',0,now=100)['action'],'image')
 def test_legacy_history_remains_excluded_only_new_due_failure_reenters(self):
  from pipeline_core.retry_policy import excluded
  self.assertTrue(excluded({'domain':'old.invalid'},now=100))
  self.assertTrue(excluded({'reason_code':'PERMANENT_EXCLUDE','recheck_after':1},now=100))
  self.assertFalse(excluded({'reason_code':'NO_PUBLIC_EMAIL','recheck_after':99},now=100))

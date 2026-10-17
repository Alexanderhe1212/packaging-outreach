import sys,unittest,copy
from outreach import problems
class Problems(unittest.TestCase):
 def test_retries_do_not_resolve_until_accepted(self):
  lead=dict(id=10,company='Example',email='info@brand.test',account='test',status='failed',error='lookup failed',updated_at=1)
  log=problems.reconcile({},[lead],2);self.assertEqual(log['10']['state'],'open')
  lead.update(status='queued',error='');log=problems.reconcile(log,[lead],3);self.assertEqual(log['10']['state'],'retrying');self.assertEqual(log['10']['reason'],'lookup failed')
  lead.update(status='sent');log=problems.reconcile(log,[lead],4);self.assertEqual(log['10']['state'],'resolved');self.assertEqual(log['10']['resolved_at'],4)
  lead.update(status='failed',error='new failure');log=problems.reconcile(log,[lead],5);self.assertEqual(log['10']['state'],'open');self.assertEqual(log['10']['first_seen'],2)
 def test_skipped_and_missing_remain_open(self):
  lead=dict(id=10,status='failed',error='bad',company='',email='',account='test',updated_at=1)
  log=problems.reconcile({},[lead],2);lead['status']='skipped';log=problems.reconcile(log,[lead],3);self.assertNotEqual(log['10']['state'],'resolved');self.assertIn('10',problems.reconcile(log,[],4))
if __name__=='__main__':unittest.main()

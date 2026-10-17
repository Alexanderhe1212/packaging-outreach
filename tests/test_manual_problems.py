import sys,unittest,copy,threading
from unittest.mock import patch
from outreach import problems,store
class Manual(unittest.TestCase):
 def test_manual_issue_persists_and_can_be_resolved(self):
  state={}
  def save(k,v):state[k]=copy.deepcopy(v)
  with patch.object(store,'get',side_effect=lambda k,d=None:copy.deepcopy(state.get(k,d))),patch.object(store,'put',side_effect=save):
   item=problems.add({'title':'Window is too wide','detail':'Narrow screen wraps poorly'})
   log=state[problems.KEY];self.assertEqual(log[item['id']]['state'],'open')
   problems.resolve({'id':item['id'],'resolution':'Adjusted responsive layout'})
   self.assertEqual(state[problems.KEY][item['id']]['state'],'resolved')
 def test_customer_problem_cannot_be_manually_hidden(self):
  with self.assertRaises(ValueError):problems.resolve({'id':'123','resolution':'ignore'})
if __name__=='__main__':unittest.main()

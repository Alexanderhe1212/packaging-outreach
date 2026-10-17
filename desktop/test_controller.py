import unittest
from unittest.mock import patch
import controller
class ControlTests(unittest.TestCase):
 def test_boot_does_not_start_sending(self):
  with patch.object(controller.subprocess,"run") as r:
   controller.boot()
   self.assertEqual(r.call_count,2)
   self.assertIn("--check-only",r.call_args.args[0])
   self.assertTrue(all("go" not in c.args[0] for c in r.call_args_list))
 def test_start_only_selected_accounts(self):
  with patch.object(controller,'request',return_value={}) as r,patch.object(controller.subprocess,'run') as service:
   controller.control('start')
   self.assertEqual([c.args for c in r.call_args_list],[('/api/radar/configure',{'account':'GUKA','accounts':['GUKA','MTT'],'mode':'shared_random','enabled':True}),('/api/start',{'account':'GUKA'}),('/api/start',{'account':'MTT'})])
 def test_pause_both(self):
  with patch.object(controller,'request',return_value={}) as r:
   controller.control('pause');self.assertEqual(r.call_count,2)
   self.assertTrue(all(c.args[0]=='/api/pause' for c in r.call_args_list))
 def test_snapshot_keeps_discovery_and_omits_email_body(self):
  answers=[{'accounts':[{'id':'MTT','paused':True,'stats':{}}]}, {'contacts':[{}], 'discovery':{'stage':'finding'}, 'automatic':{}},{'items':[{'id':1,'updated_at':2,'body':'private','company':'Example'}]}]
  with patch.object(controller,'request',side_effect=answers):
   out=controller.snapshot();self.assertEqual(out['discovery']['stage'],'finding');self.assertNotIn('body',out['leads'][0]);self.assertEqual(out['customers'],1)
 def test_unknown_action_no_request(self):
  with patch.object(controller,'request') as r:
   with self.assertRaises(ValueError):controller.control('send')
   r.assert_not_called()
if __name__=='__main__':unittest.main()

import importlib.util,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('customer_launcher',SOURCE/'launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
class PackagingTests(unittest.TestCase):
 def test_customer_paths_ignore_developer_credentials(self):
  with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,LOCALAPPDATA=temp,OUTREACH_DATA='/do-not-use',OUTREACH_KEY_MAIN='synthetic',OUTREACH_PASSWORD_MTT='synthetic',USER_RADAR_CUSTOMER_DB='/do-not-use'):
   base,env=launcher.environment()
   self.assertNotIn('OUTREACH_KEY_MAIN',env);self.assertNotIn('OUTREACH_PASSWORD_MTT',env)
   self.assertTrue(Path(env['OUTREACH_DATA']).is_relative_to(temp))
   self.assertTrue(Path(env['USER_RADAR_CUSTOMER_DB']).is_relative_to(temp))
 def test_embedded_runtime_explicit_import_path_and_utf8(self):
  cmd=launcher.command('print(sys.path[0])')
  self.assertEqual(cmd[1:3],['-X','utf8'])
  self.assertEqual(subprocess.check_output(cmd,text=True).strip(),str(launcher.ROOT))
 def test_startup_has_no_send_request(self):
  source=(SOURCE/'launcher.py').read_text()
  self.assertNotIn('/api/start',source)
  self.assertIn("store.put('paused_'+a['id'],True)",source)
 def test_installer_owns_program_only(self):
  source=(SOURCE/'installer.nsi').read_text()
  self.assertIn('RequestExecutionLevel user',source)
  self.assertIn('UserRadarCustomerRunning',source)
  self.assertNotIn('RMDir /r "$LOCALAPPDATA\\UserRadarCustomer"',source)
  self.assertNotIn('RMDir /r "$INSTDIR"',source)
  self.assertNotIn('pip install',source)
if __name__=='__main__':unittest.main()

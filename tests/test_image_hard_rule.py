import os,tempfile,unittest
from unittest.mock import patch
from email.message import EmailMessage
from outreach import store,config,mailer,pipeline
from outreach.worker import AccountWorker
class ImageHardRule(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,OUTREACH_DATA=self.tmp.name);self.env.start();store.close();config.save({'accounts':[{'id':'A','sender':'a@fixture.invalid','profile':'packaging'}]})
 def tearDown(self):store.close();self.env.stop();self.tmp.cleanup()
 def test_optional_legacy_profile_cannot_send_without_image(self):
  lid=store.add_lead('A','ready',company='Fixture',domain='fixture.invalid',email='sales@fixture.invalid');store.update(lid,subject='hello',body='A valid body')
  with patch.object(config,'profile',return_value={'image_optional':True}),patch.object(mailer,'send') as transport:
   self.assertEqual(AccountWorker('A').send(store.lead(lid)),'concept_image_missing');transport.assert_not_called()
  self.assertEqual(store.q('SELECT * FROM send_attempts'),[])
 def test_direct_transport_rejects_text_only_before_connect(self):
  msg=EmailMessage();msg['To']='sales@fixture.invalid';msg.set_content('fixture')
  with patch.object(mailer,'smtp_connect') as connect:
   self.assertEqual(mailer.send(config.account('A'),msg)[0],'blocked');connect.assert_not_called()
 def test_qc_rejection_applies_to_old_nonhybrid_profile(self):
  from outreach.dryrun import sample_png
  with patch.object(pipeline,'image_prompt',return_value='fixture'),patch.object(pipeline,'to_jpeg',side_effect=lambda b,*a:b),patch.object(pipeline,'shrink',side_effect=lambda b,*a:b),patch.object(pipeline.llm.Stage,'__init__',return_value=None),patch.object(pipeline.llm.Stage,'image',return_value=sample_png()),patch.object(pipeline.llm.Stage,'json',return_value={'approved':False,'reason':'wrong product'}):
   with self.assertRaises(ValueError):pipeline.make_image({'id':'A'},{},{},{},None)

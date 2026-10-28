import unittest
class Replies(unittest.TestCase):
 def test_auto_never_human(self):
  from outreach.reply_classification import classify
  self.assertEqual(classify({'Auto-Submitted':'auto-replied'},'Interested in samples'),'auto_reply')
 def test_conservative_human_classes(self):
  from outreach.reply_classification import classify
  for body,expected in [('Please unsubscribe me','unsubscribe'),('Not interested, thanks','human_not_interested'),('Please send a quote for these boxes','human_interested'),('Please contact Jane at jane@fiction.invalid','human_referral'),('Thank you','human_other')]:
   self.assertEqual(classify({},body),expected)
 def test_automatic_reply_blocks_followup(self):
  from outreach.reply_classification import followup_allowed
  self.assertFalse(followup_allowed({'status':'sent','reply_at':1,'followups':0,'data':{}},True))
  self.assertFalse(followup_allowed({'status':'unknown','followups':0,'data':{}},True))
 def test_prepared_followup_keeps_thread_and_image(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from email.message import EmailMessage
  from outreach import mailer
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'image.png';path.write_bytes(b'fixture-image')
   lead={'subject':'Original','company':'Fiction','email':'buyer@fiction.invalid','message_id':'<original@fiction.invalid>','image':str(path),'followups':0,'data':{'prospect':{},'followup_ready':{'index':1,'image':str(path),'body':'Hi Jane, verified follow-up'}}}
   with patch('pipeline_core.features.enabled',return_value=True),patch.object(mailer,'build',return_value=EmailMessage()) as build:
    msg=mailer.build_followup({},lead,{})
    self.assertEqual(msg['In-Reply-To'],'<original@fiction.invalid>')
    self.assertEqual(build.call_args.args[2],b'fixture-image')
    self.assertEqual(build.call_args.args[1]['body'],'Hi Jane, verified follow-up')

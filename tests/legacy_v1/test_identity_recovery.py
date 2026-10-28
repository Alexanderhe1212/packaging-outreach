import unittest
from unittest.mock import patch
from outreach import pipeline, web
import urllib.request, urllib.error

class IdentityRecovery(unittest.TestCase):
 def test_heading_is_replaced_from_exact_email_evidence(self):
  quote='Medical Aesthetics\nJane Smith\njane@brand.test'
  p={'email':'jane@brand.test','contact_identity_evidence':[{'quote':quote}]}
  with patch.object(pipeline.llm,'Stage') as stage:
   stage.return_value.json.return_value={'name':'Jane Smith','email':p['email'],'quote':quote}
   pipeline.resolve_recipient_identity({'id':'A'},p)
  self.assertEqual(pipeline.recipient_label(p),'Jane Smith')
 def test_changed_email_cannot_keep_previous_name(self):
  p={'email':'other@brand.test','verified_contact_name':'Alex Smith','contact_identity_evidence':[{'quote':'Alex Smith alex@brand.test'}]}
  with patch.object(pipeline.llm,'Stage') as stage:
   pipeline.resolve_recipient_identity({'id':'A'},p)
  stage.assert_not_called();self.assertNotIn('verified_contact_name',p)
 def test_invented_quote_is_rejected(self):
  p={'email':'phil@brand.test','contact_identity_evidence':[{'quote':'Message Us phil@brand.test'}]}
  with patch.object(pipeline.llm,'Stage') as stage:
   stage.return_value.json.return_value={'name':'Phil Smith','email':p['email'],'quote':'Phil Smith phil@brand.test'}
   pipeline.resolve_recipient_identity({'id':'A'},p)
  self.assertNotIn('verified_contact_name',p)
 def test_308_get_supported_but_post_not_rewritten(self):
  handler=web.PublicRedirectHandler();r=urllib.request.Request('https://brand.test/')
  self.assertEqual(handler.redirect_request(r,None,308,'',{},'https://brand.test/contact').full_url,'https://brand.test/contact')
  with self.assertRaises(urllib.error.HTTPError):handler.redirect_request(urllib.request.Request('https://brand.test/',data=b'x'),None,308,'',{},'https://brand.test/contact')

 def test_gzip_with_trailing_newline(self):
  import gzip
  raw=gzip.compress(b'<html>contact</html>')+b'\r\n'
  with patch.object(web,'get',return_value=(raw,'https://brand.test/','text/html')):
   self.assertEqual(web.page('https://brand.test/')[0],'<html>contact</html>')
 def test_broken_gzip_is_not_accepted(self):
  import gzip
  for raw in [gzip.compress(b'content')[:-5],gzip.compress(b'content')+b'garbage']:
   with patch.object(web,'get',return_value=(raw,'https://brand.test/','text/html')):
    with self.assertRaises(web.CrawlError):web.page('https://brand.test/')

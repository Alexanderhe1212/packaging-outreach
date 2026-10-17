import unittest,sys
from bs4 import BeautifulSoup
from website_email_bridge import normalize_published_emails
class Join(unittest.TestCase):
 def test_phone_mail_anchors_separate(self):
  s=BeautifulSoup('<p><a href="tel:962901560">962901560</a><a href="mailto:info@brand.test">info@brand.test</a></p>','html.parser');normalize_published_emails(s)
  self.assertNotIn('962901560info@brand.test',s.get_text(' ',strip=True))
 def test_inline_email_still_joins(self):
  s=BeautifulSoup('<p><b>hello</b>@brand.test</p>','html.parser');normalize_published_emails(s);self.assertIn('hello@brand.test',s.get_text(' ',strip=True))
if __name__=='__main__':unittest.main()

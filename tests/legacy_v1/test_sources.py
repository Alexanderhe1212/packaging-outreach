import sys,unittest
from unittest.mock import patch
from outreach import web
class SourceTest(unittest.TestCase):
 def test_mailto_spaces_and_mismatch(self):
  self.assertEqual(web.business_emails('<a href="mailto: jane@fixturebrand.co.uk">jane@fixturebrand.co.uk</a>'),['jane@fixturebrand.co.uk'])
  self.assertEqual(web.business_emails('<a href="mailto:other@fixturebrand.co.uk">jane@fixturebrand.co.uk</a>'),[])
 def test_flat_product_link_still_requires_product_evidence(self):
  doc='<h3 class="card-title"><a href="/soap-bar/">Soap</a></h3>'
  with patch.object(web,'page',return_value=('<title>Ordinary page</title>','https://brand.test/soap-bar/')) as fetched:
   self.assertIsNone(web.product_from_links(doc,'https://brand.test/'))
   fetched.assert_called_once_with('https://brand.test/soap-bar/')
 def test_published_email_case_is_normalized(self):
  url='https://brand.test/contact'
  with patch.object(web,'page',return_value=('<a href="mailto:Sales.Team@brand.test">Sales.Team@brand.test</a>',url)):
   self.assertEqual(web.verify_email('Sales.Team@brand.test',url,'https://brand.test/'),url)
 def test_email_hint_case_matches_published_address(self):
  doc='<a href="mailto:Sales.Team@brand.test">Sales.Team@brand.test</a>'
  with patch.object(web,'page',side_effect=web.CrawlError('fixture missing')):
   self.assertEqual(web.find_email(doc,'https://brand.test/',email_hint='Sales.Team@brand.test')[0],'sales.team@brand.test')
 def run_case(self,sources,verify):
  product={'name':'Soap','url':'https://brand.test/soap','facts':[],'price':'5','description':'Soap','image_url':'https://brand.test/photo.jpg'}
  with patch.object(web,'page',return_value=('<title>Brand</title>','https://brand.test/')),patch.object(web,'verify_email',side_effect=verify) as checked,patch.object(web,'find_email',return_value=('','')) as found,patch.object(web,'shopify_product',return_value=product),patch.object(web,'valid_product',return_value=True):
   try:result=web.crawl('https://brand.test','sales@brand.test',email_sources=sources)
   except web.CrawlError:result=None
   return result,checked.call_count,found.call_count
 def test_saved_page_is_reverified(self):
  r,n,f=self.run_case(['https://brand.test/team/contact'],lambda *a:a[1]);self.assertEqual(n,1);self.assertEqual(f,0);self.assertTrue(r['email_verified'])
 def test_other_domain_not_read(self):
  r,n,f=self.run_case(['https://unrelated.test/contact'],lambda *a:a[1]);self.assertIsNone(r);self.assertEqual(n,0)
 def test_unpublished_email_not_trusted(self):
  r,n,f=self.run_case(['https://brand.test/contact'],web.CrawlError('not published'));self.assertIsNone(r);self.assertEqual(f,1)
if __name__=='__main__':unittest.main()

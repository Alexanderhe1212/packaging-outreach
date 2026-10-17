import sys,unittest
from outreach import web
class Recovery(unittest.TestCase):
 def test_cf_public_contact(self):
  e='info@brand.test';key=37;enc=bytes([key]+[ord(c)^key for c in e]).hex()
  self.assertIn(e,web.business_emails('<span data-cfemail="'+enc+'">[email protected]</span>'))
 def test_conflicting_footer_does_not_poison_clear_sales(self):
  d='<p>Trade sales: <a href="mailto:sales@brand.test">sales@brand.test</a></p><footer><a href="mailto:sales@brand.test">support@brand.test</a></footer>'
  self.assertIn('sales@brand.test',web.business_emails(d));self.assertNotIn('support@brand.test',web.business_emails(d))
 def test_general_customer_questions_not_order_only(self):
  self.assertIn('hello@brand.test',web.business_emails('<p>Questions about our products? Contact our customer service team: hello@brand.test</p>'))
 def test_restricted_and_conflict_still_rejected(self):
  self.assertNotIn('hello@brand.test',web.business_emails('<p>For order enquiries only: hello@brand.test</p>'))
  self.assertEqual([],web.business_emails('<a href="mailto:sales@brand.test">support@brand.test</a>'))
if __name__=='__main__':unittest.main()

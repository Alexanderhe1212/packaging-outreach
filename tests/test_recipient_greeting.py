import sys,unittest
from outreach import pipeline
class Greeting(unittest.TestCase):
 def test_verified_person_is_addressed_directly(self):
  self.assertEqual(pipeline.addressed_body('Hi Brand team,\n\nYour bottles...',{'company':'Brand','verified_contact_name':'Jane Smith'}),'Hi Jane Smith,\n\nYour bottles...')
 def test_brand_name_is_not_a_person(self):
  self.assertEqual(pipeline.addressed_body('Hi Alicia J Diamonds team,\n\nYour jewellery...',{'company':'Alicia J Diamonds'}),'Hello,\n\nYour jewellery...')
 def test_mailbox_localpart_not_inferred(self):
  self.assertEqual(pipeline.addressed_body('Hello,\n\nA relevant idea.',{'email':'jane@brand.test'}),'Hello,\n\nA relevant idea.')
if __name__=='__main__':unittest.main()

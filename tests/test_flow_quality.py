import unittest
from unittest.mock import patch
from outreach import pipeline,radar
class FlowQuality(unittest.TestCase):
 def test_verified_name_priority(self):
  self.assertEqual(pipeline.recipient_label({'verified_contact_name':'Jane Smith','company':'Example'}),'Jane Smith')
 def test_department_not_person(self):
  self.assertFalse(pipeline.plausible_person_name('MOORCROFT HERITAGE VISITOR CENTRE'))
  self.assertEqual(pipeline.recipient_label({'verified_contact_name':'MOORCROFT HERITAGE VISITOR CENTRE','company':'Moorcroft'}),'Moorcroft team')
 def test_shopping_heading_not_person(self):
  self.assertFalse(pipeline.plausible_person_name('Buying Chocolates'))
 def test_company_greeting(self):
  self.assertEqual(pipeline.addressed_body('Hello,\n\nA useful idea.',{'company':'Example (Example Limited)'}),'Hi Example team,\n\nA useful idea.')
 def test_product_target_retained(self):
  self.assertEqual(radar.research_url({'website':'https://example.test','fit_source':'https://example.test/products/cream'}),'https://example.test/products/cream')
 def test_other_domain_rejected(self):
  self.assertEqual(radar.research_url({'website':'https://example.test','fit_source':'https://evil.test/products/cream'}),'https://example.test')
 def test_person_review_controls_greeting(self):
  for approved in (True, False):
   p={'company':'Example','verified_contact_name':'Jane Smith','contact_identity_evidence':[{'quote':'Jane Smith, director'}]}
   stage=unittest.mock.Mock();stage.json.side_effect=[{'is_person':approved},{'subject':'Packaging idea','body':'Hi Example team,\n\n'+('A concrete packaging observation and fitted insert recommendation. '*4)}]
   with patch.object(pipeline.llm,'Stage',return_value=stage),patch.object(pipeline,'writer_prompts',return_value=('system','facts')),patch.object(pipeline.config,'load',return_value={'accounts':[]}):
    plan=pipeline.write.__wrapped__({'id':'A'},{'inquiry_first':True},p,None)
   self.assertTrue(plan['body'].startswith('Hi Jane Smith,' if approved else 'Hi Example team,'))
   self.assertEqual(p['recipient_identity_confirmed'],approved)
 def test_bad_image_blocks_return(self):
  from outreach import llm
  stage=unittest.mock.Mock();stage.image.return_value=b'jpg';stage.json.return_value={'approved':False,'reason':'Loose beans'}
  with patch.object(llm,'Stage',return_value=stage),patch.object(pipeline,'image_prompt',return_value='prompt'),patch.object(pipeline,'to_jpeg',side_effect=lambda x,*a:x),patch.object(pipeline,'shrink',side_effect=lambda x,*a:x):
   with self.assertRaisesRegex(ValueError,'Loose beans'):
    pipeline.make_image({'id':'GUKA'},{'hybrid_concepts':True},{},{},b'photo')
if __name__=='__main__':unittest.main()

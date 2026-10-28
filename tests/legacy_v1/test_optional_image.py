import sys
from unittest.mock import patch,PropertyMock
from test_bridge import BridgeTest,store
from outreach import worker,pipeline
class OptionalImageTest(BridgeTest):
 def test_image_failure_rewrites_without_attachment_claim(self):
  p={'company':'Brand','domain':'brand.test','email':'sales@brand.test','concept_ready':True,'product_name':'Soap','product_url':'https://brand.test/soap'}
  lid=store.add_lead('A','queued',data={'prospect':p})
  profile={'image_optional':True,'hybrid_concepts':True,'inquiry_first':True,'image':{'enabled':True}}
  w=worker.AccountWorker('A')
  with patch.object(worker.AccountWorker,'profile',new_callable=PropertyMock,return_value=profile),patch.object(pipeline,'write',side_effect=[{'subject':'Concept','body':'See image','c':{'name':'C'}},{'subject':'Packaging support','body':'A relevant solution without attached artwork'}]),patch.object(pipeline,'make_image',side_effect=ValueError('image service unavailable')):
   w.process(store.lead(lid),b'fixture-photo')
  result=store.lead(lid);self.assertEqual(result['status'],'ready');self.assertFalse(result['data']['prospect']['concept_ready']);self.assertNotIn('c',result['data']['plan']);self.assertEqual(result['image'],'')
 def test_business_only_skips_image(self):
  lid=store.add_lead('A','queued',data={'prospect':{'company':'Brand','domain':'brand.test','email':'sales@brand.test','site_description':'Verified skincare brand'}})
  profile={'image_optional':True,'hybrid_concepts':True,'inquiry_first':True,'image':{'enabled':True}}
  with patch.object(worker.AccountWorker,'profile',new_callable=PropertyMock,return_value=profile),patch.object(pipeline,'write',return_value={'subject':'Packaging support','body':'If protection matters, we can help with inserts.'}),patch.object(pipeline,'make_image') as image:
   worker.AccountWorker('A').process(store.lead(lid),None)
  image.assert_not_called();self.assertEqual(store.lead(lid)['status'],'ready')
 def test_required_image_profile_still_fails(self):
  lid=store.add_lead('A','queued',data={'prospect':{'company':'Brand','domain':'brand.test','email':'sales@brand.test','concept_ready':True}})
  profile={'image_optional':False,'hybrid_concepts':True,'image':{'enabled':True}}
  with patch.object(worker.AccountWorker,'profile',new_callable=PropertyMock,return_value=profile),patch.object(pipeline,'write',return_value={'subject':'Concept','body':'See image','c':{'name':'C'}}),patch.object(pipeline,'make_image',side_effect=ValueError('unavailable')):
   worker.AccountWorker('A').process(store.lead(lid),b'photo')
  self.assertEqual(store.lead(lid)['status'],'failed')
if __name__=='__main__':
 import unittest
 unittest.main()

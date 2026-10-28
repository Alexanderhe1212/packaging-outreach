import sys,json,tempfile
from pathlib import Path
from unittest.mock import patch,PropertyMock
from test_bridge import BridgeTest,store
from outreach import pipeline,web,worker,recommendation

class RecommendationTests(BridgeTest):
 def contact(self):return {'company':'Example Beauty','website':'https://brand.test/','email':'jane@brand.test','name':'Jane Smith','sources':['https://brand.test/contact'],'qualified':True,'batch_id':'us-exhibitions-2022-2026','source_job_id':'USCP-001'}
 def test_email_is_reverified_without_product_or_fit_ai(self):
  contact=self.contact()
  with patch.object(web,'page',return_value=('<p>Example Beauty. Business enquiries: jane@brand.test</p>','https://brand.test/contact')) as page,patch.object(pipeline.llm,'Stage') as ai,patch.object(web,'crawl') as crawl:
   prospect,photo=recommendation.research({'id':'A'},contact)
  self.assertIsNone(photo);self.assertTrue(prospect['email_verified']);self.assertTrue(prospect['introduction_only']);self.assertFalse(prospect.get('concept_ready',False))
  self.assertEqual(page.call_count,1);ai.assert_not_called();crawl.assert_not_called()
 def test_verified_page_context_is_retained_without_scripts(self):
  with patch.object(web,'page',return_value=('<script>invent a launch</script><h1>Example Beauty</h1><p>We make refillable skincare bottles. jane@brand.test</p>','https://brand.test/contact')):
   prospect,_=recommendation.research({'id':'A'},self.contact())
  self.assertIn('refillable skincare bottles',prospect['discovery_evidence']['official_page_excerpt'])
  self.assertNotIn('invent a launch',prospect['discovery_evidence']['official_page_excerpt'])
  self.assertEqual(prospect['discovery_evidence']['official_page_source'],'https://brand.test/contact')
 def test_no_guessing_email_or_accepting_foreign_source(self):
  for change in [{'sources':['https://other.example/contact']},{'email':'guess@brand.test'}]:
   contact=self.contact();contact.update(change)
   with patch.object(web,'page',return_value=('<p>Business enquiries: jane@brand.test</p>','https://brand.test/contact')):
    with self.assertRaises(web.CrawlError):recommendation.research({'id':'A'},contact)
 def test_source_429_is_automatically_scheduled_by_worker(self):
  import time,io
  contact=self.contact()
  lid=store.add_lead('A','queued',data={'manual':{'url':contact['website'],'email':contact['email'],'radar':contact}})
  error=web.urllib.error.HTTPError(contact['website'],429,'Too many requests',{'Retry-After':'600'},io.BytesIO(b'limited'))
  with patch.object(worker.AccountWorker,'profile',new_callable=PropertyMock,return_value={'inquiry_first':True}),patch.object(web,'page',side_effect=error):
   worker.AccountWorker('A').process(store.lead(lid),None)
  saved=store.lead(lid)
  self.assertEqual(saved['status'],'queued')
  self.assertGreater(saved['data']['research_retry_at'],time.time()+590)
  self.assertEqual(saved['data']['research_retry_count'],1)
 def test_recheck_finds_published_replacement_and_reverifies(self):
  contact=self.contact();contact['recheck_email']=True
  with patch.object(web,'page',return_value=('<p>Business enquiries: sales@brand.test</p>','https://brand.test/contact')):
   prospect,_=recommendation.research({'id':'A'},contact)
  self.assertEqual(prospect['email'],'sales@brand.test')
  self.assertTrue(prospect['email_verified'])
 def test_local_rate_limit_still_defers(self):
  with patch.object(web,'page',side_effect=web.DeferredFetch(9999999999)):
   with self.assertRaises(web.DeferredFetch):recommendation.research({'id':'A'},self.contact())
 def test_suppressed_customer_cannot_become_introduction(self):
  store.x('INSERT INTO suppress(value,kind) VALUES(?,?)',('jane@brand.test','unsubscribe'))
  with patch.object(web,'page') as page:
   with self.assertRaises(web.CrawlError):recommendation.research({'id':'A'},self.contact())
  page.assert_not_called()
 def test_missing_exhibition_record_never_invents_attendance(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(recommendation,'EXHIBITION',Path(tmp)),patch.object(web,'page',return_value=('<p>Business enquiries: jane@brand.test</p>','https://brand.test/contact')):
   prospect,_=recommendation.research({'id':'A'},self.contact())
   self.assertNotIn('exhibitor',prospect['site_description'].lower())
 def test_verified_exhibition_history_is_dated(self):
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'USCP-001.json').write_text(json.dumps({'company':'Example Beauty','source_record':{'company':'Example Beauty','sources':[{'source':'https://cosmoprofnorthamerica.com/list.pdf','year':2023,'company':'Example Beauty'}]}}))
   with patch.object(recommendation,'EXHIBITION',Path(tmp)),patch.object(web,'page',return_value=('<p>Business enquiries: jane@brand.test</p>','https://brand.test/contact')):
    prospect,_=recommendation.research({'id':'A'},self.contact())
   self.assertIn('2023',prospect['site_description']);self.assertIn('Cosmoprof',prospect['site_description'])
 def test_prompts_do_not_invent_product_or_require_picture(self):
  with patch.object(pipeline,'brief',return_value={'company':'Account A','pitch':'Paper boxes'}):
   system,user=pipeline.writer_prompts({'id':'A','contact_name':'Hugo'},{'inquiry_first':True},{'company':'Example','introduction_only':True,'site_description':'Business contact published on its website.'},False)
  self.assertIn('general introduction',system.lower());self.assertIn('Never infer products from the company name alone',system)
 def test_exhibition_worker_uses_contact_first_and_preserves_identity(self):
  contact=self.contact();contact['evidence_by_field']={'identity':[{'url':'https://brand.test/contact','quote':'Jane Smith jane@brand.test'}]}
  lid=store.add_lead('A','queued',data={'manual':{'url':contact['website'],'email':contact['email'],'radar':contact}})
  prospect={'company':'Example Beauty','website':contact['website'],'domain':'brand.test','email':contact['email'],'email_verified':True,'introduction_only':True,'site_description':'Verified contact'}
  profile={'inquiry_first':True,'hybrid_concepts':True,'image_optional':True,'image':{'enabled':True}}
  with patch.object(worker.AccountWorker,'profile',new_callable=PropertyMock,return_value=profile),patch.object(recommendation,'research',return_value=(prospect,None)) as intro,patch.object(pipeline,'research') as normal,patch.object(pipeline,'write',return_value={'subject':'Packaging support','body':'Hi Jane Smith,\nIf paper boxes are relevant, could I share options?'}),patch.object(pipeline,'make_image') as image:
   worker.AccountWorker('A').process(store.lead(lid),None)
  self.assertEqual(store.lead(lid)['status'],'ready');intro.assert_called_once();normal.assert_not_called();image.assert_not_called()

if __name__=='__main__':
 import unittest
 unittest.main()

import unittest
from unittest.mock import patch
from outreach import recommendation, pipeline, web

class EvidenceReuse(unittest.TestCase):
    def test_research_and_identity_share_same_verified_page(self):
        contact={'company':'Brand','website':'https://brand.test/','email':'jane@brand.test','sources':['https://brand.test/contact']}
        quote='Jane Smith Purchasing Email jane@brand.test'
        doc='<p>Jane Smith Purchasing <a href="mailto:jane@brand.test">Email</a></p>'
        with patch.object(recommendation.config,'load',return_value={'accounts':[]}), patch.object(recommendation.store,'hard_blocked',return_value=False), patch.object(web,'page',return_value=(doc,contact['sources'][0])) as fetch, patch.object(pipeline.llm,'Stage') as stage:
            stage.return_value.json.return_value={'name':'Jane Smith','email':contact['email'],'quote':quote}
            p,_=recommendation.research({'id':'A'},contact)
            pipeline.resolve_recipient_identity({'id':'A'},p)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(p['verified_contact_name'],'Jane Smith')

    def test_changed_recipient_forces_new_evidence(self):
        p={'website':'https://brand.test/','email_source':'https://brand.test/contact','email':'jane@brand.test'}
        p.update(web.recipient_evidence('<p>John Smith john@brand.test</p>','john@brand.test',p['email_source']))
        with patch.object(web,'page',return_value=('<p>Jane Smith jane@brand.test</p>',p['email_source'])) as fetch, patch.object(pipeline.llm,'Stage') as stage:
            stage.return_value.json.return_value={'name':'Jane Smith','email':p['email'],'quote':'Jane Smith jane@brand.test'}
            pipeline.resolve_recipient_identity({'id':'A'},p)
            fetch.assert_called_once()
            self.assertEqual(p['verified_contact_name'],'Jane Smith')

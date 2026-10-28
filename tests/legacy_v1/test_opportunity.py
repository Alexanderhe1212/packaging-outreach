import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from outreach import opportunity

class OpportunityTests(unittest.TestCase):
    def item(self):
        return dict(domain='buyer.test', source_url='https://buyer.test/rfq', opportunity_tier='A+', buyer_role='buyer', project_name='Serum gift box', product_url='https://buyer.test/products/serum', evidence_quote='We are looking for packaging suppliers for our serum gift boxes.', published_at=datetime.now(timezone.utc).date().isoformat(), open_window_evidence='We are accepting quotes from suppliers.', requested_product='serum gift boxes', quantity='2000 units')
    def test_launch_cannot_be_demand(self):
        i=self.item();i['evidence_quote']='Our new Christmas collection has launched.'
        with patch.object(opportunity.web,'page',return_value=(i['evidence_quote'],i['source_url'])):opportunity.verify(i)
        self.assertEqual(i['opportunity_tier'],'B')
    def test_open_verified_requires_dated_quote_and_requirements(self):
        i=self.item();doc=' '.join([i[k] for k in ('evidence_quote','published_at','open_window_evidence','requested_product','quantity')])
        with patch.object(opportunity.web,'page',return_value=(doc,i['source_url'])):opportunity.verify(i)
        self.assertEqual(i['opportunity_tier'],'A+')
    def test_unknown_window_only_A(self):
        i=self.item()
        with patch.object(opportunity.web,'page',return_value=(i['evidence_quote'],i['source_url'])):opportunity.verify(i)
        self.assertEqual(i['opportunity_tier'],'A')
    def test_external_identity_not_auto_qualified(self):
        i=self.item();i['source_url']='https://board.test/rfq'
        with patch.object(opportunity.web,'page') as page:opportunity.verify(i);page.assert_not_called()
        self.assertEqual(i['opportunity_tier'],'B')
    def test_fabricated_quote_kept_in_backlog(self):
        i=self.item()
        with patch.object(opportunity.web,'page',return_value=('We sell cosmetics',i['source_url'])):opportunity.verify(i)
        self.assertEqual(i['opportunity_tier'],'B')

    def test_old_demand_not_current(self):
        i=self.item();i['published_at']='2020-01-01'
        with patch.object(opportunity.web,'page',return_value=(i['evidence_quote'],i['source_url'])):opportunity.verify(i)
        self.assertEqual(i['opportunity_tier'],'C')

"""Offline precision regressions; no model, mailbox, or external network calls."""
import json
import unittest
from unittest.mock import patch
from outreach import web, pipeline


class PrecisionTests(unittest.TestCase):
    def test_product_http_failure_becomes_reviewable_skip(self):
        def page(url):
            if '/products/' in url:
                raise OSError('HTTP 429')
            return '<title>Brand</title>',url
        with patch.object(web,'page',side_effect=page), patch.object(web,'find_email',return_value=('hello@brand.com','https://brand.com/contact')):
            with self.assertRaises(web.CrawlError):
                web.crawl('https://brand.com/products/serum')

    def test_non_shopify_json_array_is_not_catalog(self):
        with patch.object(web, 'get', return_value=(b'[]','https://brand.com/products.json','application/json')):
            self.assertIsNone(web.shopify_product('https://brand.com/'))

    def test_order_only_and_conflicting_link_rejected(self):
        self.assertEqual(web.best_email(['orders@brand.com', 'support@brand.com'], 'brand.com'), '')
        self.assertNotIn('hello@brand.com', web.business_emails('<p>For order enquiries only: hello@brand.com</p>'))
        self.assertEqual(web.business_emails('<a href="mailto:support@brand.com">info@brand.com</a>'), [])
        self.assertEqual(web.business_emails('<script>var email="info@brand.com"</script>'), [])
        self.assertEqual(web.business_emails('<p>General enquiries: info@brand.com</p>'), ['info@brand.com'])

    def test_supplied_email_is_not_proof(self):
        with patch.object(web, 'page', return_value=('<p>hello@brand.com</p>', 'https://brand.com/contact')):
            self.assertEqual(web.find_email('hello@brand.com', 'https://brand.com/', email_hint='fake@brand.com'), ('', ''))
            with self.assertRaises(web.CrawlError):
                web.verify_email('fake@brand.com', 'https://brand.com/contact', 'https://brand.com/')

    def test_cross_brand_redirect_not_a_source(self):
        with patch.object(web, 'page', return_value=('info@brand.com', 'https://agency.com/contact')):
            with self.assertRaises(web.CrawlError):
                web.verify_email('info@brand.com', 'https://brand.com/contact', 'https://brand.com/')

    def test_jsonld_skips_digital_giftcard_and_keeps_real_refill(self):
        doc = '<script type="application/ld+json">' + json.dumps([
            {'@type':'Product','name':'E-Gift Voucher','image':'/gift.jpg'},
            {'@type':'Product','name':'Perfume Refill','image':'/refill.jpg','url':'https://brand.com/products/refill'}]) + '</script>'
        p = web.jsonld_product(doc, 'https://brand.com/')
        self.assertEqual(p['name'], 'Perfume Refill')
        self.assertTrue(web.valid_product(p, 'https://brand.com/'))
        p['url'] = 'https://other.com/products/refill'
        self.assertFalse(web.valid_product(p, 'https://brand.com/'))

    def test_news_og_does_not_become_product(self):
        doc = '<a href="/shop/story">Story</a>'
        news = '<meta property="og:title" content="Launch news"><meta property="og:image" content="/news.jpg">'
        with patch.object(web, 'page', return_value=(news, 'https://brand.com/shop/story')):
            self.assertIsNone(web.product_from_links(doc, 'https://brand.com/'))

    def test_packaging_supplier_rejected_before_contact_or_ai(self):
        doc = '<title>BoxCo</title><meta name="description" content="Custom packaging solutions">'
        with patch.object(web, 'page', return_value=(doc, 'https://brand.com/')):
            with self.assertRaisesRegex(web.CrawlError, '包装同行'):
                web.crawl('https://brand.com/')

    def test_unknown_budget_physical_brand_allowed_with_evidence(self):
        product = dict(name='Rose Perfume', url='https://brand.com/products/rose',image_url='https://brand.com/rose.jpg',facts=['30ml'],price='',description='Rose')
        with patch.object(web, 'page', return_value=('<title>Brand</title>General enquiries: info@brand.com', 'https://brand.com/')), patch.object(web, 'shopify_product', return_value=product):
            p = web.crawl('https://brand.com/')
        self.assertTrue(p['email_verified'])
        self.assertEqual(p['email_source'], 'https://brand.com/')
        self.assertEqual(p['purchase_signal'], 'fit_inference')
        self.assertIn('Rose Perfume', p['match_reason'])
        self.assertEqual(p['product_source'], product['url'])

    def test_explicit_product_never_swapped_for_another_sku(self):
        with patch.object(web, 'page', return_value=('<title>Brand</title>info@brand.com', 'https://brand.com/products/requested')), patch.object(web, 'shopify_product') as catalog:
            with self.assertRaisesRegex(web.CrawlError, '不自动换'):
                web.crawl('https://brand.com/products/requested')
            catalog.assert_not_called()

    def test_missing_physical_product_rejected(self):
        with patch.object(web, 'page', return_value=('<title>Brand</title>info@brand.com', 'https://brand.com/')), patch.object(web, 'shopify_product', return_value=None), patch.object(web, 'product_from_links', return_value=None):
            with self.assertRaisesRegex(web.CrawlError, '实体产品'):
                web.crawl('https://brand.com/')

    def test_manual_research_cannot_bypass_photo_evidence(self):
        p = dict(domain='brand.com', email='info@brand.com', email_verified=True, product_name='Perfume',product_url='https://brand.com/products/rose')
        with patch.object(web, 'crawl', return_value=p), patch.object(pipeline, 'own_domains', return_value=set()), patch.object(pipeline.store, 'hard_blocked', return_value=False), patch.object(web, 'product_image', return_value=(None,None)):
            with self.assertRaisesRegex(web.CrawlError, '可展示'):
                pipeline.research({'id':'GUKA'}, 'https://brand.com', manual=True)

if __name__ == '__main__':
    unittest.main()

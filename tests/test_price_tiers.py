import tempfile
import unittest
from pathlib import Path

from packaging_outreach.config import example
from packaging_outreach.engine import Engine
from packaging_outreach import profiles
from packaging_outreach.sources import NOW
from fixture_png import png
from test_workflow import FakeProvider


def price_fetch(amount):
    def fetch(url, allowed):
        import hashlib
        if url.endswith('/'):
            text='Fixture Fragrance'
        elif url.endswith('contact'):
            text='trade@brand.example'
        else:
            text=f'50 mL fragrance USD {amount} https://brand.example/bottle.png'
        return {'url':url,'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest(),
            'checked_at':NOW().isoformat(),'provenance':'direct_public_https'}
    return fetch


class LowPriceProvider(FakeProvider):
    def __init__(self, wrong_tier=False):
        super().__init__();self.wrong_tier=wrong_tier

    def call(self, stage, prompt, data, rid, images=()):
        result=super().call(stage,prompt,data,rid,images)
        if stage=='research':
            result['candidate']['retail_price'].update(amount=49.99,source_quote='USD 49.99')
        if stage=='plan' and not self.wrong_tier:
            result={
                'a':{'structure':'folding-ste','support':'folded-card','accessories':[],
                    'description':'Scored straight-tuck cardstock carton','fit_reason':'Compact fitted presentation'},
                'b':{'structure':'folding-sleeve','support':'corrugated','accessories':[],
                    'description':'Lightweight cardstock sleeve and tray','fit_reason':'A distinct sliding reveal'},
            }
        return result


class PriceTierTests(unittest.TestCase):
    def engine(self, directory, provider, amount=49.99):
        config=example();config.update(workspace=directory,auto_discover=False,product_profile='paper-packaging')
        engine=Engine(config,provider,price_fetch(amount));engine.reference=lambda _:(png(),'image/png')
        engine.store.setting('paused','false');engine.store.add('brand-a',{})
        return engine

    def test_selected_cardstock_inserts_fixed_1000_moq(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=self.engine(directory,LowPriceProvider());engine.run(until_idle=True)
            job=next(engine.store.get(x['id']) for x in engine.store.status()['jobs'] if x['company_key'])
            self.assertEqual(job['payload']['packaging_tier'],'folding_carton')
            self.assertEqual(job['payload']['minimum_order_quantity'],1000)
            self.assertEqual({job['payload']['plan'][x]['structure'] for x in ('a','b')},
                {'folding-ste','folding-sleeve'})
            self.assertIn('production starts at 1,000 pieces',job['payload']['draft']['body'])
            self.assertEqual(job['state'],'done')
            self.assertEqual(len(list((Path(directory)/'outbox').glob('*.eml'))),1)
            tampered=dict(job['payload'],packaging_tier='rigid_box')
            with self.assertRaises(ValueError):profiles.validate_price_tier_payload(tampered)
            tampered=dict(job['payload'],minimum_order_quantity=500)
            with self.assertRaises(ValueError):profiles.validate_price_tier_payload(tampered)

    def test_low_price_rigid_plan_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=LowPriceProvider(wrong_tier=True);engine=self.engine(directory,provider)
            engine.run(until_idle=True)
            job=next(engine.store.get(x['id']) for x in engine.store.status()['jobs'] if x['company_key'])
            self.assertEqual(job['state'],'done')
            self.assertEqual(job['payload']['packaging_tier'],'rigid_box')
            self.assertIn('image',[stage for stage,_ in provider.calls])
            self.assertEqual(len(list((Path(directory)/'outbox').glob('*.eml'))),1)

    def test_price_does_not_restrict_catalogue(self):
        with tempfile.TemporaryDirectory() as directory:
            provider=FakeProvider();candidate=provider.call('research','',{},'r')['candidate']
            candidate['retail_price'].update(amount=50,source_quote='USD 50')
            engine=self.engine(directory,provider,amount=50)
            payload=engine.verify(candidate,[])
            self.assertNotIn('packaging_tier',payload)
            profile=profiles.for_payload(profiles.resolve(engine.config),payload)
            self.assertIn('folding-ste',profile['structures']);self.assertIn('hinged',profile['structures'])
            self.assertNotIn('minimum_order_quantity',payload)


if __name__=='__main__':
    unittest.main()

    def test_mixed_plan_with_no_price_has_option_scoped_moq(self):
        profile=profiles.resolve({'product_profile':'paper-packaging'})
        plan={'a':{'structure':'folding-ste','support':'folded-card','accessories':[],
                'description':'Compact paper carton','fit_reason':'Paper cradle holds the single bottle'},
              'b':{'structure':'hinged','support':'black-eva','accessories':[],
                'description':'Hinged presentation box','fit_reason':'Fitted cavity supports the fragile bottle'}}
        plan=profiles.normalize_plan(plan,profile)
        payload={'seller_profile':profile,'plan':plan,'retail_price':None}
        profiles.bind_plan(payload,plan,profile)
        self.assertEqual(payload['packaging_tier'],'mixed')
        self.assertEqual(payload['cardstock_options'],['a'])
        from packaging_outreach import sales
        payload['draft']={'body':sales.add_packaging_terms('A paper option. B rigid option.',payload)}
        self.assertIn('For any selected cardstock option',payload['draft']['body'])
        profiles.validate_product_fit_payload(payload)
        plan['a']['support']='black-eva'
        with self.assertRaises(ValueError):profiles.normalize_plan(plan,profile)

    def test_missing_fit_reason_is_not_a_complete_plan(self):
        profile=profiles.resolve({})
        plan=FakeProvider().call('plan','',{},'r')
        plan['a']['fit_reason']=''
        with self.assertRaises(ValueError):profiles.normalize_plan(plan,profile)

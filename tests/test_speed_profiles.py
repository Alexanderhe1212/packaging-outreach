import copy,json,tempfile,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from packaging_outreach import profiles,performance
from packaging_outreach.cache import PageCache
from packaging_outreach.config import example,load
from packaging_outreach.engine import Engine
from packaging_outreach.store import Store
from packaging_outreach.providers import HTTPProvider
from test_workflow import FakeProvider,fetch
from fixture_png import png


DISPLAY = {'name':'Retail displays','offer':'Custom countertop product displays',
    'target':'Retail beauty brands','design_rules':'Stable base and product-sized supports.',
    'validation_note':'Load and fit require physical sample validation.',
    'structures':{'tiered':'Tiered display','backboard':'Display with backboard'},
    'supports':['cutout','shelf'],'accessories':[],'price_policy':{'required':False}}


class SpeedAndProfileTests(unittest.TestCase):
    def test_non_packaging_profile_completes_without_retail_price_and_keeps_sender(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c.update(workspace=d,auto_discover=False,product_profile='displays',product_profiles={'displays':DISPLAY})
            p=FakeProvider();original=p.call;seen=[]
            def call(stage,prompt,data,rid,images=()):
                seen.append((stage,data))
                result=original(stage,prompt,data,rid,images)
                if stage=='research':result['candidate']['retail_price']=None
                if stage=='plan':return {k:{'structure':structure,'support':'shelf','accessories':[],'description':'Custom display','fit_reason':'Holds the actual product'} for k,structure in [('a','tiered'),('b','backboard')]}
                return result
            p.call=call;e=Engine(c,p,fetch);e.reference=lambda p:(png(),'image/png')
            e.store.setting('paused','false');e.store.add('brand-a',{});e.run(until_idle=True)
            self.assertTrue(all(j['state']=='done' for j in e.store.status()['jobs']))
            self.assertEqual(dict(seen)['research']['price_policy'],{'required':False})
            self.assertEqual(dict(seen)['image']['seller_profile']['offer'],DISPLAY['offer'])
            self.assertEqual(e.status()['performance']['brands']['brand-a']['prepared_end_to_end']['count'],1)
            self.assertEqual(e.status()['performance']['brands']['brand-a']['accepted_end_to_end']['count'],0)
            self.assertEqual(len(list((Path(d)/'outbox').glob('*.eml'))),1)

    def test_broad_packaging_requires_exact_usd_price_without_inventing_intent(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c.update(workspace=d,product_profile='paper-packaging');e=Engine(c,FakeProvider(),fetch)
            candidate=FakeProvider().call('research','',{},'r')['candidate'];candidate['retail_price']=None
            with self.assertRaises(ValueError):e.verify(candidate,[])
            self.assertEqual(profiles.resolve(c)['price_policy'],{'required':True,'minimum':0,'currencies':['USD']})

    def test_packaging_price_filter_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c.update(workspace=d,product_profile='premium-packaging');e=Engine(c,FakeProvider(),fetch)
            candidate=FakeProvider().call('research','',{},'r')['candidate'];candidate['retail_price']=None
            with self.assertRaises(ValueError):e.verify(candidate,[])

    def test_cache_single_fetch_for_concurrent_accounts_and_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def source(url,allowed):calls.append(url);time.sleep(.01);return {'text':'actual','checked_at':'original'}
            cache=PageCache(d,source,30)
            with ThreadPoolExecutor(max_workers=4) as pool:pages=list(pool.map(lambda _:cache('https://example.test',{'example.test'}),range(4)))
            self.assertEqual(len(calls),1);self.assertTrue(all(p['checked_at']=='original' for p in pages))
            with patch('packaging_outreach.cache.time.time',return_value=time.time()+31):cache('https://example.test',{'example.test'})
            self.assertEqual(len(calls),2)

    def test_accounts_share_round_robin_discovery_and_running_backpressure(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c['workspace']=d;c['brands'].append(dict(c['brands'][0],id='brand-b'))
            c['performance']['max_pending_per_brand']=1;e=Engine(c,FakeProvider(),fetch)
            e.discover_next({});first=e.store.queue()[0];self.assertEqual(first['brand'],'brand-a')
            e.discover_next({});self.assertEqual(len(e.store.queue()),1)
            e.store.advance(first['id'],'done',{},'done');e.store.setting('discovery_next_at',0)
            e.discover_next({});self.assertEqual(e.store.queue()[0]['brand'],'brand-b')
            e.store.advance(e.store.queue()[0]['id'],'done',{},'done')
            for brand in e.brands:
                jid=e.store.add(brand,{},'concept')
                with e.store.db() as db:db.execute("UPDATE jobs SET state='running' WHERE id=?",(jid,))
            e.store.setting('discovery_next_at',0);e.discover_next({})
            self.assertFalse(any(j['stage']=='research' for j in e.store.queue()))

    def test_duplicate_research_skips_http_and_image_before_spend(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c['workspace']=d;p=FakeProvider();e=Engine(c,p,fetch)
            candidate=p.call('research','',{},'r')['candidate'];e.store.add('brand-a',candidate,'concept')
            jid=e.store.add('brand-a',{});e.store.setting('paused','false')
            with patch.object(e,'verify') as verify:e.process(jid);verify.assert_not_called()
            self.assertIsNone(e.store.get(jid)['payload']['new_job_id'])

    def test_global_image_cap_applies_across_accounts(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c['workspace']=d;c['provider_concurrency']['image']=1
            lock=threading.Lock();active=0;peak=0
            class Provider:
                def call(self,*a):
                    nonlocal active,peak
                    with lock:active+=1;peak=max(peak,active)
                    time.sleep(.02)
                    with lock:active-=1
                    return {'ok':True}
            e=Engine(c,Provider(),fetch)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i:e.api({'id':str(i)},'image','',{}),range(4)))
            self.assertEqual(peak,1)

    def test_reference_download_overlaps_plan(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c['workspace']=d;p=FakeProvider();e=Engine(c,p,fetch)
            started=threading.Event();proceed=threading.Event();original=p.call
            def reference(payload):started.set();self.assertTrue(proceed.wait(2));return png(),'image/png'
            def call(stage,*args):
                if stage=='plan':self.assertTrue(started.wait(2));proceed.set()
                return original(stage,*args)
            e.reference=reference;p.call=call
            payload=e.verify(p.call('research','',{},'r')['candidate'],[])
            jid=e.store.add('brand-a',payload,'concept');e.store.setting('paused','false');e.process(jid)
            self.assertEqual(e.store.get(jid)['stage'],'draft')

    def test_end_to_end_includes_research_and_queue_and_never_counts_export_as_send(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);a=s.add('a',{'company_url':'https://one.example'},'done',origin=100)
            b=s.add('a',{'company_url':'https://two.example'},'done',origin=110)
            with s.db() as db:
                db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",('accepted',a,'one.example','a@one.example','mid','accepted','final_ack','sha',400))
                db.execute('UPDATE jobs SET payload=?,updated=? WHERE id=?',(json.dumps({'delivery':{'result':'spooled'}}),120,b))
            r=performance.report(s,300,now=401)['brands']['a']
            self.assertEqual(r['accepted_end_to_end']['p50_seconds'],300)
            self.assertEqual(r['accepted_within_target'],1)
            self.assertEqual(r['prepared_end_to_end']['p50_seconds'],10)
            self.assertEqual(r['accepted_interval']['count'],0)

    def test_stage_model_override_and_image_controls_reach_api(self):
        c={'providers':{'text':{'kind':'chat','base_url':'https://a.example','model':'default'},'plan':{'kind':'chat','base_url':'https://b.example','model':'quick','reasoning_effort':'low','max_output_tokens':1000}}}
        with patch('packaging_outreach.providers.post',return_value={'choices':[{'message':{'content':'{}'}}]}) as send:
            HTTPProvider(c).call('plan','',{},'r')
            self.assertEqual(send.call_args.args[0],'https://b.example/chat/completions')
            self.assertEqual(send.call_args.args[1]['model'],'quick')
            self.assertEqual(send.call_args.args[1]['max_completion_tokens'],1000)

    def test_invalid_limits_and_profile_rejected_before_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'outreach.json';c=example();c['provider_concurrency']['image']=0;p.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load(p)
            c=example();c['product_profile']='missing';p.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load(p)

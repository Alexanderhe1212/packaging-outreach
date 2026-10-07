import json,tempfile,unittest
from unittest.mock import patch
from packaging_outreach.context import hints
from packaging_outreach.engine import Engine
from packaging_outreach.config import example

class ContextTests(unittest.TestCase):
    def test_large_history_and_long_addresses_stay_bounded(self):
        values=['company-%05d.example'%n for n in range(10000)]
        original=list(values);selected=hints(values,9)
        self.assertLessEqual(len(selected),160);self.assertLess(len(json.dumps(selected)),3600)
        self.assertEqual(values,original);self.assertNotEqual(selected,hints(values,10))
        self.assertLess(len(json.dumps(hints(['a'*240+str(n)+'.example' for n in range(500)],0))),3600)
    def test_omitted_model_hint_does_not_bypass_local_duplicate_check(self):
        with tempfile.TemporaryDirectory() as directory:
            config=example();config.update(workspace=directory,auto_discover=False)
            engine=Engine(config);engine.store.setting('paused','false')
            domain='already.example';engine.store.add('brand-a',{'company_url':'https://'+domain},'concept')
            jid=engine.store.add('brand-a',{})
            answer={'candidate':{'company_url':'https://'+domain,'recipient':'trade@already.example'}}
            with patch('packaging_outreach.context.hints',return_value=[]),patch.object(engine,'api',return_value=answer),patch.object(engine,'verify',side_effect=AssertionError('Duplicate reached verification')):
                engine.process(jid)
            self.assertIsNone(engine.store.get(jid)['payload']['new_job_id'])
            self.assertEqual(len(engine.store.status()['jobs']),2)

    def test_status_and_discovery_only_return_bounded_metadata(self):
        from packaging_outreach.store import Store
        from packaging_outreach.sources import grounded_facts
        with tempfile.TemporaryDirectory() as d:
            store=Store(d)
            with store.db() as c:
                for i in range(300):
                    c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,0)',(str(i),'brand-a','company-%03d.example'%i,'sales@company-%03d.example'%i,'done','done','{}',i))
            info=store.discovery_context(2)
            self.assertLessEqual(len(info['excluded_company_domains']),160)
            hidden=next('company-%03d.example'%i for i in range(300) if 'company-%03d.example'%i not in info['excluded_company_domains'])
            self.assertTrue(store.discovery_known(hidden,'unknown@example.test'))
            first=store.status();second=store.status(offset=25)
            self.assertEqual(first['counts']['jobs'],300);self.assertEqual(len(first['jobs']),25)
            self.assertFalse({j['id'] for j in first['jobs']} & {j['id'] for j in second['jobs']})
            self.assertNotIn('payload',first['jobs'][0])
        self.assertEqual(grounded_facts({'product_facts':['Soap bar','They need packaging urgently']},'Soap bar'),['Soap bar'])

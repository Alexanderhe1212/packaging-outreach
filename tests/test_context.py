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

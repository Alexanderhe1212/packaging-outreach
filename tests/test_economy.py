import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from packaging_outreach.config import example,load
from packaging_outreach.engine import Engine
from packaging_outreach import sales,profiles,performance
from packaging_outreach.providers import HTTPProvider,ProviderRejected
from packaging_outreach.cli import doctor
from test_workflow import FakeProvider,fetch
from fixture_png import png


def slots():
    return {'subject':'Two directions for your fragrance','fact_index':0,
        'opening':'I prepared two concepts for your 50 mL fragrance.',
        'a_value':'The paired doors offer a clear product reveal.',
        'b_value':'The shoulder structure frames the bottle in a fitted support.',
        'service_id':'concepts'}


class EconomyProvider(FakeProvider):
    def __init__(self):super().__init__();self.inputs=[];self.correct=True
    def call(self,stage,prompt,data,rid,images=()):
        self.inputs.append((stage,data,images))
        if stage=='identity':
            self.calls.append((stage,rid));return {'correct_product':True,'correct_count':self.correct,'usable_image':True}
        result=super().call(stage,prompt,data,rid,images)
        if stage=='plan':result['email']=slots()
        return result


class EconomyTests(unittest.TestCase):
    def engine(self,d):
        c=example();c.update(workspace=d,auto_discover=False,workflow={'mode':'economy'})
        p=EconomyProvider();e=Engine(c,p,fetch);e.reference=lambda _:(png(),'image/png');e.store.setting('paused','false');e.store.add('brand-a',{});return e,p

    def test_text_only_plan_email_and_short_separate_identity_resume_to_mime(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.engine(d)
            with patch('packaging_outreach.transport.send_once') as smtp:
                e.run(until_idle=True);e.run(until_idle=True);smtp.assert_not_called()
            self.assertEqual([x[0] for x in p.calls],['research','plan','image','identity'])
            self.assertEqual([x for x in p.inputs if x[0]=='plan'][0][2],())
            self.assertEqual(len([x for x in p.inputs if x[0]=='identity'][0][2]),2)
            job=next(e.store.get(j['id']) for j in e.store.status()['jobs'] if j['company_key'])
            self.assertEqual(job['state'],'done');draft=job['payload']['draft']
            self.assertEqual(draft['body'].count('?'),1)
            self.assertIn('50 mL fragrance',draft['body'])
            self.assertEqual(draft['reply_goal'],'choose_a_or_b')
            self.assertEqual(len(list((Path(d)/'outbox').glob('*.eml'))),1)

    def test_wrong_identity_keeps_prepared_text_but_does_not_send(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.engine(d);p.correct=False;e.run(until_idle=True)
            job=next(e.store.get(j['id']) for j in e.store.status()['jobs'] if j['company_key'])
            self.assertEqual(job['state'],'blocked');self.assertIn('prepared_email',job['payload'])
            self.assertFalse((Path(d)/'outbox').exists())

    def test_ungrounded_opening_or_invented_service_rejected_before_image_spend(self):
        for field,value in [('opening','You urgently need a new supplier.'),('service_id','certified_free_shipping')]:
            with tempfile.TemporaryDirectory() as d:
                e,p=self.engine(d);original=p.call
                def call(stage,*args):
                    result=original(stage,*args)
                    if stage=='plan':result['email'][field]=value
                    return result
                p.call=call;e.run(until_idle=True)
                self.assertNotIn('image',[x[0] for x in p.calls])

    def test_legacy_text_api_gets_plain_string_no_json_mode_or_reasoning_parameter(self):
        c={'providers':{'text':{'kind':'chat','base_url':'https://api.example/v1','model':'small-text','vision':False,'json_mode':'prompt','max_output_tokens':1600,'token_limit_parameter':'max_tokens'}}}
        with patch('packaging_outreach.providers.post',return_value={'choices':[{'message':{'content':'```json\n{"ok":true}\n```'}}]}) as post:
            self.assertEqual(HTTPProvider(c).call('plan','Return JSON',{},'one'),{'ok':True})
            body=post.call_args.args[1]
            self.assertIsInstance(body['messages'][0]['content'],str)
            self.assertNotIn('response_format',body);self.assertNotIn('reasoning_effort',body)
            self.assertEqual(body['max_tokens'],1600);self.assertEqual(post.call_count,1)

    def test_vision_routing_does_not_silently_send_images_to_text_only_model(self):
        text={'kind':'chat','base_url':'https://text.example','model':'small','vision':False}
        c={'providers':{'text':text,'vision':dict(text,base_url='https://vision.example',model='small-vision',vision=True)}}
        response={'choices':[{'message':{'content':'{"correct_product":true,"correct_count":true,"usable_image":true}'}}]}
        with patch('packaging_outreach.providers.post',return_value=response) as post:
            HTTPProvider(c).call('identity','',{},'r',[(png(),'image/png')])
            self.assertTrue(post.call_args.args[0].startswith('https://vision.example'))
        del c['providers']['vision']
        with patch('packaging_outreach.providers.post') as post:
            with self.assertRaises(ProviderRejected):HTTPProvider(c).call('identity','',{},'r',[(png(),'image/png')])
            post.assert_not_called()

    def test_small_api_models_expand_without_assuming_model_name_capabilities(self):
        with tempfile.TemporaryDirectory() as d:
            c=example();c['api'].update(text_model='small-text',research_model='web-model',vision_model='vision-model')
            path=Path(d)/'config.json';path.write_text(json.dumps(c));loaded=load(path)
            self.assertEqual(loaded['providers']['research']['model'],'web-model')
            self.assertEqual(loaded['providers']['vision']['model'],'vision-model')
            self.assertEqual(loaded['providers']['text']['model'],'small-text')
            loaded['providers']['vision']['vision']=False;loaded['workflow']={'mode':'economy'}
            self.assertIn('Configure a vision-capable provider for product identity',doctor(loaded)['issues'])

    def test_reply_metric_counts_contacts_not_messages_and_excludes_unsent(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.engine(d);s=e.store
            jid=s.add('brand-a',{'company_url':'https://sent.example','recipient':'a@sent.example'},'done',origin=10)
            s.add('brand-a',{'company_url':'https://unsent.example','recipient':'b@unsent.example'},'done',origin=10)
            with s.db() as db:db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)',('a',jid,'sent.example','a@sent.example','mid','accepted','final_ack','sha',20))
            s.event('a@sent.example','reply','reply1');s.event('a@sent.example','reply','reply2');s.event('b@unsent.example','reply','unrelated')
            r=performance.report(s)['brands']['brand-a']['outreach_results']
            self.assertEqual(r['accepted_contacts'],1);self.assertEqual(r['recorded_reply_contacts'],1);self.assertEqual(r['recorded_reply_rate'],1)

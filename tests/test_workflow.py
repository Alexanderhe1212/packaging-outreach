import base64,hashlib,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from packaging_outreach.engine import Engine
from packaging_outreach.config import example
from packaging_outreach.providers import UncertainCall
from packaging_outreach.mail import render
from fixture_png import png

class FakeProvider:
    def __init__(self):self.calls=[];self.fail_image=False
    def call(self,stage,prompt,data,rid,images=()):
        self.calls.append((stage,rid))
        if stage=='research':return {'candidate':{'company':'Fixture Fragrance','brand_marker':'Fixture Fragrance','recipient':'trade@brand.example','company_url':'https://brand.example/','email_source_url':'https://brand.example/contact','product_evidence_url':'https://brand.example/product','product_facts':['50 mL fragrance'],'retail_price':{'amount':150,'currency':'USD','product_url':'https://brand.example/product','source_quote':'USD 150'},'product_image_url':'https://brand.example/bottle.png','unit_count':1,'count_evidence_quote':'50 mL fragrance'},'pages':[]}
        if stage=='plan':return {'a':{'box':'double-door','insert':'folded-card','accessories':[],'description':'Doors with supported bottle','fit_reason':'Open display'},'b':{'box':'shoulder','insert':'black-eva','accessories':['satin-ribbon'],'description':'Shoulder box with external ribbon','fit_reason':'Fitted protection'}}
        if stage=='image':
            if self.fail_image:raise UncertainCall('connection lost')
            return {'png_base64':base64.b64encode(png()).decode()}
        if stage=='draft':return {'subject':'Packaging concepts for your fragrance','body':'Option A offers an open display. Option B uses fitted support. Dimensions, fit and closure require sample validation.','identity':{'correct_product':True,'correct_count':True,'usable_image':True}}
        raise AssertionError(stage)

def fetch(url,allowed):
    from packaging_outreach.sources import NOW
    text='Fixture Fragrance' if url.endswith('/') else 'trade@brand.example' if url.endswith('contact') else '50 mL fragrance USD 150 https://brand.example/bottle.png'
    return {'url':url,'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest(),'checked_at':NOW().isoformat(),'provenance':'direct_public_https'}

class WorkflowTests(unittest.TestCase):
    def setup_engine(self,d):
        c=example();c.update(workspace=d,auto_discover=False);provider=FakeProvider();e=Engine(c,provider,fetch);e.reference=lambda p:(png(),'image/png');e.store.setting('paused','false');e.store.add('brand-a',{});return e,provider
    def test_full_workflow_spools_real_mime_without_smtp_or_vendor_cli(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.setup_engine(d)
            with patch('packaging_outreach.transport.send_once') as smtp:e.run(until_idle=True);smtp.assert_not_called()
            self.assertEqual([s for s,rid in p.calls],['research','plan','image','draft'])
            status=e.store.status();self.assertTrue(all(j['state']=='done' for j in status['jobs']))
            eml=list((Path(d)/'outbox').glob('*.eml'));self.assertEqual(len(eml),1)
            from email import policy
            from email.parser import BytesParser
            msg=BytesParser(policy=policy.default).parsebytes(eml[0].read_bytes());markup=msg.get_body(preferencelist=('html',)).get_content()
            self.assertEqual(len([x for x in msg.walk() if x.get_content_type()=='image/png']),1)
            self.assertLess(markup.index('Option A offers'),markup.index('cid:concept'))
            self.assertLess(markup.index('cid:concept'),markup.index('https://wa.me/'))
            self.assertEqual(markup.count('https://wa.me/'),2)
            count=len(p.calls);e.run(until_idle=True);self.assertEqual(len(p.calls),count)
    def test_uncertain_image_call_is_not_retried_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.setup_engine(d);p.fail_image=True;e.run(until_idle=True);e.run(until_idle=True)
            self.assertEqual(len([x for x in p.calls if x[0]=='image']),1)
            self.assertTrue(any(x['state']=='unknown' for x in e.store.status()['jobs']))
    def test_wrong_count_blocks_draft_and_outbox(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.setup_engine(d);original=p.call
            def call(*args):
                result=original(*args)
                if args[0]=='draft':result['identity']['correct_count']=False
                return result
            p.call=call;e.run(until_idle=True)
            self.assertFalse((Path(d)/'outbox').exists())
    def test_exact_public_email_required(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=self.setup_engine(d);candidate=p.call('research','',{},'fixture')['candidate'];candidate['recipient']='guessed@brand.example'
            with self.assertRaises(ValueError):e.verify(candidate,[])

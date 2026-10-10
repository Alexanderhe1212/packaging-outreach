"""离线端到端测试：假 AI 接口 + 假 Shopify 官网 + 假 SMTP，跑完 找客户 → 读官网 → 写信 → 生图 → 发送 → 去重。

运行：python3 -m unittest discover -s tests -v
"""
import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ['OUTREACH_DATA'] = tempfile.mkdtemp(prefix='outreach-test-')

from outreach import config, llm, mailer, pipeline, server, store, web  # noqa: E402
from outreach.worker import AccountWorker  # noqa: E402

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 9000 + b'\xff\xd9'
CALLS = []


class FakeAPI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        CALLS.append(self.path)
        if self.path.endswith('/responses'):
            assert b'web_search' in body
            text = json.dumps({'candidates': [{'brand': 'Ember & Oak', 'domain': 'emberoak.co.uk', 'note': 'candles'},
                                              {'brand': 'Own', 'domain': 'acme-pack.com', 'note': 'self'}]})
            out = {'output': [{'type': 'web_search_call'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': '```json\n' + text + '\n```'}]}],
                   'usage': {'input_tokens': 2100, 'output_tokens': 300, 'input_tokens_details': {'cached_tokens': 0}}}
        elif self.path.endswith('/chat/completions'):
            req = json.loads(body)
            assert req['messages'][1]['content'][1]['image_url']['detail'] == 'low', 'vision input missing'
            if req.get('reasoning_effort'):
                return self.fail(400, 'Unsupported parameter: reasoning_effort')  # relay that rejects it -> auto retry
            plan = {'product_visual': 'amber glass jar candle with cream label', 'count': 'one candle',
                    'a': {'name': 'Cream tube', 'structure': 'round cylinder tube box', 'visual': 'cream paper, gold foil, pulp insert'},
                    'b': {'name': 'Amber drawer', 'structure': 'drawer / slide box', 'visual': 'amber textured paper, ribbon pull'},
                    'scene': 'warm linen', 'subject': 'two gift box ideas for your Fireside candle',
                    'body': 'Hi Ember & Oak team,\n\nYour Fireside candle in its amber glass jar with a wooden wick looks made for gifting, '
                            'and the jar is the part that needs the most care in transit.\n\nI mocked up two packaging ideas for it (image below):\n\n'
                            'A - Cream tube: a snug pulp collar holds the jar upright.\n\nB - Amber drawer: slides open to reveal the candle.\n\n'
                            'If either fits, reply A or B with a rough quantity.\n\nBest regards,\nHugo'}
            out = {'choices': [{'message': {'content': json.dumps(plan)}}],
                   'usage': {'prompt_tokens': 1500, 'completion_tokens': 420, 'prompt_tokens_details': {'cached_tokens': 1024}}}
        elif '/images/' in self.path:
            assert b'name="image"' in body, 'reference photo not sent'
            out = {'data': [{'b64_json': base64.b64encode(JPEG).decode()}]}
        else:
            return self.fail(404, 'nope')
        self.send_json(out)

    def fail(self, code, msg):
        raw = json.dumps({'error': {'message': msg}}).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, out):
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class FakeShop(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith('/products.json'):
            data = {'products': [
                {'title': 'Gift Card', 'handle': 'gift-card', 'product_type': 'Gift Card', 'variants': [{'price': '500'}], 'images': [{'src': '/x.jpg'}]},
                {'title': 'Fireside Candle 300g', 'handle': 'fireside', 'product_type': 'Candle', 'body_html': '<p>Hand-poured soy wax, wooden wick.</p>',
                 'options': [{'name': 'Size', 'values': ['300g']}], 'variants': [{'price': '38.00'}], 'images': [{'src': 'http://%s/img.jpg' % self.headers['Host']}]}]}
            return self.send(json.dumps(data).encode(), 'application/json')
        if self.path.startswith('/img.jpg'):
            return self.send(JPEG, 'image/jpeg')
        if self.path == '/':
            html = ('<html lang="en-GB"><head><title>Ember &amp; Oak | Candles</title><meta property="og:site_name" content="Ember &amp; Oak">'
                    '<meta name="description" content="Small-batch candles from Yorkshire"></head><body>'
                    '<a href="/pages/contact">Contact</a> write to <a href="mailto:emberoakcandles@gmail.com">us</a></body></html>')
            return self.send(html.encode(), 'text/html; charset=utf-8')
        self.send_response(404)
        self.end_headers()

    def send(self, raw, ctype):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


SENT = []


class FakeSMTP:
    def __init__(self, *a, **k):
        pass

    def login(self, u, p):
        assert p == 'pw'

    def mail(self, s):
        pass

    def rcpt(self, r):
        return 250, b'ok'

    def data(self, m):
        SENT.append(m)
        return 250, b'queued'

    def quit(self):
        pass


def start(handler):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_port


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_port, shop_port = start(FakeAPI), start(FakeShop)
        cls.shop = 'http://127.0.0.1:%d' % shop_port
        config.save({'connections': {'main': {'preset': 'relay', 'kind': 'openai', 'base_url': 'http://127.0.0.1:%d/v1' % api_port}},
                     'accounts': [{'id': 'MTT', 'name': 'MTT', 'company_name': 'MTT Packaging', 'contact_name': 'Hugo',
                                   'sender': 'hello@acme-pack.com', 'whatsapp': '15555550100', 'profile': 'packaging',
                                   'smtp': {'host': 'smtp.test', 'port': 465}, 'imap': {'host': 'imap.test', 'port': 993},
                                   'signature': 'Hugo He\nMTT Packaging', 'auto_send': True, 'daily_limit': 40},
                                  {'id': 'GUKA', 'name': 'GUKA', 'company_name': 'GUKA Packaging', 'sender': 'sales@second-brand.com',
                                   'smtp': {'host': 'smtp.test', 'port': 465}, 'imap': {'host': 'imap.test', 'port': 993}}]})
        config.save_secrets(keys={'main': 'sk-test'}, passwords={'MTT': 'pw'})
        real_crawl = web.crawl
        web.crawl = lambda url, hint='': real_crawl(cls.shop, hint)  # every candidate domain resolves to the fake shop
        mailer.smtplib.SMTP_SSL = FakeSMTP
        mailer.sync_inbox = lambda acc: {'checked': 0}

    def test_full_flow(self):
        w = AccountWorker('MTT')
        w.set_paused(False)
        w.step()  # discover -> candidates
        self.assertEqual(store.next_candidate('MTT')['domain'], 'emberoak.co.uk')
        self.assertFalse(store.q("SELECT 1 FROM candidates WHERE domain='acme-pack.com'"), 'own domain must be dropped')
        w.step()  # crawl + write + image
        lead = store.next_lead('MTT', ('ready',))
        self.assertIsNotNone(lead, store.list_leads())
        p = lead['data']['prospect']
        self.assertEqual(p['product_name'], 'Fireside Candle 300g', 'gift cards are skipped, real product chosen')
        self.assertEqual(p['email'], 'emberoakcandles@gmail.com')
        self.assertEqual(p['customer_brand'], 'Ember & Oak')
        self.assertTrue(lead['subject'].startswith('two gift box'))
        self.assertNotIn('Best regards', lead['body'])
        self.assertGreater(lead['tokens'], 0)
        self.assertGreater(lead['cost'], 0)
        w.step()  # send
        self.assertTrue(SENT)
        raw = SENT[0].decode()
        self.assertIn('cid:concept', raw)
        self.assertIn('wa.me/15555550100', raw)
        self.assertIn('List-Unsubscribe', raw)
        self.assertEqual(store.lead(lead['id'])['status'], 'sent')
        # dedupe across accounts
        self.assertTrue(store.blocked('emberoakcandles@gmail.com', 'emberoak.co.uk'))
        # the rejected reasoning_effort was remembered: no second failing call
        n = len(CALLS)
        llm.Stage('write', 'MTT').json('s', 'u', image=JPEG)
        self.assertEqual(len(CALLS), n + 1)
        html = mailer.preview_html(config.account('MTT'), store.lead(lead['id']), JPEG)
        self.assertIn('data:image/jpeg', html)
        self.assertIn('/responses', CALLS[0])

    def test_email_choice(self):
        site = web.root_domain('www.brand.co.uk')
        self.assertEqual(site, 'brand.co.uk')
        self.assertEqual(web.best_email(['jobs@brand.co.uk', 'designer@agency.com', 'support@brand.co.uk', 'hello@brand.co.uk'], site),
                         'hello@brand.co.uk')
        self.assertEqual(web.best_email(['someone@agency.com'], site), '')
        self.assertIn('hello@brand.com', web.emails_in('write to hello [at] brand [dot] com'))

    def test_json_extraction(self):
        self.assertEqual(llm.extract_json('Sure!\n```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(llm.extract_json('text {"a": {"b": 2}} more'), {'a': {'b': 2}})

    def test_api_add_and_settings(self):
        server.sync_workers()
        r = server.api_add({'account': 'GUKA', 'urls': 'https://newbrand.com\nhello@another.de'})
        self.assertEqual(len(r['ids']), 2)
        self.assertEqual(store.lead(r['ids'][1])['email'], 'hello@another.de')
        s = server.api_settings_get(None)
        self.assertTrue(s['has_key']['main'])
        self.assertNotIn('sk-test', json.dumps(s), 'secrets never echoed to the UI')
        for w in server.WORKERS.values():
            w.stopped = True

    def test_accounts_are_separate_and_concepts_vary(self):
        store.suppress('only-mtt@brand-x.com', 'legacy_contacted', 'MTT')
        self.assertTrue(store.blocked('only-mtt@brand-x.com', account='MTT'))
        self.assertFalse(store.blocked('only-mtt@brand-x.com', account='GUKA'), 'accounts do not share history')
        config.save({'cross_account_dedupe': True})
        self.assertTrue(store.blocked('only-mtt@brand-x.com', account='GUKA'), 'optional cross-account lock')
        config.save({'cross_account_dedupe': False})
        lid = store.add_lead('MTT', 'sent', data={'plan': {'a': {'structure': 'magnetic flap rigid box'}, 'b': {'structure': 'drawer / slide box'}}})
        note = pipeline.variety_note(config.account('MTT'), config.profile('packaging'))
        self.assertIn('magnetic flap rigid box', note)
        self.assertIn('Do not repeat', note)
        store.update(lid, status='skipped')

    def test_prompt_is_cache_friendly(self):
        acc, prof = config.account('MTT'), config.profile('packaging')
        s1, _ = pipeline.writer_prompts(acc, prof, {'product_name': 'A'}, True)
        s2, _ = pipeline.writer_prompts(acc, prof, {'product_name': 'B'}, True)
        self.assertEqual(s1, s2, 'system prompt must not vary per lead')


if __name__ == '__main__':
    unittest.main()

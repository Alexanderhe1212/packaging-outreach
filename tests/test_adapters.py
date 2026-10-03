import base64,json,os,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path
from packaging_outreach.providers import HTTPProvider,post,ProviderRejected,RetryLater
from packaging_outreach.config import example,load
from fixture_png import png

class AdapterTests(unittest.TestCase):
 def test_agent_http_wire_protocol_with_local_server(self):
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));data=b'{"output":{"subject":"Ready","body":"Concept"}}';self.send_response(200);self.end_headers();self.wfile.write(data)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   c={'providers':{'text':{'kind':'agent_http','url':'http://127.0.0.1:'+str(server.server_port)+'/run'}}}
   result=HTTPProvider(c).call('draft','Return JSON',{'company':'Fixture'},'stable-id',[(png(),'image/png')])
   self.assertEqual(result['subject'],'Ready');self.assertEqual(seen[0]['request_id'],'stable-id');self.assertEqual(seen[0]['protocol'],'packaging-outreach.v1');self.assertEqual(base64.b64decode(seen[0]['images'][0]['base64']),png())
  finally:server.shutdown();server.server_close();thread.join()
 def test_chat_preserves_reference_images_and_json_contract(self):
  c={'providers':{'text':{'kind':'chat','base_url':'https://api.example.test/v1','model':'vision'}}}
  with patch('packaging_outreach.providers.post',return_value={'choices':[{'message':{'content':'{"ok":true}'}}]}) as send:
   self.assertEqual(HTTPProvider(c).call('draft','JSON',{},'rid',[(png(),'image/png')]),{'ok':True})
  args=send.call_args.args;self.assertTrue(args[0].endswith('/chat/completions'));self.assertEqual(args[1]['messages'][0]['content'][1]['type'],'image_url')
 def test_research_requires_actual_search_tool_trace(self):
  c={'providers':{'research':{'kind':'responses','base_url':'https://api.example.test/v1','model':'research','web_search':True}}}
  result={'output':[{'type':'message','content':[{'type':'output_text','text':'{"candidate":null}'}]}]}
  with patch('packaging_outreach.providers.post',return_value=result):
   with self.assertRaises(ProviderRejected):HTTPProvider(c).call('research','JSON',{},'rid')
   result['output'].append({'type':'web_search_call'});self.assertEqual(HTTPProvider(c).call('research','JSON',{},'rid'),{'candidate':None})
 def test_reference_image_edit_is_multipart_not_text_only_generation(self):
  c={'providers':{'image':{'kind':'image_edits','base_url':'https://api.example.test/v1','model':'image'}}}
  with patch('packaging_outreach.providers.post',return_value={'data':[{'b64_json':base64.b64encode(png()).decode()}]}) as send:
   HTTPProvider(c).call('image','One AB image',{},'rid',[(png(),'image/png')])
  args=send.call_args.args;self.assertTrue(args[0].endswith('/images/edits'));self.assertIn(b'name="image[]"',args[1]);self.assertIn(png(),args[1]);self.assertTrue(args[4].startswith('multipart/'))
 def test_simple_config_expands_and_secrets_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'outreach.json';c=example();p.write_text(json.dumps(c));loaded=load(p)
   self.assertEqual(loaded['providers']['text']['model'],c['api']['text_model'])
   c['providers']={'text':{'kind':'chat','base_url':'https://api.example.test','api_key':'do-not-store'}};p.write_text(json.dumps(c))
   with self.assertRaises(ValueError):load(p)

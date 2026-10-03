"""Loopback control UI. Same-host, JSON-only mutations; never a public unauthenticated API."""
import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
PAGE='''<!doctype html><meta charset="utf-8"><title>Packaging Outreach</title><style>body{font:16px system-ui;max-width:980px;margin:40px auto;padding:20px;color:#173138}button{padding:12px 22px;margin-right:10px}pre{white-space:pre-wrap;background:#f2f5f4;padding:20px}</style><h1>Packaging Outreach</h1><p>独立运行 · 多品牌 · API 可替换</p><button onclick="act('start')">启动</button><button onclick="act('pause')">暂停</button><button onclick="load()">刷新结果</button><pre id="status"></pre><script>async function load(){document.getElementById('status').textContent=JSON.stringify(await(await fetch('/status')).json(),null,2)}async function act(x){await fetch('/'+x,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});load()}load();setInterval(load,5000)</script>'''

def serve(engine,port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def valid(self):return self.headers.get('Host') in ('127.0.0.1:'+str(port),'localhost:'+str(port))
        def reply(self,value,code=200,html=False):
            raw=(value if html else json.dumps(value,ensure_ascii=False)).encode();self.send_response(code);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if not self.valid():return self.reply({'error':'Loopback host required'},403)
            if self.path=='/':return self.reply(PAGE,html=True)
            if self.path=='/status':return self.reply(engine.store.status())
            self.reply({'error':'Not found'},404)
        def do_POST(self):
            if not self.valid() or self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')):return self.reply({'error':'Same origin required'},403)
            if self.headers.get('Content-Type')!='application/json':return self.reply({'error':'JSON required'},415)
            if self.path not in ('/start','/pause'):return self.reply({'error':'Not found'},404)
            engine.store.setting('paused','false' if self.path=='/start' else 'true');self.reply({'paused':self.path=='/pause'})
    stop=threading.Event();worker=threading.Thread(target=engine.run,kwargs={'stop':stop},daemon=True);worker.start()
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print('Open http://127.0.0.1:'+str(port),flush=True)
    try:server.serve_forever()
    finally:stop.set();server.server_close();worker.join()

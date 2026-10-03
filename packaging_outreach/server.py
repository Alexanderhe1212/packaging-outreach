"""Loopback control UI. Same-host, JSON-only mutations; never a public unauthenticated API."""
import json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Outreach · 外贸获客</title>
<style>body{font:16px system-ui;max-width:1050px;margin:30px auto;padding:20px;color:#173138}button{padding:12px 22px;margin:0 10px 12px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:12px 8px;border-bottom:1px solid #d9e3e1}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f4;padding:20px}.scroll{overflow:auto}#error{color:#9c2929}</style>
<h1>外贸获客</h1><p>匹配客户 → 产品方案 → 效果图 → 个性邮件</p><button onclick="act('start')">启动</button><button onclick="act('pause')">暂停</button><button onclick="load()">刷新</button><p id="state"></p><p id="error" role="alert"></p><h2>实际速度</h2><p id="target"></p><div class="scroll"><table><thead><tr><th>账号</th><th>SMTP 接受数</th><th>全流程中位耗时</th><th>95% 分位</th><th>待完成</th><th>超目标</th><th>待处理异常</th></tr></thead><tbody id="brands"></tbody></table></div><p>准备完成与发送接受分别计时；SMTP 接受不代表客户已收件。暂无发送样本时不估算速度。</p><details><summary>任务、阶段与准备耗时</summary><pre id="status"></pre></details>
<script>
const el=id=>document.getElementById(id),duration=x=>x===null||x===undefined?'暂无':Math.round(x)+' 秒';
async function load(){try{let r=await fetch('/status');if(!r.ok)throw Error('读取失败 '+r.status);let s=await r.json(),m=s.performance;el('state').textContent=s.paused?'已暂停领取新任务':'运行中';el('target').textContent='目标 '+m.target_seconds+' 秒 / 客户（包含获客、排队、生图、正文和发送；超过目标继续处理）';let rows=[];for(let [brand,b] of Object.entries(m.brands)){let tr=document.createElement('tr');for(let value of [brand,b.accepted_count,duration(b.accepted_end_to_end.p50_seconds),duration(b.accepted_end_to_end.p95_seconds),b.active,b.over_target,b.blocked+b.unknown]){let td=document.createElement('td');td.textContent=value;tr.append(td)}rows.push(tr)}el('brands').replaceChildren(...rows);el('status').textContent=JSON.stringify(s,null,2);el('error').textContent=''}catch(e){el('error').textContent=e.message}}
async function act(x){try{let r=await fetch('/'+x,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),s=await r.json();if(!r.ok)throw Error(s.error||'操作失败');await load()}catch(e){el('error').textContent=e.message}}
load();setInterval(load,5000)</script></html>'''


def serve(engine,port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def valid(self):return self.headers.get('Host') in ('127.0.0.1:'+str(port),'localhost:'+str(port))
        def reply(self,value,code=200,html=False):
            raw=(value if html else json.dumps(value,ensure_ascii=False)).encode();self.send_response(code);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if not self.valid():return self.reply({'error':'Loopback host required'},403)
            if self.path=='/':return self.reply(PAGE,html=True)
            if self.path=='/status':return self.reply(engine.status())
            self.reply({'error':'Not found'},404)
        def do_POST(self):
            if not self.valid() or self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')):return self.reply({'error':'Same origin required'},403)
            if self.headers.get('Content-Type')!='application/json':return self.reply({'error':'JSON required'},415)
            if self.path not in ('/start','/pause'):return self.reply({'error':'Not found'},404)
            if self.path=='/start':
                from .cli import doctor
                report=doctor(engine.config)
                if not report['ready']:return self.reply({'error':'; '.join(report['issues'])},400)
            engine.store.setting('paused','false' if self.path=='/start' else 'true');self.reply({'paused':self.path=='/pause'})
    stop=threading.Event();worker=threading.Thread(target=engine.run,kwargs={'stop':stop},daemon=True);worker.start()
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print('Open http://127.0.0.1:'+str(port),flush=True)
    try:server.serve_forever()
    finally:stop.set();server.server_close();worker.join()

"""Desktop control: reuse existing APIs and account protections."""
import json,sys,urllib.request,subprocess,os
from pathlib import Path
ROOT=Path.home()/'Library/Application Support'
def request(path,data=None):
 req=urllib.request.Request('http://127.0.0.1:18800'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=12) as r:return json.load(r)
def control(action):
 if action not in ('start','pause'):raise ValueError('Unsupported action')
 if action=='start':
  request('/api/radar/configure',{'account':'GUKA','accounts':['GUKA','MTT'],'mode':'shared_random','enabled':True})
  subprocess.run(['/bin/launchctl','kickstart','gui/%s/com.userradar.autoprospect'%os.getuid()],check=True,timeout=10)
 for account in ('GUKA','MTT'):request('/api/'+action,{'account':account})
def boot():
 # Ensure services only. Never implicitly start sending on window launch.
 outreach=ROOT/'OutreachPilot/app'
 subprocess.run(['/usr/bin/python3','-c',"import runpy; assert runpy.run_path('app.py',run_name='launcher')['ensure_running']()"],cwd=outreach,check=True,timeout=25)
 radar=ROOT/'UserRadar/automatic-app'
 subprocess.run([str(radar/'.venv/bin/python'),str(radar/'desktop_launcher.py'),'--check-only'],cwd=radar,check=True,timeout=20)
def status():
 s=request('/api/state');a=[x for x in s['accounts'] if x['id'] in ('GUKA','MTT')]
 return '  |  '.join(x['id']+'：'+('已暂停' if x['paused'] else '运行中')+' · 今日接受 '+str(x.get('stats',{}).get('accepted_today',0)) for x in a)
def snapshot():
 state=request('/api/state')
 radar=request('/api/radar')
 leads=request('/api/leads?limit=50').get('items',[])
 return {'accounts':[{k:a.get(k) for k in ('id','paused','activity','error','stats')} for a in state['accounts'] if a['id'] in ('GUKA','MTT')],
         'discovery':radar.get('discovery',{}),'automatic':radar.get('automatic',{}),
         'customers':len(radar.get('contacts',[])),
         'leads':[{k:p.get(k) for k in ('id','company','account','status','error','updated_at')} for p in sorted(leads,key=lambda x:x.get('updated_at',0),reverse=True)[:8]]}
if __name__=='__main__':
 try:
  action=sys.argv[1]
  if action=='boot':boot()
  elif action not in ('status','snapshot'):control(action)
  print(json.dumps({'ok':True,'data':snapshot()},ensure_ascii=False))
 except Exception as e:
  print(json.dumps({'ok':False,'error':'操作未完成：'+str(e)[:250]},ensure_ascii=False));sys.exit(1)

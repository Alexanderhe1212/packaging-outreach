"""Optional official EasySpider executor; fixed read-only task, existing attribution rules."""
import json,os,signal,subprocess,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
BASE=Path.home()/'Library/Application Support/UserRadar/integrations/EasySpider'
CONFIG=BASE/'integration.json'
def make_task(url,identifier):
 common=dict(history=1,tabIndex=0,useLoop=False,xpath='',iframe=False,wait=0,waitType=0,beforeJS='',beforeJSWaitTime=0,afterJS='',afterJSWaitTime=0,waitElement='',waitElementTime=10,waitElementIframeIndex=0)
 fields=[]
 for name,kind in [('html',3),('url',5),('title',6),('status',9)]:
  fields.append(dict(name=name,nodeType=0,contentType=kind,relative=False,relativeXPath='/html/body',iframe=False,default='',paraType='text',recordASField=1,beforeJS='',beforeJSWaitTime=0,JS="return String((performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0)" if name=='status' else '',JSWaitTime=0,afterJS='',afterJSWaitTime=0,downloadPic=0,splitLine=0))
 graph=[dict(option=0,title='root',sequence=[1,2],parameters=common),dict(option=1,title='Open public page',sequence=[],isInLoop=False,parameters=dict(common,url=url,links=url,maxWaitTime=20,scrollType=0,scrollCount=1,scrollWaitTime=1,cookies='',wait=2)),dict(option=3,title='Capture rendered contact evidence',sequence=[],isInLoop=False,parameters=dict(common,clear=1,newLine=1,params=fields))]
 return dict(id=identifier,name='User Radar public contact capture',version='0.6.5',url=url,links=url,containJudge=False,quitWaitTime=0,cloudflare=0,environment=0,outputFormat='json',saveName='radar',saveThreshold=1,recordLog=1,dataWriteMode=2,outputParameters=[dict(name=f['name'],type='text',recordASField=1) for f in fields],graph=graph)
def validate_capture(row,domain):
 actual=urlsplit(row.get('url',''));host=(actual.hostname or '').lower().removeprefix('www.')
 if actual.scheme not in ('http','https') or host!=domain:raise ValueError('EasySpider returned another domain; discarded')
 status=str(row.get('status','0'))
 if status!='200':
  e=ValueError('EasySpider HTTP '+status+'; capture unavailable');e.http_status=int(status) if status.isdigit() else 0;raise e
 body=row.get('html','');title=row.get('title','').lower()
 if not body or len(body.encode())>2000000:raise ValueError('EasySpider empty or oversized page')
 if any(s in title for s in ('just a moment','access denied','attention required')) or 'verify you are human' in body.lower()[:3000]:raise ValueError('EasySpider challenge page; not customer data')
 return body
def available():
 if os.environ.get('USER_RADAR_EASYSPIDER')=='0':return False
 try:return Path(json.loads(CONFIG.read_text())['executable']).is_file()
 except (OSError,ValueError,KeyError):return False
def fetch(url,domain):
 from app import public_url,host
 from rate_limits import check,observe
 from browser_transport import check_budget,budget_remaining,_stop_owned
 check(url);check_budget();public_url(url)
 if host(url)!=domain:raise ValueError('Only the requested company domain is allowed')
 cfg=json.loads(CONFIG.read_text());identifier=int(uuid.uuid4().hex[:10],16)
 taskdir=Path.home()/'Library/Application Support/EasySpider/execution_instances';taskdir.mkdir(parents=True,exist_ok=True)
 task=taskdir/(str(identifier)+'.json');task.write_text(json.dumps(make_task(url,identifier)))
 root=Path(cfg['cwd']);run=BASE/'runs'/str(identifier);run.mkdir(parents=True)
 env=dict(os.environ,PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_DEFAULT_TIMEOUT='2',EASYSPIDER_DATA_DIR=str(run),EASYSPIDER_APP_RESOURCES=cfg['resources'])
 deadline=time.monotonic()+budget_remaining(60)
 (run/'config.json').write_text(json.dumps({'absolute_user_data_folder':str(run/'unused-profile')}))
 log=open(run/'executor.log','w')
 proc=subprocess.Popen([cfg['executable'],'--ids','['+str(identifier)+']','--read_type','local','--config_folder',str(run)+os.sep,'--headless','1','--keyboard','0','--saved_file_name','radar'],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
 try:
  while proc.poll() is None:
   check_budget()
   if time.monotonic()>=deadline:raise ValueError('EasySpider timed out')
   time.sleep(.1)
  outputs=[run/'Data'/('Task_'+str(identifier))/'radar.json',root/'Data'/('Task_'+str(identifier))/'radar.json',Path.home()/'Library/Application Support/EasySpider/Data'/('Task_'+str(identifier))/'radar.json']
  output=next((f for f in outputs if f.exists()),None)
  if not output:raise ValueError('EasySpider produced no capture; see '+str(run/'executor.log'))
  if output.stat().st_size>2500000:raise ValueError('EasySpider output too large')
  records=json.loads(output.read_text())
  if not isinstance(records,list) or len(records)!=1:raise ValueError('EasySpider invalid capture count')
  try:body=validate_capture(records[0],domain)
  except ValueError as e:
   if getattr(e,'http_status',None)==429:raise observe(url,60,'EasySpider browser')
   raise
  (run/'capture.json').write_text(json.dumps(records[0],ensure_ascii=False));return body
 finally:
  _stop_owned(proc)
  log.close();task.unlink(missing_ok=True)

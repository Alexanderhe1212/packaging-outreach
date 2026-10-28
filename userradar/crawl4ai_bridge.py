"""Optional isolated Crawl4AI reader; original contact attribution stays in Radar."""
import json,os,subprocess,time
from pathlib import Path
from easyspider_bridge import validate_capture
BASE=Path.home()/'Library/Application Support/UserRadar/integrations/Crawl4AI'
PYTHON=BASE/'venv/bin/python'
def available():
 return os.environ.get('USER_RADAR_CRAWL4AI')!='0' and (BASE/'enabled').exists() and PYTHON.is_file()
def validate_result(data,domain):
 if not data.get('success'):raise ValueError('Crawl4AI read failed: '+str(data.get('error',''))[:250])
 try:return validate_capture(data,domain)
 except ValueError as error:
  error.args=(str(error).replace('EasySpider','Crawl4AI'),)
  raise
def fetch(url,domain):
 from app import public_url,host
 from rate_limits import check,observe,parse_retry_after
 from browser_transport import check_budget,budget_remaining,_stop_owned,LOCAL
 check(url);check_budget();public_url(url)
 if host(url)!=domain:raise ValueError('Only the requested company domain is allowed')
 timeout=budget_remaining(48);end=time.monotonic()+timeout
 p=subprocess.Popen([str(PYTHON),str(Path(__file__).with_name('crawl4ai_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
 first=True
 try:
  while True:
   check_budget();left=min(end-time.monotonic(),budget_remaining(48))
   if left<=0:raise ValueError('Crawl4AI timed out')
   try:
    out,err=p.communicate(json.dumps({'url':url,'timeout_ms':max(1,int(timeout*1000))}) if first else None,timeout=min(.1,left));break
   except subprocess.TimeoutExpired:first=False
  if p.returncode:raise ValueError('Crawl4AI: '+err[-250:])
  data=json.loads(out)
  if data.get('status')==429:
   LOCAL.blocked=True
   raise observe(url,parse_retry_after(data.get('retry_after')) or 60,'Crawl4AI')
  return validate_result(data,domain)
 finally:_stop_owned(p)

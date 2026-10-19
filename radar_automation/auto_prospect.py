"""One company at a time: discover, read official site, save, hand off."""
import fcntl,json,os,signal,threading,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
import ai_discovery,app,customer_store,prospect_filter
from name_email_lookup import qualify_report,host
from extension_api import safe_contact
from sequential_prospect import public_fallback
HOME=Path.home()/'Library/Application Support/UserRadar/automatic'
STOP=threading.Event()
def api(path,data=None):
 req=urllib.request.Request('http://127.0.0.1:18800'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
def write(name,value):
 HOME.mkdir(parents=True,exist_ok=True);p=HOME/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2));t.replace(p)
def state(**kw):write('status.json',dict(updated_at=time.time(),**kw))
def indexed_public(c,url):
 email=c.get('email','').strip()
 for source in c.get('sources',[]):
  if host(source.get('url',''))!=host(url) or email not in source.get('quote','') or not email:continue
  p=public_fallback({'emails':[{'email':email,'source':source['url']}]},{'website':url})
  if not p:continue
  p['email_status']='AI 网页检索的官网公共邮箱线索；待官网实时复核，未验证投递'
  p['qualification_mode']='official_company_email_pending_recheck'
  p['evidence_by_field']['email'][0].update(quote=source['quote'],retrieval='ai_web_search_pending_live_recheck')
  return p
 return None

def one():
 history=json.loads((HOME/'history.json').read_text()) if (HOME/'history.json').exists() else []
 excluded={host(p['website']) for p in customer_store.customers()}
 excluded.update(x['domain'] for x in history)
 existing=api('/api/leads?limit=1000').get('items',[])
 excluded.update(p['domain'] for p in existing if p.get('domain'))
 cursor_file=HOME/'search-cursor.json'
 cursor=json.loads(cursor_file.read_text()).get('attempt',0) if cursor_file.exists() else len(history)
 write('search-cursor.json',{'attempt':cursor+1})
 category=['tea coffee','cosmetics skincare','chocolate confectionery','candles home fragrance','gifts jewellery'][cursor%5]
 market=['UK','USA','Australia','Canada','Germany','France','Netherlands'][(cursor//5)%7]
 state(status='discovering',stage='AI 寻找下一家包装业务官网',processed=len(history))
 run=HOME/('run-'+str(time.time_ns()));run.mkdir(parents=True)
 found=ai_discovery.discover(dict(category=category,markets=market,site_preference='Find consumer-product brands in the specified category with readable official Contact pages. Exclude packaging/filling machinery, industrial equipment, packaging manufacturers, agencies unrelated to physical products, and exhibitors without relevant consumer products. Exhibition attendance alone is not purchasing intent.',excluded_domains=sorted(excluded)[-80:]),STOP,lambda **k:None,evidence_dir=run,company_only=True)
 candidates=[c for c in found.get('companies',[]) if host(c.get('website','')) not in excluded and not prospect_filter.reason(c.get('company',''),c.get('fit_reason',''))]
 if not candidates:raise ValueError('本轮未找到新的公司官网')
 c=candidates[0];url=app.public_url(c['website']);domain=host(url)
 if domain in excluded:raise ValueError('AI 返回已处理公司，等待下一轮')
 state(status='researching',stage='查询官网联系人和公共邮箱',website=url,company=c.get('company',''),processed=len(history))
 target=c.get('contact_source','')
 if host(target)!=domain:target=url
 start=time.time();report=qualify_report(app.research(target,max_seconds=45,name_email_only=True,cancel=STOP))
 if STOP.is_set():return
 people=[safe_contact(p,url,report,name_email_only=True) for p in report.get('qualified_people',[])]
 people=[p for p in people if p]
 # Keep the minimum useful lead. The official-site crawler owns all evidence.
 p=people[0] if people else public_fallback(report,{'website':url})
 if not p:p=indexed_public(c,url)
 saved=[]
 if p:
  p.update(company=c.get('company') or domain,fit_reason=c.get('fit_reason',''),fit_source=c.get('fit_source',''),batch_id='automatic-sequential')
  p.setdefault('contact_kind','person');saved=[customer_store.save(p)['customer']['id']]
 result=dict(domain=domain,company=c.get('company'),website=url,started_at=start,finished_at=time.time(),saved_ids=saved,status='saved' if saved else 'no_public_email',errors=report.get('errors',[]))
 (run/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));history.append(result);write('history.json',history)
 state(status='saved' if saved else 'skipped',stage='已保存，等待账号领取' if saved else '未查到可验证的官网邮箱，保留网站记录',**{k:v for k,v in result.items() if k!='status'})
 print(json.dumps(result,ensure_ascii=False),flush=True)
 return result

def main():
 HOME.mkdir(parents=True,exist_ok=True)
 with (HOME/'worker.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())
  import recheck_queue
  rechecks=threading.Thread(target=recheck_queue.run,args=(STOP,api),daemon=True,name='saved-recheck-handoff');rechecks.start()
  while not STOP.is_set():
   try:
    config=api('/api/radar')['automatic'];accounts=api('/api/state')['accounts']
    enabled=config.get('accounts') or [config.get('account')]
    active=[a for a in accounts if a['id'] in enabled and not a['paused']]
    if not config.get('enabled') or not active:
     state(status='waiting',stage='开发已暂停，暂停查找新公司');STOP.wait(30);continue
    from exhibition_handoff import waiting_for_exhibition
    if waiting_for_exhibition():
     state(status='waiting',stage='先完成展会名单查询与交接，完成后自动启动 AI 搜索')
     STOP.wait(30);continue
    pending=sum(a.get('stats',{}).get('actionable_pending',sum(a.get('stats',{}).get(k,0) for k in ('queued','researching','writing','imaging','ready'))) for a in active)
    if pending>=10:
     state(status='waiting',stage='开发队列已有十家，等待处理后继续查找');STOP.wait(30);continue
    one()
    STOP.wait(5)  # Different company next; per-site limits remain in the crawler.
   except Exception as e:
    state(status='error',stage='本轮未完成，将稍后重试',error=str(e)[:250]);print(type(e).__name__+': '+str(e)[:250],flush=True)
    STOP.wait(30)
 state(status='stopped',stage='已停止')
if __name__=='__main__':main()

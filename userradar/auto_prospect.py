"""One company at a time: discover, read official site, save, hand off."""
import fcntl,json,os,re,signal,threading,time,urllib.request
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
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=15) as r:return json.load(r)
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

def contact_priority(person):
 title=person.get('title','').lower()
 quotes=[e.get('quote','') for e in person.get('evidence_by_field',{}).get('identity',[]) if person.get('name') and person.get('email') and person['name'].lower() in e.get('quote','').lower() and person['email'].lower() in e.get('quote','').lower()]
 text=title+' '+ ' '.join(quotes).lower()
 if re.search(r'\b(procurement|purchasing|buyer|sourcing|aankoop|inkoop|einkauf|achats)\b|采购',text):return 0
 if re.search(r'\b(packaging|operations|supply chain)\b',title):return 1
 if re.search(r'\b(founder|owner|director|ceo)\b',title):return 2
 return 3

def recover_active_candidate():
 """A crash after selection must leave an explicit review receipt, never lose the lead."""
 path=HOME/'active-candidate.json'
 if not path.exists():return
 row=json.loads(path.read_text());domain=host(row.get('website',''))
 history=json.loads((HOME/'history.json').read_text()) if (HOME/'history.json').exists() else []
 if domain and not any(x.get('domain')==domain and x.get('finished_at',0)>=row.get('selected_at',0) for x in history):
  history.append(dict(domain=domain,website=row['website'],company=row.get('company',''),status='pending_review',reason_code='EVIDENCE_MISMATCH',last_error='Interrupted candidate; inspect saved results before restarting',recheck_after=time.time()+30*86400,finished_at=time.time(),saved_ids=[]))
  write('history.json',history)
 path.unlink()

def one():
 from pipeline_core import features
 if features.enabled('candidate_pool'):recover_active_candidate()
 history=json.loads((HOME/'history.json').read_text()) if (HOME/'history.json').exists() else []
 excluded={host(p['website']) for p in customer_store.customers()}
 from pipeline_core import features,retry_policy
 excluded.update(x['domain'] for x in history if not features.enabled('unified_retry') or retry_policy.excluded(x))
 existing=api('/api/leads?limit=1000').get('items',[])
 excluded.update(p['domain'] for p in existing if p.get('domain'))
 cursor_file=HOME/'search-cursor.json'
 cursor=json.loads(cursor_file.read_text()).get('attempt',0) if cursor_file.exists() else len(history)
 write('search-cursor.json',{'attempt':cursor+1})
 from recruitment_strategy import packaging_brief as search_brief,PACKAGING_FOCUSES
 brief=search_brief(cursor,sorted(excluded))
 if features.enabled('candidate_pool'):
  try:
   from pipeline_core.scoring import keyword_metrics
   import random
   metrics=keyword_metrics(history,existing);write('keyword-metrics.json',metrics)
   choices=[search_brief(i,sorted(excluded)) for i in range(len(PACKAGING_FOCUSES))]
   brief=random.choices(choices,weights=[metrics.get(x['search_focus'],{}).get('weight',1) for x in choices],k=1)[0]
  except Exception:pass

 state(status='discovering',stage='AI 寻找下一家包装业务官网',processed=len(history))
 run=HOME/('run-'+str(time.time_ns()));run.mkdir(parents=True)
 pool=[]
 if features.enabled('candidate_pool'):
  try:pool=json.loads((HOME/'candidate-pool.json').read_text())
  except (OSError,ValueError):pool=[]
  pool=[c for c in pool if host(c.get('website','')) not in excluded]
 if pool:
  found={'companies':pool,'notes':'saved candidate pool'}
 else:
  if features.enabled('candidate_pool'):
   brief=dict(brief);brief['search_focus']=str(brief.get('search_focus',''))+' Return 10–20 distinct eligible companies, each with public source evidence.'
  found=ai_discovery.discover(brief,STOP,lambda **k:None,evidence_dir=run,company_only=True)
 seen=set();candidates=[]
 for c in found.get('companies',[]):
  domain=host(c.get('website',''))
  if not domain or domain in seen or domain in excluded or prospect_filter.reason(c.get('company',''),c.get('fit_reason','')):continue
  c.setdefault('search_keyword',brief['search_focus'])
  seen.add(domain);candidates.append(c)
 if features.enabled('candidate_pool'):
  # Sequential verification is a concurrency bound of one; each result is saved immediately.
  try:
   from pipeline_core.scoring import score
   for candidate in candidates:candidate['priority_score']=score(candidate)
   candidates.sort(key=lambda c:c['priority_score']['total'],reverse=True)
   if candidates:write('active-candidate.json',dict(candidates[0],selected_at=time.time()))
   write('candidate-pool.json',candidates[1:20])
  except Exception:pass  # Existing single-candidate path remains available.

 if not candidates:
  result=dict(status='no_match',stage='本轮暂无合格业务信号，下一轮更换搜索方向',processed=len(history),notes=found.get('notes',''),search_focus=brief['search_focus'])
  write('last-search.json',dict(updated_at=time.time(),**result))
  state(**result)
  STOP.wait(25)
  return result
 c=candidates[0];url=app.public_url(c['website']);domain=host(url)
 from recruitment_strategy import verify
 from public_sources import SourceReader
 signal=verify(c,SourceReader(folder=run,cancel=STOP).read,mode=brief.get("prospecting_mode","recruitment"))
 (run/'recruitment.json').write_text(json.dumps(signal,ensure_ascii=False,indent=2))
 if not signal['eligible']:
  result=dict(domain=domain,company=c.get('company'),website=url,finished_at=time.time(),saved_ids=[],status='recruitment_pending',recruitment=signal)
  if features.enabled('unified_retry'):result.update(reason_code='EVIDENCE_MISMATCH',recheck_after=time.time()+30*86400)
  result['search_keyword']=c.get('search_keyword',brief['search_focus'])
  history.append(result);write('history.json',history)
  state(status='skipped',stage='业务信号证据待核实，保留记录并继续下一家',**{k:v for k,v in result.items() if k!='status'})
  return result
 c['fit_reason']='Public business signal, not confirmed purchasing: '+signal['evidence']['job_title']+'; '+signal['evidence']['job_posted_date']+'; '+signal['evidence']['job_quote']

 if domain in excluded:raise ValueError('AI 返回已处理公司，等待下一轮')
 state(status='researching',stage='查询官网联系人和公共邮箱',website=url,company=c.get('company',''),processed=len(history))
 target=c.get('contact_source','')
 if host(target)!=domain:target=url
 start=time.time();report=qualify_report(app.research(target,max_seconds=45,name_email_only=True,email_only=True,cancel=STOP))
 if STOP.is_set():return
 people=[safe_contact(p,url,report,name_email_only=True) for p in report.get('qualified_people',[])]
 people=sorted((p for p in people if p),key=contact_priority)
 # Keep the minimum useful lead. The official-site crawler owns all evidence.
 p=people[0] if people else public_fallback(report,{'website':url})
 if not p:p=indexed_public(c,url)
 if p and (p.get('email','').partition('@')[0].lower() in {'careers','career','jobs','recruitment','recruiting','hr','noreply','no-reply'} or re.search(r'\b(human resources|recruiter|talent acquisition)\b',p.get('title',''),re.I)):
  p=None
 saved=[]
 if p:
  p.update(company=c.get('company') or domain,fit_reason=c.get('fit_reason',''),fit_source=c.get('fit_source',''),batch_id='automatic-sequential')
  p.setdefault('evidence_by_field',{})['recruitment']=[signal]
  p.setdefault('contact_kind','person')
  if features.enabled('candidate_pool'):
   from pipeline_core.scoring import score
   p['priority_score']=score(dict(p,fit_status='passed',contact_identity='named_buyer' if p.get('procurement_authority_confirmed') is True else 'named_other' if p.get('name') and p['contact_kind']=='person' else 'generic_company',identity_source=next(iter(p.get('sources',[])),'')))
  saved=[customer_store.save(p,upgrade=True)['customer']['id']]
  if p.get('contact_kind')=='company_public':
   import buyer_track
   buyer_track.schedule(HOME/'buyer-track.json',url,report,c.get('company') or domain)
 result=dict(domain=domain,company=c.get('company'),website=url,started_at=start,finished_at=time.time(),saved_ids=saved,status='saved' if saved else 'no_public_email',recruitment=signal,errors=report.get('errors',[]))
 if not saved and features.enabled('unified_retry'):result.update(reason_code='NO_PUBLIC_EMAIL',recheck_after=time.time()+30*86400)
 result['search_keyword']=c.get('search_keyword',brief['search_focus'])
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
    import buyer_track
    buyer_track.poll(HOME/'buyer-track.json')
    one()
    STOP.wait(5)  # Different company next; per-site limits remain in the crawler.
   except Exception as e:
    state(status='error',stage='本轮未完成，将稍后重试',error=str(e)[:250]);print(type(e).__name__+': '+str(e)[:250],flush=True)
    STOP.wait(30)
 state(status='stopped',stage='已停止')
if __name__=='__main__':main()

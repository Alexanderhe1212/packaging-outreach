"""Durable, sequential research completion; sending remains in OutreachPilot."""
import json
import os
import time
import urllib.error
from pathlib import Path

DEFAULT_QUEUE = Path.home()/'Library/Application Support/UserRadar/maintenance/2026-10-18/overnight/email-rechecks.json'
TERMINAL = {'completed_no_email','completed_handoff','completed_protected','completed_review_required','completed_error'}

def write(path, data):
    path=Path(path);tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)

def finish(item, snapshot, path, save_report, handoff):
    report=snapshot.get('report') or {}
    result=path.parent/('recheck-'+str(item['id'])+'.json')
    write(result,snapshot);item['result_file']=str(result)
    receipt=save_report(item,report,path.parent/'handoff')
    item['save_receipt']=receipt
    item['saved_contact_ids']=receipt.get('contact_ids',[])
    item['emails_found']=receipt.get('emails',[])
    item['retrieval_errors']=report.get('errors',[])
    if not item['saved_contact_ids']:
        item['status']='completed_review_required' if receipt.get('status')=='excluded_business' else ('completed_no_email' if snapshot.get('status')=='done' else 'completed_error')
        return
    item['status']='saved_waiting'
    item['next_check_at']=0

from pipeline_events import measured as pipeline_measured

@pipeline_measured('handoff')
def _legacy_transfer(item,handoff):
    result=handoff(item['id'],item['saved_contact_ids'][0])
    item['handoff']=result
    state=result.get('status')
    item['status']=({'queued':'completed_handoff','protected':'completed_protected','review_required':'completed_review_required'}.get(state,'saved_waiting'))
    item['next_check_at']=time.time()+60

def transfer(item,handoff):
    from pipeline_core import features,retry_policy
    if not features.enabled('unified_retry'):return _legacy_transfer(item,handoff)
    # Handoff POST may have succeeded even when its response was lost.
    try:result=handoff(item['id'],item['saved_contact_ids'][0])
    except Exception as exc:
        item.update(retry_policy.decide('POST_UNKNOWN',item.get('retry_count',0)))
        item.update(status='completed_review_required',note=str(exc)[:300]);return
    item['handoff']=result
    state=result.get('status')
    item['status']={'queued':'completed_handoff','protected':'completed_protected','review_required':'completed_review_required'}.get(state,'saved_waiting')
    if item['status']=='saved_waiting':
        policy=retry_policy.decide('NETWORK',item.get('retry_count',0),deferred=True,
                                  deadline=time.time()+60)
        item.update(policy);item['next_check_at']=policy['next_retry_at']


def step(path, fetch, save_report, handoff):
    """One source job at a time; a deferred handoff never blocks the next site."""
    path=Path(path)
    if not path.exists():return {'status':'no_queue'}
    data=json.loads(path.read_text());items=data['items'];now=time.time()
    for item in items:
        if item.get('status')=='starting':
            item['status']='completed_review_required'
            item['note']='Interrupted research start; inspect source jobs before retry.';item['reason_code']='POST_UNKNOWN'
            write(path,data)
            return {'status':'review_required','id':item['id']}
    # Finished results have priority. Never restart a job just because a poll failed.
    for item in items:
        if item.get('status')=='researching':
            if item.get('next_retry_at',0)>now:continue
            try:snapshot=fetch('/api/research-job/'+item['job']['id'])
            except urllib.error.HTTPError as exc:
                if exc.code!=404:
                    from pipeline_core import features,retry_policy
                    if not features.enabled('unified_retry'):raise
                    item.update(retry_policy.decide(exc,item.get('retry_count',0)))
                    if item['action']!='retry':item['status']='completed_review_required'
                    write(path,data);continue
                item['status']='completed_review_required';item['note']='Source job expired; no duplicate query started.';item['reason_code']='JOB_EXPIRED'
                write(path,data);return {'status':'expired_job','id':item['id']}
            except (TimeoutError,ConnectionError,urllib.error.URLError) as exc:
                from pipeline_core import features,retry_policy
                if not features.enabled('unified_retry'):raise
                item.update(retry_policy.decide(exc,item.get('retry_count',0)))
                if item['action']!='retry':item['status']='completed_review_required'
                write(path,data);continue
            if snapshot.get('status') not in ('done','error','cancelled'):return {'status':'researching','id':item['id']}
            finish(item,snapshot,path,save_report,handoff);write(path,data)
            if item['status']=='saved_waiting':
                transfer(item,handoff);write(path,data)
            return {'status':item['status'],'id':item['id']}
    for item in items:
        if item.get('status')=='completed_review_pending':
            snapshot=json.loads(Path(item['result_file']).read_text())
            finish(item,snapshot,path,save_report,handoff);write(path,data)
            if item['status']=='saved_waiting':
                transfer(item,handoff);write(path,data)
            return {'status':item['status'],'id':item['id']}
    for item in items:
        if item.get('status')=='saved_waiting' and item.get('next_check_at',0)<=now:
            transfer(item,handoff);write(path,data)
            if item['status']!='saved_waiting':return {'status':item['status'],'id':item['id']}
    for item in items:
        if item.get('status')=='pending':
            # Persist intent first: an ambiguous interrupted POST needs review,
            # not a blind repeat that could duplicate an already-running query.
            item['status']='starting';write(path,data)
            try:item['job']=fetch('/api/research-start',{'url':item['website'],'refresh':True})
            except Exception:
                item['status']='completed_review_required';item['note']='Research start outcome uncertain; inspect source jobs before retry.'
                write(path,data);raise
            item['status']='researching';write(path,data)
            return {'status':'researching','id':item['id']}
    return {'status':'waiting' if any(x.get('status')=='saved_waiting' for x in items) else 'completed'}

def save_report(item,report,receipts):
    from name_email_lookup import qualify_report
    from prospect_filter import reason
    text=' '.join(str(e.get('text','')) for e in report.get('business_evidence',[]) if isinstance(e,dict))
    excluded=reason(item.get('company',''),text)
    if excluded:return {'contact_ids':[],'emails':[],'saved':0,'status':'excluded_business','reason':excluded}
    from exhibition_handoff import save_completed
    qualified=qualify_report(report)
    return save_completed({'record_id':'RECHECK-'+str(item['id']),'company':item['company'],
                          'website':item['website'],'results':[{'report':qualified}]},receipts)

def run(stop,api):
    """Runs inside the existing singleton automatic worker; honors user pauses."""
    import urllib.request
    path=Path(os.environ.get('USER_RADAR_RECHECK_QUEUE',str(DEFAULT_QUEUE)))
    def fetch(route,data=None):
        req=urllib.request.Request('http://127.0.0.1:18830'+route,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Origin':'http://127.0.0.1:18830','Content-Type':'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=15) as r:return json.load(r)
    def handoff(lid,cid):return api('/api/radar/recheck-handoff',{'lead_id':lid,'contact_id':cid})
    while not stop.is_set():
        delay=5
        try:
            setting=api('/api/radar')['automatic'];accounts=api('/api/state')['accounts']
            enabled=setting.get('accounts') or [setting.get('account')]
            if setting.get('enabled') and any(a['id'] in enabled and not a['paused'] for a in accounts):
                result=step(path,fetch,save_report,handoff)
                if result['status'] in ('completed','no_queue'):delay=30
            else:delay=30
        except urllib.error.HTTPError as exc:
            try:delay=max(30,min(float(exc.headers.get('Retry-After','60')),86400))
            except (ValueError,TypeError):delay=60
            print('Recheck HTTP wait: '+str(exc.code),flush=True)
        except Exception as exc:
            print('Recheck needs attention: '+type(exc).__name__+': '+str(exc)[:200],flush=True);delay=60
        stop.wait(delay)

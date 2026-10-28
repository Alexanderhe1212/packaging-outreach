"""User Radar source adapter. Import is held; release is an explicit action.

Only server-owned saved records are accepted. Existing ownership/suppression and
the normal official-site/product/image/send pipeline remain authoritative.
"""
import json
import random
import re
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from . import config,store,web,prospect_filter
from .person_identity import plausible_person_name, explicit_short_name, press_mailbox

LOCK=threading.RLock()

def contacts():
    pairing=Path.home()/'Library/Application Support/UserRadar/extension-pairing.json'
    conf=json.loads(pairing.read_text())
    request=urllib.request.Request('http://127.0.0.1:18830/api/extension/customers',headers={
        'Authorization':'Bearer '+conf['token'],'X-User-Radar-Extension':conf.get('extensionId','penhejnbohdbokelgmhheknekikldcjh')})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=10) as response:
        rows=json.load(response)['customers']
    eligible=[]
    for p in rows:
        u=urlsplit(p.get('website',''));email=p.get('email','').strip()
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:continue
        if not re.fullmatch(r'[^\s@;]+@[^\s@;]+\.[^\s@;]+',email):continue
        if press_mailbox(email):continue
        # Original official evidence must exist; search-index-only observations
        # may be staged, but are re-read by the normal pipeline before sending.
        sources=[s for s in p.get('sources',[]) if web.root_domain(web.host(s))==web.root_domain(u.hostname)]
        if not sources or not p.get('id'):continue
        if not (p.get('name') and p.get('qualified') or p.get('contact_kind')=='company_public'):continue
        valid_name=plausible_person_name(p.get('name','')) or any(
            explicit_short_name(p.get('name',''),email,e.get('quote',''))
            for e in (p.get('evidence_by_field') or {}).get('email',[]))
        if p.get('name') and not valid_name:
            p=dict(p,name='',qualified=False,contact_kind='company_public')
        if prospect_filter.reason(p.get('company',''),p.get('fit_reason','')):continue
        from pipeline_core.identity import email_quality
        p['email_quality']=email_quality(email)
        if p['email_quality']['role']=='excluded':continue
        eligible.append(p)
    return eligible

def discovery_status():
    try:return json.loads((Path.home()/'Library/Application Support/UserRadar/automatic/status.json').read_text())
    except (OSError,ValueError):return {}

def overview(_query=None):
    rows=contacts()
    imported=store.q("SELECT id,account,status,domain,email FROM leads WHERE source='user_radar' ORDER BY id DESC")
    return dict(contacts=rows,imported=imported,accounts=[dict(id=a['id'],name=a.get('name',a['id'])) for a in config.load()['accounts']],
                automatic=store.get('radar_source',{}),discovery=discovery_status())

def research_url(contact):
    website = contact['website']
    target = contact.get('fit_source') or ''
    parts = urlsplit(target)
    # Fit evidence may be a contact page or catalogue, not a selected SKU.
    # Keep it in the contact evidence; let the normal homepage product verifier
    # select a real product instead of demanding Product JSON-LD on that page.
    informational = bool(re.search(
        r'(?i)/(?:contact(?:us|s|-us|-en-informatie)?|collections|shop|products)/?$'
        r'|/(?:(?:en|fr|de|nl)/)?page/(?:our-[^/]+|contacts?)/?$', parts.path))
    informational = informational or bool(re.search(r'(?i)/(?:collections/[^/]+|product-category(?:/[^/]+)*|pages/(?:order-a-sample|request-a-sample))/?$', parts.path))
    if (parts.scheme in ('http','https') and not parts.username and not parts.password
            and web.root_domain(web.host(target)) == web.root_domain(web.host(website))
            and parts.path.strip('/') and not informational and not web.NON_PRODUCT_PATH.search(target)):
        return target
    return website

def upgrade_contact(lead,p):
    """Upgrade only an unsent generic lead; invalidate its old greeting and image draft."""
    if not p.get('name') or not p.get('qualified') or p.get('contact_kind')=='company_public':return False
    with store._lock:
        current=store.lead(lead['id'])
        if current['status']=='sent' and p['email'].lower()!=current['email'].lower():
            store.put('second_contact_candidate:'+str(current['id']),dict(parent_id=current['id'],account=current['account'],contact=dict(p)))
        if current['status'] not in ('queued','radar_review','ready') or current.get('sent_at') or current.get('message_id') or current.get('tries'):return False
        old=(current['data'].get('manual') or {}).get('radar') or {}
        if old.get('name') and old.get('contact_kind')!='company_public':return False
        probe=dict(current,email=p['email'])
        if store._conflict(store.db(),probe,preparation=True):return False
        data=dict(current['data']);data['manual']=dict(url=research_url(p),email=p['email'],radar=dict(p))
        for key in ('prospect','image_plan','image_qc'):data.pop(key,None)
        from pipeline_core.identity import register
        register(store.db(),current['domain'],str(current['id']),current['account'])
        register(store.db(),current['domain'],'radar:'+p['id'],current['account'])
        store.update(current['id'],email=p['email'],data=data,status='radar_review' if current['status']=='radar_review' else 'queued',subject='',body='',image='',error='')
        for key in store.identity_keys(p['email'],current['domain'],current['company']):
            store.x('INSERT OR IGNORE INTO identity_claims VALUES(?,?)',(key,current['id']))
        store.event(current['id'],'contact_upgrade','completed','VERIFIED_NAME_UPGRADE',current['account'])
        return True


def import_contacts(data, held=True):
    account=data['account'];config.account(account)
    ids=data.get('contact_ids',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(i,str) for i in ids):raise ValueError('请选择 1–100 条已保存客户')
    with LOCK:
        known={p['id']:p for p in contacts()};added=[];skipped=[];seen=set()
        selected=[known[i] for i in ids if i in known]
        if len(selected)!=len(set(ids)):raise ValueError('包含不存在或不合格的客户编号')
        selected.sort(key=lambda p:not bool(p.get('name')))
        for p in selected:
            domain=web.host(p['website'])
            if domain in seen:skipped.append(dict(domain=domain,reason='同公司优先选择一位联系人'));continue
            seen.add(domain)
            prior=store.q("SELECT id FROM leads WHERE source='user_radar' AND domain=?",(domain,),one=True)
            if prior:
                upgrade_contact(store.lead(prior['id']),p)
                skipped.append(dict(domain=domain,reason='已经导入过；仅允许原账号未发首封前升级'));continue
            manual=dict(url=research_url(p),email=p['email'],radar=dict(p))
            lid=store.claim_prospect(account,dict(company=p.get('company') or domain,domain=domain,email=p['email']),
                                     source='user_radar',manual=manual,hold=held)
            if lid:
                store.event(lid,'handoff','completed','SAVED_CONTACT_IMPORTED',account)
                added.append(lid);store.audit('radar_imported',account,lid,origin=data.get('_origin'),result='held' if held else 'queued')
            else:skipped.append(dict(domain=domain,reason='既有客户或跨账号保护阻止'))
        return dict(ids=added,skipped=skipped,held=held)

def release(data):
    account=data['account'];config.account(account)
    ids=data.get('ids',[])
    if not isinstance(ids,list) or not ids or len(ids)>100:raise ValueError('请选择待开发客户')
    with LOCK,store._lock:
        rows=[store.lead(int(i)) for i in ids]
        if any(not r or r['source']!='user_radar' or r['account']!=account or r['status']!='radar_review' for r in rows):
            raise ValueError('客户状态或账号不匹配，请刷新')
        released=[];skipped=[]
        for row in rows:
            reason=store._conflict(store.db(),row,preparation=True)
            if reason:skipped.append(dict(id=row['id'],reason=reason));continue
            store.update(row['id'],status='queued');released.append(row['id'])
            store.audit('radar_released',account,row['id'],origin=data.get('_origin'),result='queued')
        return dict(ids=released,skipped=skipped)

def configure(data):
    account=data['account'];config.account(account)
    enabled=data.get('enabled')
    if not isinstance(enabled,bool):raise ValueError('enabled 必须为布尔值')
    with LOCK:
        previous=store.get('radar_source',{})
        mode=data.get('mode',previous.get('mode','single'))
        accounts=data.get('accounts',previous.get('accounts',[account])) if mode=='shared_random' else [account]
        if mode not in ('single','shared_random') or not isinstance(accounts,list) or not accounts:raise ValueError('客户分配模式无效')
        for aid in accounts:config.account(aid)
        store.put('radar_source',dict(account=account,accounts=list(dict.fromkeys(accounts)),mode=mode,enabled=enabled))
    return store.get('radar_source')

def pull_one(account):
    setting=store.get('radar_source',{})
    accounts=setting.get('accounts') or [setting.get('account')]
    if not setting.get('enabled') or account not in accounts:return None
    with LOCK:
        rows=contacts();rows.sort(key=lambda p:not bool(p.get('name')))
        imported_roots={web.root_domain(web.host(r['domain'])) for r in
                        store.q("SELECT domain FROM leads WHERE source='user_radar'") if r.get('domain')}
        for p in rows:
            domain=web.host(p['website'])
            # Research may redirect the stored domain to a subdomain. Keep
            # failed imports in the existing retry path, not as fresh leads.
            if web.root_domain(domain) in imported_roots:
                prior=store.q("SELECT id FROM leads WHERE source='user_radar' AND domain=?",(domain,),one=True)
                if prior:upgrade_contact(store.lead(prior['id']),p)
                continue
            key='radar_assignment:'+domain
            assigned=store.get(key)
            if not assigned:
                available=[a for a in accounts if not store.get('paused_'+a,True)]
                if not available:return None
                assigned=random.choice(available) if setting.get('mode')=='shared_random' else accounts[0]
                from pipeline_core import features
                if features.enabled('account_routing'):
                    mapping=features.option('account_routing_categories',{})
                    category=p.get('verified_packaging_category','')
                    if category and mapping.get(category) in available:assigned=mapping[category]
                store.put(key,assigned)
            if assigned!=account:continue
            result=import_contacts(dict(account=account,contact_ids=[p['id']]),held=False)
            if result['ids']:return store.lead(result['ids'][0])
    return None


def recheck_handoff(data):
    """Requeue only a failed, never-sent original from an existing saved contact."""
    # Fetch the local Radar response before taking the database lock.
    contact=next((p for p in contacts() if p['id']==data['contact_id']),None)
    with LOCK, store._lock:
        lead = store.lead(int(data['lead_id']))
        if not lead:raise ValueError('原客户记录不存在')
        if lead['status'] in ('sent','sending','unknown','bounced','unsubscribed','replied') or lead.get('sent_at') or lead.get('message_id') or store.hard_blocked(lead.get('email',''),lead['account']):
            return {'status':'protected','lead_id':lead['id']}
        if store.q("SELECT id FROM send_attempts WHERE lead=? AND result IN ('sent','sending','unknown','bounced')",(lead['id'],),one=True):
            return {'status':'protected','lead_id':lead['id']}
        if lead['status'] in ('queued','researching','writing','imaging','ready'):
            return {'status':'already_active','lead_id':lead['id']}
        if lead['status']!='failed':return {'status':'review_required','lead_id':lead['id']}
        if not contact: return {'status':'review_required','reason':'saved_contact_not_eligible','lead_id':lead['id']}
        if web.root_domain(web.host(contact['website']))!=web.root_domain(lead['domain']):
            raise ValueError('补查联系人不属于原官网')
        if store.hard_blocked(contact['email'],lead['account']):return {'status':'protected','lead_id':lead['id']}
        d=lead['data']
        d.setdefault('retry_history',[]).append({'at':__import__('time').time(),'action':'saved_recheck_handoff','contact_id':contact['id'],'error':lead.get('error','')})
        d['manual']={'url':contact['website'],'email':contact['email'],'radar':dict(contact),'introduction_mode':True}
        for key in ('prospect','plan','image_prompt'):d.pop(key,None)
        # Keep retry deadlines and the original account. Existing claims and all
        # send gates are checked again by the normal worker before any SMTP call.
        store.update(lead['id'],status='queued',data=d,error='',image='')
        store.audit('recheck_handoff',lead['account'],lead['id'],data.get('_origin'),'queued')
        return {'status':'queued','lead_id':lead['id'],'account':lead['account']}


def queue_second_contact(account):
    from pipeline_core import features
    if not features.enabled('second_contact'):return None
    with LOCK,store._lock:
        for record in store.q("SELECT key,value FROM kv WHERE key LIKE 'second_contact_candidate:%'"):
            entry=json.loads(record['value'])
            if entry['account']!=account or entry.get('consumed'):continue
            parent=store.lead(entry['parent_id']);p=entry['contact']
            if not parent:continue
            data=dict(manual=dict(url=research_url(p),email=p['email'],radar=p),second_contact_parent_id=parent['id'])
            probe=dict(id=-1,account=account,email=p['email'],company=parent['company'],domain=parent['domain'],data=data)
            if not store._second_contact_exception(store.db(),probe,parent) or store._conflict(store.db(),probe,preparation=True):continue
            lid=store.add_lead(account,'queued',source='second_contact',company=parent['company'],domain=parent['domain'],email=p['email'],data=data)
            from pipeline_core.identity import register
            register(store.db(),parent['domain'],lid,account)
            entry['consumed']=lid;store.put(record['key'],entry)
            store.event(lid,'handoff','completed','SECOND_CONTACT_SAME_ACCOUNT',account)
            return store.lead(lid)
    return None

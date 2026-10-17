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
from . import config,store,web

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
        # Original official evidence must exist; search-index-only observations
        # may be staged, but are re-read by the normal pipeline before sending.
        sources=[s for s in p.get('sources',[]) if web.root_domain(web.host(s))==web.root_domain(u.hostname)]
        if not sources or not p.get('id'):continue
        if not (p.get('name') and p.get('qualified') or p.get('contact_kind')=='company_public'):continue
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
    if (parts.scheme in ('http','https') and not parts.username and not parts.password
            and web.root_domain(web.host(target)) == web.root_domain(web.host(website))
            and parts.path.strip('/') and not web.NON_PRODUCT_PATH.search(target)):
        return target
    return website

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
            if store.q("SELECT id FROM leads WHERE source='user_radar' AND domain=?",(domain,),one=True):
                skipped.append(dict(domain=domain,reason='已经导入过'));continue
            manual=dict(url=research_url(p),email=p['email'],radar=dict(p))
            lid=store.claim_prospect(account,dict(company=p.get('company') or domain,domain=domain,email=p['email']),
                                     source='user_radar',manual=manual,hold=held)
            if lid:
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
        for p in rows:
            domain=web.host(p['website'])
            if store.q("SELECT id FROM leads WHERE source='user_radar' AND domain=?",(domain,),one=True):continue
            key='radar_assignment:'+domain
            assigned=store.get(key)
            if not assigned:
                available=[a for a in accounts if not store.get('paused_'+a,True)]
                if not available:return None
                assigned=random.choice(available) if setting.get('mode')=='shared_random' else accounts[0]
                store.put(key,assigned)
            if assigned!=account:continue
            result=import_contacts(dict(account=account,contact_ids=[p['id']]),held=False)
            if result['ids']:return store.lead(result['ids'][0])
    return None

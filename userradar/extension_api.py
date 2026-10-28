"""Authenticated local bridge for the paired Chrome extension only."""
import base64
import copy
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock()
JOBS={}

def configuration_path():
    return Path(os.environ.get('USER_RADAR_EXTENSION_CONFIG',str(Path.home()/'Library/Application Support/UserRadar/extension-pairing.json')))

def extension_id():
    override=os.environ.get('USER_RADAR_EXTENSION_ID','')
    if override:
        if not re.fullmatch('[a-p]{32}',override):raise ValueError('Invalid extension identity')
        return override
    manifest=json.loads((ROOT/'chrome-extension/manifest.json').read_text())
    digest=hashlib.sha256(base64.b64decode(manifest['key'],validate=True)).hexdigest()[:32]
    return ''.join(chr(ord('a')+int(c,16)) for c in digest)

def get_configuration():
    with LOCK:
        path=configuration_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.exists():data=json.loads(path.read_text())
        else:
            data={'token':secrets.token_urlsafe(48)}
            fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(data,stream)
        os.chmod(str(path),0o600)
        return {'apiBase':'http://127.0.0.1:18830','token':data['token'],'extensionId':extension_id()}

def normalized(value):return re.sub(r'[^\w]','',value or '').casefold()

def evidence_matches(rows, name, value=None, phone=False):
    for ev in rows or []:
        if not isinstance(ev,dict):continue
        p=urlsplit(ev.get('url',''))
        quote=ev.get('quote','')
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:continue
        if normalized(name) not in normalized(quote):continue
        if value is None:return True
        if phone:
            if re.sub(r'\D','',value) in re.sub(r'\D','',quote):return True
        elif value.casefold() in quote.casefold():return True
    return False

def safe_contact(person, website, report=None, *, name_email_only=False):
    from app import ROLE,is_role
    from batch_jobs import key_role_rank
    from enrichment import shared_mailbox
    from person_identity import plausible_person_name, explicit_short_name
    from contact_quality import phone_info
    if not isinstance(person,dict):return None
    p=copy.deepcopy(person)
    if report:
        from team_enrichment import remove_company_channels,company_channels
        p=remove_company_channels(p,company_channels(report))
    name=p.get('name','').strip();title=p.get('title','').strip();mail=p.get('email','').strip()
    fields=p.get('evidence_by_field',{})
    domain=(urlsplit(website).hostname or '').lower().removeprefix('www.')
    valid_name=plausible_person_name(name) or (name_email_only and any(explicit_short_name(name,mail,e.get('quote','')) for e in fields.get('email',[])))
    if (not p.get('qualified') or not valid_name
        or (not name_email_only and (not ROLE.search(title) or key_role_rank(p)>=9)) or not re.fullmatch(r'[^\s;@]+@[^\s;@]+\.[^\s;@]+',mail)
        or is_role(mail) or shared_mailbox(mail,domain,website)
        or not evidence_matches(fields.get('identity'),name)
        or not evidence_matches(fields.get('email'),name,mail)):
        return None
    # Identity role must itself be quoted, never just supplied by a candidate.
    if not name_email_only and not any(normalized(title) in normalized(ev.get('quote','')) for ev in fields.get('identity',[])):return None
    mobile=p.get('mobile','');info=phone_info(mobile)
    if (not mobile or info['mobile']!=mobile or p.get('phone_conflict') or p.get('phone_stale')
        or not evidence_matches(fields.get('phone'),name,mobile,phone=True)):mobile=''
    whatsapp=[]
    for w in p.get('whatsapp',[]):
        if not isinstance(w,dict) or w.get('attribution')!='person' or normalized(w.get('attributed_name'))!=normalized(name):continue
        source=w.get('person_source',{})
        if not evidence_matches([source],name):continue
        if not w.get('url') or not ('whatsapp' in source.get('quote','').casefold() or 'wa.me' in source.get('quote','').casefold()):continue
        if not (w.get('url') in source.get('quote','') or (w.get('phone') and evidence_matches([source],name,w['phone'],phone=True))):continue
        whatsapp.append(w)
    from contact_products import annotate_people
    responsibilities=annotate_people([p])[0]['product_responsibilities']
    sources=list(dict.fromkeys(ev.get('url') for values in fields.values() for ev in values if isinstance(ev,dict) and ev.get('url')))
    return {'website':website,'name':name,'title':title,'email':mail,'mobile':mobile,'whatsapp':whatsapp,
        'sources':sources,'evidence_by_field':fields,'qualified':True,'qualification_mode':'name_email' if name_email_only else 'name_role_email','email_decodings':p.get('email_decodings',[]),
        'verified_at':p.get('checked_at') or (report or {}).get('checked_at') or '',
        'product_responsibilities':responsibilities,'email_status':'公开来源归属核实；未验证投递','procurement_authority_confirmed':False,
        'mobile_verified_personal':bool(mobile),'whatsapp_verified_personal':bool(whatsapp)}

def job_snapshot(identifier):
    from batch_jobs import get_batch
    with LOCK:
        if identifier not in JOBS:raise ValueError('插件查询记录不存在')
    job=get_batch(identifier);contacts=[]
    for item in job.get('items',[]):
        for result in item.get('results',[]):
            report=result.get('report',{})
            website=report.get('website') or item.get('website','')
            for person in report.get('people',[]):
                contact=safe_contact(person,website,report,name_email_only=job.get('mode')=='name_email')
                if not contact:continue
                cid=hashlib.sha256(('\0'.join((website,contact['name'].casefold(),contact['email'].casefold()))).encode()).hexdigest()[:24]
                contact.update(contact_id=cid,source_job_id=identifier)
                if not any(p['contact_id']==cid for p in contacts):contacts.append(contact)
    with LOCK:JOBS[identifier]['contacts']={p['contact_id']:copy.deepcopy(p) for p in contacts}
    items=job.get('items',[])
    progress=items[0].get('progress') if len(items)==1 else job.get('progress','')
    warnings=list(job.get('errors',[]))
    for item in items:
        for result in item.get('results',[]):
            for error in result.get('report',{}).get('errors',[]):
                message=error.get('error','') if isinstance(error,dict) else str(error)
                if message and message not in warnings:warnings.append(message)
    return {'id':identifier,'status':job['status'],'progress':progress or job.get('progress',''),'contacts':contacts,'errors':warnings}

def dispatch(handler):
    """Return True iff this request belongs to the authenticated extension API."""
    if not handler.path.startswith('/api/extension/'):return False
    conf=get_configuration();origin=handler.headers.get('Origin');expected='chrome-extension://'+conf['extensionId']
    allowed={expected,'http://127.0.0.1:18830'}
    request_host=handler.headers.get('Host','')
    def respond(data,status=200,raw=None,mime=None):
        body=raw if raw is not None else json.dumps(data,ensure_ascii=False).encode()
        handler.send_response(status);handler.send_header('Content-Type',mime or 'application/json; charset=utf-8')
        handler.send_header('Cache-Control','no-store');handler.send_header('X-Content-Type-Options','nosniff')
        if origin in allowed:
            handler.send_header('Access-Control-Allow-Origin',origin);handler.send_header('Vary','Origin')
        handler.send_header('Content-Length',str(len(body)));handler.end_headers()
        handler.wfile.write(body)
        return True
    if request_host!='127.0.0.1:18830':return respond({'error':'本地服务地址不匹配'},403)
    if origin is not None and origin not in allowed:return respond({'error':'未配对的请求来源'},403)
    if handler.command=='OPTIONS':
        requested={s.strip().lower() for s in handler.headers.get('Access-Control-Request-Headers','').split(',') if s.strip()}
        if origin not in allowed or handler.headers.get('Access-Control-Request-Method') not in ('GET','POST') or not requested.issubset({'authorization','content-type','x-user-radar-extension'}):return respond({'error':'不接受此跨域请求'},403)
        handler.send_response(204);handler.send_header('Access-Control-Allow-Origin',origin);handler.send_header('Vary','Origin')
        handler.send_header('Access-Control-Allow-Methods','GET, POST');handler.send_header('Access-Control-Allow-Headers','Authorization, Content-Type, X-User-Radar-Extension');handler.send_header('Content-Length','0');handler.end_headers();return True
    token=handler.headers.get('Authorization','')
    if not hmac.compare_digest(token,'Bearer '+conf['token']) or handler.headers.get('X-User-Radar-Extension')!=conf['extensionId']:
        return respond({'error':'插件未配对，请使用本机安装包'},401)
    path=handler.path
    try:
        if handler.command=='GET':
            if path=='/api/extension/health':
                from importlib.metadata import version
                return respond({'ok':True,'app':'user-radar','version':2,
                    'components':{'extruct':version('extruct'),'theHarvester':'4.8.2-local-parser','website-email-contact-scraper':'d6a92b9-local-email-parser'},
                    'contact_rule':'name+individual_email; role/mobile/WhatsApp optional; no missing-channel searches'})
            if path.startswith('/api/extension/job/'):return respond(job_snapshot(path.rsplit('/',1)[-1]))
            if path=='/api/extension/customers':
                from customer_store import customers
                return respond({'customers':customers()})
            if path=='/api/extension/export':
                from customer_store import export_csv
                return respond({},raw=export_csv(),mime='text/csv; charset=utf-8')
        if handler.command=='POST':
            if handler.headers.get('Content-Type','').split(';')[0]!='application/json':return respond({'error':'需要 JSON 请求'},415)
            size=int(handler.headers.get('Content-Length','0'))
            if not 0<size<=4096:return respond({'error':'请求大小无效'},400)
            data=json.loads(handler.rfile.read(size))
            if not isinstance(data,dict):return respond({'error':'请求格式无效'},400)
            if path=='/api/extension/start':
                if set(data)!={'website'}:return respond({'error':'仅接受官网地址'},400)
                from app import public_url
                from batch_jobs import start_batch
                website=public_url(data['website'])
                result=start_batch([website],mode='name_email')
                with LOCK:JOBS[result['id']]={'website':website,'contacts':{}}
                return respond(result)
            if path=='/api/extension/save':
                if set(data)!={'job_id','contact_id'}:return respond({'error':'仅接受已核实的查询编号和联系人编号'},400)
                job_snapshot(data['job_id'])
                with LOCK:contact=copy.deepcopy(JOBS[data['job_id']]['contacts'].get(data['contact_id']))
                if not contact:return respond({'error':'联系人不符合姓名与具名邮箱要求'},400)
                from customer_store import save
                return respond(save(contact))
        return respond({'error':'接口不存在'},404)
    except (ValueError,TypeError,KeyError) as error:
        return respond({'error':str(error)},400)
    except Exception:
        return respond({'error':'查询服务暂时不可用，请查看用户雷达后台'},503)

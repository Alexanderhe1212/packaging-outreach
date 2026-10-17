"""Join exact full-name records from one official website; never fuzzy identity."""
import copy,re
from urllib.parse import urlsplit
from contact_quality import phone_info

def _host(url):return (urlsplit(url or '').hostname or '').lower().removeprefix('www.')
def _name(name):return ' '.join((name or '').casefold().split())
def join_official_people(people,scopes_by_source,role,is_role):
    from whatsapp_attribution import attributed_channels
    groups={}
    for p in people:
        if len(p.get('name','').split())<2:continue
        groups.setdefault((_host(p.get('source')),_name(p['name'])),[]).append(p)
    joined=[]
    for (domain,name),items in groups.items():
        identities=[p for p in items if role.search(p.get('title','')) and not p.get('contact_only') and not p.get('historical')]
        # Identical names with multiple unrelated companies never join here.
        if not domain or not identities:
            joined.extend(items);continue
        addresses={p['email'].casefold() for p in items if p.get('email') and (not is_role(p['email']) or (p.get('signed_contact') and p.get('person_designated_role_email'))) and not p.get('shared_email') and not p.get('historical')}
        if len(addresses)>1:
            joined.extend(items);continue
        p=copy.deepcopy(next((x for x in identities if x.get('email')),identities[0]))
        p['sources']=list(dict.fromkeys(x['source'] for x in items if x.get('source')))
        p['title']=identities[0]['title'];p['contact_only']=False
        if addresses:
            p['email']=next(iter(addresses))
            mail_items=[x for x in items if x.get('email','').casefold()==p['email']]
            p['source']=mail_items[0]['source']
            p['evidence_by_field']=dict(p.get('evidence_by_field',{}))
            p['evidence_by_field']['email']=[{'url':x['source'],'quote':x.get('evidence',''),'source_type':'official'} for x in mail_items]
        p.setdefault('evidence_by_field',{})['identity']=[{'url':x['source'],'quote':x.get('evidence',''),'source_type':'official'} for x in identities]
        numbers={}
        for x in items:
            info=phone_info(x.get('phone',''),x.get('country_hint'))
            if info['phone_e164']:numbers.setdefault(info['phone_e164'],[]).append(x)
        mobile=[n for n in numbers if phone_info(n)['mobile']]
        selected=mobile if mobile else list(numbers)
        if len(selected)==1:
            n=selected[0];p['phone']=n;p['phone_raw']=numbers[n][0].get('phone_raw') or n
            p['evidence_by_field']['phone']=[{'url':x['source'],'quote':x.get('evidence',''),'source_type':'official'} for x in numbers[n]]
        elif len(selected)>1:p.update(phone='',phone_raw='',phone_conflict=True,phone_variants=[{'phone':n,'source':numbers[n][0]['source']} for n in selected])
        channels=list(p.get('explicit_whatsapp',[]))
        for source,scopes in scopes_by_source.items():
            if _host(source)!=domain:continue
            owned,_=attributed_channels(scopes,p['name'],p.get('email',''),identity_verified=True,email_verified=bool(p.get('email')))
            channels.extend(owned)
        p['explicit_whatsapp']=list({(w.get('url',''),w.get('phone',''),w.get('source','')):w for w in channels}.values())
        if not p.get('phone') and not p.get('phone_conflict'):
            wa_numbers={w['phone'] for w in p['explicit_whatsapp'] if w.get('phone') and phone_info(w['phone'])['phone_e164']}
            if len(wa_numbers)==1:p.update(phone=next(iter(wa_numbers)),phone_raw=next(iter(wa_numbers)))
        if p['explicit_whatsapp']:p['evidence_by_field']['whatsapp']=[{'url':w['source'],'quote':w['ownership_quote'],'source_type':'official'} for w in p['explicit_whatsapp']]
        p['identity_only']=not bool(p.get('email') or p.get('phone'))
        p['status']=p.get('status','')+'；按同域完整姓名合并证据，未验证任职、投递或接通'
        joined.append(p)
    return joined

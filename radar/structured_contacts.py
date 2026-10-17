"""Local-only extruct adapter. Never join fields across people or organizations."""
import json
import re
from urllib.parse import unquote, urlsplit
from person_identity import plausible_person_name


def extract_people(raw, url, role, is_role, region=None):
    if not re.search(r'application/ld\+json|itemscope',raw,re.I):return []
    import extruct
    try:
        data=extruct.extract(raw,base_url=url,syntaxes=['json-ld','microdata'],uniform=True)
    except (ValueError,TypeError,RecursionError):return []
    result=[];seen=set();budget=[500]
    def scalar(value):
        values=value if isinstance(value,list) else [value]
        values=list(dict.fromkeys(v.strip() for v in values if isinstance(v,str) and v.strip()))
        return values[0] if len(values)==1 else ''
    def walk(obj,depth=0):
        if depth>20 or budget[0]<=0:return
        budget[0]-=1
        if isinstance(obj,list):
            for item in obj:walk(item,depth+1)
            return
        if not isinstance(obj,dict):return
        kinds=obj.get('@type',[]);kinds=[kinds] if isinstance(kinds,str) else kinds
        if not isinstance(kinds,(list,tuple)):kinds=[]
        kinds={v.rstrip('/').rsplit('/',1)[-1].rsplit('#',1)[-1] for v in kinds if isinstance(v,str)}
        if 'Person' in kinds:
            name=scalar(obj.get('name'));title=scalar(obj.get('jobTitle'))
            if plausible_person_name(name) and len(title)<=120 and role.search(title):
                email=unquote(scalar(obj.get('email'))).removeprefix('mailto:').split('?',1)[0]
                if not re.fullmatch(r'[^\s;@]+@[^\s;@]+\.[^\s;@]+',email) or is_role(email):email=''
                phone=scalar(obj.get('telephone'))
                # Evidence contains exactly this Person's direct fields. Nested
                # Organization/contactPoint/colleague fields are never inherited.
                fields={k:obj[k] for k in ('@type','@id','name','jobTitle','email','telephone','sameAs') if k in obj}
                evidence=json.dumps(fields,ensure_ascii=False,sort_keys=True)
                key=(name.casefold(),title.casefold(),email.casefold(),phone)
                if key not in seen:
                    seen.add(key)
                    result.append(dict(name=name,title=title,email=email,phone=phone,phone_raw=phone,
                        country_hint=region,source=url,evidence=evidence,
                        structured_record=fields,structured_syntax=syntax,structured_format='extruct JSON-LD/Microdata',
                        status='公开结构化 Person 条目；当前归属与缺失项继续独立核对'))
        for key,value in obj.items():
            if key in ('author','creator','review','reviewer','comment'):continue
            if isinstance(value,(dict,list)):walk(value,depth+1)
    for syntax in ('json-ld','microdata'):walk(data.get(syntax,[]))
    return result


def person_whatsapp_scopes(people,source):
    """Only an actual sameAs WhatsApp link on that exact Microdata Person."""
    from bs4 import BeautifulSoup
    from contact_quality import whatsapp_links
    scopes=[]
    for person in people:
        if person.get('structured_syntax')!='microdata':continue
        values=person.get('structured_record',{}).get('sameAs',[])
        if isinstance(values,str):values=[values]
        for value in values if isinstance(values,list) else []:
            if not isinstance(value,str):continue
            soup=BeautifulSoup('<a></a>','html.parser');soup.a['href']=value
            for channel in whatsapp_links(soup,source):
                scopes.append(dict(text=person['evidence'],names=[person['name']],
                    channels=[dict(channel,evidence_kind='person_structured_link')],excluded_reason=''))
    return scopes

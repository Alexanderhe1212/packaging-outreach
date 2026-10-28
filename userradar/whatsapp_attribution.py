"""Published WhatsApp evidence owned by one contact, never account discovery."""
import re,unicodedata,json
from urllib.parse import urlsplit,parse_qs
from bs4 import BeautifulSoup
from contact_quality import whatsapp_links,phone_info

SHARED=re.compile(r'customer\s*(?:support|service|care)|help\s*desk|helpline|general\s*enquir|support\s*team|order\s*(?:support|enquir)|客服|总机|service\s+client',re.I)
EXCLUDED=re.compile(r'footer|navbar|recommend|suggest|related|comment|social.share|share.button|customer.service|customer.support',re.I)
LABEL=re.compile(r'\b(?:whats\s*app|wa)\b(?:\s+(?:number|no\.?|on))?\s*[:：/–-]?\s*((?:\+|00)?\d[\d\s().-]{5,25}\d)',re.I)

def _norm(s):return ' '+re.sub(r'[^\w@]+',' ',unicodedata.normalize('NFKC',s or '').casefold()).strip()+' '
def has(text,value):return bool(value) and _norm(value) in _norm(text)

def _blocked(node):
    for parent in [node]+list(node.parents):
        if parent.name in ('body','html','[document]'):break
        if parent.name in ('footer','nav','aside') or parent.get('role') in ('contentinfo','navigation'):return '页脚、导航或推荐区域'
        marker=' '.join([str(parent.get('id','')),' '.join(parent.get('class',[])),str(parent.get('aria-label',''))])
        if EXCLUDED.search(marker):return '客服、推荐、评论或分享区域'
        if parent.has_attr('hidden') or parent.get('aria-hidden')=='true':return '未显示内容'
    return ''

def publication_scopes(soup,source,region=None):
    """Retain DOM ownership alongside channel evidence instead of flattening it."""
    records=[]
    # Save structured Person.sameAs before scripts are removed. Organization
    # contact points do not establish an individual's WhatsApp.
    def walk(obj):
        if isinstance(obj,list):
            for item in obj:walk(item)
        if not isinstance(obj,dict):return
        kind=obj.get('@type',[]);kind=[kind] if isinstance(kind,str) else kind
        if 'Person' in kind and isinstance(obj.get('name'),str):
            values=obj.get('sameAs',[]);values=[values] if isinstance(values,str) else values
            for value in values if isinstance(values,list) else []:
                if not isinstance(value,str):continue
                tag=BeautifulSoup('<a></a>','html.parser');tag.a['href']=value;links=whatsapp_links(tag,source)
                for channel in links:records.append({'text':obj['name']+' '+str(obj.get('email','')),'names':[obj['name']],'channels':[dict(channel,evidence_kind='person_structured_link')],'excluded_reason':''})
        for value in obj.values():
            if isinstance(value,(dict,list)):walk(value)
    for script in soup.find_all('script',type='application/ld+json'):
        try:walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):pass
    events=[]
    for tag in soup.select('a[href]'):
        parsed=urlsplit(tag['href'])
        if parsed.scheme!='whatsapp' and parsed.hostname not in ('wa.me','api.whatsapp.com','web.whatsapp.com'):continue
        links=whatsapp_links(BeautifulSoup(str(tag),'html.parser'),source)
        if not links:continue
        # text-only wa.me/ links share a message and identify no recipient.
        if not any(w['phone'] or '/message/' in w['url'] for w in links):continue
        for w in links:events.append((tag,dict(w,evidence_kind='person_scoped_link')))
    for tag in soup.find_all(['p','li','address','td','div','span']):
        text=tag.get_text(' ',strip=True)
        if len(text)>600 or not LABEL.search(text):continue
        if any(LABEL.search(c.get_text(' ',strip=True)) for c in tag.find_all(['p','li','address','td','div','span'])):continue
        for match in LABEL.finditer(text):
            raw=match.group(1).strip();info=phone_info(raw,region)
            if info['phone_e164']:events.append((tag,{'phone':info['phone_e164'],'url':'','source':source,'status':'公开原文明示 WhatsApp；未验证账号','evidence_kind':'person_label','published_text':match.group(0),'phone_raw':raw,'country_inference':info.get('country_inference','')}))
    for node,channel in events:
        rejected=_blocked(node)
        if channel.get('phone') and not phone_info(channel['phone'])['phone_e164']:rejected='所发布号码格式或号段无效'
        if re.search(r'\bshare\b|分享',node.get_text(' ',strip=True)+' '+str(node.get('aria-label','')),re.I):rejected='WhatsApp 分享按钮'
        if rejected:
            records.append({'text':node.get_text(' ',strip=True),'names':[],'channels':[channel],'excluded_reason':rejected});continue
        for card in ([node]+list(node.parents))[:5]:
            if card.name in ('html','body','main'):break
            text=card.get_text(' ',strip=True)
            if len(text)>1000:break
            # Headings that are job titles are not person identities.
            from contact_extract import NAME
            from app import ROLE
            names=list(dict.fromkeys(h.get_text(' ',strip=True) for h in card.find_all(['h1','h2','h3','h4','h5','p','strong','span']) if NAME.fullmatch(h.get_text(' ',strip=True)) and not ROLE.search(h.get_text(' ',strip=True)) and not re.search(r'whatsapp|phone|mobile|email|contact|office|chat|message',h.get_text(' ',strip=True),re.I)))
            reason='多个联系人共用的区域' if len(names)>1 else '客服或共享渠道' if SHARED.search(text) else ''
            records.append({'text':text,'names':names,'channels':[channel],'excluded_reason':reason})
            if names or reason:break
    # Some page builders place several people in one container. Split only the
    # parser's explicit name/contact lines, stopping at the next person or shared
    # office, instead of lending the whole multi-person parent to each number.
    from public_contact_blocks import extract_public_blocks
    from app import ROLE,emails,is_role
    for person in extract_public_blocks(soup,source,ROLE,emails,is_role):
        quote=person.get('evidence','')
        for match in LABEL.finditer(quote):
            raw=match.group(1).strip();info=phone_info(raw,region)
            if not info['phone_e164']:continue
            channel={'phone':info['phone_e164'],'url':'','source':source,'status':'公开原文明示 WhatsApp；未验证账号','evidence_kind':'person_label','published_text':match.group(0),'phone_raw':raw,'country_inference':info.get('country_inference','')}
            records.append({'text':quote,'names':[person['name']],'channels':[channel],'excluded_reason':''})
    seen=set();unique=[]
    for r in records:
        key=json.dumps(r,sort_keys=True)
        if key not in seen:seen.add(key);unique.append(r)
    return unique

def attributed_channels(scopes,name,email='',identity_verified=False,email_verified=False):
    accepted=[];rejected=[]
    for scope in scopes:
        text=scope['text'];reason=scope.get('excluded_reason','')
        if reason:rejected.append({'reason':reason,'channels':scope['channels']});continue
        if scope.get('pdf_evidence'):
            # First names on a PDF button are only a consistency check. The
            # independent full-name identity AND the exact verified email are
            # mandatory; URI and printed phone were already compared spatially.
            if not email_verified or not email or scope.get('scope_email','').casefold()!=email.casefold():
                rejected.append({'reason':'PDF条目邮箱尚未与完整姓名独立关联','channels':scope['channels']});continue
            if scope.get('published_addressee') and not has(name,scope['published_addressee']):
                rejected.append({'reason':'PDF按钮署名与已核对联系人不一致','channels':scope['channels']});continue
        full=has(text,name)
        address_match=email_verified and has(text,email)
        if not identity_verified or not (full or address_match):continue
        if scope.get('names') and any(not has(n,name) for n in scope['names']):
            rejected.append({'reason':'条目署名属于其他联系人','channels':scope['channels']});continue
        # A neighbouring person's email cannot lend ownership to the candidate.
        from app import emails
        addresses=emails(text)
        if addresses and (not email or any(a.casefold()!=email.casefold() for a in addresses)):
            rejected.append({'reason':'条目邮箱与目标联系人不一致','channels':scope['channels']});continue
        for w in scope['channels']:
            accepted.append(dict(w,attribution='person',attributed_name=name,ownership_basis='同一公开联系人条目中的明确 WhatsApp 发布',ownership_quote=text[:1000],account_status='未验证账号当前有效性'))
    unique={(w.get('url',''),w.get('phone',''),w['source']):w for w in accepted}
    return list(unique.values()),rejected

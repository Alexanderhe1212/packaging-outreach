"""Join independently read identity and contact evidence; no guessed channels."""
import re,time,unicodedata
from urllib.parse import urlsplit, urljoin, unquote
from app import is_role,emails,ROLE,host
from contact_quality import phone_info,qualify
from public_sources import acceptable_url
import phonenumbers as pn


def norm(value):
    value=unicodedata.normalize('NFKC',value or '').casefold()
    return re.sub(r'[^\w@]+',' ',value).strip()

def contains(text,value):return bool(value) and (' '+norm(value)+' ') in (' '+norm(text)+' ')

def title_matches(text,title):
    def undot(value):return re.sub(r'\bC\.?\s*E\.?\s*O\.?\b','CEO',value,flags=re.I)
    return contains(undot(text),undot(title))

def brand_mailbox(address,company,website):
    """A brand-named address is a shared route, even in a founder's post."""
    compact=lambda value:re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKC',value).casefold())
    local=compact(address.split('@')[0])
    company=re.sub(r'\b(?:pvt|private|limited|ltd|inc|llc|pty)\b\.?','',company,flags=re.I)
    brands={compact(company),compact(host(website).split('.')[0])}-{''}
    return local in brands

def shared_mailbox(address,company,website):
    return is_role(address) or brand_mailbox(address,company,website)

def matching_phones(block,wanted,region):
    target=phone_info(wanted,region)['phone_e164']
    if not target:return []
    found=[]
    for line in block.splitlines():
        # Keep candidate numbers separate instead of concatenating every digit
        # on the contact card. A published country code may contain whitespace.
        line=re.sub(r'\+\s+(\d)',r'+\1',line)
        for match in pn.PhoneNumberMatcher(line,region):
            info=phone_info(match.raw_string,region)
            if info['phone_e164']==target:found.append((info,match.raw_string))
    return found

def evidence(d,block,official):
    ev={'url':d['url'],'quote':block[:1400],'checked_at':d['checked_at'],'source_type':'official' if official else 'public'}
    for key in ('published_date','source_year','date_basis'):
        if key in d:ev[key]=d[key]
    context=next((x for x in d.get('block_contexts',[]) if x['text']==block),{})
    if context.get('page'):ev['page']=context['page']
    return ev

def company_linked(document,company,website):
    domain=host(website)
    if contains(document['text'],company):return True
    core=re.sub(r'(?:\s*[,.(]?\s*(?:pvt|private|ltd|limited|inc|llc|corp|corporation)\.?\)?)+$','',company,flags=re.I).strip()
    if len(core.split())>=2 and contains(document['text'],core):return True
    if any(host(x)==domain for x in document['links'] if x.startswith('http')):return True
    # PDFs print website addresses as text rather than HTML links. Require a
    # complete domain token; neither email-only nor evil-suffix matches suffice.
    return bool(domain and re.search(r'(?<![\w@.-])(?:https?://)?(?:www\.)?'+re.escape(domain)+r'(?![\w.-])',document['text'],re.I))



# An official page linking a social profile, supplier, marketplace or press
# article does not turn that service into the company's work-email domain.
_SHARED_HOSTS=('linkedin.com','facebook.com','instagram.com','youtube.com','twitter.com','x.com','tiktok.com','pinterest.com','whatsapp.com','wa.me','google.com','gmail.com','outlook.com','hotmail.com','yahoo.com','amazon.com','linktr.ee')
def official_mail_domain(domain,candidate,reader,docs,checks):
    website=candidate['website'];company=candidate.get('company','');base=host(website)
    if not domain or any(domain==s or domain.endswith('.'+s) for s in _SHARED_HOSTS):return False,[]
    official_docs=[d for d,official in docs if official]
    parts=urlsplit(website);root=parts.scheme+'://'+parts.netloc+'/'
    external=re.compile(r'\b(?:external|third[- ]party|agenc(?:y|ies)|suppliers?|vendors?|clients?|partners?|on behalf of|represented by|service provider|distributors?)\b',re.I)
    own_contact=re.compile(r'\b(?:press\s*office|head\s*office|registered\s*office|corporate\s+(?:communications|contacts?)|company\s+(?:contact|email)|customer\s+(?:service|care)|contact\s+us|our\s+(?:email|contact)|official\s+(?:email|contact))\b',re.I)
    def published_domain_proof(items):
        for doc in items:
            scopes=[item.get('text','') for item in doc.get('email_contexts',[])]+[item.get('text','') for item in doc.get('link_contexts',[]) if item.get('url','').lower().startswith('mailto:')]
            for scope in scopes:
                if len(scope)>600 or external.search(scope) or not own_contact.search(scope):continue
                matching=sorted(a for a in emails(scope) if host('https://'+a.rsplit('@',1)[-1])==domain)
                if matching:return [evidence(doc,scope,True)]
        return []
    proof=published_domain_proof(official_docs)
    if proof:return True,proof
    # One extra root read fits the SourceReader's eight-document limit alongside
    # the original six candidates and at most one linked regional homepage.
    if not any(d['url'].rstrip('/')==root.rstrip('/') for d in official_docs):
        try:
            d=reader.read(root)
            if host(d['url'])==base:
                official_docs.append(d);checks.append({'url':root,'status':'已独立读取官方邮箱域名关系','checked_at':d['checked_at']})
        except Exception as exc:checks.append({'url':root,'status':'官方邮箱域名关系未读到：'+str(exc)[:140]})
    proof=published_domain_proof(official_docs)
    if proof:return True,proof
    # Regional affiliation requires an explicit official site declaration,
    # self-entity heading and reciprocal site declaration. A supplier portfolio
    # can contain the brand and a backlink without proving employment.
    regional=re.compile(r'\b(?:regional|international|global|group|corporate|country|national|official|united kingdom|uk|us|usa|european)\s+(?:web\s*site|site)\b',re.I)
    for d in official_docs:
        declared=[]
        for item in d.get('link_contexts',[]):
            linked=urljoin(d['url'],item.get('url',''))
            if acceptable_url(linked) and host(linked)==domain and regional.search(item.get('label','')) and not external.search(item.get('text','')):
                declared.append((linked,item))
        if not declared:continue
        linked,item=declared[0];target=urlsplit(linked);alias_root=target.scheme+'://'+target.netloc+'/'
        try:
            other=reader.read(alias_root)
            checks.append({'url':alias_root,'status':'已独立读取候选地区域名关系','checked_at':other['checked_at']})
        except Exception as exc:
            checks.append({'url':alias_root,'status':'地区域名关系未读到：'+str(exc)[:140]});return False,[]
        if host(other['url'])!=domain:return False,[]
        self_entity=any(contains(h,company) and not external.search(h) for h in other.get('entity_headings',[]))
        back=next((item for item in other.get('link_contexts',[]) if acceptable_url(urljoin(other['url'],item.get('url',''))) and host(urljoin(other['url'],item.get('url','')))==base and regional.search(item.get('label','')) and not external.search(item.get('text',''))),None)
        if company and self_entity and back:
            return True,[evidence(d,item.get('text','')+' '+linked,True),evidence(other,' / '.join(other.get('entity_headings',[]))+' '+back.get('text',''),False)]
        return False,[]
    return False,[]

def is_linkedin(url):
    p=urlsplit(url);h=p.hostname or ''
    return p.scheme in ('http','https') and (h=='linkedin.com' or h.endswith('.linkedin.com')) and p.path.startswith('/in/')

def verify_candidate(candidate,reader,*,published_identity=None,excluded_channels=None):
    from person_identity import plausible_person_name
    c=candidate;name=c.get('name','').strip();title=c.get('title','').strip();email=c.get('email','').strip()
    result={'name':name,'title':title,'email':'','phone':'','source':'','status':'多来源补查；归属未确认','evidence_by_field':{},'source_checks':[],'linkedin_url':'','linkedin_note':'未找到公开领英依据','company':c.get('company',''),'website':c.get('website','')}
    published=published_identity or {}
    published_source=published.get('source','')
    published_target=bool(norm(published.get('name',''))==norm(name) and norm(published.get('title',''))==norm(title) and acceptable_url(published_source) and host(published_source)==host(c.get('website','')))
    if not plausible_person_name(name) or not title or not acceptable_url(c.get('website','')):

        result['status']='姓名、职位或公司地址不完整';return result
    if re.search(r'guarantee|contact|privacy|support|customer|our team',name,re.I):return result
    docs=[]
    sources=list(c.get('sources',[]))
    if published_target:
        sources=[{'url':published_source}]+[s for s in sources if s.get('url')!=published_source]
    for source in sources[:6]:
        url=source.get('url','')
        if not acceptable_url(url):continue
        if is_linkedin(url) and url==c.get('linkedin_url'):
            result['linkedin_url']=url;result['linkedin_note']='公开搜索索引线索；未独立读取确认'
        try:
            d=reader.read(url);official=host(url)==host(c['website'])
            company_match=official or company_linked(d,c.get('company',''),c['website'])
            if not company_match:
                result['source_checks'].append({'url':url,'status':'未确认来源与公司关联'});continue
            docs.append((d,official))
            check={'url':url,'status':'已独立读取','checked_at':d['checked_at']}
            check.update({k:d[k] for k in ('published_date','source_year','date_basis') if k in d})
            if d.get('pdf_channel_error'):check['channel_note']=d['pdf_channel_error']
            result['source_checks'].append(check)
        except Exception as e:result['source_checks'].append({'url':url,'status':str(e)[:180]})
    official_team=[]
    if published_target:
        for d,official in docs:
            if not official:continue
            for person in d.get('people',[]):
                if norm(person.get('name',''))==norm(name) and norm(person.get('title',''))==norm(title):
                    official_team.append(evidence(d,person.get('evidence',''),True))
    if not ROLE.search(title) and not official_team:
        result['status']='来源已读取；该职位未属于关键业务岗位，且未独立重读到官网团队身份';return result
    # Resolve a missing candidate email only from an independently read, tight
    # Person scope. theHarvester domain hits alone never establish ownership.
    if not email:
        observed=set()
        for d,official in docs:
            hints=list(d.get('email_hints',[]))
            if host(d.get('url',''))!=host(c['website']) and '@' in d.get('text',''):
                from harvester_bridge import email_hints
                hints.extend(email_hints(d['text'],d['url'],target_domain=host(c['website'])))
            for block in d.get('blocks',[]):
                if len(block)>900 or not contains(block,name) or not title_matches(block,title):continue
                for hint in hints:
                    address=hint.get('email','')
                    if address and address.casefold() in block.casefold() and not shared_mailbox(address,c.get('company',''),c['website']):observed.add(address)
        if len(observed)==1:
            email=next(iter(observed));c=dict(c,email=email)
            result['email_resolution']='theHarvester / website-email-contact-scraper 公开线索与同人姓名、职位原文交叉核对；仍经完整邮箱域名与身份核实'
            result['email_decodings']=[dict(item,source=d['url']) for d,_ in docs for item in d.get('email_decodings',[]) if item.get('email','').casefold()==email.casefold()]
    alias_proofs=[]
    email_domain=host('https://'+email.rsplit('@',1)[-1]) if '@' in email else ''
    website_domain=host(c['website'])
    domain_ok=bool(email_domain and (email_domain==website_domain or email_domain.endswith('.'+website_domain)))
    if email_domain and not domain_ok and any(not official for d,official in docs):
        domain_ok,alias_proofs=official_mail_domain(email_domain,c,reader,docs,result['source_checks'])
    if alias_proofs:result['evidence_by_field']['work_domain']=alias_proofs
    identities=list(official_team);mail=[];phones=[];wa=[]
    wanted_phone=c.get('phone','');wanted_wa=c.get('whatsapp_url','')
    for d,official in docs:
        # Tight person blocks prevent footer contacts or recommended posts from
        # attaching to the profile at the top of a page.
        person_blocks=[b for b in d['blocks'] if contains(b,name)]
        for block in person_blocks:
            ev=evidence(d,block,official)
            if title_matches(block,title):
                if re.search(r'\b(former|previously|ex-founder|ex-ceo)\b',block,re.I):continue
                identities.append(ev)
                if is_linkedin(d['url']):result['linkedin_note']='已独立读取公开领英页面，姓名、公司与职位一致'
            found=emails(block)
            email_domain=host('https://'+email.rsplit('@',1)[-1]) if '@' in email else ''
            work_domain=official or domain_ok
            if email and work_domain and not shared_mailbox(email,c.get('company',''),c['website']) and email.casefold() in [a.casefold() for a in found] and len(set(a.casefold() for a in found))==1 and len(block)<=900:
                mail.append(ev)
            if wanted_phone and re.sub(r'\D','',wanted_phone) and len(block)<=500:
                def compatible_address(address):
                    domain=host('https://'+address.rsplit('@',1)[-1])
                    role_address=is_role(address) or address.split('@')[0].casefold() in ('export','exports')
                    return address.casefold()==email.casefold() or (role_address and domain==host(c['website']))
                if not found or all(compatible_address(a) for a in found):
                    for info,raw in matching_phones(block,wanted_phone,d.get('country_hint')):phones.append((ev,info,raw))
            # Recover a channel from the original person block, even when the
            # AI omitted it. Require a complete named identity and the sole
            # candidate email in this very block; never borrow a footer phone.
            if not wanted_phone and len(block)<=500 and title_matches(block,title) and not re.search(r'\b(former|previously|ex-founder|ex-ceo)\b',block,re.I):
                addresses={a.casefold() for a in found}
                if email and addresses=={email.casefold()} and work_domain and not shared_mailbox(email,c.get('company',''),c['website']):
                    observed={}
                    for line in block.splitlines():
                        line=re.sub(r'\+\s+(\d)',r'+\1',line)
                        for match in pn.PhoneNumberMatcher(line,d.get('country_hint')):
                            info=phone_info(match.raw_string,d.get('country_hint'))
                            if info['phone_e164']:observed[info['phone_e164']]=(ev,info,match.raw_string)
                    if len(observed)==1:phones.extend(observed.values())
        # Signed first-person contact invitations can span separate DOM blocks.
        # Only the source parser's independently produced, exact-name records
        # may bridge those blocks; research quotes/aliases cannot do so.
        for person in d.get('people',[]):
            if official and norm(person.get('name',''))==norm(name) and norm(person.get('title',''))==norm(title) and not person.get('signed_contact'):
                # The independently read, exact full-name/title official card
                # proves its own fields even when AI omitted the card's phone.
                ev=evidence(d,person.get('evidence',''),True)
                identities.append(ev)
                observed=person.get('email','')
                if email and observed.casefold()==email.casefold() and not shared_mailbox(email,c.get('company',''),c['website']):mail.append(ev)
                info=phone_info(person.get('phone',''),person.get('country_hint') or d.get('country_hint'))
                if info['phone_e164']:phones.append((ev,info,person['phone']))
                for channel in person.get('explicit_whatsapp',[]):
                    if channel.get('attribution')=='person' and norm(channel.get('attributed_name'))==norm(name):wa.append(dict(channel,person_source=ev))
            if not person.get('signed_contact') or norm(person.get('name'))!=norm(name):continue
            if not title_matches(person.get('title',''),title):continue
            ev=evidence(d,person.get('evidence',''),official)
            identities.append(ev)
            result['signed_contact']=True
            published=person.get('email') or person.get('published_email') or person.get('role_email') or ''
            if published:
                result['published_email']=published
                result['email_kind']=person.get('email_kind','published_signed_business_email')
            designated_role=bool(person.get('person_designated_role_email') and is_role(email) and not brand_mailbox(email,c.get('company',''),c['website']))
            if email and published.casefold()==email.casefold() and (designated_role or not shared_mailbox(email,c.get('company',''),c['website'])):
                mail.append(ev)
                if designated_role:result['person_designated_role_email']=True
            info=phone_info(person.get('phone',''),person.get('country_hint') or d.get('country_hint'))
            if info['phone_e164']:phones.append((ev,info,person['phone']))
            for channel in person.get('explicit_whatsapp',[]):
                if channel.get('attribution')=='person' and norm(channel.get('attributed_name'))==norm(name):wa.append(dict(channel,person_source=ev))
    if identities:result['evidence_by_field']['identity']=identities
    if mail:result['email']=email;result['evidence_by_field']['email']=mail;result['source']=mail[0]['url']
    if phones:
        mobiles={info['mobile'] for ev,info,raw in phones if info['mobile']}
        if len(mobiles)>1:
            result.update(phone_conflict=True,phone_variants=[{'phone':info['phone_e164'],'source':ev['url']} for ev,info,raw in phones])
            result['evidence_by_field']['phone']=[ev for ev,info,raw in phones]
        else:
            ev,info,raw=next((p for p in phones if p[1]['mobile']),phones[0]);result.update(phone=info['phone_e164'],phone_raw=raw,**info);result['evidence_by_field']['phone']=[ev]
    from whatsapp_attribution import attributed_channels
    rejected=[]
    for d,official in docs:
        matched,exclusions=attributed_channels(d.get('whatsapp_scopes',[]),name,email,identity_verified=bool(identities),email_verified=bool(mail))
        for w in matched:
            ev={'url':d['url'],'quote':w['ownership_quote'],'checked_at':d['checked_at'],'source_type':'official' if official else 'public'}
            wa.append(dict(w,person_source=ev))
        rejected.extend(exclusions)
    wa=list({(w.get('url',''),w.get('phone',''),w['source']):w for w in wa}.values())
    result['whatsapp_exclusions']=rejected
    if not result.get('phone') and not result.get('phone_conflict'):
        for channel in wa:
            info=phone_info(channel.get('phone',''))
            if info['phone_e164']:
                result.update(phone=info['phone_e164'],phone_raw=channel.get('phone_raw') or channel['phone'],**info)
                result['evidence_by_field']['phone']=[channel['person_source']]
                if channel.get('country_inference'):result['country_inference']=channel['country_inference']
                break
    # The fresh website observation identifies public company channels. A
    # repost or press release cannot relabel those as an individual's mobile.
    excluded=excluded_channels or {}
    channel_key=lambda value:re.sub(r'\D','',str(value)) if not str(value).startswith(('http://','https://','whatsapp:')) else str(value).strip().rstrip('/').casefold()
    blocked_numbers={channel_key(v) for key in ('phones','whatsapp') for v in excluded.get(key,[]) if v}
    blocked_urls={str(v).strip().rstrip('/').casefold() for v in list(excluded.get('whatsapp',[]))+list(excluded.get('whatsapp_urls',[])) if v}
    wa_kept=[]
    for w in wa:
        if (w.get('phone') and channel_key(w['phone']) in blocked_numbers) or (w.get('url') and w['url'].strip().rstrip('/').casefold() in blocked_urls):
            result['whatsapp_exclusions'].append({'reason':'与本轮官网公司公共渠道一致，不计本人WhatsApp','channels':[w]})
        else:wa_kept.append(w)
    wa=wa_kept
    if result.get('phone') and channel_key(result['phone']) in blocked_numbers:
        result['phone_exclusion']='与本轮官网公司公共渠道一致，不计本人手机'
        result.update(phone='',phone_raw='',mobile='',phone_e164='')
        result['evidence_by_field'].pop('phone',None)
    if result.get('email','').casefold() in {str(v).casefold() for v in excluded.get('emails',[]) if v}:
        result['email']='';mail=[];result['evidence_by_field'].pop('email',None)
        result['email_exclusion']='与本轮官网公司公共邮箱一致，不计具名工作邮箱'
    if not wa:result['evidence_by_field'].pop('whatsapp',None)
    result['explicit_whatsapp']=wa
    if wa:result['evidence_by_field']['whatsapp']=[w['person_source'] for w in wa]
    if not identities:result['email']='';result['status']='身份与职位尚未独立核对'
    elif not mail:result['status']='姓名职位有依据，具名工作邮箱尚未独立核对'
    else:result['status']='姓名、职位与具名工作邮箱已按公开来源关联；任职及投递未人工确认'
    result['sources']=list(dict.fromkeys(e['url'] for values in result['evidence_by_field'].values() for e in values))
    result['email_status']='公开来源已读取；未验证投递' if result['email'] else '未核对到具名工作邮箱'
    result['official_email']=bool(mail and any(e['source_type']=='official' for e in mail))
    dated=[e for values in result['evidence_by_field'].values() for e in values if e.get('source_year')]
    if dated:
        result['evidence_years']=sorted({e['source_year'] for e in dated})
        result['evidence_age_note']='来源年份：'+', '.join(map(str,result['evidence_years']))+'；读取时间不代表任职或联系方式已重新确认'
    cutoff=time.gmtime().tm_year-2
    phone_evidence=result['evidence_by_field'].get('phone',[])
    if result.get('phone') and phone_evidence and all(e.get('source_year',cutoff+1)<=cutoff for e in phone_evidence):
        result['published_phone']=result['phone'];result['phone_stale']=True
        result.update(phone='',phone_raw='',mobile='')
        result['phone_review_note']='手机仅有较旧公开依据，保留原号码待近期同人来源复核'
    stale_fields=[field for field in ('identity','email') if result['evidence_by_field'].get(field) and all(e.get('source_year',cutoff+1)<=cutoff for e in result['evidence_by_field'][field])]
    if stale_fields:
        result.update(historical=True,needs_review=True,review_required=True,current_status='历史资料待复核')
        result['email_stale']='email' in stale_fields
        if result.get('email'):result['published_email']=result.pop('email');result['email']=''
        result['status']='历史公开资料已关联；当前任职或邮箱归属待复核，暂不进入开发名单'
    if email and shared_mailbox(email,c.get('company',''),c['website']) and not result.get('person_designated_role_email'):
        result['email_exclusion']='共享品牌或岗位邮箱，不计具名个人工作邮箱'
    qualify({'people':[result],'whatsapp':[]},is_role)
    if result['email']:result['email_status']='公开来源已读取；未验证投递'
    return result


def report_for(company,people):
    r={'website':company['website'],'people':people,'emails':[],'phones':[],'whatsapp':[],'clues':[],'pages':list(dict.fromkeys(s for p in people for s in p.get('sources',[]))),'errors':[], 'note':'多来源补查：姓名、职位和具名工作邮箱必须有独立读取依据；公开领英索引不能单独证明身份。邮箱投递、手机接通及 WhatsApp 可用性未验证。'}
    qualify(r,is_role)
    for p in r['people']:
        if p.get('email'):p['email_status']='公开来源已读取；未验证投递'
    import time
    r['checked_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    return r

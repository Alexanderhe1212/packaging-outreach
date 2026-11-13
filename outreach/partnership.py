"""Reviewed designer outreach, using existing ownership and transport protection."""
import hashlib,json,time,re
from html.parser import HTMLParser
from . import web,store,config

def digest(lead):
    return hashlib.sha256(json.dumps([lead.get(k,'') for k in ('account','domain','email','subject','body')],ensure_ascii=False).encode()).hexdigest()

def eligible(lead):
    proof=lead.get('data',{}).get('partnership_review',{})
    return (lead.get('source')=='designer_partnership' and proof.get('digest')==digest(lead)
            and proof.get('email_verified') is True and bool(proof.get('work_quote'))
            and 0<=time.time()-proof.get('checked_at',0)<30*86400)

def verify_reviewed_contact(data):
    """A reviewed official contact excerpt can establish a studio's alternate domain."""
    review = data.get('contact_review', {})
    if review.get('kind') != 'official_business_contact':
        return web.verify_email(data['email'], data['contact_url'], data['website'], data['company'])
    email = data['email'].strip().lower()
    source = data['contact_url']
    domain = web.root_domain(web.host(data['website']))
    if web.root_domain(web.host(source)) != domain or not web.EMAIL_RE.fullmatch(email):
        raise ValueError('商务邮箱复核必须来自工作室官网')
    doc, final = web.page(source)
    quote = review.get('quote', '')
    compact = lambda value: re.sub(r'\s+', ' ', value).casefold().strip()
    if (web.root_domain(web.host(final)) != domain
            or email not in web.business_emails(doc)
            or web.score_email(email, web.root_domain(email.split('@')[-1])) < 0
            or len(quote) < 25 or len(quote) > 1200
            or compact(quote) not in compact(web.strip_tags(doc))
            or set(web.emails_in(quote)) != {email}
            or web.restricted_contact(quote)
            or not re.search(r'(?i)\b(contact|email|come through|enquiries)\b', quote)
            or not review.get('ownership_basis', '').strip()):
        raise ValueError('商务邮箱归属复核证据不完整')
    return final


def work_text(raw):
    # Portfolio images may carry the only published description of a work.
    class Descriptions(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.descriptions = []
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == 'meta' and attributes.get('name', '').lower() == 'description':
                self.descriptions.append(attributes.get('content', ''))
            if tag == 'img':
                alt = attributes.get('alt', '')
                if alt:
                    self.descriptions.append(alt)
    parser = Descriptions()
    parser.feed(raw)
    return web.strip_tags(raw) + '\n' + '\n'.join(parser.descriptions)


def prepare(data):
    account=data['account'];config.account(account)
    site=data['website'];source=data['contact_url'];work=data['work_url']
    domain=web.root_domain(web.host(site))
    if any(web.root_domain(web.host(u))!=domain for u in (source,work)):
        raise ValueError('合作证据必须来自工作室官网')
    email=data['email'].strip().lower()
    verified=verify_reviewed_contact(data)
    raw,final=web.page(work)
    text=work_text(raw)
    compact=lambda s:re.sub(r'\s+',' ',s).casefold().strip()
    quote=data['work_quote']
    if web.root_domain(web.host(final))!=domain or len(quote)<15 or compact(quote) not in compact(text):
        raise ValueError('具体作品原文未在官网核实')
    body=data['body'].strip();subject=data['subject'].strip()
    if len(body)<120 or not subject or data['work_name'].casefold() not in body.casefold():
        raise ValueError('合作邮件必须提到核实作品')
    greeting=data.get('greeting') or ('Hi '+data['company']+' team,')
    if not body.startswith(greeting):raise ValueError('称呼不一致')
    if data.get('name'):
        contact_raw,_=web.page(source)
        if compact(data['name']) not in compact(web.strip_tags(contact_raw)):
            raise ValueError('联系人姓名未在官网核实')
    p=dict(company=data['company'],customer_brand=data['company'],domain=domain,website=site,email=email,email_verified=True,email_source=verified,recipient_company=data['company'])
    lid=store.claim_prospect(account,p,source='designer_partnership',hold=True)
    if not lid:return {'status':'protected_duplicate','id':None}
    lead=store.lead(lid);d=lead['data'];lead.update(subject=subject,body=body)
    d['partnership_review']=dict(digest=digest(lead),email_verified=True,work_quote=quote,work_url=work,work_name=data['work_name'],contact_url=source,checked_at=time.time())
    if data.get('contact_review'):
        d['partnership_review']['contact_review'] = data['contact_review']
    d['plan']=dict(subject=subject,body=body)
    store.update(lid,status='ready',data=d,subject=subject,body=body)
    return {'status':'ready','id':lid}

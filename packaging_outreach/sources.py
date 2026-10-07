#!/usr/bin/env python3
"""Public HTTPS evidence parsing and exact source validation."""
import argparse, datetime as dt, hashlib, html, http.client, ipaddress, json, os
import re, socket, ssl, subprocess, sys, tempfile, selectors, signal, time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin

PROTOCOL = 'personal-mail.v1'
NOW = lambda: dt.datetime.now(dt.timezone.utc)
class Blocked(ValueError): pass

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
def host(url):
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise Blocked('Credential-free public HTTPS URL required')
    return u.hostname.lower().removeprefix('www.')

def same_official(company,a,b):
    # Match the existing new-app policy; region support must be reviewed separately.
    return host(a)==host(b)

class TextParser(HTMLParser):
    def __init__(self):super().__init__();self.hidden=0;self.text=[];self.mail=[];self.images=[]
    def handle_starttag(self,t,a):
        if t in ('script','style'):self.hidden+=1
        if t=='a':
            href=dict(a).get('href','')
            if href.lower().startswith('mailto:'):self.mail.append(href[7:].split('?')[0])
        attrs=dict(a)
        if t=='img' and attrs.get('src'):self.images.append(attrs['src'])
        if t=='meta' and attrs.get('property')=='og:image' and attrs.get('content'):self.images.append(attrs['content'])
    def handle_endtag(self,t):
        if t in ('script','style') and self.hidden:self.hidden-=1
    def handle_data(self,x):
        if not self.hidden:self.text.append(x)
def normalize(s):return re.sub(r'\s+',' ',html.unescape(s)).strip().lower()

def permitted_address(value,allow_synthetic=False):
    ip=ipaddress.ip_address(value)
    if ip.version==6 and ip in ipaddress.ip_network('::ffff:0:0:0/96'):
        ip=ipaddress.IPv4Address(int(ip)&0xffffffff)
    elif ip.version==6 and ip.ipv4_mapped:
        ip=ip.ipv4_mapped
    if ip.is_global:return True
    return bool(allow_synthetic and ip.version==4 and ip in ipaddress.ip_network('198.18.0.0/15'))

class PinnedHTTPS(http.client.HTTPSConnection):
    allow_synthetic=False
    def connect(self):
        answers=socket.getaddrinfo(self.host,self.port,type=socket.SOCK_STREAM)
        if not answers or any(not permitted_address(x[4][0],self.allow_synthetic) for x in answers):
            raise Blocked('Non-public DNS address; no fallback or network change')
        self.sock=socket.create_connection(answers[0][4][:2],self.timeout)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self.host)

def fetch_public(url,allowed,max_bytes=2000000,timeout=20,allow_synthetic=False):
    for _ in range(5):
        h=host(url)
        if h not in allowed:raise Blocked('Redirect left reviewed official host')
        u=urlsplit(url);conn=PinnedHTTPS(u.hostname,timeout=timeout,context=ssl.create_default_context())
        conn.allow_synthetic=allow_synthetic
        try:
            conn.request('GET',(u.path or '/')+('?' + u.query if u.query else ''),headers={'User-Agent':'Personal-Mail-Research/1.0','Accept':'text/html'})
            res=conn.getresponse()
            if res.status in (301,302,303,307,308):
                location=res.getheader('Location')
                if not location:raise Blocked('Redirect lacks location')
                url=urljoin(url,location);continue
            if res.status!=200 or 'text/html' not in res.getheader('Content-Type',''):
                raise Blocked('Official page unavailable/non-HTML')
            raw=res.read(max_bytes+1)
            if len(raw)>max_bytes:raise Blocked('Page byte budget exceeded')
            charset=res.headers.get_content_charset() or 'utf-8'
            p=TextParser();p.feed(raw.decode(charset,errors='replace'))
            return {'url':url,'text':' '.join(p.text),'mailto':p.mail,'images':[urljoin(url,x) for x in p.images],'sha256':hashlib.sha256(raw).hexdigest(),'checked_at':NOW().isoformat(),'provenance':'direct_public_https'}
        finally:conn.close()
    raise Blocked('Redirect limit exceeded')


def grounded_facts(candidate, product_text):
    proposed=candidate.get('product_facts',[])
    if not isinstance(proposed,list):return []
    anchors=proposed+[candidate.get('count_evidence_quote','')]
    found=[]
    for value in anchors:
        if isinstance(value,str) and value.strip() and len(value)<=500 and normalize(value) in normalize(product_text) and value not in found:
            found.append(value.strip())
    return sorted(found,key=len)[:3]

def verify_candidate(x,request,fetcher,allow_browser=False):
    policy=request.get('price_policy',{'required':True,'minimum':100,'currencies':['USD','EUR']})
    required=('company','brand_marker','recipient','company_url','email_source_url','product_evidence_url','product_facts')
    if not all(x.get(k) for k in required):raise Blocked('Incomplete candidate; missing official evidence/price')
    company=x['company'];recipient=x['recipient'].lower()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',recipient):raise Blocked('Invalid published email')
    exclusions=request.get('constraints',{})
    if recipient in exclusions.get('excluded_recipients',[]) or recipient.split('@')[1] in exclusions.get('excluded_domains',[]):raise Blocked('Excluded recipient/domain')
    urls=[x[k] for k in ('company_url','email_source_url','product_evidence_url')]
    if any(not same_official(company,urls[0],u) for u in urls[1:]):raise Blocked('Cross-host official evidence needs a separate reviewed policy')
    allowed={host(urls[0])};pages={}
    for u in urls:
        if u not in pages:pages[u]=fetcher(u,allowed)
    for p in pages.values():
        if p.get('provenance') not in ({'direct_public_https','official_subscription_browser_excerpt'} if allow_browser else {'direct_public_https'}) or not p.get('sha256'):raise Blocked('Model text is not independently fetched evidence')
        if host(p['url']) not in allowed:raise Blocked('Final source host mismatch')
        checked=dt.datetime.fromisoformat(p['checked_at'])
        if checked.tzinfo is None or not 0<=(NOW()-checked).total_seconds()<86400:raise Blocked('Evidence must be freshly verified')
    home,contact,product=[pages[u] for u in urls]
    if normalize(x['brand_marker']) not in normalize(home['text']) and (len(normalize(company))<4 or normalize(company) not in normalize(home['text'])):raise Blocked('Neither brand marker nor exact company name present on company page')
    published=re.findall(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}',contact['text']+' '+' '.join(contact.get('mailto',[])),re.I)
    if recipient not in [s.lower() for s in published]:raise Blocked('Recipient not exactly published')
    facts=grounded_facts(x,product['text'])
    if not facts:raise Blocked('One grounded product name or specification required')
    price=x.get('retail_price')
    if price is None and not policy.get('required'):
        validated_price=None
    else:
        validated_price=verify_price(price,x,product,policy)
    payload=dict(brand_marker=x['brand_marker'] if normalize(x['brand_marker']) in normalize(home['text']) else None,company_url=x['company_url'],email_source_url=contact['url'],checked_at=contact['checked_at'],facts=facts,product_facts=facts,public_emails=[recipient],email_evidence=[{'email':recipient,'source_url':contact['url'],'role':'published_business_contact; purchasing_authority_not_established'}],product_evidence_url=product['url'],retail_price=validated_price,purchase_intent='not_established',purchasing_authority='not_established',engineering_approved=False,source_origin=('official_subscription_public_browser' if allow_browser else 'direct_public_official_fetch'),source_evidence=[{k:p[k] for k in ('url','sha256','checked_at')} for p in pages.values()],inferences=[])
    return {'company':company,'recipient':recipient,'payload':payload}

def verify_price(price,x,product,policy):
    if not isinstance(price,dict):raise Blocked('Profile requires an official exact-SKU price')
    amount=price.get('amount');currency=price.get('currency');quote=price.get('source_quote','')
    if type(amount) not in (int,float) or not policy.get('minimum',0)<=amount<float('inf') or not isinstance(currency,str) or not re.fullmatch(r'[A-Z]{3}',currency) or (policy.get('currencies') and currency not in policy['currencies']):raise Blocked('Price does not meet configured exact-SKU policy; no guessed FX')
    if price.get('product_url')!=x['product_evidence_url'] or not quote or normalize(quote) not in normalize(product['text']):raise Blocked('Price source must be exact target SKU page and literal quote')
    token=r'(?<![\d.,])'+(str(int(amount))+r'(?:[.,]00)?' if amount==int(amount) else re.escape(f'{amount:.2f}').replace(r'\.',r'[.,]'))+r'(?![\d.,])'
    # Intentionally conservative: localized/comma prices require a reviewed parser.
    currency_present=bool(re.search(r'\b'+currency+r'\b',quote)) or (currency=='EUR' and '€' in quote) or (currency=='USD' and '$' in quote and 'USD' in product['text'])
    if not re.search(token,quote) or not currency_present:raise Blocked('Price amount/currency not present in exact quote')
    return dict(amount=amount,currency=currency,product_url=product['url'],checked_at=product['checked_at'],source_quote=quote)

"""Public website contact research. No mail, account access or outreach integration."""
from business_fit import evidence, assess
import functools
import copy
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from bs4 import BeautifulSoup
from contact_extract import contact_cards, prepare_visible_contacts, named_role_mentions
from contact_quality import phone_info, whatsapp_links, qualify, country_hint

ROOT = Path(__file__).resolve().parent
PORT = 18830
AGENT = 'DecisionFinder/0.1'
EMAIL = re.compile(r'[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I)
ROLE = re.compile(r'\b(C[.]?E[.]?O[.]?|C[.]?F[.]?O[.]?|chief financial officer|(?:international|commercial|corporate|business development|export|sales and marketing) director|founders?|co-founders?|owners?|president|managing director|(?:sales|marketing|export(?:s)?)\s*(?:[-–—]\s*)?director|director\s*(?:[-–—]\s*)?(?:of\s+)?(?:exports?|marketing|sales|operations|commercial|business development|sustainability)|procurement|purchasing|sourcing|supply chain|packaging|managing partner|general manager|head of (?:(?:legal|human rights|compliance|ethics|environment|social responsibility)\s*(?:,|&|and)\s*){0,3}(?:business|marketing|sales|exports?|procurement|purchasing|sourcing|operations|sustainability)|(?:sales|marketing|brand|exports?|business development|international sales)\s+manager|manager\s+(?:(?:dept\.?|department)\s+(?:of|pf)\s+)?(?:marketing|exports?|procurement|purchasing)|chief executive|chief growth officer|chief operating officer|chief commercial officer|vice president|operations director|säljchef|key account manager chef|einkauf|beschaffung|geschäftsführer|inhaber|achats|directeur|acquisti)\b|创始人|采购|总经理|董事长|^\s*(?:executive\s+)?director\s*$', re.I)
GENERIC = {'ceo','owner','director','founder','info','hello','contact','sales','support','admin','office','help','careers','press','marketing','customerservice','service','orders','privacy','accounts','ap','purchasing','procurement','ahoy','business','enquiries','inquiries','wholesale','trade','team','customers','customercare','customer.service','hr','care'}
LINK = re.compile(r'about|team|leadership|management|founder|contact|our-story|people|procurement|purchasing|supplier|products|private-label|packaging|impressum|kontakt|关于|团队|联系', re.I)
PHONE = re.compile(r'(?:\+\d{1,3}[\s.-]*(?:\(0\)[\s.-]*)?)(?:\d[\s().-]*){6,14}\d')

def phones(text):
    return sorted(set(m.strip(' .-') for m in PHONE.findall(text)))

def normalize_phone(phone):
    phone = phone.lstrip('/')
    return '+' + re.sub(r'\D', '', phone.replace('(0)', '')) if phone.startswith('+') else phone

def person_blocks(text, url, method):
    """Only associate a compact explicit name/title/phone/email block.

    A candidate must begin with a name and a relevant title; a second name or
    a second address/phone rejects it rather than mixing adjacent contacts.
    """
    from person_identity import plausible_person_name
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    found = []
    for i, name in enumerate(lines):
        if not plausible_person_name(name):continue
        if not re.fullmatch(r'[A-ZÀ-ÖØ-Þ][\wÀ-ž\x27.-]+(?: [A-ZÀ-ÖØ-Þ][\wÀ-ž\x27.-]+){1,3}', name): continue
        if i+1 >= len(lines) or not ROLE.search(lines[i+1]): continue
        tail = []
        for line in lines[i+1:i+7]:
            if not (ROLE.search(line) or re.search(r'authorized signatory|prokuristin|^(?:senior )?tea taster$',line,re.I) or re.fullmatch(r'(?:(?:Tel\.?|Phone|Tél\.?|Mobile|Mob\.?|Cell|Mobil|电话|手机)\s*:?\s*)?\+?[\d ()-]{7,25}',line,re.I) or EMAIL.fullmatch(line)):
                break
            tail.append(line)
        block = '\n'.join(tail)
        addresses = emails(block)
        numbers = []
        for line in tail:
            value=re.sub(r'^(?:Tel\.?|Phone|Tél\.?|Mobile|Mob\.?|Cell|Mobil|电话|手机)\s*:?\s*','',line,flags=re.I)
            if re.fullmatch(r'\+?[\d ()-]{7,25}',value) and 7<=len(re.sub(r'\D','',value))<=15:
                numbers.append(value)
        if len(addresses) != 1 or is_role(addresses[0]) or len(numbers) > 1: continue
        found.append({'name':name, 'title':lines[i+1], 'email':addresses[0], 'phone':normalize_phone(numbers[0]) if numbers else '', 'phone_raw':numbers[0] if numbers else '', 'phone_kind':'联系人条目所列办公电话；接通情况未验证', 'source':url, 'status':method, 'evidence':name+'\n'+block})
    return found

def supplemental(raw, source):
    p = urllib.parse.urlsplit(source)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:
        raise ValueError('请填写可核对的官网来源链接。')
    if not isinstance(raw,str) or len(raw)>100000: raise ValueError('补查文本过长')
    people = person_blocks(raw,source,'人工补查文本提取；来源真实性需核对')
    return {'website':source,'people':people,'emails':[],'phones':[], 'clues':[], 'pages':[], 'errors':[], 'note':'这是人工补查文本解析，未自动访问来源；不等于已验证邮箱可投递、电话可接通或对方负责包装采购。', 'mode':'supplemental_text'}

@functools.lru_cache(maxsize=256)
def confirm_public_dns(name):
    # This Mac's proxy returns benchmark-range Fake-IP addresses. Confirm the
    # original hostname against public DNS before using that local proxy route.
    from browser_transport import budget_remaining
    req = urllib.request.Request('https://cloudflare-dns.com/dns-query?' + urllib.parse.urlencode({'name':name,'type':'A'}), headers={'Accept':'application/dns-json'})
    with urllib.request.urlopen(req,timeout=budget_remaining(8)) as r:
        records=json.loads(r.read(65536)).get('Answer',[])
    addresses=[ipaddress.ip_address(x['data']) for x in records if x.get('type')==1]
    if not addresses or any(not a.is_global for a in addresses):
        raise ValueError('公开 DNS 未确认此域名指向公网。')

def transport_ip(raw):
    address=ipaddress.ip_address(raw)
    if address.version==6:
        if address.ipv4_mapped is not None:return address.ipv4_mapped
        # IPv4-translated addresses supplied by this host's network proxy.
        if address in ipaddress.ip_network('::ffff:0:0:0/96'):
            return ipaddress.IPv4Address(address.packed[-4:])
    return address

def public_url(url):
    from browser_transport import check_budget
    check_budget()
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('请输入普通的公司官网地址（http/https）。')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    check_budget()
    ips=[transport_ip(a[4][0]) for a in addresses]
    if ips and all(a.version==4 and a in ipaddress.ip_network('198.18.0.0/15') for a in ips):
        try: ipaddress.ip_address(p.hostname)
        except ValueError: confirm_public_dns(p.hostname)
        else: raise ValueError('不接受代理内部 IP，请填写官网域名。')
    elif not ips or any(not a.is_global for a in ips):
        raise ValueError('该地址未解析到公开互联网；未访问本机或内网。')
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))

def host(url):
    return (urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.')

class OfficialShopRedirect(ValueError):
    def __init__(self,source,target,status):
        super().__init__('官网首页跳转至其公开 shop 子域，须重新核对目标抓取规则。')
        self.source=source;self.target=target;self.http_status=status


def official_shop_target(source,target):
    """Only the exact HTTPS homepage's own shop child; no arbitrary sites/paths."""
    try:
        a,b=urllib.parse.urlsplit(source),urllib.parse.urlsplit(target)
        if any(p.scheme!='https' or p.username is not None or p.password is not None or p.port not in (None,443)
               or p.path not in ('','/') or p.query or p.fragment for p in (a,b)):return False
        return bool(a.hostname and b.hostname and b.hostname.lower()=='shop.'+host(source)
                    and not host(source).startswith('shop.'))
    except ValueError:return False


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, domain):
        self.domain = domain
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if host(newurl) != self.domain:
            from browser_transport import LOCAL
            if (getattr(LOCAL,'canonical_bootstrap',False) and host(req.full_url)==self.domain
                    and code in (301,302,303,307,308) and official_shop_target(req.full_url,newurl)):
                public_url(newurl)
                # Never follow here. The website scheduler must check cooldown,
                # public DNS and the new host's robots before its first request.
                raise OfficialShopRedirect(req.full_url,newurl,code)
            raise ValueError('页面跳转到了另一个域名，已跳过。')
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch_plain(url, domain):
    from browser_transport import budget_remaining,check_budget
    public_url(url)
    if host(url) != domain:
        raise ValueError('仅查看输入官网的同域页面。')
    req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain,application/xhtml+xml'})
    with urllib.request.build_opener(Redirects(domain)).open(req, timeout=budget_remaining(15)) as r:
        if r.headers.get_content_type() not in ('text/html', 'text/plain', 'application/xhtml+xml'):
            raise ValueError('不是可读取的网页。')
        content = r.read(2_000_001)
        check_budget()
        if len(content) > 2_000_000:
            raise ValueError('页面超过读取上限。')
        return content.decode(r.headers.get_content_charset() or 'utf-8', errors='replace')

def fetch(url, domain):
    from pipeline_core.fetcher import read
    def alternate(target):
        # Preserve Radar's established no-browser-on-403 safety contract.
        raise urllib.error.HTTPError(target,403,'BLOCKED: manual review required',{},None)
    body,_=read(url,lambda target:(_fetch_uncached(target,domain),target),refresh=True,alternate=alternate)
    return body

def _fetch_uncached(url, domain):
    from browser_transport import fetch_browser, LOCAL,check_budget,budget_remaining,budget_wait
    from rate_limits import check,observe
    check_budget()
    check(url)
    # Once normal browser transport succeeds, reuse that transport for this
    # research only. A continuing 429 stops the whole domain query.
    if getattr(LOCAL, 'blocked', False):
        raise ValueError('网站仍在限流，本轮已停止读取该域名')
    from browser_transport import installed_browser_available
    if getattr(LOCAL, 'browser_mode', False) or (not url.split('?')[0].endswith('/robots.txt') and installed_browser_available()):
        return fetch_browser(url, domain)
    try: return fetch_plain(url, domain)
    except urllib.error.HTTPError as e:
        if e.code != 429: raise
        from email.utils import parsedate_to_datetime
        retry=e.headers.get('Retry-After','10')
        try: delay=max(0,int(retry))
        except (TypeError,ValueError):
            try: delay=max(0,parsedate_to_datetime(retry).timestamp()-time.time())
            except (TypeError,ValueError,OverflowError):
                LOCAL.blocked=True
                error=ValueError('网站限流且重试时间无法确认，本轮停止')
                error.http_status=429
                raise error
        limited=observe(url,delay,e.headers.get('Server',''))
        if delay>60:
            LOCAL.blocked=True
            raise limited
        if getattr(LOCAL,'deadline',None) is not None or getattr(LOCAL,'cancel',None) is not None:
            if budget_remaining() is not None and delay>=budget_remaining():
                LOCAL.blocked=True
                raise limited
            budget_wait(max(1,delay))
        else:time.sleep(max(1,delay))
    except (TimeoutError,socket.timeout):pass
    except urllib.error.URLError as e:
        if not isinstance(e.reason,(TimeoutError,socket.timeout)):raise
    result=fetch_browser(url,domain)
    LOCAL.browser_mode=True
    return result

def emails(text):
    return sorted(set(m.rstrip('.') for m in EMAIL.findall(text)))

def is_role(address):
    from person_identity import press_mailbox
    local = address.split('@')[0].lower()
    return press_mailbox(address) or local in GENERIC or local in {'kontakt', 'contacto', 'contatti', 'contato'} or local.startswith(('info.', 'sales.', 'support.'))

def contact_priority(url):
    # Match the path only: a brand such as teamtea must not make every product
    # URL look like a team page.
    path=urllib.parse.urlsplit(url).path.lower()
    if re.search(r'/(?:products?|collections?|blogs?)/',path): return 4
    if re.search(r'contact|kontakt|get-in-touch|reach-us|procurement|purchasing|联系我们',path): return 0
    from contact_routes import team_priority
    if team_priority(url) is not None: return 1
    if re.search(r'policies|terms|privacy|legal',path): return 2
    return 3

def extract(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    people, contacts, snippets = [], [], []
    region = country_hint(soup)
    from whatsapp_attribution import publication_scopes,attributed_channels
    prepare_visible_contacts(soup)
    wa_scopes=publication_scopes(soup,url,region)
    from structured_contacts import extract_people,person_whatsapp_scopes
    people.extend(extract_people(html,url,ROLE,is_role,region))
    wa_scopes.extend(person_whatsapp_scopes(people,url))
    for tag in soup(['script', 'style', 'noscript', 'svg']): tag.decompose()
    prepare_visible_contacts(soup)
    from signed_contacts import signed_contacts
    from public_contact_blocks import extract_public_blocks
    people.extend(signed_contacts(soup,url,ROLE,emails,is_role))
    people.extend(extract_public_blocks(soup,url,ROLE,emails,is_role))
    people.extend(contact_cards(soup,url,ROLE,emails,is_role))
    people.extend(named_role_mentions(soup,url))
    people.extend(person_blocks(soup.get_text('\n',strip=True),url,'官网连续联系人条目提取；可查看原文'))
    visible = soup.get_text(' ', strip=True)
    all_emails = set(emails(visible))
    for a in soup.select('a[href]'):
        if a['href'].lower().startswith('mailto:'):
            all_emails.update(emails(urllib.parse.unquote(a['href'].split('?')[0])))
    for address in sorted(all_emails):
        contacts.append({'email': address, 'kind': '公司通用邮箱' if is_role(address) else '公开邮箱；归属人待核实', 'source': url})
    # Keep evidence fragments, never infer that nearby names own an email.
    for tag in soup.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'article', 'section', 'div']):
        text = tag.get_text(' ', strip=True)
        if 5 < len(text) <= 400 and ROLE.search(text):
            if any(len(c.get_text(' ', strip=True)) > 5 and ROLE.search(c.get_text(' ', strip=True)) for c in tag.find_all(['p','li','h1','h2','h3','h4','div'])):
                continue
            if text not in [s['text'] for s in snippets]: snippets.append({'text': text, 'source': url})
    links = []
    for a in soup.select('a[href]'):
        candidate = urllib.parse.urljoin(url, a['href']).split('#')[0]
        if host(candidate) == host(url) and LINK.search(a.get_text(' ', strip=True) + ' ' + urllib.parse.urlsplit(candidate).path):
            links.append(candidate)
    links=list(dict.fromkeys(u for u in links if urllib.parse.urlsplit(u).scheme in ('http','https') and not re.search(r'about-rewards|cart|checkout|login|wishlist|account|customer_authentication',u,re.I)))
    links.sort(key=contact_priority)
    for person in people:
        owned,_=attributed_channels(wa_scopes,person.get('name',''),person.get('email',''),identity_verified=bool(person.get('name') and person.get('title')),email_verified=bool(person.get('email')))
        proven=person.get('explicit_whatsapp',[]) if person.get('signed_contact') else []
        person['explicit_whatsapp']=list({(w.get('url',''),w.get('phone',''),w.get('source','')):w for w in proven+owned}.values())
        person['country_hint'] = region
        if region: person['country_source'] = url
    from person_identity import plausible_person_name
    people=[p for p in people if plausible_person_name(p.get('name',''))]
    for person in people:
        decoding=[dict(item,source=url) for item in soup.__dict__.get('_ur_email_decodings',[]) if item.get('email','').casefold()==person.get('email','').casefold()]
        if decoding:person['email_decodings']=decoding
    return people, contacts, snippets[:30], links

from pipeline_events import measured as pipeline_measured

@pipeline_measured('verify')
def research(raw,cancel=None,max_seconds=45,on_update=None,core_first=False,name_email_only=False,email_only=False):
    from request_budget import request_scope
    with request_scope(seconds=max_seconds,cancel=cancel):
        return _research(raw,cancel=cancel,max_seconds=max_seconds,on_update=on_update,core_first=core_first,name_email_only=name_email_only,email_only=email_only)

def _research(raw,cancel=None,max_seconds=45,on_update=None,core_first=False,name_email_only=False,email_only=False):
    from request_budget import request_scope
    from browser_transport import reset_budget
    reset_budget()
    cancel=cancel or threading.Event()
    began=time.monotonic()
    deadline=began+max(0,float(max_seconds))
    fetch_attempts=0
    def read_page(url,domain):
        nonlocal fetch_attempts
        fetch_attempts+=1
        return fetch(url,domain)
    def publish():
        from contact_progress import mark_progress
        result['checked_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        result['elapsed_seconds']=round(time.monotonic()-began,3)
        result['website_fetch_attempts']=fetch_attempts
        mark_progress(result)
        if on_update:
            on_update(assess(copy.deepcopy(result)))
    if cancel.is_set():raise ValueError("查询已停止")
    if not isinstance(raw, str) or not raw.strip(): raise ValueError('请填写公司官网。')
    input_url=raw.strip() if '://' in raw else 'https://'+raw.strip()
    from rate_limits import check as check_cooldown
    check_cooldown(input_url)
    start = public_url(input_url)
    domain = host(start)
    origin = urllib.parse.urlsplit(start)
    robots_url = urllib.parse.urlunsplit((origin.scheme, origin.netloc, '/robots.txt', '', ''))
    from robots_rules import read_robots
    try:
        # Failure to confirm rules ends the attempt; a timeout is never a bypass.
        with request_scope(seconds=8 if core_first else max_seconds,cancel=cancel):
            robot,robots_status=read_robots(urllib.parse.urlunsplit((origin.scheme,origin.netloc,'','','')),domain,read_page)
    except Exception as e:
        if getattr(e,'http_status',None)==429:raise
        raise ValueError('无法读取官网抓取规则：'+str(e))
    result = {'website': start, 'people': [], 'emails': [], 'phones': [], 'whatsapp': [], 'business_evidence': [], 'clues': [], 'pages': [], 'errors': [], 'note': '公开展示不等于邮箱可投递或电话可接通，也不代表当前采购需求。没有发送邮件或拨打电话。最多查看 12 个同域页面；姓名、职位及具名工作邮箱齐全才计入合格客户。手机与 WhatsApp 单独核对。'}
    from contact_routes import choose_contact_routes,guessed_contact_routes,is_contact_url,published_contact_children,published_support_route,published_locale_entry
    queue, seen = [start], set()
    support_followed=False
    locale_followed=False
    contact_targets={start} if is_contact_url(start) else set()
    result.update(read_strategy='contact_first',contact_pages=[],contact_people=[])
    result['note']+=' 优先查看Contact/联系我们；公开联系人线索数量不代表员工或客户总数。'
    source_scopes={}
    supplemented=False
    if email_only:
        result['read_strategy']='email_first';result['discovery_steps']=[]
        result['note']='找到公开来源邮箱即可结束；姓名及其他渠道仅保留直接观察到的信息。公开邮箱不等于可投递或有采购意向。未发送邮件。'
    while (queue or (email_only and not supplemented)) and len(seen) < 12 and time.monotonic() < deadline and not cancel.is_set():
        if email_only and not supplemented and (not queue or len(seen)>=2):
            supplemented=True
            from email_discovery import discover_sitemap,search_routes
            extra=[]
            for label,operation,seconds in [('sitemap',lambda:discover_sitemap(start,robot),5),('search',lambda:search_routes(start),9)]:
                tick=time.monotonic()
                try:
                    with request_scope(seconds=seconds,cancel=cancel):urls=operation()
                    extra.extend(u for u in urls if u not in seen)
                    if label=='search':
                        from browser_transport import LOCAL
                        result['search_diagnostics']=getattr(LOCAL,'search_diagnostics',{})
                    result['discovery_steps'].append(dict(stage=label,urls=urls,seconds=round(time.monotonic()-tick,2)))
                except Exception as error:
                    result['discovery_steps'].append(dict(stage=label,error=str(error)[:180],seconds=round(time.monotonic()-tick,2)))
                    if getattr(error,'http_status',None)==429:
                        result['errors'].append(dict(url=start,error=str(error),http_status=429));queue=[];break
            else:
                contact_targets.update(extra);queue=list(dict.fromkeys(extra+queue))
            if not queue:break
        url = queue.pop(0)
        if url in seen: continue
        seen.add(url)
        if not robot.can_fetch(AGENT, url):
            result['errors'].append({'url': url, 'error': '官网 robots.txt 不允许读取'})
            continue
        try:
            # The home page is only a short navigation scout; reserve time
            # for the site's published Contact destination and one team page.
            from browser_transport import LOCAL
            previous_bootstrap=getattr(LOCAL,'canonical_bootstrap',False)
            LOCAL.canonical_bootstrap=bool(url==start and not result['pages'] and not result.get('canonical_website'))
            try:
                from browser_transport import installed_browser_available
                page_seconds=12 if email_only else 24 if installed_browser_available() else (10 if url==start and url not in contact_targets else 12)
                with request_scope(seconds=page_seconds,cancel=cancel):
                    html = read_page(url, domain)
            finally:LOCAL.canonical_bootstrap=previous_bootstrap
            people, contacts, clues, links = extract(html, url)
            if name_email_only:
                from name_email_lookup import contacts_from_html
                people=contacts_from_html(html,url,existing_people=people)
            from contact_products import annotate_people
            people=annotate_people(people)
            routes=list(dict.fromkeys(published_contact_children(html,url)+choose_contact_routes(html,url)))
            if email_only:
                from email_discovery import page_routes
                routes=list(dict.fromkeys(routes+page_routes(html,url)))
            contact_targets.update(routes)
            if url in contact_targets or is_contact_url(url):
                result['contact_pages'].append(url)
                result['contact_people'].extend({'name':p['name'],'title':p.get('title',''),'email':p.get('email',''),'source':url} for p in people)
            result['business_evidence'].extend(evidence(html, url))
            soup = BeautifulSoup(html,'html.parser')
            from whatsapp_attribution import publication_scopes
            prepare_visible_contacts(soup)
            source_scopes[url]=publication_scopes(soup,url,country_hint(soup))
            result['whatsapp'].extend(whatsapp_links(soup, url))
            for tag in soup(['script','style','noscript']): tag.decompose()
            from public_company_contacts import public_phones
            result['phones'].extend(public_phones(soup,url,people))
            result['pages'].append(url)
            result['people'].extend(people)
            result['emails'].extend(contacts)
            result['clues'].extend(clues)
            from official_join import join_official_people
            result['people']=join_official_people(result['people'],source_scopes,ROLE,is_role)
            qualify(result, is_role)
            publish()
            if email_only and result['emails']:
                result['note'] += ' 已找到官网公开邮箱，结束本轮；不推断收件人姓名或可投递性。'
                break
            if name_email_only:
                from name_email_lookup import qualify_report
                if qualify_report(result)['qualified_people']:
                    result['note'] += ' 已找到姓名与具名邮箱，不再补齐选填渠道。'
                    break
            if core_first and result['core_people']:
                result['note'] += ' 已找到姓名、职位、工作邮箱及公开商务电话，官网阶段提前结束；WhatsApp 为可选字段。'
                break
            if result['complete_people']:
                result['note'] += ' 已找到姓名、职位、工作邮箱、手机及公开 WhatsApp 链接齐全的联系人，提前结束查询。'
                break
            locale_links=[]
            if not locale_followed and not routes and not result['useful_partial']:
                locale_links=published_locale_entry(html,url)
                if locale_links:
                    locale_followed=True
                    result['locale_entry']=locale_links[0]
            contact_links=routes or (guessed_contact_routes(html,start) if url==start and not contact_targets and not locale_links else [])
            contact_targets.update(contact_links)
            team_links=[u for u in links if contact_priority(u)==1 and not re.search(r'global-presence|core-values|process|csr|sustainab|careers|polic',u,re.I)]
            from contact_routes import team_priority
            team_links.sort(key=lambda u:(team_priority(u),len(u)))
            follow=locale_links+contact_links+team_links[:1]
            if not support_followed and url in contact_targets and not result['useful_partial']:
                support=published_support_route(html,url)
                if support:
                    support_followed=True
                    follow+=support
                    contact_targets.update(support)
            for u in follow:
                if u not in seen and u not in queue:queue.append(u)
            queue.sort(key=lambda u:(0 if u in contact_targets else 1,contact_priority(u)))
        except Exception as e:
            if isinstance(e,OfficialShopRedirect) and url==start and not result['pages'] and not result.get('canonical_website'):
                result['canonical_website']=e.target
                result['redirects']=[{'from':e.source,'to':e.target,'http_status':e.http_status}]
                try:
                    check_cooldown(e.target)
                    target=public_url(e.target);target_origin=urllib.parse.urlsplit(target)
                    with request_scope(seconds=8 if core_first else max_seconds,cancel=cancel):
                        target_robot,_=read_robots(urllib.parse.urlunsplit((target_origin.scheme,target_origin.netloc,'','','')),host(target),read_page)
                    start=target;domain=host(target);robot=target_robot
                    queue=[target];contact_targets=set()
                    publish()
                    continue
                except Exception as target_error:
                    from rate_limits import details
                    failure={'url':e.target,'error':'业务子域规则核对未完成：'+str(target_error)[:180]}
                    failure.update(details(target_error))
                    status=getattr(target_error,'http_status',getattr(target_error,'code',None))
                    if isinstance(status,int):failure['http_status']=status
                    if status==429:
                        from rate_limits import share_observed_cooldown
                        share_observed_cooldown(input_url,e.target)
                    result['errors'].append(failure);publish();break
            failure={'url':url,'error':str(e)[:220]}
            status=getattr(e,'http_status',getattr(e,'code',None))
            if isinstance(status,int):failure['http_status']=status
            if hasattr(e,'retry_after_seconds'):failure['retry_after_seconds']=e.retry_after_seconds
            from rate_limits import details
            failure.update(details(e))
            result['errors'].append(failure)
            from browser_transport import LOCAL
            if status==429:
                if result.get('canonical_website') and host(url)==host(result['canonical_website']):
                    from rate_limits import share_observed_cooldown
                    share_observed_cooldown(input_url,result['canonical_website'])
                publish();break
            if url==start and not contact_targets and not is_contact_url(start):
                fallback=guessed_contact_routes('',start);contact_targets.update(fallback);queue=fallback+[u for u in queue if u not in fallback]
                # A slow homepage must not prevent an independent attempt at
                # the conventional contact endpoint. A 429 remains a stop.
            if getattr(LOCAL,'blocked',False): break
            publish()
        if queue and time.monotonic()<deadline and not cancel.is_set():time.sleep(0.1)
    result['contact_people']=list({(p['name'].casefold(),p['source']):p for p in result['contact_people']}.values())
    result['contact_published_name_count']=len({p['name'].casefold() for p in result['contact_people']})
    result['elapsed_seconds']=round(time.monotonic()-began,3)
    result['cancelled']=cancel.is_set()
    result['budget_exhausted']=bool(queue and not result.get('complete_people') and time.monotonic()>=deadline)
    if result['cancelled']:result['note']+=' 查询已停止，保留已读取的证据。'
    elif result['budget_exhausted']:result['note']+=' 官网读取预算已到，未读页面及缺失字段仍待补查。'
    for key in ('people', 'emails', 'phones', 'whatsapp', 'clues', 'business_evidence'):
        result[key] = list({json.dumps(item, sort_keys=True): item for item in result[key]}.values())
    result['checked_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    from contact_progress import mark_progress
    result['website_fetch_attempts']=fetch_attempts
    return assess(mark_progress(qualify(result, is_role)))

gate = threading.BoundedSemaphore(1)

def trusted_quick_report(data):
    """Reuse only the server's report for this exact site, never submitted fields."""
    identifier=data.get('source_job_id')
    if not identifier:return None
    from quick_research import get_job,cache_key
    job=get_job(identifier)
    report=job.get('report')
    if job['status']!='done' or not report:
        raise ValueError('官网快读尚未完成或没有可复用报告。')
    if cache_key(report.get('website',''))!=cache_key(data.get('website','')):
        raise ValueError('官网报告与补查地址不一致。')
    return report

class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_OPTIONS(self):
        from extension_api import dispatch
        if dispatch(self):return
        self.send_json({"error":"Not found"},404)
    def do_GET(self):
        if self.path.startswith("/api/extension/"):
            from extension_api import dispatch
            if dispatch(self):return
        if self.path.startswith('/benchmark-large10/'):
            name=self.path[len('/benchmark-large10/'):]
            allowed={'retest-diagnosis/report.html':'text/html; charset=utf-8','retest-diagnosis/summary.json':'application/json; charset=utf-8','retest-diagnosis/contacts.csv':'text/csv; charset=utf-8','retest-diagnosis/application-results.png':'image/png','retest-diagnosis/report-preview.png':'image/png','report.html':'text/html; charset=utf-8','summary.json':'application/json; charset=utf-8','contacts.csv':'text/csv; charset=utf-8','baseline/report.html':'text/html; charset=utf-8','baseline/summary.json':'application/json; charset=utf-8','baseline/contacts.csv':'text/csv; charset=utf-8'}
            allowed.update({'retest-oct17/'+file:mime for file,mime in {'known-contacts.csv':'text/csv; charset=utf-8','report.html':'text/html; charset=utf-8','summary.json':'application/json; charset=utf-8','contacts.csv':'text/csv; charset=utf-8','application-results.png':'image/png','report-preview.png':'image/png'}.items()})
            allowed.update({'chrome-plugin/'+file:mime for file,mime in {'report.html':'text/html; charset=utf-8','summary.json':'application/json; charset=utf-8','contacts.csv':'text/csv; charset=utf-8','real-toolbar.png':'image/png','report-preview.png':'image/png'}.items()})
            allowed.update({'components-retest/'+file:mime for file,mime in {'report.html':'text/html; charset=utf-8','summary.json':'application/json; charset=utf-8','results.json':'application/json; charset=utf-8','contacts.csv':'text/csv; charset=utf-8'}.items()})
            allowed.update({'name-email-retest/'+file:mime for file,mime in {'report.html':'text/html; charset=utf-8','summary.json':'application/json; charset=utf-8','results.json':'application/json; charset=utf-8','results-query-original.json':'application/json; charset=utf-8','contacts.csv':'text/csv; charset=utf-8'}.items()})
            allowed.update({'sequential/'+file:mime for file,mime in {'report.html':'text/html; charset=utf-8','contacts.csv':'text/csv; charset=utf-8','summary.json':'application/json; charset=utf-8'}.items()})
            if name not in allowed or not (ROOT/'benchmark-large10'/name).is_file():return self.send_json({'error':'报告文件不存在'},404)
            raw=(ROOT/'benchmark-large10'/name).read_bytes()
            self.send_response(200);self.send_header('Content-Type',allowed[name]);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if self.path.startswith('/benchmark-guka/'):
            name=self.path[len('/benchmark-guka/'):]
            allowed={'automatic-team/report.html':'text/html; charset=utf-8','automatic-team/summary.json':'application/json; charset=utf-8','automatic-team/contacts.csv':'text/csv; charset=utf-8','report.html':'text/html; charset=utf-8','summary.json':'application/json; charset=utf-8','researched-team.csv':'text/csv; charset=utf-8'}
            if name not in allowed or not (ROOT/'benchmark-guka'/name).is_file():return self.send_json({'error':'报告文件不存在'},404)
            raw=(ROOT/'benchmark-guka'/name).read_bytes()
            self.send_response(200);self.send_header('Content-Type',allowed[name]);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if self.path.startswith('/benchmark10-new/'):
            name=self.path[len('/benchmark10-new/'):]
            allowed={'contact-first-final/report.html':'text/html; charset=utf-8','contact-first-final/summary.json':'application/json','contact-first-final/verified-contacts.csv':'text/csv; charset=utf-8','contact-first-pilot/report.html':'text/html; charset=utf-8','optimized-v2/report.html':'text/html; charset=utf-8','optimized-v2/summary.json':'application/json','optimized-v2/verified-contacts.csv':'text/csv; charset=utf-8','optimized-v2/rea-batch-evidence.json':'application/json','batch10-live/report.html':'text/html; charset=utf-8','batch10-live/summary.json':'application/json','batch10-live/verified-contacts.csv':'text/csv; charset=utf-8','parallel-v1/report.html':'text/html; charset=utf-8','parallel-v1/summary.json':'application/json','parallel-v1/rea-batch-evidence.json':'application/json','channels-v2/report.html':'text/html; charset=utf-8','channels-v2/summary.json':'application/json','channels-v2/rea-app-evidence.json':'application/json','automatic/report.html':'text/html; charset=utf-8','automatic/summary.json':'application/json','automatic/rea-app-evidence.json':'application/json','report.html':'text/html; charset=utf-8','summary.json':'application/json','black-tea-evidence.json':'application/json'}
            if name not in allowed or not (ROOT/'benchmark10-new'/name).is_file():return self.send_json({'error':'报告尚未生成或文件不存在'},404)
            raw=(ROOT/'benchmark10-new'/name).read_bytes()
            self.send_response(200);self.send_header('Content-Type',allowed[name]);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        reports={'whatsapp-three/report.html':'text/html; charset=utf-8','whatsapp-three/summary.json':'application/json','whatsapp-three/official-contact-evidence.json':'application/json','whatsapp-three/paul-linkedin-evidence.json':'application/json','whatsapp-three/lauren-linkedin-evidence.json':'application/json','whatsapp-three/paul-public-post-evidence.json':'application/json','whatsapp/report.html':'text/html; charset=utf-8','whatsapp/summary.json':'application/json','whatsapp/contacts.csv':'text/csv; charset=utf-8','whatsapp/rea-contact-evidence.json':'application/json','whatsapp/rea-business-contact-evidence.json':'application/json','multisource/report.html':'text/html; charset=utf-8','multisource/summary.json':'application/json','multisource/contacts.csv':'text/csv; charset=utf-8','multisource/rea-actual-terms-evidence.json':'application/json','report.html':'text/html; charset=utf-8','summary.json':'application/json','contacts.csv':'text/csv; charset=utf-8','rea-teamtea-runtime.json':'application/json','rea-salt-runtime.json':'application/json'}
        if self.path.startswith('/benchmark20/'):
            name=self.path[len('/benchmark20/'):]
            if name not in reports or not (ROOT/'benchmark20'/name).is_file():return self.send_json({'error':'报告尚未生成或文件不存在'},404)
            raw=(ROOT/'benchmark20'/name).read_bytes()
            self.send_response(200);self.send_header('Content-Type',reports[name]);self.send_header('Content-Length',str(len(raw)))
            if name.endswith('.csv'):self.send_header('Content-Disposition','attachment; filename="user-radar-benchmark-contacts.csv"')
            self.end_headers();self.wfile.write(raw);return
        if self.path.startswith('/api/batch/'):
            from batch_jobs import get_batch
            try:return self.send_json(get_batch(self.path.rsplit('/',1)[-1]))
            except ValueError as e:return self.send_json({'error':str(e)},404)
        if self.path.startswith('/api/team-enrichment/'):
            from team_enrichment import get_team
            try:return self.send_json(get_team(self.path.rsplit('/',1)[-1]))
            except ValueError as e:return self.send_json({'error':str(e)},404)
        if self.path.startswith('/api/discovery/'):
            from ai_discovery import get_job
            try: return self.send_json(get_job(self.path.rsplit('/',1)[-1]))
            except ValueError as e: return self.send_json({'error':str(e)},404)
        if self.path.startswith('/api/research-job/'):
            from quick_research import get_job
            try:return self.send_json(get_job(self.path.rsplit('/',1)[-1]))
            except ValueError as e:return self.send_json({'error':str(e)},404)
        if self.path == '/api/health':
            return self.send_json({'app':'decision-finder','ok':True})
        if self.path in ('/ui.js','/team.js','/discovery.js','/batch.js','/quick.js'):
            raw = (ROOT/self.path.lstrip('/')).read_bytes()
            self.send_response(200); self.send_header('Content-Type','application/javascript; charset=utf-8'); self.end_headers(); self.wfile.write(raw)
            return
        if self.path != '/': return self.send_json({'error':'Not found'},404)
        raw = (ROOT/'index.html').read_bytes()
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.path.startswith("/api/extension/"):
            from extension_api import dispatch
            if dispatch(self):return
        if self.path not in ('/api/research','/api/research-start','/api/research-stop','/api/supplemental','/api/discover','/api/discovery-stop','/api/batch','/api/batch-stop','/api/team-enrichment','/api/team-enrichment-stop'): return self.send_json({'error':'Not found'},404)
        if self.headers.get('Origin') != f'http://127.0.0.1:{PORT}' or self.headers.get('Content-Type') != 'application/json':
            return self.send_json({'error':'仅接受本地页面请求'},403)
        gated=self.path in ('/api/research','/api/supplemental')
        if gated and not gate.acquire(blocking=False): return self.send_json({'error':'已有查询进行中，请等待完成'},429)
        try:
            size = int(self.headers.get('Content-Length',0))
            if not 0 < size <= 120000: raise ValueError('请求大小无效')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('请求格式无效')
            if self.path == '/api/research-start':
                from quick_research import start_job
                return self.send_json(start_job(data.get('url',''),refresh=data.get('refresh') is True))
            if self.path == '/api/research-stop':
                from quick_research import stop_job
                return self.send_json(stop_job(data.get('id','')))
            if self.path == '/api/batch':
                from batch_jobs import start_batch
                return self.send_json(start_batch(data.get('websites'),mode=data.get('mode','team')))
            if self.path == '/api/batch-stop':
                from batch_jobs import stop_batch
                return self.send_json(stop_batch(data.get('id','')))
            if self.path == '/api/team-enrichment':
                from team_enrichment import start_team
                if data.get('core_only') is True:
                    from rate_limits import check as check_cooldown
                    check_cooldown(data.get('website',''))
                    return self.send_json(start_team(data.get('website',''),core_only=True,official_report=trusted_quick_report(data)))
                return self.send_json(start_team(data.get('website','')))
            if self.path == '/api/team-enrichment-stop':
                from team_enrichment import stop_team
                return self.send_json(stop_team(data.get('id','')))
            if self.path == '/api/discover':
                from ai_discovery import start_job
                if data.get('core_only') is True:
                    from rate_limits import check as check_cooldown
                    check_cooldown(data.get('website',''))
                    return self.send_json(start_job(data.get('idea',''),data.get('website',''),core_only=True,official_report=trusted_quick_report(data)))
                return self.send_json(start_job(data.get('idea',''),data.get('website','')))
            if self.path == '/api/discovery-stop':
                from ai_discovery import stop_job
                return self.send_json(stop_job(data.get('id','')))
            self.send_json(supplemental(data.get('text',''),data.get('url','')) if self.path=='/api/supplemental' else research(data.get('url','')))
        except Exception as e:
            from rate_limits import RateLimited,details
            self.send_json({'error':str(e),'error_metadata':details(e)},429 if isinstance(e,RateLimited) else 400)
        finally:
            if gated:gate.release()

if __name__ == '__main__':
    print(f'Open http://127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()

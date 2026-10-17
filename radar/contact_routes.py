"""Prioritize published official contact navigation without guessing people."""
import re
from urllib.parse import urljoin,urlsplit,urlunsplit,unquote
from bs4 import BeautifulSoup

_CONTACT_LABEL=re.compile(r'\b(?:contacts?(?:\s+us)?|get\s+in\s+touch|reach\s+us|kontakt|contacto|contatti|contactez(?:[-\s]+nous)?)\b|联系我们|聯繫我們|联系我们|联系我|聯絡我們',re.I)
_CONTACT_PATH=re.compile(r'^(?:contacts?(?:[-_]?us)?|contact[-_]?(?:info|information)|get[-_]in[-_]touch|reach[-_]us|kontakt|contacto|contatti|contactez[-_]nous|联系我们|聯繫我們|聯絡我們)(?:\.(?:html?|php|aspx?))?$',re.I)
_EXCLUDED=re.compile(r'^(?:products?|collections?|blog|news|articles?|account|login|signin|checkout|cart|admin|wp-admin)$',re.I)
_LANGUAGE=re.compile(r'[a-z]{2}(?:[-_][A-Za-z]{2})?',re.I)
_NON_COMPANY_ABOUT=re.compile(r'(?:^|[/_-])(?:klarna|vipme|rewards?|loyalty|memberships?|payments?|delivery|shipping|returns?|privacy|polic(?:y|ies)|terms|cookies?|careers?|vacancies)(?:$|[/_.-])',re.I)
_BUSINESS_ENTRY=re.compile(r'\b(?:suppliers?|procurement|purchasing|business[-\s]+contacts?)\b',re.I)

def team_priority(url):
    """Rank corporate people pages without promoting payment/member About pages."""
    path=unquote(urlsplit(url).path)
    if _NON_COMPANY_ABOUT.search(path):return None
    if re.search(r'team|leadership|management|people|board|executive',path,re.I):return 0
    if re.search(r'about|our[-_]story|company|corporate|impressum',path,re.I):return 1
    return None

def _host(url):
    parsed=urlsplit(url)
    return (parsed.hostname or '').lower().removeprefix('www.')

def _safe_url(value,start_url):
    try:
        if not isinstance(value,str) or not value.strip() or re.search(r'[\x00-\x20\\]',value.strip()):return None
        p=urlsplit(urljoin(start_url,value.strip()))
        if p.scheme not in ('http','https') or p.username or p.password or p.port not in (None,80,443):return None
        if not p.hostname or _host(urlunsplit(p))!=_host(start_url):return None
        if p.query or any(_EXCLUDED.fullmatch(x) for x in unquote(p.path).strip('/').split('/')):return None
        return urlunsplit((p.scheme,p.netloc,p.path or '/','',''))
    except (ValueError,TypeError):return None

def is_contact_url(url):
    try:
        p=urlsplit(url)
        if p.scheme not in ('http','https'):return False
        parts=[s for s in unquote(p.path).strip('/').split('/') if s]
        if not parts or any(_EXCLUDED.fullmatch(s) for s in parts):return False
        # Only conventional root/CMS/language navigation, never product/article slugs.
        if len(parts)>1 and not all(x.lower() in ('pages','page','company','corporate','help','i') or _LANGUAGE.fullmatch(x) for x in parts[:-1]):return False
        return bool(_CONTACT_PATH.fullmatch(parts[-1]))
    except (ValueError,TypeError):return False

def choose_contact_routes(raw_html,start_url):
    routes=[]
    current=_safe_url(start_url,start_url)
    if current and is_contact_url(current):routes.append(current)
    found=[]
    for order,a in enumerate(BeautifulSoup(raw_html or '', 'html.parser').find_all('a',href=True)):
        url=_safe_url(a.get('href'),start_url)
        if not url:continue
        label=' '.join((a.get_text(' ',strip=True),a.get('aria-label',''),a.get('title','')))
        by_label=bool(_CONTACT_LABEL.search(label))
        business=bool(_BUSINESS_ENTRY.search(label))
        if not by_label and not business and not is_contact_url(url):continue
        found.append((0 if business else 1 if by_label else 2,order,url))
    for _,_,url in sorted(found):
        if url not in routes:routes.append(url)
    return routes

def guessed_contact_routes(raw_html,start_url):
    """At most two conventional fallback paths, based on current public HTML."""
    safe=_safe_url(start_url,start_url)
    if not safe:return []
    p=urlsplit(safe);origin=urlunsplit((p.scheme,p.netloc,'/','',''))
    # Retain the published locale instead of guessing at an unrelated root.
    # Accept locale-shaped segments only, not arbitrary URL directories.
    parts=[x for x in p.path.strip('/').split('/') if x]
    locale=[]
    for part in parts:
        clean=re.sub(r'\.(?:html?|php)$','',part,flags=re.I)
        if not _LANGUAGE.fullmatch(clean):break
        locale.append(clean)
    prefix='/'.join(locale)
    soup=BeautifulSoup(raw_html or '', 'html.parser')
    # A linked external shop/blog does not establish this site's CMS. Only
    # navigation on the exact official host may inform its fallback paths.
    links=[urlsplit(safe).path.lower() for a in soup.find_all('a',href=True) for safe in [_safe_url(a.get('href'),start_url)] if safe]
    shopify=bool(re.search(r'(?:cdn\.shopify\.com|shopify\.theme|name=[\"\x27]shopify)',raw_html or '',re.I))
    if shopify or any(re.match(r'(?:https?://[^/]+)?/pages/',x) for x in links):paths=['/pages/contact-us','/pages/contact']
    elif re.search(r'\.html?$',p.path) or any(re.search(r'\.html?$',x) for x in links):paths=['/contacts.html','/contact-us.html'] if locale else ['/contact.html','/contact-us.html']
    elif any(re.search(r'\.php$',x) for x in links):paths=['/contactus.php','/contact.php']
    else:paths=['/contact','/contact-us']
    return [urljoin(origin,('/'+prefix+x) if prefix else x) for x in paths]


def published_locale_entry(raw_html,start_url):
    """One published same-host landing page from an explicit country selector.

    A locale splash is navigation, not a failed Contact page. Follow its actual
    link before guessing paths; never manufacture locale URLs or traverse all
    countries. The selected locale does not establish a company's location.
    """
    soup=BeautifulSoup(raw_html or '', 'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    if not (re.search(r'country\s*selector|select\s+(?:a\s+)?country|choose\s+(?:a\s+)?(?:country|region)',title,re.I) or soup.find(attrs={'data-qaid':'locale-homepage-links'})):
        return []
    language=(soup.html.get('lang','en') if soup.html else 'en').split('-')[0].lower()
    choices=[]
    for order,a in enumerate(soup.find_all('a',href=True)):
        url=_safe_url(a.get('href'),start_url)
        if not url:continue
        path=urlsplit(url).path
        match=re.fullmatch(r'/([a-z]{2})(?:[-_][a-z]{2})?/(?:home|index(?:\.html?)?)?/?',path,re.I)
        if not match:continue
        choices.append((0 if match.group(1).lower()==language else 1,order,url))
    return [sorted(choices)[0][2]] if choices else []


def published_contact_children(raw_html,start_url,limit=3):
    """Follow one bounded level of actual same-site department contact links.

    No URL guessing or cross-site/subdomain traversal. A department link is
    considered only after its conventional Contact parent has been read.
    """
    if not is_contact_url(start_url):return []
    prefix=urlsplit(start_url).path.rstrip('/')+'/'
    found=[]
    excluded=re.compile(r'privacy|terms|legal|login|account|career|vacanc|sponsor|sponsring|press|media|investor|customer[-_ ]?(?:service|support)',re.I)
    for order,a in enumerate(BeautifulSoup(raw_html or '', 'html.parser').find_all('a',href=True)):
        url=_safe_url(a.get('href'),start_url)
        if not url:continue
        path=urlsplit(url).path
        if not path.startswith(prefix):continue
        tail=unquote(path[len(prefix):]).strip('/')
        label=a.get_text(' ',strip=True)+' '+a.get('aria-label','')+' '+tail
        if not tail or '/' in tail or excluded.search(label):continue
        priority=0 if re.search(r'sales|business|commercial|professional|professionell|procurement|purchas|supplier|b2b|inköp|företag',label,re.I) else 1
        found.append((priority,order,url))
    return list(dict.fromkeys(url for _,_,url in sorted(found)))[:max(0,min(3,limit))]


def published_support_route(raw_html,start_url):
    """One explicitly linked FAQ landing page, only from a Contact/Help page."""
    path=urlsplit(start_url).path.rstrip('/')
    if not (is_contact_url(start_url) or re.search(r'(?:^|/)help(?:\.html?)?$',path,re.I)):
        return []
    for anchor in BeautifulSoup(raw_html or '', 'html.parser').find_all('a',href=True):
        label=anchor.get_text(' ',strip=True)
        if not re.fullmatch(r'(?:FAQs?|Frequently\s+Asked\s+Questions)\s*[↗→]?',label,re.I):continue
        url=_safe_url(anchor.get('href'),start_url)
        if url and url!=_safe_url(start_url,start_url):return [url]
    return []

"""Conservative contact-card extraction; person attribution stays inside one card."""
import re
from urllib.parse import unquote
from bs4 import BeautifulSoup
from contact_quality import country_hint, phone_info, whatsapp_links
from person_identity import plausible_person_name

NAME=re.compile(r"[A-ZÀ-ÖØ-Þ][\wÀ-ž'.-]+(?: (?:van |von |de |del |da )?[A-ZÀ-ÖØ-Þ][\wÀ-ž'.-]+){1,3}")
# Team cards can publish useful identities outside procurement decision roles.
# This display-only predicate does not broaden AI prospect eligibility.
DISPLAY_JOB = re.compile(r'^(?:sales manager|(?:finance|financial) director|social media\s*(?:&|and)\s*marketing|operations\s*(?:&|and)\s*logistics|sales\s*(?:&|and)\s*development|(?:[A-Za-z][A-Za-z &/\-]{0,65} )?(?:engineer|specialist))$', re.I)

def displayed_job_title(value, role):
    return len(value) <= 120 and bool(role.search(value) or DISPLAY_JOB.fullmatch(value))

EXCLUDE=re.compile(r'contact|about|our |team|company|customer|support|head office|join|privacy|terms',re.I)

def contact_cards(soup,url,role,emails,is_role):
    region=country_hint(soup);found=[]
    for heading in soup.find_all(['h1','h2','h3','h4','h5','h6']):
        name=heading.get_text(' ',strip=True)
        if not plausible_person_name(name) or EXCLUDE.search(name) or role.search(name):continue
        for card in list(heading.parents)[:3]:
            if card.name in ('body','html'):break
            text=card.get_text('\n',strip=True)
            if len(text)>700:break
            names=[h.get_text(' ',strip=True) for h in card.find_all(['h1','h2','h3','h4','h5','h6']) if plausible_person_name(h.get_text(' ',strip=True))]
            if len(set(names))>1:break
            titles=[x for x in text.splitlines() if displayed_job_title(x,role) and x!=name and len(x)<120 and '@' not in x]
            if not titles:continue
            addresses=set(emails(text))
            for a in card.select('a[href]'):
                if a['href'].lower().startswith('mailto:'):addresses.update(emails(unquote(a['href'].split('?')[0])))
            if len(addresses)>1:break
            email=next(iter(addresses),'')
            if email and is_role(email):email=''
            numbers=[]
            for a in card.select('a[href]'):
                if a['href'].lower().startswith('tel:'):numbers.append(unquote(a['href'][4:]).split('?')[0])
            for match in re.finditer(r'(?:mobile|mob|cell|mobil|whatsapp|tel(?:ephone)?|phone)\s*[:.]?\s*(\+?[\d][\d ()\-]{6,24}\d)',text,re.I):numbers.append(match[1])
            for line in text.splitlines():
                if re.fullmatch(r'\+?[\d ()-]{7,25}',line) and 7<=len(re.sub(r'\D','',line))<=15:numbers.append(line)
            numbers=list(dict.fromkeys(numbers))
            from whatsapp_attribution import publication_scopes,attributed_channels
            wa,_=attributed_channels(publication_scopes(card,url,region),name,email,identity_verified=True,email_verified=bool(email))
            for w in wa:
                if w['phone'] and w['phone'] not in numbers:numbers.append(w['phone'])
            mobile=[n for n in numbers if phone_info(n,region)['mobile']]
            # Multiple ambiguous phones stay as evidence, not arbitrarily picked.
            chosen=mobile[0] if len(mobile)==1 else numbers[0] if len(numbers)==1 else ''
            found.append({'name':name,'title':titles[0],'email':email,'phone':chosen,'phone_raw':chosen,'country_hint':region,'source':url,'status':'官网独立联系人卡片；缺失项不推测','evidence':text,'contact_phone_candidates':numbers,'explicit_whatsapp':wa})
            break
    return found


def prepare_visible_contacts(soup):
    from website_email_bridge import normalize_published_emails
    normalize_published_emails(soup)
    # theHarvester's genericClean preserves contiguous addresses interrupted
    # by inline emphasis or <wbr>. Keep the same rendered-text semantics inside
    # the original DOM so independent person-card verification can confirm them.
    inline=soup.find_all(['wbr','em','b','strong'])
    for tag in inline:tag.unwrap()
    if inline:soup.smooth()
    # Expose actual mailto/tel targets where a page renders only “Email”/“Call”.
    for a in soup.select('a[href]'):
        href=a['href']
        if href.lower().startswith(('mailto:','tel:')):
            value=unquote(href.split(':',1)[1].split('?')[0])
            if value and value not in a.get_text():a.append(' '+value)
    # Decode only the standard public Cloudflare email attribute, not arbitrary JS.
    for tag in soup.select('[data-cfemail]'):
        try:
            data=bytes.fromhex(tag['data-cfemail']);decoded=bytes(x^data[0] for x in data[1:]).decode()
            if '@' in decoded:tag.string=decoded
        except (ValueError,UnicodeDecodeError,IndexError):pass


def named_role_mentions(soup,url):
    """Keep explicit founder statements as incomplete identities, not contact matches."""
    found=[]
    pattern=re.compile(r'\b(?:founded|co-founded|established)\s+(?:in\s+\d{4}\s+)?by\s+([A-Z][a-zÀ-ž\x27-]+(?:\s+[A-Z][a-zÀ-ž\x27-]+){1,2})(?:\s+and\s+([A-Z][a-zÀ-ž\x27-]+(?:\s+[A-Z][a-zÀ-ž\x27-]+){1,2}))?')
    for tag in soup.find_all(['p','li']):
        text=tag.get_text(' ',strip=True)
        if len(text)>650:continue
        for match in pattern.finditer(text):
            for name in match.groups():
                if name and plausible_person_name(name):found.append({'name':name,'title':'Founder（官网创立叙述；当前任职待核实）','email':'','phone':'','source':url,'status':'官网明确创立叙述；未关联邮箱或手机','evidence':text,'identity_only':True})
    return found

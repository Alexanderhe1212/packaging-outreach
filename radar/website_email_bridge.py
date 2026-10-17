"""Local published-email decoding only; person attribution stays in the caller."""
from bs4.element import Comment
from third_party.website_email_contact_scraper.extract_emails import (
    deobfuscate_text, decode_cfemail, extract_emails, _is_false_positive,
)
from third_party.website_email_contact_scraper.html_text import build_page, soup_to_text
from third_party.website_email_contact_scraper.social_regexes import EMAIL_REGEX_GLOBAL

ENGINE='website-email-contact-scraper local-email-parser'
SKIP={'script','style','noscript','template','svg','canvas','iframe','form'}
BLOCK={'div','section','article','address','p','li','table','tr','td','h1','h2','h3','h4','h5','h6','footer','nav'}

def addresses(text):
    if len(text)>10000:return []
    return list(dict.fromkeys(m.group(0).lower() for m in EMAIL_REGEX_GLOBAL.finditer(text)
        if not _is_false_positive(m.group(0).lower())))

def normalize_published_emails(soup):
    """Decode only explicit published spellings inside their original DOM scope.

    Retain original spellings alongside decoding method. No identity, mailbox
    pattern, phone, or WhatsApp is synthesized. Repeated calls are idempotent.
    """
    records=soup.__dict__.setdefault("_ur_email_decodings",[])
    def record(tag,original,email,method):
        item=dict(original=original[:1000],email=email,method=method,engine=ENGINE)
        if item not in records:records.append(item)
    for node in list(soup.find_all(string=True))[:12000]:
        if isinstance(node,Comment) or any(p.name in SKIP for p in node.parents):continue
        original=str(node)
        if len(original)>10000:continue
        decoded=deobfuscate_text(original)
        if decoded!=original:
            found=addresses(decoded)
            if found:
                for email in found:record(node.parent,original,email,'published_text_deobfuscation')
                node.replace_with(decoded)
    for tag in soup.select('a[href*="/cdn-cgi/l/email-protection#"]')[:1000]:
        if any(p.name in SKIP for p in tag.parents):continue
        href=tag.get('href','')
        try:email=decode_cfemail(href.split('#',1)[1]).lower()
        except (ValueError,IndexError):continue
        if email not in addresses(email):continue
        if email not in tag.get_text():
            record(tag,href,email,'cloudflare_href_xor');tag.append(' '+email)
    # Only tight inline containers: never join text across person cards or
    # block boundaries. Add the published contiguous address in its own node.
    for tag in reversed(soup.find_all(['p','a','span','li','td','address'])[:3000]):
        if any(p.name in SKIP for p in [tag]+list(tag.parents)):continue
        if tag.find(list(BLOCK)):continue
        text=tag.get_text(' ',strip=True)
        if len(text)>1000:continue
        # Separate contact links: inline joining must not concatenate phone and email.
        if tag.find('a', href=True):continue
        joined=soup_to_text(tag)
        for email in addresses(joined):
            if email not in text.lower():
                record(tag,str(tag),email,'contiguous_inline_text');tag.append(' '+email)
    return records

def email_hints(raw,source):
    """Unqualified page-level leads; never return ownership or inferred channels."""
    if len(raw)>1500000:return []
    return [dict(email=h['value'],source=source,engine=ENGINE,qualified=False,
        status='Published page email; individual attribution requires separate verification')
        for h in extract_emails(build_page(source,raw))][:100]

"""Published page-level phone channels; never assign them to an individual."""
import re
from urllib.parse import unquote
from contact_quality import phone_info, country_hint

LABELLED = re.compile(r'\b(?:tel(?:ephone)?\.?|phone|call(?:\s+us)?|toll[ -]free)\s*[:：.]?\s*(\+?\d[\d \t().-]{5,28}\d)',re.I)
INTERNATIONAL = re.compile(r'(?<!\w)\+\d[\d \t().-]{6,28}\d')


def public_phones(soup, url, people=()):
    region=country_hint(soup)
    candidates=[]
    for anchor in soup.select('a[href]'):
        if anchor['href'].lower().startswith('tel:'):
            candidates.append(unquote(anchor['href'][4:]).split('?')[0])
    for tag in soup.find_all(['p','li','address','div','span']):
        text=tag.get_text('\n',strip=True)
        if len(text)>450:continue
        candidates.extend(m[1] for m in LABELLED.finditer(text))
        # An explicit international number may be printed without a tel link.
        # Domestic numbers need a telephone label; postal codes are not phones.
        candidates.extend(m[0] for m in INTERNATIONAL.finditer(text))
    assigned=set()
    for person in people:
        if not (person.get('name') and person.get('title') and person.get('source')==url):continue
        if any(person.get(k) for k in ('phone_conflict','phone_stale','historical')):continue
        number=person.get('phone') or person.get('mobile') or ''
        parsed=phone_info(number,person.get('country_hint') or region)
        if number:assigned.add(re.sub(r'\D','',parsed['phone_e164'] or number))
    found={}
    for raw in candidates:
        raw=raw.strip(' .-')
        digits=re.sub(r'\D','',raw)
        if not 7<=len(digits)<=15:continue
        parsed=phone_info(raw,region)
        if raw.startswith(('+','00')) and not parsed['phone_e164']:continue
        number=parsed['phone_e164'] or raw
        key=re.sub(r'\D','',number)
        if key in assigned:continue
        found.setdefault(key,{'phone':number,'phone_raw':raw,'source':url,
                              'kind':'官网公开公司/部门电话；未确认个人归属',
                              'phone_note':'未验证接通；'+('按原文保留，未推定国家号' if not parsed['phone_e164'] else '仅号码格式已标准化')})
    return list(found.values())

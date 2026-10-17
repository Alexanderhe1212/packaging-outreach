"""Evidence-only contact qualification; never probes WhatsApp accounts."""
import re
from urllib.parse import urlsplit, parse_qs, unquote
import phonenumbers as pn


def phone_info(raw, region=None):
    result = {'phone_type': 'unknown', 'mobile': '', 'phone_e164': '', 'phone_note': '类型待核实；未验证归属或接通'}
    raw = raw or ''
    if raw.startswith(('+', '00')): raw = raw.replace('(0)', '')
    raw = re.sub(r'[\s().-]', '', raw)
    if raw.startswith('00'): raw = '+' + raw[2:]
    if not raw or (not raw.startswith('+') and not region):
        return result  # No country guessing from domains or page language.
    try:
        number = pn.parse(raw, region)
        if not pn.is_valid_number(number): return result
        if not raw.startswith('+'):
            result['country_inference'] = '根据官网明确地址国家 ' + region + ' 补全；需核对联系人所在地'
        result['phone_e164'] = pn.format_number(number, pn.PhoneNumberFormat.E164)
        kind = pn.number_type(number)
        if kind == pn.PhoneNumberType.MOBILE:
            result.update(phone_type='mobile', mobile=result['phone_e164'], phone_note='号段识别为手机；未验证归属或接通')
        elif kind == pn.PhoneNumberType.FIXED_LINE:
            result.update(phone_type='landline', phone_note='号段识别为座机，不计作手机')
        elif kind == pn.PhoneNumberType.FIXED_LINE_OR_MOBILE:
            result['phone_note'] = '此号段无法区分手机与座机'
    except pn.NumberParseException:
        pass
    return result


def whatsapp_links(soup, source):
    result = []
    for tag in soup.select('a[href]'):
        url = tag['href'].strip()
        p = urlsplit(url)
        if p.scheme not in ('http', 'https', 'whatsapp') or p.username or p.password: continue
        number = ''
        if p.hostname == 'wa.me' and re.fullmatch(r'/[1-9][0-9]{6,14}/?', p.path):
            number = p.path.strip('/')
        elif (p.hostname in ('api.whatsapp.com', 'web.whatsapp.com') and p.path.rstrip('/') == '/send') or (p.scheme=='whatsapp' and p.netloc=='send'):
            value = re.sub(r'[ ()-]','',parse_qs(p.query).get('phone', [''])[0])
            if re.fullmatch(r'\+?[1-9][0-9]{6,14}', value): number = value.lstrip('+')
        if not number and p.scheme in ('http','https') and p.hostname=='wa.me' and re.fullmatch(r'/message/[A-Za-z0-9]+/?',p.path):
            result.append({'phone':'','url':url,'source':source,'status':'官网公开 WhatsApp 商业短链接；未公开号码及归属'})
        if number:
            result.append({'phone': '+'+number, 'url': url, 'source': source, 'status': '官网公开 WhatsApp 链接；账号可用性与归属待核实'})
    return result


def qualify(result, is_role):
    unique = {}
    for p in result['people']:
        # Translated job titles and formatting variants do not create new people.
        name=p.get('name','').casefold().strip()
        email=p.get('email','').casefold().strip()
        key=(name,email) if email else (name,'',p.get('title','').casefold(),re.sub(r'\D','',p.get('phone','')))
        if key in unique:
            previous=unique[key]
            sources=list(dict.fromkeys(previous.get('sources',[previous.get('source')])+p.get('sources',[p.get('source')])))
            titles=list(dict.fromkeys(previous.get('titles',[previous.get('title')])+[p.get('title')]))
            # Prefer the observation with an explicitly parseable mobile, but
            # retain every observed source and title for independent review.
            if phone_info(p.get('phone',''),p.get('country_hint'))['mobile'] and not phone_info(previous.get('phone',''),previous.get('country_hint'))['mobile']:
                unique[key]=p
            old_number=phone_info(previous.get('phone',''),previous.get('country_hint'))
            new_number=phone_info(p.get('phone',''),p.get('country_hint'))
            if old_number['phone_e164'] and new_number['phone_e164'] and old_number['phone_e164']!=new_number['phone_e164']:
                variants=previous.get('phone_variants',[])+[{'phone':old_number['phone_e164'],'source':previous.get('source')},{'phone':new_number['phone_e164'],'source':p.get('source')}]
                unique[key]['phone_variants']=list({(v['phone'],v['source']):v for v in variants}.values())
                if old_number['phone_type']==new_number['phone_type']:
                    unique[key].update(phone_conflict=True,phone='',phone_raw='',mobile='')
            all_fields=set(previous.get('evidence_by_field',{}))|set(p.get('evidence_by_field',{}))
            unique[key]['evidence_by_field']={field:list({(e['url'],e.get('quote','')):e for e in previous.get('evidence_by_field',{}).get(field,[])+p.get('evidence_by_field',{}).get(field,[])}.values()) for field in all_fields}
            unique[key]['sources']=sources
            unique[key]['titles']=titles
            unique[key]['explicit_whatsapp']=list({(w.get('url',''),w.get('phone',''),w.get('source','')):w for w in previous.get('explicit_whatsapp',[])+p.get('explicit_whatsapp',[])}.values())
        else: unique[key] = p
    result['people'] = list(unique.values())
    for p in result['people']:
        p.update(phone_info(p.get('phone', ''), p.get('country_hint')))
        if p.get('phone_conflict'):p['phone_note']='不同来源号码不一致，待人工核对；未计为手机'
        p['qualified'] = bool(p.get('name', '').strip() and p.get('title', '').strip() and p.get('email') and (not any(is_role(e.strip()) for e in p['email'].split(';')) or (p.get('signed_contact') is True and p.get('person_designated_role_email') is True)))
        p['email_status'] = '官网公开；未验证投递' if p.get('email') else '未找到具名邮箱'
        published=p.get('explicit_whatsapp',[])
        p['whatsapp']=[w for w in published if w.get('attribution')=='person' and w.get('attributed_name','').strip().casefold()==p.get('name','').strip().casefold()]
        pending=[w for w in published if w not in p['whatsapp']]
        if pending:p['unverified_whatsapp']=pending
        p['complete'] = bool(p['qualified'] and p['mobile'] and p['whatsapp'])
    result['qualified_people'] = [p for p in result['people'] if p['qualified']]
    result['complete_people'] = [p for p in result['people'] if p['complete']]
    return result


def country_hint(soup):
    """Only a unique explicit structured postal country, never infer from TLD."""
    import json
    countries = set()
    aliases = {'AUSTRALIA':'AU', 'UNITED KINGDOM':'GB', 'UNITED STATES':'US', 'GERMANY':'DE', 'POLAND':'PL', 'CHINA':'CN', 'UK':'GB', 'SOUTH AFRICA':'ZA', 'SRI LANKA':'LK', 'INDIA':'IN'}
    def walk(obj):
        if isinstance(obj,list):
            for item in obj: walk(item)
        if not isinstance(obj,dict): return
        if 'addressCountry' in obj:
            value=obj['addressCountry']
            if isinstance(value,dict): value=value.get('name','')
            if isinstance(value,str):
                code=aliases.get(value.upper(),value.upper())
                countries.add(code if code in pn.SUPPORTED_REGIONS else 'UNKNOWN')
        for value in obj.values():
            if isinstance(value,(dict,list)): walk(value)
    for tag in soup.find_all('script',type='application/ld+json'):
        try: walk(json.loads(tag.string or tag.get_text()))
        except (ValueError,TypeError): pass
    if not countries:
        # A printed postal address is country evidence; a TLD or a shipping
        # destination list is not. Conflicting address countries stay unknown.
        for tag in soup.find_all(['address','p','li','div']):
            text=tag.get_text(' ',strip=True)
            if len(text)>450 or not re.search(r'\d',text) or not re.search(r'\b(?:road|rd|street|st|square|avenue|lane|address|postal|p\.?o\.?\s*box)\b',text,re.I):continue
            for label,code in aliases.items():
                if re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',text,re.I):countries.add(code)
    return next(iter(countries)) if len(countries)==1 and 'UNKNOWN' not in countries else None

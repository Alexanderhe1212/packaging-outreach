"""Fast named-email leads: role optional, no missing-channel completion."""
import copy,re,time
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from person_identity import plausible_person_name

MODE='name_email'
def host(url):return (urlsplit(url).hostname or '').lower().removeprefix('www.')

def contacts_from_html(raw,url,existing_people=None):
    from app import extract,emails,is_role
    from contact_extract import prepare_visible_contacts
    from enrichment import shared_mailbox
    soup=BeautifulSoup(raw,'html.parser');prepare_visible_contacts(soup)
    for tag in soup(['script','style','noscript','footer','nav','aside','form']):tag.decompose()
    people=copy.deepcopy(existing_people) if existing_people is not None else extract(raw,url)[0]
    seen={(p['name'].casefold(),p.get('email','').casefold()) for p in people}
    # Explicit prose such as "contact Jane Smith email: jane@example.com".
    # Each match owns its own address even when several people share a paragraph.
    pattern=re.compile(r'(?:[Cc]ontact\s+|\bor\s+)([A-ZÀ-ÖØ-Þ][\wÀ-ž\x27.-]+(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž\x27.-]+){1,3})\s*,?\s+email\s*:\s*([^\s;<>]+@[^\s;<>]+\.[A-Za-z]{2,})')
    for paragraph in soup.find_all(['p','li']):
        text=paragraph.get_text(' ',strip=True)
        if len(text)>1000 or re.search(r'press enquiries|media enquiries|privacy|recruitment',text,re.I):continue
        for match in pattern.finditer(text):
            name,mail=match.groups();mail=mail.rstrip('.,')
            key=(name.casefold(),mail.casefold())
            if key in seen or not plausible_person_name(name) or is_role(mail) or shared_mailbox(mail,host(url),url):continue
            people.append(dict(name=name,title='',email=mail,phone='',source=url,evidence=match.group(0),qualification_mode=MODE))
            seen.add(key)
    for heading in soup.find_all(['h1','h2','h3','h4','h5','h6','strong','b']):
        name=heading.get_text(' ',strip=True)
        if not plausible_person_name(name):continue
        for card in list(heading.parents)[:3]:
            if card.name in ('body','html'):break
            text=card.get_text('\n',strip=True)
            if len(text)>700:break
            names={h.get_text(' ',strip=True) for h in card.find_all(['h1','h2','h3','h4','h5','h6','strong','b']) if plausible_person_name(h.get_text(' ',strip=True))}
            if len(names)>1:break
            addresses=set(emails(text))
            if len(addresses)!=1:continue
            email=next(iter(addresses))
            if is_role(email) or shared_mailbox(email,host(url),url):break
            key=(name.casefold(),email.casefold())
            if key not in seen:
                people.append(dict(name=name,title='',email=email,source=url,evidence=text,phone='',qualification_mode=MODE))
                seen.add(key)
            break
    return people


def retain_observed_optional(person):
    """Keep optional fields already printed in one named-email card; no searches."""
    from app import emails
    from contact_quality import phone_info
    p=copy.deepcopy(person)
    name=p.get('name','').strip();mail=p.get('email','').strip()
    text=p.get('evidence','');source=p.get('source','')
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if (not source or not name or len(text)>700 or name not in lines or
        {v.casefold() for v in emails(text)}!={mail.casefold()}):return p
    index=lines.index(name)
    if not p.get('title') and index+1<len(lines):
        value=lines[index+1]
        if len(value)<=120 and '@' not in value and re.search(r'manager|director|head|chief|officer|founder|owner|specialist|trainer|expert|säljare|chef|采购|经理|总监',value,re.I):
            p['title']=value
    if not p.get('mobile') and not p.get('phone_conflict') and not p.get('phone_stale'):
        numbers={}
        for line in lines[index+1:]:
            value=re.sub(r'^(?:mobile|mob|tel|phone|mobil)\s*[:.]?\s*','',line,flags=re.I)
            if not re.fullmatch(r'(?:\+|00)?[\d ()-]{7,25}',value):continue
            info=phone_info(value,p.get('country_hint'))
            if info['mobile']:numbers[info['mobile']]=info
        if len(numbers)==1:
            mobile,info=next(iter(numbers.items()));p.update(info);p['phone']=mobile
            p.setdefault('evidence_by_field',{})['phone']=[{'url':source,'quote':text,'source_type':'official'}]
    return p

def qualify_report(report):
    from extension_api import evidence_matches
    from app import is_role
    from enrichment import shared_mailbox
    from team_enrichment import remove_company_channels,company_channels
    report=copy.deepcopy(report);report['qualification_mode']=MODE;out=[]
    report['people']=[retain_observed_optional(p) for p in report.get('people',[])]
    owners={}
    for p in report['people']:
        if p.get('mobile'):owners.setdefault(p['mobile'],set()).add(p.get('name','').casefold())
    for p in report['people']:
        if len(owners.get(p.get('mobile'),set()))>1:
            p.update(phone='',mobile='',phone_e164='',phone_conflict=True)
            p.setdefault('evidence_by_field',{}).pop('phone',None)
    excluded=company_channels(report)
    for p in report.get('people',[]):
        p=remove_company_channels(p,excluded)
        name=p.get('name','').strip();mail=p.get('email','').strip()
        ev=p.setdefault('evidence_by_field',{})
        quote=p.get('evidence','');url=p.get('source','')
        if name and mail and name.casefold() in quote.casefold() and mail.casefold() in quote.casefold() and url:
            source=dict(url=url,quote=quote,source_type='official' if host(url)==host(report['website']) else 'public')
            ev.setdefault('identity',[source]);ev.setdefault('email',[source])
        p['qualified']=bool(plausible_person_name(name) and re.fullmatch(r'[^\s;@]+@[^\s;@]+\.[^\s;@]+',mail) and not is_role(mail) and not shared_mailbox(mail,host(report['website']),report['website']) and evidence_matches(ev.get('identity'),name) and evidence_matches(ev.get('email'),name,mail) and not p.get('historical') and not p.get('review_required'))
        p['qualification_mode']=MODE
        p['complete']=p['qualified']
        if not any(q.get('name','').casefold()==name.casefold() and q.get('email','').casefold()==mail.casefold() for q in out):out.append(p)
    report['people']=out;report['qualified_people']=[p for p in out if p['qualified']];report['complete_people']=report['qualified_people']
    report['note']='姓名与具名邮箱为必填；职位、本人手机和 WhatsApp 选填。仅作公开来源联系人线索，未确认采购权或邮箱投递。'
    return report

def run(identifier):
    import ai_discovery as discovery
    from app import research
    from public_sources import SourceReader
    job=discovery.JOBS[identifier]
    def update(**values):
        with discovery.LOCK:job.update(values)
    try:
        if job['cancel'].is_set():update(status='cancelled',finished_at=time.time());return
        update(status='running',started_at=time.time(),progress='查找姓名与具名邮箱；其他信息选填')
        report=research(job['target_website'],cancel=job['cancel'],max_seconds=40,name_email_only=True)
        report=qualify_report(report)
        with discovery.LOCK:job['results']=[dict(candidate={'website':job['target_website']},report=report,verified=bool(report['qualified_people']))]
        if not report['qualified_people'] and not job['cancel'].is_set():
            from rate_limits import check
            check(job['target_website'])
            update(progress='补查公开来源的姓名与具名邮箱')
            found=discovery.discover(job['target_website'],job['cancel'],lambda **kw:None,name_email_only=True)
            reader=SourceReader(cancel=job['cancel']);reader.deadline=time.monotonic()+45
            for c in found.get('companies',[])[:3]:
                if job['cancel'].is_set():break
                if host(c.get('website',''))!=host(job['target_website']):continue
                mail=c.get('email','');name=c.get('name','')
                if not plausible_person_name(name) or '@' not in mail:continue
                # Retain employer-domain affiliation, without biography or role checks.
                if not (mail.rsplit('@',1)[1].lower()==host(job['target_website']) or mail.rsplit('@',1)[1].lower().endswith('.'+host(job['target_website']))):continue
                for source in c.get('sources',[])[:3]:
                    if job['cancel'].is_set():break
                    doc=reader.read(source.get('url',''))
                    if doc.get('error'):continue
                    blocks=[b for b in doc.get('blocks',[]) if len(b)<=700 and name.casefold() in b.casefold() and mail.casefold() in b.casefold()]
                    if not blocks:continue
                    quote=blocks[0];ev=dict(url=doc['url'],quote=quote,source_type='public',checked_at=doc.get('checked_at',''))
                    report['people'].append(dict(name=name,title=c.get('title',''),email=mail,phone='',mobile='',whatsapp=[],source=doc['url'],evidence=quote,evidence_by_field={'identity':[ev],'email':[ev]}));break
            report=qualify_report(report)
            with discovery.LOCK:job['results'][0].update(report=report,verified=bool(report['qualified_people']))
        update(status='cancelled' if job['cancel'].is_set() else 'done',finished_at=time.time(),progress='已完成；找到 '+str(len(report['qualified_people']))+' 位具名联系人，选填信息缺项留空')
    except Exception as error:
        with discovery.LOCK:job['errors'].append(str(error)[:200])
        update(status='cancelled' if job['cancel'].is_set() else ('done' if job['results'] else 'error'),finished_at=time.time(),progress='本轮结束，保留已找到的具名联系人')

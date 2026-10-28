"""Contact-first introductions: verify the mailbox, never invent product fit."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from . import config,store,web,prospect_filter

EXHIBITION=Path.home()/'Library/Application Support/UserRadar/source-research/us-2022-2026/contact-run'

def observation(contact, source):
    generic='The company publishes this business contact on its official website.'
    identifier=contact.get('source_job_id','')
    if contact.get('batch_id')!='us-exhibitions-2022-2026' or not re.fullmatch(r'USCP-[A-Za-z0-9_-]+',identifier):
        return generic,source
    try:
        saved=json.loads((EXHIBITION/(identifier+'.json')).read_text())
        record=saved['source_record']
        if record['company'].strip().casefold()!=contact['company'].strip().casefold():return generic,source
        sources=[r for r in record.get('sources',[]) if isinstance(r.get('year'),int) and 2022<=r['year']<=2026
                 and (urlsplit(r.get('source','')).hostname or '')=='cosmoprofnorthamerica.com']
        if not sources:return generic,source
        record=max(sources,key=lambda r:r['year'])
        return 'The company is listed in the %s Cosmoprof North America Las Vegas exhibitor directory. This is historical participation, not evidence of current buying intent.' % record['year'],record['source']
    except (OSError,ValueError,TypeError,KeyError):return generic,source

def research(account, contact):
    site=web.normalize(contact.get('website',''))
    company=str(contact.get('company') or web.host(site))
    email=str(contact.get('email') or '').strip().lower()
    if prospect_filter.reason(company):raise web.IneligibleProspect(prospect_filter.reason(company))
    own={web.root_domain(web.host(a.get('website',''))) for a in config.load()['accounts'] if a.get('website')}
    own.update(web.root_domain(a.get('sender','').split('@')[-1]) for a in config.load()['accounts'] if a.get('sender'))
    if web.root_domain(web.host(site)) in own or store.hard_blocked(email,account['id']):
        raise web.CrawlError('自家或已抑制客户')
    last_error=None
    for source in contact.get('sources',[])[:3]:
        if not isinstance(source,str) or web.root_domain(web.host(source))!=web.root_domain(web.host(site)):continue
        try:
            _doc,final=web.verified_email_page(email,source,site,company)
        except Exception as error:
            if isinstance(error,web.DeferredFetch):raise
            if web.transient_failure(error) is not None:
                raise web.CrawlError(str(error)) from error
            last_error=error
            continue
        reason=prospect_filter.reason(company,web.strip_tags(_doc))
        if reason:raise web.IneligibleProspect(reason)
        fact,fact_source=observation(contact,final)
        return dict(company=company,customer_brand=company,website=site,domain=web.host(site),email=email,
                    email_source=final,email_verified=True,introduction_only=True,concept_ready=False,
                    site_description=fact,site_description_source=fact_source,
                    discovery_evidence={'observation':fact,'source':fact_source,
                                        'official_page_excerpt':web.strip_tags(_doc)[:6000],
                                        'official_page_source':final},
                    match_reason='General packaging introduction; product and purchasing needs have not been verified.',
                    purchase_signal='general_introduction',product_facts=[],product_image_url='',
                    **web.recipient_evidence(_doc,email,final)),None
    if contact.get('recheck_email'):
        # Bounded official-site rediscovery; never replace a mailbox from a guess.
        doc,final=web.page(site)
        replacement,source=web.find_email(doc,final,company,limit=3)
        if replacement:
            updated=dict(contact,email=replacement,sources=[source],recheck_email=False)
            return research(account,updated)
    if isinstance(last_error,web.urllib.error.URLError):
        raise web.CrawlError('官网邮箱来源暂不可读取：%s' % last_error) from last_error
    raise web.CrawlError('未找到官网公开商务邮箱')

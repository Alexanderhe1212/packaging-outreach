"""Research and commit ONE discovered company before accepting the next.

No mail integration. Discovery is supplied by the AI's live website search.
The lock covers crawling and saving; the ledger is durable and resumable.
"""
import fcntl
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import app
import customer_store
from extension_api import safe_contact
from name_email_lookup import qualify_report, host

ROOT = Path(__file__).parent / 'research-runs' / 'sequential-20261017'

def public_fallback(report, company):
    candidates = [c for c in report.get('emails', [])
                  if host(c.get('source', '')) == host(company['website'])
                  and app.EMAIL.fullmatch(c.get('email', ''))
                  and (c['email'].rsplit('@', 1)[-1].lower() == host(company['website'])
                       or (c['email'].rsplit('@',1)[-1].lower() in {'gmail.com','outlook.com','hotmail.com','yahoo.com'}
                           and c['email'].split('@')[0].lower() == host(company['website']).split('.')[0]
                           and len(c['email'].split('@')[0]) >= 5))]
    # Prefer business enquiries over support. Never repurpose privacy/HR inboxes.
    candidates = [c for c in candidates if c['email'].split('@')[0].lower() not in
                  ('privacy','hr','careers','press','accounts','legal','dpo')]
    candidates.sort(key=lambda c: (not c['email'].lower().startswith(('wholesale@','trade@','sales@','hello@','info@')), c['email']))
    if not candidates:
        return None
    c = candidates[0]
    return dict(website=company['website'], name='', title='', email=c['email'],
                mobile='', whatsapp=[], sources=[c['source']], evidence_by_field={
                    'email':[dict(url=c['source'], quote=c['email'], source_type='official')]},
                verified_at=datetime.now(timezone.utc).isoformat(), qualified=False,
                qualification_mode='official_company_email', contact_kind='company_public',
                email_status='官网公开联系邮箱；未核实个人归属，未验证投递',
                mobile_verified_personal=False, whatsapp_verified_personal=False,
                procurement_authority_confirmed=False)

def process(company):
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT/'queue.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_path = ROOT/'ledger.json'
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else dict(started_at=time.time(), companies=[])
        if any(host(c['website']) == host(company['website']) for c in ledger['companies']):
            raise ValueError('该公司已经处理；请选择下一家')
        if len(ledger['companies']) >= 10:
            raise ValueError('本批已完成 10 家')
        start = time.time()
        (ROOT/'current.json').write_text(json.dumps(dict(company=company,status='researching',started_at=start),ensure_ascii=False))
        report = qualify_report(app.research(company.get('contact_url') or company['website'], max_seconds=40, name_email_only=True))
        contacts = [safe_contact(p, company['website'], report, name_email_only=True) for p in report.get('qualified_people', [])]
        contacts = [p for p in contacts if p]
        if not contacts:
            fallback = public_fallback(report, company)
            if fallback: contacts = [fallback]
        saved = []
        for p in contacts:
            p.update(company=company['company'], fit_reason=company['fit_reason'], fit_source=company['fit_source'], batch_id=ROOT.name)
            p.setdefault('contact_kind','person')
            saved.append(customer_store.save(p)['customer'])
        result = dict(company, contacts=saved, started_at=start, finished_at=time.time(), elapsed_seconds=round(time.time()-start,3), status='saved' if saved else 'no_public_email', errors=report.get('errors',[]))
        (ROOT/(host(company['website'])+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
        ledger['companies'].append(result)
        ledger['updated_at']=time.time()
        tmp=ROOT/'ledger.tmp';tmp.write_text(json.dumps(ledger,ensure_ascii=False,indent=2));tmp.replace(ledger_path)
        (ROOT/'current.json').write_text(json.dumps(dict(status='ready_for_next',completed=len(ledger['companies'])),ensure_ascii=False))
        print(json.dumps(result,ensure_ascii=False))

def supplement_public(observation):
    """Save an AI-read official-page observation when the crawler was blocked.

    The caller must supply a verbatim published email, source and retrieval kind;
    indexed-page evidence is labelled separately from a live page fetch.
    """
    with (ROOT/'queue.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=ROOT/'ledger.json';ledger=json.loads(path.read_text());company=ledger['companies'][-1]
        if observation['email'] not in observation['quote']:raise ValueError('邮箱不在来源原文中')
        contact=public_fallback({'emails':[dict(email=observation['email'],source=observation['source'])]},company)
        if not contact:raise ValueError('必须是本公司官网公开的公共邮箱')
        contact['evidence_by_field']['email'][0].update(quote=observation['quote'],retrieval=observation['retrieval'])
        contact.update(company=company['company'],fit_reason=company['fit_reason'],fit_source=company['fit_source'],batch_id=ROOT.name,email_status='官网公开邮箱；'+observation['retrieval']+'；未验证投递')
        company['contacts'].append(customer_store.save(contact)['customer']);company['status']='saved'
        company['finished_at']=time.time();ledger['updated_at']=time.time()
        path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
        print(json.dumps(dict(company=company['company'],email=contact['email'],status='saved'),ensure_ascii=False))

def supplement_named(observation):
    """Retain an explicitly named, attributed public work-email observation."""
    with (ROOT/'queue.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=ROOT/'ledger.json';ledger=json.loads(path.read_text());company=ledger['companies'][-1]
        if host(observation['source'])!=host(company['website']):raise ValueError('不是当前公司官网')
        ev=dict(url=observation['source'],quote=observation['quote'],source_type='official',retrieval=observation['retrieval'])
        person=dict(qualified=True,name=observation['name'],title=observation.get('title',''),email=observation['email'],evidence_by_field={'identity':[ev],'email':[ev]})
        contact=safe_contact(person,company['website'],name_email_only=True)
        if not contact:raise ValueError('姓名和邮箱的来源关联不成立')
        contact.update(company=company['company'],fit_reason=company['fit_reason'],fit_source=company['fit_source'],batch_id=ROOT.name,contact_kind='person',email_status='具名工作邮箱；'+observation['retrieval']+'；未验证投递')
        company['contacts'].append(customer_store.save(contact)['customer']);company['status']='saved'
        company['finished_at']=time.time();ledger['updated_at']=time.time()
        path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
        print(json.dumps(dict(company=company['company'],name=contact['name'],email=contact['email'],status='saved'),ensure_ascii=False))

if __name__ == '__main__':
    process(json.load(sys.stdin))

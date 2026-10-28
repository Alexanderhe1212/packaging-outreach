"""Save sourced exhibitor observations to Radar; the existing mail pipeline owns sending."""
import hashlib
import json
import re
from pathlib import Path
from exhibition_contacts import company_website
from extension_api import safe_contact
from name_email_lookup import host
from sequential_prospect import public_fallback
import customer_store

BATCH = 'us-exhibitions-2022-2026'
STATUS = Path.home() / 'Library/Application Support/UserRadar/source-research/us-2022-2026/contact-run/status.json'

def contacts_for(item):
    contacts = {}
    website = item.get('website', '')
    if website and not company_website(website):
        return []
    for result in item.get('results', []):
        report = result.get('report') or {}
        site = website or report.get('website', '')
        if not company_website(site):
            continue
        attributed_report = dict(report, people=report.get('people', []) + report.get('qualified_people', []))
        for person in report.get('qualified_people', []):
            contact = safe_contact(person, site, attributed_report, name_email_only=True)
            if contact and any(host(ev.get('url',''))==host(site) for ev in contact['evidence_by_field'].get('email', [])):
                contact['contact_kind'] = 'person'
                contacts[contact['email'].casefold()] = contact
        for email in report.get('emails', []):
            if not isinstance(email, dict):
                continue
            contact = public_fallback({'emails':[email]}, {'website':site})
            if contact:
                contact['verified_at'] = report.get('checked_at') or ''
                contacts.setdefault(contact['email'].casefold(), contact)
    for contact in contacts.values():
        contact.update(company=item.get('company') or host(contact['website']), batch_id=BATCH,
                       source_job_id=item['record_id'],
                       fit_reason='Public exhibitor observation; packaging relevance and official email must be rechecked before sending. Participation does not confirm buying intent.',
                       fit_source='')
    return list(contacts.values())

def save_completed(item, receipts):
    identifier = item['record_id']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
        raise ValueError('Invalid exhibition record ID')
    digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipts = Path(receipts)
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = receipts / (identifier + '.json')
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get('source_sha256') == digest:
            return previous
    rows = contacts_for(item)
    saved = [customer_store.save(contact) for contact in rows]
    receipt = {'record_id':identifier, 'company':item.get('company',''), 'source_sha256':digest,
               'contact_ids':[r['customer']['id'] for r in saved], 'emails':[r['customer']['email'] for r in saved],
               'created':sum(r['created'] for r in saved), 'saved':len(saved),
               'status':'saved_for_standard_outreach' if saved else 'no_eligible_official_email'}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    tmp.replace(path)
    return receipt

def waiting_for_exhibition(path=STATUS):
    path = Path(path)
    if not path.exists():
        return False
    try:
        status = json.loads(path.read_text())
        total = int(status.get('total') or 0)
        return not (status.get('status')=='completed' and total>0 and int(status.get('completed',0))>=total)
    except (OSError, ValueError, TypeError):
        return True

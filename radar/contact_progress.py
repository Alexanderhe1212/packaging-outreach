"""Progress criteria; do not change the older mobile + WhatsApp filter."""


def core_person(person):
    return bool(person.get('qualified') and person.get('source')
                and (person.get('phone_e164') or person.get('mobile'))
                and not any(person.get(flag) for flag in
                            ('historical', 'review_required', 'needs_review',
                             'phone_conflict', 'phone_stale', 'phone_exclusion')))


def observed_identity(person):
    if not (person.get('name') and person.get('title') and person.get('source')):return False
    if any(person.get(flag) for flag in ('historical','review_required','needs_review')):return False
    # A search candidate can retain its proposed name/title and source URL even
    # after the original failed identity verification. It is not an observation.
    if 'source_checks' in person:
        return bool(person.get('evidence_by_field',{}).get('identity'))
    return True


def mark_progress(report):
    for person in report.get('people', []):
        person['core_complete'] = core_person(person)
    report['core_people'] = [p for p in report.get('people', []) if p['core_complete']]
    # A page read, page title or empty task is never a useful contact result.
    # Named roles may be useful partial evidence; company channels stay separate.
    report['useful_partial'] = bool(
        any(observed_identity(p) for p in report.get('people', []))
        or any(p.get('email') and p.get('source') for p in report.get('emails', []))
        or any(p.get('phone') and p.get('source') for p in report.get('phones', [])))
    return report

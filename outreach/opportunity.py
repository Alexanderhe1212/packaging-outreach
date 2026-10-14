"""Conservative, source-backed procurement grading; fit alone never becomes demand."""
import html
import re
from datetime import datetime, timezone
from . import web


def plain(text):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text or ''))).strip().lower()


def verify(item):
    item['checked_at'] = datetime.now(timezone.utc).isoformat()
    requested = str(item.get('opportunity_tier') or 'C').upper()
    item['opportunity_tier'] = 'B' if item.get('project_name') and item.get('product_url') else 'C'
    item['procurement_status'] = 'unconfirmed'
    item['verification'] = 'Project/fit only; purchasing evidence has not been verified.'
    if requested not in ('A+', 'A'):
        return item
    source = item.get('source_url') or item.get('signal_source') or ''
    quote = str(item.get('evidence_quote') or '')
    # Third-party boards and agency mandates stay reviewable, never automatically qualified.
    if not source or web.root_domain(web.host(source)) != web.root_domain(item.get('domain','')):
        item['verification'] = 'Buyer identity/authority on external source needs manual verification.'
        return item
    try:
        doc, final = web.page(source)
    except Exception:
        item['verification'] = 'Evidence source could not be fetched; kept in backlog.'
        return item
    text, q = plain(doc), plain(quote)
    if web.root_domain(web.host(final)) != web.root_domain(item.get('domain','')) or len(q) < 25 or q not in text:
        item['verification'] = 'Verbatim evidence not found on buyer source.'
        return item
    demand = re.search(r'\b(rfq|request for quot\w*|looking for.{0,65}(?:packaging|box|bag).{0,30}(?:suppliers?|manufacturers?)|(?:seeking|need).{0,70}(?:packaging|box|bag).{0,30}(?:suppliers?|manufacturers?)|(?:packaging|box|bag).{0,45}(?:suppliers?|manufacturers?).{0,35}(?:needed|wanted)|replacement suppliers?)\b', q)
    if not demand or re.search(r'\b(closed|expired|awarded|no longer accepting)\b', q):
        item['verification'] = 'No unambiguous active buyer packaging request in the quote.'
        return item
    if item.get('buyer_role') not in ('buyer', 'brand_buyer'):
        item['verification'] = 'Authorized procurement role needs manual verification.'
        return item
    item['opportunity_tier'] = 'A'
    item['procurement_status'] = 'demand_verified_window_unconfirmed'
    item['verification'] = 'Buyer-site procurement quote verified; ask whether the window is still open.'
    try:
        published = datetime.fromisoformat(str(item.get('published_at',''))[:10]).date()
        age = (datetime.now(timezone.utc).date() - published).days
    except ValueError:
        age = 9999
    if age > 180 and str(item.get('published_at') or '').lower() not in ('', 'unknown', 'not stated'):
        item['opportunity_tier'] = 'C'
        item['procurement_status'] = 'historical_or_date_unverified'
        item['verification'] = 'Old or invalid publication date; current demand must be reconfirmed.'
        return item
    opened = plain(str(item.get('open_window_evidence') or ''))
    known = [item.get(k) for k in ('requested_product','quantity','specifications','arrival_requirement')]
    known = [v for v in known if v and str(v).lower() not in ('unknown','not stated','n/a')]
    # Recent publication, exact acceptance wording and two cited requirements are all necessary.
    if requested == 'A+' and 0 <= age <= 30 and str(published) in text and len(opened) >= 20 and opened in text and re.search(r'(?:accepting|inviting|submit|open for).{0,50}(?:quotes|quotations|suppliers|proposals|bids)', opened) and len(known) >= 2 and all(plain(str(v)) in text for v in known):
        item['opportunity_tier'] = 'A+'
        item['procurement_status'] = 'open_verified'
        item['verification'] = 'Recent dated buyer source, open-window quote and at least two requirements verified.'
    return item

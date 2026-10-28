"""Additive company identity aliases; never changes established account ownership."""
import re,time
from .evidence import company_key
_MX_CACHE={}

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS companies(company_key TEXT PRIMARY KEY,canonical_id TEXT NOT NULL,account TEXT NOT NULL DEFAULT "")')
    db.execute('CREATE TABLE IF NOT EXISTS contact_aliases(alias_id TEXT PRIMARY KEY,company_key TEXT NOT NULL,canonical_id TEXT NOT NULL)')

def register(db,domain,identifier,account=''):
    schema(db);key=company_key(domain if '://' in domain else 'https://'+domain)
    if not key:raise ValueError('company domain required')
    db.execute('INSERT OR IGNORE INTO companies VALUES(?,?,?)',(key,str(identifier),account))
    canonical=db.execute('SELECT canonical_id FROM companies WHERE company_key=?',(key,)).fetchone()[0]
    db.execute('INSERT OR IGNORE INTO contact_aliases VALUES(?,?,?)',(str(identifier),key,canonical))
    return canonical

def email_quality(email,mx_lookup=None):
    value=str(email).strip().lower()
    if not re.fullmatch(r'[^\s@;<>]+@[^\s@;<>]+\.[^\s@;<>]+',value):return dict(status='invalid',role='none',reason='INVALID_SYNTAX')
    local,domain=value.split('@')
    excluded={'press','media','privacy','dpo','jobs','hr','careers','career','recruitment','recruiting','noreply','no-reply'}
    generic={'info','sales','hello','contact','business','office','enquiries','inquiries'}
    role='excluded' if local in excluded else 'customer_service' if local in {'support','help','care','customerservice'} else 'generic_company' if local in generic else 'unverified_person'
    if role=='excluded':return dict(status='invalid',role=role,reason='EXCLUDED_CHANNEL')
    cacheable=mx_lookup is None
    cached=_MX_CACHE.get(domain) if cacheable else None
    if cached and cached[0]>time.monotonic():return dict(cached[1],role=role)
    if mx_lookup is None:
        # DNS is a read-only quality check, never SMTP recipient probing.
        try:
            import dns.resolver
            mx_lookup=lambda host:list(dns.resolver.resolve(host,'MX',lifetime=5))
        except ImportError:return dict(status='pending_review',role=role,reason='MX_CHECK_UNAVAILABLE')
    try:mx=mx_lookup(domain)
    except Exception:return dict(status='pending_review',role=role,reason='MX_CHECK_UNAVAILABLE')
    result=dict(status='valid' if mx else 'invalid',role=role,reason='MX_PRESENT' if mx else 'NO_MX')
    if cacheable:
        if len(_MX_CACHE)>1000:_MX_CACHE.clear()
        _MX_CACHE[domain]=(time.monotonic()+3600,result)
    return result

"""Optional additional send gates. Existing limits and suppression always remain."""
import datetime,time
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pipeline_core import features
ZONES={'US':['America/New_York','America/Chicago','America/Denver','America/Los_Angeles','America/Anchorage','Pacific/Honolulu'],
 'UK':['Europe/London'],'GB':['Europe/London'],'AU':['Australia/Sydney','Australia/Adelaide','Australia/Perth'],
 'DE':['Europe/Berlin'],'FR':['Europe/Paris'],'NL':['Europe/Amsterdam'],'IT':['Europe/Rome'],'ES':['Europe/Madrid','Atlantic/Canary'],
 'IE':['Europe/Dublin'],'BE':['Europe/Brussels'],'SE':['Europe/Stockholm'],'DK':['Europe/Copenhagen'],'PL':['Europe/Warsaw'],'AT':['Europe/Vienna'],'CH':['Europe/Zurich'],'FI':['Europe/Helsinki'],'NO':['Europe/Oslo'],'PT':['Europe/Lisbon','Atlantic/Azores']}
def local_window(p,now=None):
    now=now or datetime.datetime.now(datetime.timezone.utc)
    zone=p.get('verified_timezone')
    zones=[zone] if zone else ZONES.get(str(p.get('country','')).upper(),[])
    if not zones:return False
    try:
        for name in zones:
            local=now.astimezone(ZoneInfo(name));minute=local.hour*60+local.minute
            if local.weekday()>4 or not (540<=minute<690 or 810<=minute<960):return False
    except ZoneInfoNotFoundError:return False
    return True

def check(account,lead):
    if not features.enabled('send_guard'):return ''
    from . import store
    p=lead.get('data',{}).get('prospect',{})
    if not local_window(p):return 'recipient_local_hours'
    now=time.time();key='guard_started_'+account['id'];started=store.get(key)
    if not started:started=now;store.put(key,started)
    cap=min(60,20+5*int((now-started)//86400))
    configured=int(account.get('daily_limit') or 0)
    if configured:cap=min(cap,configured)
    if store.sent_today(account['id'])>=cap:return 'warmup_daily_limit'
    last=store.q('SELECT result FROM send_attempts WHERE account=? AND finished IS NOT NULL ORDER BY finished DESC LIMIT 50',(account['id'],))
    if any(x['result']=='auth_error' for x in last) or (len(last)==50 and sum(x['result']=='bounced' for x in last)/50>.03):
        store.put('paused_'+account['id'],True);store.put('guard_alert_'+account['id'],'Authentication failure or bounce threshold');return 'guard_auto_paused'
    domain=lead.get('domain','')
    recent=store.q("SELECT MAX(a.finished) t FROM send_attempts a JOIN leads l ON l.id=a.lead WHERE l.domain=? AND a.result IN ('sent','unknown')",(domain,),one=True)
    if recent and recent['t'] and now-recent['t']<features.option('recipient_domain_interval_seconds',900):return 'recipient_domain_interval'
    return ''

def dns_check(account,lookup=None):
    address=account.get('sender') or account.get('email') or account.get('from_email') or ''
    domain=address.partition('@')[2]
    if not domain:return dict(status='unknown',reason='sender_domain_missing')
    if lookup is None:
        try:
            import dns.resolver
            lookup=lambda name:[str(r).replace('"','') for r in dns.resolver.resolve(name,'TXT',lifetime=5)]
        except ImportError:return dict(domain=domain,status='unknown',reason='dns_dependency_unavailable')
    result=dict(domain=domain,checked_at=time.time(),note='DNS records are not proof of message authentication or delivery')
    selector=account.get('dkim_selector')
    for kind,name,prefix in [('spf',domain,'v=spf1'),('dmarc','_dmarc.'+domain,'v=DMARC1'),('dkim',str(selector)+'._domainkey.'+domain,'v=DKIM1')]:
        if kind=='dkim' and not selector:result[kind]='selector_unknown';continue
        try:result[kind]='record_present' if any(prefix.lower() in r.lower() for r in lookup(name)) else 'record_not_found'
        except Exception:result[kind]='lookup_unavailable'
    return result

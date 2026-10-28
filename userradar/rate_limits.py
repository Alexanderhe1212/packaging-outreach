"""Remember actual per-website Retry-After deadlines; never retry early."""
import datetime
import math
import threading
import time
from urllib.parse import urlsplit
from email.utils import parsedate_to_datetime

LOCK=threading.RLock()
COOLDOWNS={}


def parse_retry_after(value):
    if not isinstance(value,str) or not value.strip():return None
    try:return max(0,int(value))
    except ValueError:
        try:return max(0,parsedate_to_datetime(value).timestamp()-time.time())
        except (ValueError,TypeError,OverflowError):return None


def key(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')


class RateLimited(ValueError):
    def __init__(self, entry, cached=False):
        remaining=max(0,math.ceil(entry['until']-time.monotonic()))
        self.http_status=429
        self.retry_after_seconds=entry['requested_wait']
        self.remaining_retry_seconds=remaining
        self.retry_at=entry['retry_at']
        self.rate_limit_cache_hit=cached
        self.response_server=entry.get('response_server','')
        message=('该官网仍在限流冷却中，约'+str(remaining)+'秒后可重试；本轮未访问网站。') if cached else (
            '官网 HTTP 429 要求等待'+str(self.retry_after_seconds)+'秒；仍需约'+str(remaining)+'秒，已保留本轮已得信息。')
        super().__init__(message)


def _prune():
    now=time.monotonic()
    for domain in list(COOLDOWNS):
        if COOLDOWNS[domain]['until']<=now:del COOLDOWNS[domain]


def observe(url, seconds, response_server=''):
    seconds=float(seconds)
    if not math.isfinite(seconds) or seconds<0:raise ValueError('限流等待时间无法确认，本轮停止')
    now=time.monotonic()
    with LOCK:
        _prune()
        entry={'until':now+seconds,'requested_wait':int(math.ceil(seconds)),
               'retry_at':datetime.datetime.fromtimestamp(time.time()+seconds,datetime.timezone.utc).isoformat(),
               'response_server':str(response_server)[:80]}
        previous=COOLDOWNS.get(key(url))
        if previous and previous['until']>entry['until']:entry=previous
        COOLDOWNS[key(url)]=entry
        return RateLimited(entry)


def check(url):
    with LOCK:
        _prune()
        entry=COOLDOWNS.get(key(url))
        if entry:raise RateLimited(entry,cached=True)


def share_observed_cooldown(alias_url,observed_url):
    """Copy the verified canonical site's existing deadline, never restart it."""
    with LOCK:
        _prune()
        entry=COOLDOWNS.get(key(observed_url))
        previous=COOLDOWNS.get(key(alias_url))
        if entry and (not previous or entry['until']>previous['until']):
            COOLDOWNS[key(alias_url)]=entry


def details(error):
    return {name:getattr(error,name) for name in ('http_status','retry_after_seconds',
            'remaining_retry_seconds','retry_at','rate_limit_cache_hit','response_server') if hasattr(error,name)}

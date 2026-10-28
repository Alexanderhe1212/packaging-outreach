"""One bounded retry policy. Waiting is not an attempt; ambiguous writes need review."""
import datetime
import email.utils
import time
import socket
import urllib.error

CODES = {'RATE_LIMITED','TIMEOUT','NETWORK','BLOCKED','NO_PUBLIC_EMAIL',
         'EVIDENCE_MISMATCH','IMAGE_QC_FAILED','RETRY_EXHAUSTED','PERMANENT_EXCLUDE',
         'POST_UNKNOWN','JOB_EXPIRED'}

def timestamp(value):
    try:return max(0, float(value or 0))
    except (TypeError,ValueError):
        try:return datetime.datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
        except (TypeError,ValueError):return 0

def classify(error):
    if isinstance(error,str) and error in CODES:return error
    seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        code=getattr(error,'code',None)
        if code==429:return 'RATE_LIMITED'
        if code==403:return 'BLOCKED'
        if isinstance(error,(TimeoutError,socket.timeout)):return 'TIMEOUT'
        if isinstance(error,(ConnectionError,urllib.error.URLError)) or code in (408,500,502,503,504):return 'NETWORK'
        error=getattr(error,'__cause__',None) or getattr(error,'__context__',None)
    return 'EVIDENCE_MISMATCH'

def decide(error, retry_count=0, *, now=None, deferred=False, deadline=0, jitter=0):
    now=time.time() if now is None else now
    count=max(0,int(retry_count));reason=classify(error)
    until=max(timestamp(deadline),timestamp(vars(error).get('retry_at',0) if hasattr(error,'__dict__') else 0))
    headers=getattr(error,'headers',None) or {}
    value=headers.get('Retry-After')
    if value:
        try:until=max(until,now+max(0,float(value)))
        except (TypeError,ValueError):
            try:until=max(until,email.utils.parsedate_to_datetime(value).timestamp())
            except (TypeError,ValueError,OverflowError):pass
    out=dict(reason_code=reason,retry_count=count,next_retry_at=0,last_error=str(error)[:300],action='review')
    if deferred:
        out.update(action='retry',next_retry_at=max(now+5,until));return out
    if reason in ('RATE_LIMITED','TIMEOUT','NETWORK'):
        budget=6 if reason=='RATE_LIMITED' else 3
        if count>=budget:out['reason_code']='RETRY_EXHAUSTED';return out
        delay=min(21600,300*2**count*(1+max(0,min(float(jitter),.25))))
        out.update(action='retry',retry_count=count+1,next_retry_at=max(now+delay,until))
    elif reason=='NO_PUBLIC_EMAIL':out.update(action='contacts',recheck_after=now+30*86400)
    elif reason=='IMAGE_QC_FAILED':out['action']='image'
    elif reason=='PERMANENT_EXCLUDE':out['action']='exclude'
    elif reason=='BLOCKED':out['recheck_after']=now+30*86400
    return out

def excluded(record, *, now=None):
    now=time.time() if now is None else now
    if not record.get('reason_code'):return True
    if record['reason_code'] not in {'NO_PUBLIC_EMAIL','TIMEOUT','NETWORK','BLOCKED','RATE_LIMITED','RETRY_EXHAUSTED','EVIDENCE_MISMATCH'}:return True
    after=timestamp(record.get('recheck_after'))
    return not after or after>now

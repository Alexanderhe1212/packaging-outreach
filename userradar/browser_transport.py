"""Bounded fallback following normal browser behavior; no challenge solving."""
import json,subprocess,threading,os,signal,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
NODE='node'
LOCAL=threading.local()

def check_budget():
    cancel=getattr(LOCAL,'cancel',None)
    if cancel and (cancel.is_set() if hasattr(cancel,'is_set') else cancel()):
        raise ValueError('本轮查询已停止')
    deadline=getattr(LOCAL,'deadline',None)
    if deadline is not None and time.monotonic()>=deadline:
        raise ValueError('本轮查询时间已到，保留已核实结果')

def budget_remaining(cap=None):
    check_budget()
    deadline=getattr(LOCAL,'deadline',None)
    left=max(0,deadline-time.monotonic()) if deadline is not None else None
    return cap if left is None else left if cap is None else min(cap,left)

def budget_wait(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        check_budget()
        time.sleep(min(.1,end-time.monotonic(),budget_remaining(.1)))
    check_budget()

def reset_budget():
    # SourceReader resets fallback counters, not its caller's deadline/cancel scope.
    LOCAL.count=0
    LOCAL.browser_mode=False
    LOCAL.blocked=False

def _stop_owned(p):
    # start_new_session makes this PID our isolated process group, including Chrome.
    try:os.killpg(p.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:p.communicate(timeout=.5)
    except subprocess.TimeoutExpired:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.communicate(timeout=2)

def installed_browser_available():
    from crawl4ai_bridge import available as crawl_available
    from easyspider_bridge import available as easy_available
    return crawl_available() or easy_available()

def fetch_browser(url,domain):
    from app import public_url,host
    from rate_limits import check as check_cooldown
    check_cooldown(url)
    check_budget()
    public_url(url)
    if host(url)!=domain:raise ValueError('浏览器读取仅支持同域网页')
    if getattr(LOCAL,'count',0)>=4:raise ValueError('本轮浏览器补查已达上限')
    LOCAL.count=getattr(LOCAL,'count',0)+1
    from crawl4ai_bridge import available as crawl_available,fetch as capture_crawl
    if not url.split('?')[0].endswith('/robots.txt') and crawl_available():
        return capture_crawl(url,domain)
    from easyspider_bridge import available,fetch as capture_easyspider
    if not url.split("?")[0].endswith("/robots.txt") and available():
        return capture_easyspider(url,domain)
    timeout=budget_remaining(48)
    end=time.monotonic()+timeout
    p=subprocess.Popen([NODE,str(ROOT/'browser_fetch.cjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    first=True
    try:
        while True:
            check_budget()
            remaining=min(end-time.monotonic(),budget_remaining(48))
            if remaining<=0:raise ValueError('浏览器读取超时，已结束本轮读取进程')
            try:
                out,err=p.communicate(json.dumps({'url':url,'timeout_ms':max(1,int(timeout*1000))}) if first else None,timeout=min(.1,remaining))
                break
            except subprocess.TimeoutExpired:
                first=False
    except BaseException:
        _stop_owned(p)
        raise
    if p.returncode:raise ValueError('浏览器未能读取该页：'+err[-200:])
    check_budget()
    data=json.loads(out)
    if data.get('status')==429:
        LOCAL.blocked=True
        from rate_limits import parse_retry_after,observe
        delay=parse_retry_after(data.get('retry_after'))
        if delay is not None:raise observe(url,delay,data.get('server',''))
        error=ValueError('浏览器返回 HTTP 429；未绕过限制')
        error.http_status=429
        raise error
    if data.get('status')!=200:raise ValueError('浏览器返回 HTTP '+str(data.get('status'))+'；未绕过限制')
    if host(data['url'])!=domain:raise ValueError('浏览器跳转到不同域名，未采用结果')
    return data['text'] if url.split('?')[0].endswith('/robots.txt') else data['html']

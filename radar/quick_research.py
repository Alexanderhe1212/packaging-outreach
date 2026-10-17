"""Bounded website lane, independent of long AI searches. No model calls here."""
import copy
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit

from contact_progress import mark_progress

LOCK = threading.RLock()
WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix='website')
SLOTS = threading.BoundedSemaphore(6)
JOBS = OrderedDict()
CACHE = OrderedDict()
ACTIVE_LIMIT = 6
HISTORY_LIMIT = 40
CACHE_LIMIT = 32
CACHE_TTL = 300
TERMINAL = {'done', 'cancelled', 'error'}


def cache_key(raw):
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2048:
        raise ValueError('请填写有效的公司官网地址。')
    value = raw.strip()
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError('请输入普通的公司官网地址（http/https）。')
    # Do not collapse distinct schemes, www hosts, paths or query parameters.
    # Network/public-address validation still happens in the website reader.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', parsed.query, ''))


def _snapshot(job):
    now = job.get('ended') or time.monotonic()
    metrics = copy.deepcopy(job['metrics'])
    metrics['elapsed_seconds'] = round(now - job['submitted'], 3)
    metrics['queue_seconds'] = round((job.get('started') or now) - job['submitted'], 3)
    return {'id': job['id'], 'status': job['status'],
            'report': copy.deepcopy(job.get('report')), 'metrics': metrics,
            'error_metadata':copy.deepcopy(job.get('error_metadata',{})),
            'progress': job['progress'], 'error': job.get('error', '')}


def get_job(job_id):
    with LOCK:
        if job_id not in JOBS:
            raise ValueError('官网查询不存在或已过期，请重新查询。')
        return _snapshot(JOBS[job_id])


def start_job(url, refresh=False):
    key = cache_key(url)
    with LOCK:
        now = time.monotonic()
        for old_key in list(CACHE):
            if now - CACHE[old_key]['saved'] >= CACHE_TTL:
                del CACHE[old_key]
        entry = None if refresh else CACHE.get(key)
        if not entry and not SLOTS.acquire(blocking=False):
            raise ValueError('官网查询队列已满，请等待现有查询完成。')
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'status': 'queued', 'submitted': now,
               'cancel': threading.Event(), 'progress': '等待官网读取名额',
               'metrics': {'first_result_seconds': None, 'core_complete_seconds': None,
                           'cache_hit': False, 'source_checked_at': None,
                           'website_fetch_attempts': 0,
                           'ai_calls': 0, 'input_tokens': 0, 'output_tokens': 0}}
        JOBS[job_id] = job
        while len(JOBS) > HISTORY_LIMIT:
            expired = next((k for k, j in JOBS.items() if j['status'] in TERMINAL and not j.get('pending')), None)
            if expired is None:
                break
            del JOBS[expired]
        if entry:
            job.update(report=copy.deepcopy(entry['report']), status='done', started=now, ended=now,
                       progress='使用五分钟内的已核实官网结果')
            job['metrics'].update(cache_hit=True, source_checked_at=entry['report'].get('checked_at'),
                                  first_result_seconds=0.0, cache_age_seconds=round(now-entry['saved'], 3),
                                  core_complete_seconds=0.0 if entry['report'].get('core_people') else None)
            CACHE.move_to_end(key)
        else:
            job['pending'] = True
            # UI termination is bounded even if a system DNS call stalls. The
            # admission slot remains held until the worker actually exits.
            job['watchdog'] = threading.Timer(75, _timeout, args=(job_id, '排队及官网读取总等待超时'))
            job['watchdog'].daemon = True
            job['watchdog'].start()
            WORKERS.submit(_run, job_id, key)
        return {'id': job_id, 'cache_hit': bool(entry)}


def stop_job(job_id):
    with LOCK:
        if job_id not in JOBS:
            raise ValueError('官网查询不存在或已过期。')
        job = JOBS[job_id]
        if job['status'] not in TERMINAL:
            job['cancel'].set()
            job.update(status='cancelled', ended=time.monotonic(), progress='已停止，保留已核实结果')
        return _snapshot(job)


def _timeout(job_id, reason):
    with LOCK:
        job = JOBS.get(job_id)
        if job and job['status'] not in TERMINAL:
            job['cancel'].set()
            job.update(status='error', ended=time.monotonic(), error=reason,
                       progress='已停止等待，保留已核实结果')


def _publish(job_id, report):
    report = mark_progress(copy.deepcopy(report))
    with LOCK:
        job = JOBS[job_id]
        if job['status'] in TERMINAL:
            return
        job['report'] = report
        elapsed = round(time.monotonic() - job['submitted'], 3)
        if report['useful_partial'] and job['metrics']['first_result_seconds'] is None:
            job['metrics']['first_result_seconds'] = elapsed
        if report['core_people'] and job['metrics']['core_complete_seconds'] is None:
            job['metrics']['core_complete_seconds'] = elapsed
        job['metrics']['source_checked_at'] = report.get('checked_at')
        job['metrics']['website_fetch_attempts'] = report.get('website_fetch_attempts', 0)
        job['progress'] = '已读取 %d 个官网页面，继续核对公开字段' % len(report.get('pages', []))


def _run(job_id, key):
    try:
        _read(job_id, key)
    finally:
        with LOCK:
            job = JOBS[job_id]
            job['watchdog'].cancel()
            if job.get('read_watchdog'):
                job['read_watchdog'].cancel()
            job['pending'] = False
        SLOTS.release()


def _read(job_id, key):
    from app import research
    with LOCK:
        job = JOBS[job_id]
        if job['cancel'].is_set():
            return
        job.update(status='running', started=time.monotonic(), progress='读取官网及公开联系页面')
        job['read_watchdog'] = threading.Timer(46, _timeout, args=(job_id, '官网读取超过45秒预算'))
        job['read_watchdog'].daemon = True
        job['read_watchdog'].start()
    try:
        report = research(key, cancel=job['cancel'], max_seconds=45,
                          on_update=lambda r: _publish(job_id, r), core_first=True)
        _publish(job_id, report)
        with LOCK:
            if job['cancel'].is_set():
                return
            job.update(status='done', ended=time.monotonic(), progress='官网阶段完成')
            if report.get('useful_partial') and not report.get('budget_exhausted') and not report.get('cancelled'):
                CACHE[key] = {'saved': time.monotonic(), 'report': copy.deepcopy(report)}
                CACHE.move_to_end(key)
                while len(CACHE) > CACHE_LIMIT:
                    CACHE.popitem(last=False)
    except Exception as error:
        from rate_limits import details
        with LOCK:
            if not job['cancel'].is_set():
                job.update(status='error', ended=time.monotonic(), error=str(error)[:300],
                           error_metadata=details(error),
                           progress='官网读取失败，已核实结果保留')

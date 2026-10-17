"""Persistent operational issues; retrying is not the same as resolved."""
import time
KEY = 'problem_log_v1'

def reconcile(log, leads, now):
    log = {key: dict(value) for key, value in log.items()}
    for lead in leads:
        key = str(lead['id'])
        status = lead['status']
        if key not in log and status not in ('failed', 'unknown'):
            continue
        issue = log.setdefault(key, dict(first_seen=now, reason='', state='open'))
        issue.update({k: lead.get(k, '') for k in ('id','company','email','account','status')})
        if lead.get('error'):
            issue['reason'] = lead['error']
        old = issue['state']
        issue['state'] = ('resolved' if status in ('sent','replied') else
                          'retrying' if status in ('queued','researching','writing','imaging','ready','sending') else 'open')
        if old != issue['state']:
            issue['changed_at'] = now
        if issue['state'] == 'resolved':
            issue.setdefault('resolved_at', now)
        else:
            issue.pop('resolved_at', None)
    return log

def overview(_query=None):
    from . import store
    with store._lock:
        old = store.get(KEY, {})
        leads = store.q('SELECT id,company,email,account,status,error,updated_at FROM leads')
        log = reconcile(old, leads, time.time())
        if log != old:
            store.put(KEY, log)
    items = sorted(log.values(), key=lambda x: (x['state']=='resolved', -x.get('changed_at',x['first_seen'])))
    return dict(items=items, open=sum(x['state']!='resolved' for x in items), resolved=sum(x['state']=='resolved' for x in items))

def add(data):
    import uuid
    from . import store
    title = str(data.get('title','')).strip()[:150]
    if not title:
        raise ValueError('请填写问题标题')
    key = 'manual-' + uuid.uuid4().hex
    item = dict(id=key, company=title, reason=str(data.get('detail','')).strip()[:3000],
                account='手动记录', email='', status='manual', state='open', first_seen=time.time())
    with store._lock:
        log = store.get(KEY, {}); log[key] = item; store.put(KEY, log)
    return item

def resolve(data):
    from . import store
    key = str(data.get('id',''))
    if not key.startswith('manual-'):
        raise ValueError('客户失败记录按实际结果更新，不能手动掩盖')
    resolution = str(data.get('resolution','')).strip()[:3000]
    if not resolution:
        raise ValueError('请记录如何解决')
    with store._lock:
        log = store.get(KEY, {})
        if key not in log:raise ValueError('问题不存在')
        log[key].update(state='resolved', resolution=resolution, resolved_at=time.time())
        store.put(KEY, log)
    return {'ok':True}

"""Persistent operational issues; retrying is not the same as resolved."""
import time
import re
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
        issue['next_check_at'] = lead.get('next_check_at') or 0
        issue['reason_code'] = lead.get('reason_code') or ''
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

def category(item, now):
    if item.get('state')=='resolved':return 'resolved'
    if item.get('status') in ('skipped','bounced','unsubscribed') or '已抑制' in item.get('reason',''):return 'protected'
    if item.get('status')=='queued' and item.get('next_check_at',0)>now:return 'waiting'
    if item.get('reason_code') in ('BLOCKED','EVIDENCE_MISMATCH','RETRY_EXHAUSTED','POST_UNKNOWN','JOB_EXPIRED'):return 'review'
    if item.get('state')=='retrying':return 'retrying'
    if item.get('status')=='failed' and re.search(
            r'未找到官网|没有可验证|邮箱来源未验证|联系人邮箱原文|联系人身份来源|'
            r'HTTP.*(?:403|404|429)|自动补查已达上限|包装匹配度|官网跳转|域名停放',
            item.get('reason','')):
        return 'review'
    return 'attention'


def retry_action(lead):
    # A failed concept may have an incorrect plan too: rebuild both using saved facts.
    reason = lead.get('error', '')
    return 'write' if 'Concept image review failed:' in reason else 'research'

def issue_group(item):
    reason = item.get('reason', '')
    if item.get('status')=='unknown':return '发送结果待核实'
    if '429' in reason or '限流' in reason or item.get('category')=='waiting':return '来源限流与等待'
    if '联系人' in reason and ('原文' in reason or '身份' in reason):return '称呼与身份待核实'
    if '邮箱' in reason and ('未找到' in reason or '未验证' in reason or '没有' in reason):return '公开邮箱待补查'
    if '403' in reason or '404' in reason:return '官网访问受限'
    if '产品' in reason or '套装' in reason:return '产品与数量核实'
    if 'Codex' in reason or 'AI ' in reason:return 'AI 服务与生成'
    if 'image' in reason.lower() or '图片' in reason:return '图片质量复核'
    return '其他记录'

def overview(_query=None):
    from . import store
    with store._lock:
        old = store.get(KEY, {})
        leads = store.q("SELECT id,company,email,account,status,error,updated_at,json_extract(data,'$.reason_code') AS reason_code,COALESCE(json_extract(data,'$.research_retry_at'),0) AS next_check_at FROM leads")
        log = reconcile(old, leads, time.time())
        if log != old:
            store.put(KEY, log)
    items = sorted(log.values(), key=lambda x: (x['state']=='resolved', -x.get('changed_at',x['first_seen'])))
    for item in items:
        item['category']=category(item,time.time())
        item['group']=issue_group(item)
    counts={name:sum(item['category']==name for item in items) for name in ('attention','review','waiting','retrying','protected','resolved')}
    return dict(counts=counts,items=items, open=sum(x['state']!='resolved' for x in items), resolved=sum(x['state']=='resolved' for x in items))

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

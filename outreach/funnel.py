"""Observed event funnel; historical replies remain explicitly unclassified."""
import collections,json,statistics,time
from . import store
STAGES=[('discovered','发现公司'),('fit_status','适配通过'),('email_evidence','邮箱核实'),('contact_identity','具名采购'),('saved','保存'),('handoff','交接'),('ready','图文完成'),('smtp_accept','SMTP 接受')]

def report(query=None):
    query=query or {};filters={k:v[0] if isinstance(v,list) else v for k,v in query.items()}
    since=time.time()-max(1,min(90,int(filters.get('days',7))))*86400
    rows=store.q('SELECT e.*,l.data,l.domain FROM lead_events e LEFT JOIN leads l ON CAST(l.id AS TEXT)=CAST(e.lead_id AS TEXT) WHERE e.created_at>=?',(since,))
    accepted=[]
    for row in rows:
        data=json.loads(row.get('data') or '{}');p=data.get('prospect') or {};manual=(data.get('manual') or {}).get('radar') or {}
        values=dict(account=row.get('account'),region=p.get('country',''),tier=(manual.get('priority_score') or p.get('priority_score') or {}).get('tier',''),keyword=manual.get('search_keyword',''),variant=(data.get('plan') or {}).get('variant_id',''))
        if all(not filters.get(k) or str(v)==str(filters[k]) for k,v in values.items()):accepted.append(row)
    buckets=collections.defaultdict(list)
    for row in accepted:
        stage=row['stage'];status=row['status']
        if stage=='lead':
            if status in ('queued','radar_review','writing'):buckets['saved'].append(row)
            if status=='ready':buckets['ready'].append(row)
        elif stage in ('fit_status','email_evidence','contact_identity'):
            if status in ('passed','public_verified','named_buyer'):buckets[stage].append(row)
        else:buckets[stage].append(row)
    result=[]
    for stage,label in STAGES:
        selected=buckets[stage];durations=[r['duration_ms'] for r in selected if r['duration_ms'] is not None]
        result.append(dict(stage=stage,label=label,count=len({str(r['lead_id']) for r in selected if r['lead_id'] is not None}),median_ms=statistics.median(durations) if durations else None))
    replies=collections.Counter(r['status'] for r in buckets['reply'])
    historical=store.q("SELECT count(*) n FROM leads l WHERE reply_at IS NOT NULL AND NOT EXISTS(SELECT 1 FROM inbox_events i WHERE i.lead_id=l.id)"+(' AND account=?' if filters.get('account') else ''),([filters['account']] if filters.get('account') else []),one=True)['n']
    failures=collections.Counter(r['reason_code'] for r in accepted if r['status'] in ('failed','blocked','review','unknown'))
    inquiries=store.q("SELECT id,account,company,reply_excerpt FROM leads WHERE json_extract(data,'$.inquiry_status')='interested' ORDER BY reply_at DESC LIMIT 100")
    referrals=[json.loads(r['value']) for r in store.q("SELECT value FROM kv WHERE key LIKE 'referral:%'")]
    return dict(referrals=referrals,stages=result,replies=dict(replies),historical_unclassified=historical,top_failures=failures.most_common(10),inquiries=inquiries,as_of=time.time(),note='事件记录范围内统计；SMTP 接受不等于送达。缺少耗时显示未测量。',variant_status='样本不足' if len({r['lead_id'] for r in buckets['smtp_accept']})<20 else '仅观测，不推断因果')

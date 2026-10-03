"""Measured latency and cadence. A target is never a forced cancellation timer."""
import math,time


def distribution(values):
    values = sorted(values)
    def percentile(p):
        return round(values[max(0, math.ceil(p * len(values)) - 1)], 2) if values else None
    return {'count': len(values), 'p50_seconds': percentile(.5), 'p95_seconds': percentile(.95)}


def report(store, target=300, now=None):
    now = time.time() if now is None else now
    with store.db() as c:
        rows = [dict(r) for r in c.execute('''SELECT j.id,j.brand,j.stage,j.state,j.updated,t.origin,
            a.result,a.updated AS accepted_at,
            json_extract(j.payload,'$.delivery.result') AS delivery
            FROM jobs j LEFT JOIN timing t ON t.job_id=j.id LEFT JOIN attempts a ON a.job_id=j.id
            WHERE j.company_key!='' ORDER BY j.updated DESC LIMIT 500''')]
        stages = [dict(r) for r in c.execute('SELECT stage,started,ended,outcome FROM stage_times ORDER BY id DESC LIMIT 2000')]
        calls = [dict(r) for r in c.execute('SELECT stage,started,ended,state FROM runs ORDER BY started DESC LIMIT 2000')]
    brands = {}
    for row in rows:
        b = brands.setdefault(row['brand'], {'accepted': [], 'prepared': [], 'accepted_at': [], 'active': 0, 'over_target': 0, 'unknown': 0, 'blocked': 0, 'unmeasured_legacy': 0})
        if row['result'] == 'accepted':
            b['accepted_at'].append(row['accepted_at'])
            if row['origin'] is not None:b['accepted'].append(max(0, row['accepted_at'] - row['origin']))
            else:b['unmeasured_legacy'] += 1
        elif row['delivery'] == 'spooled':
            if row['origin'] is not None:b['prepared'].append(max(0, row['updated'] - row['origin']))
        elif row['state'] in ('queued', 'running'):
            b['active'] += 1
            if row['origin'] is not None and now - row['origin'] > target:b['over_target'] += 1
        elif row['state'] in ('unknown', 'blocked'):
            b[row['state']] += 1
    result = {}
    for brand, values in brands.items():
        times = sorted(values['accepted_at'])
        result[brand] = {
            'accepted_count': len(values['accepted_at']),
            'accepted_end_to_end': distribution(values['accepted']),
            'prepared_end_to_end': distribution(values['prepared']),
            'accepted_interval': distribution([b-a for a,b in zip(times,times[1:])]),
            'accepted_within_target': sum(x <= target for x in values['accepted']),
            **{k: values[k] for k in ('active', 'over_target', 'unknown', 'blocked', 'unmeasured_legacy')},
        }
    def timings(data, finished):
        names = sorted({r['stage'] for r in data})
        return {stage: distribution([max(0,r['ended']-r['started']) for r in data if r['stage']==stage and r['ended'] is not None and finished(r)]) for stage in names}
    return {'target_seconds': target, 'target_is_cancellation_timeout': False,
            'window': 'most recent 500 customer jobs / 2000 stage records',
            'brands': result, 'stages': timings(stages,lambda r:True),
            'completed_api_calls': timings(calls,lambda r:r['state']=='complete'),
            'unknown_api_calls': sum(r['state']=='unknown' for r in calls)}

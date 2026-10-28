"""Evidence-based prioritization; score is never permission to send."""
from datetime import datetime,timezone
from . import features

def score(record,now=None):
    now=now or datetime.now(timezone.utc)
    weights=features.option('score_weights',{})
    defaults=dict(fit=30,signal=25,contact=25,scale=10,freshness=10)
    weights={k:max(0,min(100,float(weights.get(k,v)))) for k,v in defaults.items()}
    parts={}
    def add(key,fraction,source='',state='verified'):
        parts[key]=dict(points=round(weights[key]*fraction,2),source_url=source,state=state)
    fit_source=record.get('fit_source') or record.get('product_url') or ''
    add('fit',1 if fit_source and record.get('fit_status')=='passed' else 0,fit_source,'verified' if fit_source else 'unknown')
    signal_source=record.get('signal_source') or ''
    signal=record.get('purchase_signal') or record.get('signal_type')
    add('signal',1 if signal_source and signal=='confirmed_procurement' and record.get('evidence_quote') else 0,signal_source,'verified' if signal_source else 'unknown')
    identity=record.get('contact_identity','none');source=record.get('identity_source','')
    fraction={'named_buyer':1,'named_other':.65,'generic_company':.32}.get(identity,0)
    if identity.startswith('named_') and not source:fraction=0
    add('contact',fraction,source,'verified' if source or identity=='generic_company' else 'unknown')
    source=record.get('scale_source','')
    add('scale',1 if source and record.get('scale_verified') is True else 0,source,'verified' if source and record.get('scale_verified') is True else 'unknown')
    try:
        date=datetime.fromisoformat(record.get('published_at','').replace('Z','+00:00'))
        if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
        days=max(0,(now-date).total_seconds()/86400)
        add('freshness',1 if days<=30 else .7 if days<=90 else .2,signal_source)
    except (ValueError,TypeError):add('freshness',.5,state='unknown')
    total=round(sum(p['points'] for p in parts.values()),2)
    return dict(total=total,tier='A' if total>=features.option('score_a_threshold',75) else 'B' if total>=features.option('score_b_threshold',45) else 'C',components=parts)

def keyword_metrics(history,leads):
    """Only observed cohorts; automatic/unknown replies never count as human."""
    result={};by_domain={x.get('domain'):x for x in leads}
    for row in history:
        keyword=row.get('search_keyword')
        if not keyword:continue
        item=result.setdefault(keyword,dict(candidates=0,saved=0,human_replies=0))
        item['candidates']+=1;item['saved']+=bool(row.get('saved_ids'))
        lead=by_domain.get(row.get('domain'),{})
        classification=(lead.get('data') or {}).get('reply_classification','')
        item['human_replies']+=classification.startswith('human_')
    for item in result.values():
        item['weight']=1+(item['saved']+2*item['human_replies'])/(item['candidates']+3)
        if item['candidates']>=10 and not item['saved']:item['weight']=.25
        item['sample_status']='sufficient' if item['candidates']>=20 else 'insufficient'
    return result

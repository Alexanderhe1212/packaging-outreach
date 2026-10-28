"""Opt-in, pre-rendered follow-ups; no preparation happens during SMTP send."""
import copy,time
from pathlib import Path
from pipeline_core import features
from . import store,config,pipeline
from .reply_classification import followup_allowed

def candidate(account):
    if not features.enabled('auto_followup'):return None
    for row in store.q("SELECT id FROM leads WHERE account=? AND status='sent' AND reply_at IS NULL AND followups<2 ORDER BY sent_at",(account,)):
        lead=store.lead(row['id'])
        if not followup_allowed(lead,True) or not lead.get('sent_at') or not lead.get('message_id'):continue
        days=[4,9][int(lead['followups'])]
        if time.time()<lead['sent_at']+days*86400:continue
        if store.q("SELECT 1 FROM inbox_events WHERE lead_id=? LIMIT 1",(lead['id'],),one=True):continue
        reason=store._conflict(store.db(),lead,followup=True)
        if not reason:return lead
    return None

def prepare(account,profile):
    lead=candidate(account['id'])
    if not lead:return False
    data=dict(lead['data']);index=int(lead['followups'])+1
    if (data.get('followup_ready') or {}).get('index')==index:return False
    p=data.get('prospect') or {};plan=copy.deepcopy(data.get('plan') or {})
    if not p.get('product_name') or not p.get('email_verified') or not lead.get('image'):return False
    greeting='Hi '+pipeline.recipient_label(p)+','
    product=p['product_name']
    question=('Would a sample of the proposed paper insert for '+product+' be useful for your evaluation?' if index==1 else 'If packaging for '+product+' is on your roadmap, what quantity and target delivery date should we work around?')
    plan['body']=greeting+'\n\n'+question+'\n\nWe can review the proposed structure against your requirements before quoting.'
    from pipeline_core.evidence import read_asset
    if not p.get('product_asset'):return False  # Missing verified reference needs normal research, never guessing.
    photo=read_asset(p['product_asset'])
    image,prompt=pipeline.make_image(account,profile,p,plan,photo)
    path=config.data_dir()/'accounts'/account['id']/'images'/('followup-%s-%s.jpg'%(lead['id'],index))
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(image)
    data['followup_ready']=dict(index=index,body=plan['body'],image=str(path),prepared_at=time.time())
    store.update(lead['id'],data=data);return True

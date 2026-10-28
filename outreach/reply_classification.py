"""Classify newly observed inbox messages, without reinterpreting historical replies."""
import re,time,json
from pipeline_core import features

def classify(headers,text):
    subject=str(headers.get('Subject',''))
    if str(headers.get('Auto-Submitted','no')).lower() not in ('no','') or re.search(r'auto.?reply|out of office|automatic reply|自动回复',subject,re.I):return 'auto_reply'
    if re.search(r'unsubscribe|remove me|stop emailing|退订',text,re.I):return 'unsubscribe'
    if re.search(r'not interested|no thanks|no thank you|不感兴趣',text,re.I):return 'human_not_interested'
    if re.search(r'(?:contact|speak to|reach out to|forwarded to).{0,100}[\w.+-]+@[\w.-]+\.[a-z]{2,}',text,re.I):return 'human_referral'
    if re.search(r'(?:please|can you|could you|would like).{0,60}(?:quote|quotation|sample|pricing|price list)|send.{0,20}(?:quote|sample)',text,re.I):return 'human_interested'
    return 'human_other'

def followup_allowed(lead,enabled):
    return bool(enabled and lead.get('status')=='sent' and not lead.get('reply_at') and int(lead.get('followups') or 0)<2 and not lead.get('data',{}).get('followup_stopped'))

def record(account,uid,lid,classification,text=''):
    from . import store
    if not features.enabled('reply_classification'):return
    with store._lock:
        if store.q('SELECT id FROM inbox_events WHERE account=? AND uid=? AND lead_id=?',(account,str(uid),lid),one=True):return
        cur=store.x('INSERT OR IGNORE INTO inbox_events(account,uid,lead_id,classification,created_at) VALUES(?,?,?,?,?)',(account,str(uid),lid,classification,time.time()))
        lead=store.lead(lid)
        if not lead:return
        data=dict(lead['data']);data.update(reply_classification=classification,followup_stopped=True)
        if classification=='human_interested':data['inquiry_status']='interested'
        store.update(lid,data=data)
        store.event(lid,'reply',classification,classification.upper(),account)
        if classification=='human_referral':
            for address in set(re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)):
                if address.lower()==lead['email'].lower():continue
                key='referral:'+str(lid)+':'+address.lower()
                if not store.get(key):store.put(key,dict(parent_id=lid,account=account,email=address.lower(),status='pending_review',reason_code='PUBLIC_IDENTITY_VERIFICATION_REQUIRED'))
        if classification=='human_interested':
            store.suppress(lead['domain'],'reply',account,'Interested inquiry; automatic outreach stopped')
            for other in store.q("SELECT id FROM leads WHERE domain=? AND id<>? AND status IN ('queued','writing','imaging','ready','radar_review')",(lead['domain'],lid)):
                store.update(other['id'],status='skipped',error='该公司已有有效询盘，停止自动流程')

import base64,hashlib,html,json,os,time,uuid
from email.message import EmailMessage
from email import policy
from email.utils import formatdate
from pathlib import Path
from urllib.parse import urlencode
from . import transport
from .config import secret
from .salutation import with_greeting

def render(brand,payload,mid):
    d=dict(payload['draft']);d['body']=with_greeting(d['body'],payload['company']);msg=EmailMessage(policy=policy.SMTP)
    msg['From']=brand['sender'];msg['To']=payload['recipient'];msg['Subject']=d['subject'];msg['Message-ID']=mid;msg['Date']=formatdate(localtime=False)
    msg['List-Unsubscribe']='<mailto:'+brand['sender']+'?subject=Unsubscribe>'
    links=['https://wa.me/'+brand['whatsapp']+'?'+urlencode({'text':'Please tell me more about option '+letter+' for '+payload['company']}) for letter in ['A','B']]
    footer='Reply "unsubscribe" to stop receiving these proposals.'
    msg.set_content(d['body']+'\n\nOption A: '+links[0]+'\nOption B: '+links[1]+'\n\n'+brand['signature']+'\n'+footer)
    markup=''.join('<p>'+html.escape(x).replace('\n','<br>')+'</p>' for x in d['body'].split('\n\n'))
    markup+='<img src="cid:concept" alt="A and B product concepts" style="width:100%;max-width:900px">'
    markup+='<p><a href="'+html.escape(links[0],quote=True)+'">Discuss option A on WhatsApp</a><br><a href="'+html.escape(links[1],quote=True)+'">Discuss option B on WhatsApp</a></p>'
    markup+='<p>'+html.escape(brand['signature']).replace('\n','<br>')+'</p><p>'+footer+'</p>'
    msg.add_alternative('<!doctype html><html><body>'+markup+'</body></html>',subtype='html')
    msg.get_payload()[-1].add_related(base64.b64decode(payload['concept_png']),maintype='image',subtype='png',cid='<concept>',disposition='inline',filename='product-concepts.png')
    return msg

def sync(store,brand,recipient=None):
    with store.db() as c:
        rows=c.execute('SELECT a.recipient,a.message_id FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.brand=?',(brand['id'],)).fetchall()
    known={}
    for row in rows:known.setdefault(row['recipient'],[]).append(row['message_id'])
    if recipient is not None:known={recipient:known.get(recipient,[])}
    if not known:return {'result':'synced_readonly','events':[]}
    result=transport.sync_replies(known,secret(brand['password_env']),brand)
    for event in result.get('events',[]):store.event(event['recipient'],event['kind'],event['evidence'])
    return result

def send(store,config,brand,job):
    payload=job['payload'];mid=payload.setdefault('message_id','<'+uuid.uuid4().hex+'@'+brand['sender'].split('@')[1]+'>')
    raw=render(brand,payload,mid).as_bytes();sha=hashlib.sha256(raw).hexdigest()
    directory=store.root/'outbox';directory.mkdir(exist_ok=True)
    path=directory/(job['id']+'.eml');path.write_bytes(raw)
    if not config.get('auto_send'):return {'result':'spooled','path':str(path)}
    if store.setting('mail_verified:'+brand['id'])!=connection_fingerprint(brand):raise ValueError('Run mailbox-test once for this profile before auto-send')
    if not all(payload.get('draft',{}).get('identity',{}).get(k) is True for k in ('correct_product','correct_count','usable_image')):raise ValueError('Product identity unresolved')
    if hashlib.sha256(base64.b64decode(payload['concept_png'])).hexdigest()!=payload.get('concept_sha256'):raise ValueError('Concept hash changed')
    if sync(store,brand,job['recipient']).get('result')!='synced_readonly':raise ValueError('Current inbox sync unavailable')
    aid=store.claim_send(job,mid,sha)
    result=transport.send_once(raw,brand['sender'],job['recipient'],secret(brand['password_env']),brand,lambda stage,detail:store.trace(aid,stage,detail))
    store.trace(aid,'result',result)
    if result['result']=='rejected' and result.get('stage')=='rcpt':store.event(job['recipient'],'hard_reject','SMTP '+aid)
    return dict(result,attempt_id=aid,message_id=mid,path=str(path),delivered=False)

def mailbox_test(store,brand,png):
    from .images import validate_png
    validate_png(png);mid='<'+uuid.uuid4().hex+'@'+brand['sender'].split('@')[1]+'>';tid='mail-test-'+uuid.uuid4().hex
    payload={'recipient':brand['sender'],'company':'Own-account mailbox verification','draft':{'subject':'Packaging Outreach mailbox test','body':'Controlled own-account test: text plus one real PNG MIME part.'},'concept_png':base64.b64encode(png).decode()}
    raw=render(brand,payload,mid).as_bytes();store.setting(tid,json.dumps({'message_id':mid,'result':'started'}))
    result=transport.send_once(raw,brand['sender'],brand['sender'],secret(brand['password_env']),brand,lambda stage,detail:store.trace(tid,stage,detail))
    store.setting(tid,json.dumps(dict(result,message_id=mid,image_sha256=hashlib.sha256(png).hexdigest(),connection=connection_fingerprint(brand))))
    store.setting('last_mail_test:'+brand['id'],tid)
    if result['result']!='accepted':return dict(result,message_id=mid,verified=False)
    return verify_mailbox_test(store,brand)

def connection_fingerprint(brand):
    return hashlib.sha256(json.dumps({k:brand[k] for k in ['sender','smtp_host','smtp_port','imap_host','imap_port']},sort_keys=True).encode()).hexdigest()

def verify_mailbox_test(store,brand):
    tid=store.setting('last_mail_test:'+brand['id'])
    if not tid:raise ValueError('No prior own-account test')
    test=json.loads(store.setting(tid))
    if test.get('result')!='accepted' or test.get('connection')!=connection_fingerprint(brand):raise ValueError('Test lacks accepted submission for current identity')
    received=transport.verify_imap(test['message_id'],secret(brand['password_env']),brand,{'concept':test['image_sha256']})
    verified=received.get('received') is True and received.get('image_hashes_match') is True
    if verified:store.setting('mail_verified:'+brand['id'],connection_fingerprint(brand))
    return {'message_id':test['message_id'],'receipt':received,'verified':verified}

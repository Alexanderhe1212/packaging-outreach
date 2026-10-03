"""SMTP submission boundaries and readonly IMAP evidence. No retries."""
import hashlib,imaplib,re,smtplib,ssl,time,socket
from email import policy
from email.parser import BytesParser

RUNTIME_REVISION = 'smtp-finalack120-v2'
DEFAULT_FINAL_ACK_TIMEOUT = 120

def timeout_settings(config):
    write=float(config.get('data_write_timeout_seconds',90))
    ack=float(config.get('final_ack_timeout_seconds',DEFAULT_FINAL_ACK_TIMEOUT))
    if not 20<=write<=90 or not 20<=ack<=180:
        raise ValueError('Bounded DATA/final-ack timeout required')
    return write,ack

class StageFailure(Exception):
    def __init__(self,code,stage):self.code,self.stage=code,stage

def send_once(raw,sender,recipient,password,config,event,smtp_factory=None):
    client=None;stage='connect';accepted=False;started=time.monotonic();last=started
    def mark(value,**extra):
        nonlocal stage,last
        now=time.monotonic();extra.update(elapsed_ms=round((now-started)*1000),stage_elapsed_ms=round((now-last)*1000));last=now
        stage=value;event(value,extra)
    def expect(code,allowed):
        if code not in allowed:raise StageFailure(code,stage)
    try:
        # Validate before connecting or issuing DATA. Waiting longer never resends bytes.
        write_timeout,ack_timeout=timeout_settings(config)
        context=ssl.create_default_context()
        factory=smtp_factory or smtplib.SMTP_SSL
        client=factory(config['smtp_host'],config['smtp_port'],timeout=20,context=context)
        mark('connected',mime_bytes=len(raw),socket_timeout_seconds=20,transport_revision=RUNTIME_REVISION,final_ack_timeout_seconds=ack_timeout);expect(client.ehlo()[0],{250});mark('ehlo',size_limit=getattr(client,'esmtp_features',{}).get('size'))
        expect(client.login(sender,password)[0],{235,503});mark('authenticated')
        # Match stdlib sendmail's optional SIZE declaration without changing DATA.
        features=getattr(client,'esmtp_features',{});mail_options=[]
        normalized_size=len(re.sub(br'\r\n|\r|\n',b'\r\n',raw))
        if not raw.endswith((b'\r\n',b'\r',b'\n')):normalized_size+=2
        if 'size' in features:mail_options.append('size='+str(normalized_size))
        mark('mail',options=mail_options);code,_=client.mail(sender,mail_options);expect(code,{250});mark('mail_accepted',code=code)
        mark('rcpt');code,_=client.rcpt(recipient);expect(code,{250,251});mark('rcpt_accepted',code=code)
        mark('data_command');client.putcmd('data');code,_=client.getreply();expect(code,{354})
        # Write a durable uncertainty marker before any body bytes reach the socket.
        if getattr(client,'sock',None):client.sock.settimeout(write_timeout)
        mark('data_started',data_reply_code=code,socket_timeout_seconds=write_timeout)
        normalized=re.sub(br'\r\n|\r|\n',b'\r\n',raw)
        quoted=re.sub(br'(?m)^\.',b'..',normalized)
        if not quoted.endswith(b'\r\n'):quoted+=b'\r\n'
        wire=quoted+b'.\r\n';mark('data_wire_prepared',wire_bytes=len(wire))
        # Keep uncertainty stage while recording metrics; sendall may partially write.
        stage='data_started'
        client.send(wire);mark('data_complete',wire_bytes=len(wire),meaning='socket_sendall_returned_not_server_ack')
        if getattr(client,'sock',None):client.sock.settimeout(ack_timeout)
        mark('final_ack_wait',socket_timeout_seconds=ack_timeout)
        code,_=client.getreply()
        if code==250:
            mark('final_ack',code=code,result='accepted');accepted=True
            return {'result':'accepted','stage':'final_ack','code':code}
        mark('final_ack',code=code)
        raise StageFailure(code,stage)
    except StageFailure as e:
        result='deferred' if 400<=e.code<500 else 'rejected' if 500<=e.code<600 else 'unknown' if stage in ('data_started','data_wire_prepared','data_complete','final_ack_wait','final_ack') else 'retryable_before_data'
        event('result',{'result':result,'code':e.code,'stage':stage})
        return dict(result=result,stage=stage,code=e.code)
    except Exception as e:
        result='unknown' if stage in ('data_started','data_wire_prepared','data_complete','final_ack_wait','final_ack') else 'retryable_before_data'
        # Never include exception messages: authentication exceptions may carry sensitive data.
        cause=e.__context__
        reason='socket_timeout' if isinstance(e,(TimeoutError,socket.timeout)) or isinstance(cause,(TimeoutError,socket.timeout)) else 'socket_io_error' if isinstance(cause,OSError) else 'server_eof_or_disconnect' if isinstance(e,smtplib.SMTPServerDisconnected) else 'other'
        event('result',{'result':result,'error_type':type(e).__name__,'cause_type':type(cause).__name__ if cause else None,'reason':reason,'stage':stage,'elapsed_ms':round((time.monotonic()-started)*1000),'stage_elapsed_ms':round((time.monotonic()-last)*1000)})
        return dict(result=result,stage=stage,error_type=type(e).__name__)
    finally:
        if client:
            try:client.close()
            except Exception:pass

def inspect_message(raw,message_id,image_hashes,expected=None):
    msg=BytesParser(policy=policy.default).parsebytes(raw)
    received_mid=str(msg.get('Message-ID','')).strip()
    suffix=message_id[1:]
    rewritten=bool(re.fullmatch(r'<[A-Fa-f0-9]{16}\+'+re.escape(suffix),received_mid))
    if received_mid!=message_id and not rewritten:return None
    from email.utils import parseaddr,parsedate_to_datetime
    if expected:
        if parseaddr(str(msg.get('From','')))[1].lower()!=expected['sender'] or parseaddr(str(msg.get('To','')))[1].lower()!=expected['recipient'] or str(msg.get('Subject',''))!=expected['subject']:return None
        texts=[p.get_content().replace('\r\n','\n') for p in msg.walk() if p.get_content_type() in ('text/plain','text/html')]
        digest=hashlib.sha256('\0'.join(texts).encode()).hexdigest()
        if digest!=expected['content_sha256']:return None
        try:
            when=parsedate_to_datetime(str(msg.get('Date',''))).timestamp()
            if not expected['earliest']<=when<=expected['latest']:return None
        except Exception:return None
    images={str(p.get('Content-ID','')).strip('<>'):hashlib.sha256(p.get_payload(decode=True) or b'').hexdigest() for p in msg.walk() if p.get_content_maintype()=='image'}
    htmlpart=msg.get_body(preferencelist=('html',));markup=htmlpart.get_content() if htmlpart else ''
    return dict(message_id=message_id,received_message_id=received_mid,provider_prefix_rewrite=rewritten,from_header=str(msg.get('From','')),to_header=str(msg.get('To','')),signature_link=re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*<img[^>]+src="cid:signature"',markup),whatsapp_links=re.findall(r'href="(https://wa.me/[^"]+)"',markup),received=True,images=images,image_hashes_match=all(images.get(k)==v for k,v in image_hashes.items()),mime_sha256=hashlib.sha256(raw).hexdigest())

def verify_imap(message_id,password,config,image_hashes,imap_factory=None,expected=None):
    if not re.fullmatch(r'<[^\s<>"\\]+@[^\s<>"\\]+>',message_id):raise ValueError('Invalid Message-ID')
    client=None
    try:
        factory=imap_factory or imaplib.IMAP4_SSL
        client=factory(config['imap_host'],config['imap_port'],ssl_context=ssl.create_default_context(),timeout=60)
        if client.login(config['sender'],password)[0]!='OK':return {'received':False,'result':'imap_auth_failed'}
        # readonly + PEEK prevents marking messages read or modifying the mailbox.
        if client.select('INBOX',readonly=True)[0]!='OK':return {'received':False,'result':'imap_select_failed'}
        typ,data=client.uid('search',None,'HEADER','Message-ID','"'+message_id[1:]+'"')
        if typ!='OK':return {'received':False,'result':'imap_search_failed'}
        uids=data[0].split() if data and data[0] else []
        if not uids:
            typ,data=client.uid('search',None,'ALL');uids=data[0].split() if typ=='OK' and data and data[0] else []
        for uid in uids[-20:]:
            if expected:
                typ,headers=client.uid('fetch',uid,'(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM TO SUBJECT DATE)])')
                matches=False
                for header in headers if typ=='OK' else []:
                    if isinstance(header,tuple):
                        candidate=BytesParser(policy=policy.default).parsebytes(header[1]);value=str(candidate.get('Message-ID','')).strip()
                        matches=value==message_id or bool(re.fullmatch(r'<[A-Fa-f0-9]{16}\+'+re.escape(message_id[1:]),value))
                if not matches:continue
            typ,parts=client.uid('fetch',uid,'(BODY.PEEK[])')
            if typ!='OK':continue
            for part in parts:
                if isinstance(part,tuple) and len(part)>1:
                    result=inspect_message(part[1],message_id,image_hashes,expected)
                    if result:return dict(result,uid=uid.decode('ascii'),result='received')
        return {'received':False,'result':'not_found','absence_is_not_non_submission':True}
    except Exception as e:return {'received':False,'result':'imap_error','error_type':type(e).__name__}
    finally:
        if client:
            try:client.logout()
            except Exception:pass

# Only inspect mail corresponding to our known outbound contacts, not arbitrary inbox content.
def sync_replies(known,password,config,imap_factory=None):
    from email.utils import parseaddr
    client=None;results=[];deadline=time.monotonic()+120;phase="connect"
    def bounded():
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError('Readonly inbox sync deadline')
        if getattr(client,'sock',None):client.sock.settimeout(min(20,left))
    try:
        factory=imap_factory or imaplib.IMAP4_SSL;client=factory(config['imap_host'],config['imap_port'],ssl_context=ssl.create_default_context(),timeout=20)
        bounded()
        phase='login'
        if client.login(config['sender'],password)[0]!='OK':return {'result':'imap_unavailable','stage':phase,'events':[]}
        phase='select'
        if client.select('INBOX',readonly=True)[0]!='OK':return {'result':'imap_unavailable','stage':phase,'events':[]}
        for recipient,mids in known.items():
            if not re.fullmatch(r'[^\s@<>"\\]+@[^\s@<>"\\]+',recipient):continue
            bounded()
            phase='search'
            typ,data=client.uid('search',None,'FROM','"'+recipient+'"')
            if typ!='OK':raise RuntimeError('Readonly IMAP command failed')
            for uid in (data[0].split() if data and data[0] else [])[-30:]:
                bounded()
                phase='fetch'
                typ,parts=client.uid('fetch',uid,'(BODY.PEEK[]<0.131072>)')
                if typ!='OK':raise RuntimeError('Readonly IMAP command failed')
                for part in parts:
                    if not isinstance(part,tuple) or len(part)<2:continue
                    msg=BytesParser(policy=policy.default).parsebytes(part[1])
                    if parseaddr(str(msg.get('From','')))[1].lower()!=recipient:continue
                    refs=str(msg.get('In-Reply-To',''))+' '+str(msg.get('References',''))
                    related=any(mid in refs for mid in mids)
                    texts=[]
                    for leaf in msg.walk():
                        if leaf.get_content_type()=='text/plain':
                            try:texts.append(leaf.get_content())
                            except Exception:pass
                    fresh=[]
                    for line in '\n'.join(texts).splitlines():
                        if re.match(r'(?i)^(on .+wrote:|from:|发件人[:：]|-+original message)',line.strip()):break
                        if not line.lstrip().startswith('>'):fresh.append(line)
                    text='\n'.join(fresh).lower()
                    stop=any(p in text for p in ('unsubscribe','stop contacting','remove me','do not contact','no thanks','non merci','不要联系','退订'))
                    rejected=any(p in text for p in ('not interested','no interest','not a fit','不感兴趣','不需要'))
                    if not related and not stop and not rejected:continue
                    kind='unsubscribe' if stop else 'hard_reject' if rejected else 'reply'
                    results.append(dict(recipient=recipient,kind=kind,evidence='IMAP uid '+uid.decode()+' reply '+str(msg.get('Message-ID','')),message_id=str(msg.get('Message-ID',''))))
        return {'result':'synced_readonly','events':results}
    except Exception as e:return {'result':'imap_auth_error' if isinstance(e,imaplib.IMAP4.error) and any(x in str(e).lower() for x in ('auth','login','password')) else 'imap_error','stage':phase,'error_type':type(e).__name__,'events':results}
    finally:
        if client:
            try:client.logout()
            except Exception:pass

import json,unittest
from packaging_outreach.transport import send_once,verify_imap
from email import policy
from email.parser import BytesParser
import hashlib

class SMTPFake:
    def __init__(self,*args,fail=None,final=250,**kwargs):self.fail=fail;self.final=final;self.reply=0;self.raw=None;self.closed=False
    def ehlo(self):return (250,b'ok')
    def login(self,*args):
        if self.fail=='auth':raise TimeoutError('must not leak password')
        return (235,b'ok')
    def mail(self,*args):return (250,b'ok')
    def rcpt(self,*args):return (550 if self.fail=='rcpt' else 250,b'ok')
    def putcmd(self,*args):
        if self.fail=='data_command':raise TimeoutError()
    def getreply(self):
        self.reply+=1
        if self.reply==1:return (354,b'send')
        if self.fail=='final':raise TimeoutError()
        return (self.final,b'queue')
    def send(self,raw):
        if self.fail=='body':raise OSError('secret-like error must not be logged')
        self.raw=raw
    def close(self):self.closed=True

class TransportTests(unittest.TestCase):
    def run_smtp(self,**kw):
        self.traces=[];self.fake=SMTPFake(**kw)
        out=send_once(b'From: a@example.test\r\n\r\n.dot\nlast','a@example.test','b@example.test','DO_NOT_LOG',dict(smtp_host='example.test',smtp_port=465),lambda s,d:self.traces.append((s,d)),smtp_factory=lambda *a,**k:self.fake)
        self.assertNotIn('DO_NOT_LOG',json.dumps(self.traces));return out
    def test_final250_and_dot_stuffing(self):
        self.assertEqual(self.run_smtp()['result'],'accepted');self.assertIn(b'\r\n..dot\r\n',self.fake.raw);self.assertTrue(self.fake.raw.endswith(b'\r\n.\r\n'));self.assertTrue(self.fake.closed)
    def test_auth_timeout_predata(self):self.assertEqual(self.run_smtp(fail='auth')['result'],'retryable_before_data')
    def test_rcpt_reject(self):self.assertEqual(self.run_smtp(fail='rcpt')['result'],'rejected')
    def test_data_command_disconnect_before_body(self):self.assertEqual(self.run_smtp(fail='data_command')['result'],'retryable_before_data')
    def test_body_disconnect_unknown(self):self.assertEqual(self.run_smtp(fail='body')['result'],'unknown')
    def test_final_timeout_unknown(self):self.assertEqual(self.run_smtp(fail='final')['result'],'unknown')
    def test_final4xx_deferred(self):self.assertEqual(self.run_smtp(final=451)['result'],'deferred')
    def test_final5xx_rejected(self):self.assertEqual(self.run_smtp(final=550)['result'],'rejected')
    def test_imap_readonly_and_exact_mime_hash(self):
        raw=b'From: a@example.test\r\nTo: b@example.test\r\nMessage-ID: <test@example.test>\r\n\r\nhello'
        calls=[]
        class IMAPFake:
            def __init__(self,*a,**k):pass
            def login(self,*a):return ('OK',[])
            def select(self,name,readonly=False):calls.append(('select',readonly));return ('OK',[])
            def uid(self,cmd,*args):
                calls.append((cmd,args));return ('OK',[b'7']) if cmd=='search' else ('OK',[(b'7',raw)])
            def logout(self):pass
        out=verify_imap('<test@example.test>','DO_NOT_LOG',dict(imap_host='example.test',imap_port=993,sender='b@example.test'),{},imap_factory=IMAPFake)
        self.assertTrue(out['received']);self.assertIn(('select',True),calls);self.assertIn('BODY.PEEK',repr(calls));self.assertEqual(out['mime_sha256'],hashlib.sha256(raw).hexdigest())
    def test_imap_invalid_header_rejected(self):
        with self.assertRaises(ValueError):verify_imap('bad" header','x',{}, {})

class PrefixReceiptTests(unittest.TestCase):
    def test_valid_prefix_keeps_original_and_received_ids(self):
        from packaging_outreach.transport import inspect_message
        raw=b'Message-ID: <1234567890ABCDEF+test@example.test>\r\n\r\nhello'
        out=inspect_message(raw,'<test@example.test>',{})
        self.assertTrue(out['provider_prefix_rewrite']);self.assertEqual(out['message_id'],'<test@example.test>')
    def test_invalid_prefix_or_suffix_rejected(self):
        from packaging_outreach.transport import inspect_message
        for mid in ('<wrong+test@example.test>','<1234567890ABCDEF+other@example.test>','<1234567890ABCDE+test@example.test>'):
            self.assertIsNone(inspect_message(('Message-ID: '+mid+'\r\n\r\nhello').encode(),'<test@example.test>',{}))
    def test_wrong_identity_cannot_match_prefix(self):
        from packaging_outreach.transport import inspect_message
        raw=b'From: wrong@example.test\r\nTo: b@example.test\r\nMessage-ID: <1234567890ABCDEF+test@example.test>\r\n\r\nhello'
        self.assertIsNone(inspect_message(raw,'<test@example.test>',{}, {'sender':'a@example.test','recipient':'b@example.test','subject':''}))

class PhaseTimeoutTests(unittest.TestCase):
    def test_data_and_ack_have_separate_bounded_timeouts(self):
        calls=[]
        class Sock:
            def settimeout(self,v):calls.append(v)
        fake=SMTPFake();fake.sock=Sock();out=send_once(b'x','a@test','b@test','PRIVATE',{'smtp_host':'test','smtp_port':465,'data_write_timeout_seconds':90,'final_ack_timeout_seconds':75},lambda *x:None,smtp_factory=lambda *a,**k:fake)
        self.assertEqual(calls,[90,75]);self.assertEqual(out['result'],'accepted')
    def test_socket_timeout_after_data_stays_unknown(self):
        traces=[]
        class Fake(SMTPFake):
            def send(self,raw):
                try:raise TimeoutError('PRIVATE must never appear')
                except OSError:raise __import__('smtplib').SMTPServerDisconnected('Server not connected')
        out=send_once(b'x','a@test','b@test','PRIVATE',{'smtp_host':'test','smtp_port':465},lambda s,d:traces.append((s,d)),smtp_factory=lambda *a,**k:Fake())
        self.assertEqual(out['result'],'unknown');self.assertEqual(traces[-1][1]['reason'],'socket_timeout');self.assertNotIn('PRIVATE',json.dumps(traces))

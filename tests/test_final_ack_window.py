"""Advance a fake server clock; never sleep, connect, or send a real email."""
import smtplib
import unittest
from unittest.mock import Mock, patch
from packaging_outreach import transport


class DelayedSMTP:
    def __init__(self, clock, outcome='accepted', delay=115):
        self.clock, self.outcome, self.delay = clock, outcome, delay
        self.sock = self
        self.timeouts, self.writes = [], []
        self.replies = 0
        self.closed = False

    def settimeout(self, seconds): self.timeouts.append(seconds)
    def ehlo(self): return 250, b'fixture'
    def login(self, *args): return 235, b'fixture'
    def mail(self, *args): return 250, b'fixture'
    def rcpt(self, *args): return 250, b'fixture'
    def putcmd(self, command): pass
    def send(self, wire): self.writes.append(wire)
    def close(self): self.closed = True
    def getreply(self):
        self.replies += 1
        if self.replies == 1: return 354, b'fixture'
        if self.delay > self.timeouts[-1]:
            self.clock[0] += self.timeouts[-1]
            try: raise TimeoutError('fixture timeout')
            except OSError: raise smtplib.SMTPServerDisconnected('fixture disconnect')
        self.clock[0] += self.delay
        if self.outcome == 'disconnect': raise smtplib.SMTPServerDisconnected('EOF')
        return 250, b'fixture final'


class FinalAckWindowTests(unittest.TestCase):
    def run_case(self, **kwargs):
        clock = [0.0]; fake = DelayedSMTP(clock, **kwargs); events = []
        factory = Mock(return_value=fake)
        raw = b'Message-ID: <unchanged@example.test>\r\n\r\noriginal bytes\r\n'
        with patch.object(transport.time, 'monotonic', side_effect=lambda: clock[0]):
            result = transport.send_once(raw, 'from@example.test', 'to@example.test', 'fixture',
                {'smtp_host': 'fixture', 'smtp_port': 465}, lambda s,d: events.append((s,d)), factory)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['timeout'], 20)
        context = factory.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(fake.timeouts, [90, 120])
        self.assertEqual(fake.writes, [raw+b'.\r\n'])
        self.assertTrue(fake.closed)
        self.assertEqual(dict(events)['connected']['transport_revision'], transport.RUNTIME_REVISION)
        return result, events

    def test_final_250_after_115_seconds_keeps_original_bytes_once(self):
        result, events = self.run_case()
        self.assertEqual(result['result'], 'accepted')
        self.assertEqual(events[-1][1]['stage_elapsed_ms'], 115000)

    def test_slow_final_reply_is_unknown_without_a_second_connection(self):
        result, events = self.run_case(delay=121)
        self.assertEqual(result['result'], 'unknown')
        self.assertEqual(events[-1][1]['reason'], 'socket_timeout')
        self.assertEqual(events[-1][1]['stage_elapsed_ms'], 120000)

    def test_final_disconnect_is_unknown_without_replaying_data(self):
        result, _ = self.run_case(outcome='disconnect', delay=1)
        self.assertEqual(result['result'], 'unknown')
        self.assertEqual(result['stage'], 'final_ack_wait')

    def test_invalid_timeout_rejected_before_connect(self):
        for value in (0, 181, float('inf'), float('nan')):
            factory = Mock()
            result = transport.send_once(b'x','a','b','fixture',
                {'final_ack_timeout_seconds':value}, lambda *args:None, factory)
            factory.assert_not_called()
            self.assertEqual(result['result'], 'retryable_before_data')

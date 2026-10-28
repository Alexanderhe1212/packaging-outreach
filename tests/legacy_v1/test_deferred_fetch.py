"""A local fetch deadline defers research without starting SMTP or blocking other leads."""
import sys
import time
from unittest.mock import patch
from test_bridge import BridgeTest, store
from outreach import worker, web

class DeferredFetchTest(BridgeTest):
    def test_direct_deadline_defers_research_and_keeps_next_lead_available(self):
        first = store.add_lead('A', 'queued', data={'manual': {'url': 'https://example.com'}})
        second = store.add_lead('A', 'queued')
        deadline = time.time() + 900
        with patch.object(worker.pipeline, 'research', side_effect=web.DeferredFetch(deadline)), patch.object(worker.AccountWorker, 'send') as send:
            worker.AccountWorker('A').process(store.lead(first), None)
        saved = store.lead(first)
        self.assertEqual(saved['status'], 'queued')
        self.assertEqual(saved['data']['research_retry_count'], 0)
        self.assertAlmostEqual(saved['data']['research_retry_at'], deadline, delta=0.01)
        self.assertEqual(store.next_lead('A', ('queued',))['id'], second)
        send.assert_not_called()

    def test_waiting_without_a_request_does_not_exhaust_real_attempt_budget(self):
        lid = store.add_lead('A', 'queued', data={'manual': {'url': 'https://example.com'}, 'research_retry_count': 3})
        with patch.object(worker.pipeline, 'research', side_effect=web.DeferredFetch(time.time() + 900)), patch.object(worker.AccountWorker, 'send') as send:
            worker.AccountWorker('A').process(store.lead(lid), None)
        self.assertEqual(store.lead(lid)['status'], 'queued')
        self.assertEqual(store.lead(lid)['data']['research_retry_count'], 3)
        send.assert_not_called()

    def test_429_remains_scheduled_after_three_failures(self):
        import io,urllib.error
        lid=store.add_lead('A','queued',data={'manual':{'url':'https://example.com'},'research_retry_count':3})
        error=urllib.error.HTTPError('https://example.com',429,'Limited',{'Retry-After':'7200'},io.BytesIO(b''))
        with patch.object(worker.pipeline,'research',side_effect=error),patch.object(worker.AccountWorker,'send') as send:
            worker.AccountWorker('A').process(store.lead(lid),None)
        saved=store.lead(lid)
        self.assertEqual(saved['status'],'queued')
        self.assertGreaterEqual(saved['data']['research_retry_at'],time.time()+7199)
        send.assert_not_called()

    def test_direct_deadline_defers_auto_candidate(self):
        store.add_candidates('A', [{'domain': 'example.com', 'brand': 'Example'}])
        with patch.object(worker.web.FETCH_GUARD, 'wait_seconds', return_value=0), patch.object(worker.store, 'queue_recontact', return_value=None), patch.object(worker.pipeline, 'research', side_effect=web.DeferredFetch(time.time() + 900)):
            worker.AccountWorker('A').prepare_one()
        saved = store.q('SELECT status FROM candidates WHERE domain=?', ('example.com',), one=True)
        self.assertEqual(saved['status'], 'retry_wait')

if __name__ == '__main__':
    import unittest
    unittest.main()

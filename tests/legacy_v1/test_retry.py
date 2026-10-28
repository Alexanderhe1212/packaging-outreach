import sys,time,urllib.error,io
from test_bridge import BridgeTest,patch,store
from outreach import worker,web
class RetryTest(BridgeTest):
 def test_transient_defers_without_blocking_next(self):
  first=store.add_lead('A','queued',data={'manual':{'url':'https://example.com'}})
  second=store.add_lead('A','queued')
  err=web.CrawlError('temporary');err.__cause__=urllib.error.HTTPError('https://example.com',503,'unavailable',{'Retry-After':'900'},io.BytesIO())
  w=worker.AccountWorker('A')
  with patch.object(worker.pipeline,'research',side_effect=err):w.process(store.lead(first),None)
  p=store.lead(first);self.assertEqual(p['status'],'queued');self.assertGreater(p['data']['research_retry_at'],time.time()+890)
  self.assertEqual(store.next_lead('A',('queued',))['id'],second)
  p['data']['research_retry_count']=3;store.update(first,data=p['data'])
  with patch.object(worker.pipeline,'research',side_effect=err):w.process(store.lead(first),None)
  self.assertEqual(store.lead(first)['status'],'failed')
 def test_permanent_error_not_retried(self):
  lid=store.add_lead('A','queued',data={'manual':{'url':'https://example.com'}})
  with patch.object(worker.pipeline,'research',side_effect=web.CrawlError('no verified email')):worker.AccountWorker('A').process(store.lead(lid),None)
  self.assertEqual(store.lead(lid)['status'],'failed')
if __name__=='__main__':
 import unittest
 unittest.main()

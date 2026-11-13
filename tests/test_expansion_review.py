import tempfile,pathlib,json,unittest
from unittest.mock import patch
from outreach import expansion_review as e
class Review(unittest.TestCase):
 def test_stale_review_and_missing_checks_rejected(self):
  with tempfile.TemporaryDirectory() as t,patch.object(e,'HOME',pathlib.Path(t)):
   row={'website':'https://example.com','review':'pending','evidence':{'candidate':{'sources':[{'url':'https://event.test/one'}]}}};e.save({'rows':[row]})
   with self.assertRaises(ValueError):e.review({'website':row['website'],'decision':'approved','revision':'stale'})
   with self.assertRaises(ValueError):e.review({'website':row['website'],'decision':'approved','revision':e.revision(row)})
 def test_approval_and_return_never_touch_sender(self):
  with tempfile.TemporaryDirectory() as t,patch.object(e,'HOME',pathlib.Path(t)),patch.object(e.store,'audit'):
   row={'website':'https://example.com','review':'pending','evidence':{'candidate':{'sources':[{'url':'https://event.test/one'}]}}};e.save({'rows':[row]})
   data=dict(website=row['website'],decision='approved',revision=e.revision(row),grade='B',industry_verified=True,compliance_checked=True,exhibitor_source='https://event.test/one',note='Verified sources')
   self.assertTrue(e.review(data)['ok']);saved=e.load()['rows'][0];self.assertEqual(saved['review_revision'],e.revision(saved))
   data.update(decision='rejected',note='Needs more evidence');e.review(data);self.assertEqual(e.load()['rows'][0]['review'],'rejected')

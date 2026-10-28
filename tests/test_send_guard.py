import unittest,datetime
from unittest.mock import patch
class Guard(unittest.TestCase):
 def test_disabled_preserves_legacy(self):
  from outreach.send_guard import check
  with patch('pipeline_core.features.enabled',return_value=False):self.assertEqual(check({},{}),'')
 def test_conservative_us_window_and_weekend(self):
  from outreach.send_guard import local_window
  utc=datetime.timezone.utc
  self.assertTrue(local_window({'country':'US','verified_timezone':'America/New_York'},datetime.datetime(2026,10,21,17,30,tzinfo=utc)))
  self.assertFalse(local_window({'country':'US'},datetime.datetime(2026,10,24,17,30,tzinfo=utc)))
  self.assertFalse(local_window({},datetime.datetime(2026,10,21,17,30,tzinfo=utc)))

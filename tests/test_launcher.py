"""Offline launcher tests: no browsers, real accounts, or mail connections."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('outreach_app_launcher', ROOT / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class LauncherTests(unittest.TestCase):
    def test_simultaneous_clicks_start_one_service(self):
        with tempfile.TemporaryDirectory() as temp:
            healthy = threading.Event()
            calls = []
            def spawn(*args, **kwargs):
                calls.append(args)
                time.sleep(.04)
                healthy.set()
            with patch.object(app.config, 'data_dir', return_value=Path(temp)), \
                 patch.object(app, 'running', side_effect=healthy.is_set), \
                 patch.object(app.subprocess, 'Popen', side_effect=spawn):
                results = []
                threads = [threading.Thread(target=lambda: results.append(app.ensure_running())) for _ in range(6)]
                for t in threads: t.start()
                for t in threads: t.join(3)
            self.assertEqual(len(calls), 1)
            self.assertEqual(results, [True] * 6)
            self.assertIn('--no-browser', calls[0][0])

    def test_lock_excludes_and_releases(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app.config, 'data_dir', return_value=Path(temp)):
            with app.process_lock('service.lock') as first:
                self.assertTrue(first)
                with app.process_lock('service.lock', False) as second:
                    self.assertFalse(second)
            with app.process_lock('service.lock', False) as third:
                self.assertTrue(third)

    def test_background_duplicate_never_opens_browser_or_starts_workers(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app.config, 'data_dir', return_value=Path(temp)):
            with app.process_lock('service.lock'), patch.object(sys, 'argv', ['app.py', '--no-browser']), \
                 patch.object(app, 'open_window') as window, patch.object(app, 'running') as running:
                app.main()
                window.assert_not_called()
                running.assert_not_called()

    def test_open_does_not_start_accounts(self):
        with patch.object(app, 'ensure_running', return_value=True), patch.object(app, 'running', return_value=True), \
             patch.object(app, 'call') as call, patch.object(app, 'open_window') as window:
            self.assertEqual(app.cli('open', []), 0)
            call.assert_not_called()
            window.assert_called_once()

    def test_start_failure_has_bounded_retries(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app.config, 'data_dir', return_value=Path(temp)), \
             patch.object(app, 'running', return_value=False), patch.object(app.subprocess, 'Popen') as spawn, \
             patch('time.sleep'):
            self.assertFalse(app.ensure_running())
            spawn.assert_called_once()


if __name__ == '__main__':
    unittest.main()

"""Search acknowledgement must represent finished provider work, never enqueue."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

fake = ModuleType('app.jobs_queue')
fake.jobs_queue = SimpleNamespace()
sys.modules['app.jobs_queue'] = fake
spec = importlib.util.spec_from_file_location('completion', Path(__file__).parents[1] / 'bazarr/api/wait_for_search.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CompletionTests(unittest.TestCase):
    def test_waits_for_completion(self):
        statuses = iter(['pending', 'running', 'completed'])
        fake.jobs_queue.get_job_status = lambda _: next(statuses)
        fake.jobs_queue.get_job_returned_value = lambda _: ('', 204)
        with patch.object(module.time, 'sleep') as sleep:
            self.assertEqual(module.wait_for_search(1), ({'completed': True}, 200))
            self.assertEqual(sleep.call_count, 2)
    def test_missing_failed_or_duplicate_cannot_authorize_generation(self):
        for status in ['failed', None]:
            fake.jobs_queue.get_job_status = lambda _, value=status: value
            self.assertEqual(module.wait_for_search(1)[1], 503)
        self.assertEqual(module.wait_for_search(False)[1], 409)
    def test_provider_error_is_propagated(self):
        fake.jobs_queue.get_job_status = lambda _: 'completed'
        fake.jobs_queue.get_job_returned_value = lambda _: ('unreadable file', 409)
        self.assertEqual(module.wait_for_search(1)[1], 409)
    def test_timeout_is_not_completion(self):
        self.assertEqual(module.wait_for_search(1, timeout=0)[1], 503)

if __name__ == '__main__': unittest.main()

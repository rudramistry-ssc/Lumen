"""Real subprocess cancellation checks; no model inference or accuracy claims."""
import sys
import time
import unittest
from signspeak_llm.deadline import run_bounded


class DeadlineTests(unittest.TestCase):
    def test_normal_worker(self):
        result = run_bounded([sys.executable, "-c", "import sys; print(sys.stdin.read())"], {"test": 1}, seconds=5)
        self.assertTrue(result["ok"], result)
        self.assertIn(b'"test": 1', result["stdout"])

    def test_hung_worker_and_child_cancelled(self):
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
        start = time.monotonic()
        result = run_bounded([sys.executable, "-c", code], {}, seconds=6)
        self.assertTrue(result["deadline_exceeded"], result)
        self.assertTrue(result["cancellation"]["worker_stopped"], result)
        self.assertEqual(result["cancellation"]["tree_termination"], "confirmed")
        self.assertFalse(result["cancellation"]["shared_server_stopped"])
        self.assertLess(time.monotonic()-start, 7)

    def test_windows_blocked_stdin_is_also_bounded(self):
        start = time.monotonic()
        result = run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], {"large": "x"*2_000_000}, seconds=6)
        self.assertTrue(result["deadline_exceeded"], result)
        self.assertTrue(result["cancellation"]["worker_stopped"], result)
        self.assertLess(time.monotonic()-start, 7)

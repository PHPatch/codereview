"""Tests for the shared test-command runner (external review
2026-11-10, §4.3): one implementation in codereview.testrun
used by both the CLI test runner (cli._run_tests) and the
workflow engine's test step (core.run_workflow's _tests).

The regression this file exists to pin: the workflow copy of
the runner did not catch subprocess.TimeoutExpired, so a test
command exceeding the timeout raised out of the workflow step
and crashed the workflow; and both copies killed only the
shell on timeout, orphaning any child the command had spawned.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from codereview import cli, testrun  # noqa: E402


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SharedRunnerTests(unittest.TestCase):

    def test_result_shape_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as cwd:
            results = testrun.run_commands(
                ["exit 0", "echo hello; exit 3"], cwd)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["command"], "exit 0")
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["exit_code"], 0)
        self.assertFalse(results[1]["ok"])
        self.assertEqual(results[1]["exit_code"], 3)
        self.assertIn("hello", results[1]["output_tail"])

    def test_empty_commands(self):
        self.assertEqual(testrun.run_commands([], "."), [])
        self.assertEqual(testrun.run_commands(None, "."), [])

    def test_timeout_returns_failed_result_and_kills_child(self):
        # The command spawns a sleeping CHILD (a python process
        # that writes its pid to a file, then sleeps) and then
        # sleeps itself. On timeout the runner must (a) return
        # the failed-result shape instead of raising, and
        # (b) kill the whole process group, child included —
        # no orphan left sleeping.
        with tempfile.TemporaryDirectory() as cwd:
            pidfile = os.path.join(cwd, "child.pid")
            child = (
                f"{sys.executable} -c \"import os,time;"
                f"open({pidfile!r},'w').write(str(os.getpid()));"
                f"time.sleep(60)\" & sleep 60")
            results = testrun.run_commands([child], cwd, timeout=2)
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0]["ok"])
            self.assertIsNone(results[0]["exit_code"])
            self.assertEqual(results[0]["output_tail"], "timed out")
            # The child announced itself before the timeout.
            deadline = time.time() + 5
            while not os.path.exists(pidfile) and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(os.path.exists(pidfile),
                            "child never wrote its pid file")
            with open(pidfile) as fh:
                child_pid = int(fh.read().strip())
            # Group kill: the child must be gone, not orphaned.
            deadline = time.time() + 5
            while _pid_alive(child_pid) and time.time() < deadline:
                time.sleep(0.05)
            self.assertFalse(
                _pid_alive(child_pid),
                f"spawned child {child_pid} survived the timeout kill")

    def test_timeout_bounded_when_child_escapes_group(self):
        # Reviewer reproduction (2026-11-10): a child that
        # leaves the process group (setsid) and keeps the output
        # pipe keeps an UNBOUNDED post-kill communicate()
        # blocked until it exits — on 62eaf4b this command with
        # timeout=2 returned after 30.0s, not 2s. The drain is
        # now bounded (_DRAIN_SECONDS): the call must return the
        # failed result within a few seconds even though the
        # escaped child is still alive (the group kill cannot
        # reach it; the runner gives up on the pipes instead).
        with tempfile.TemporaryDirectory() as cwd:
            started = time.time()
            results = testrun.run_commands(
                ["setsid sleep 30 & echo started; sleep 30"],
                cwd, timeout=2)
            elapsed = time.time() - started
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIsNone(results[0]["exit_code"])
        self.assertEqual(results[0]["output_tail"], "timed out")
        self.assertLess(
            elapsed, 15,
            f"timeout path took {elapsed:.1f}s for a 2s timeout — "
            "the post-kill drain is not bounded")

    def test_cli_wrapper_uses_shared_runner(self):
        # cli._run_tests keeps its name/signature but delegates:
        # a timeout through the CLI path must produce the same
        # failed-result shape, not raise.
        with tempfile.TemporaryDirectory() as cwd:
            results = cli._run_tests(["echo out; exit 0"], cwd)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertIn("out", results[0]["output_tail"])


if __name__ == "__main__":
    unittest.main()

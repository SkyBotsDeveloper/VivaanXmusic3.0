import importlib.util
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "dyno_supervisor", Path(__file__).resolve().parents[1] / "scripts/dyno_supervisor.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class DailyRestartTest(unittest.TestCase):
    def test_three_am_india_is_previous_day_2130_utc(self):
        now = datetime(2026, 11, 23, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(
            guard.next_daily_restart(now).astimezone(timezone.utc),
            datetime(2026, 11, 23, 21, 30, tzinfo=timezone.utc),
        )

    def test_boot_at_or_after_deadline_does_not_loop(self):
        now = datetime(2026, 12, 31, 3, 0, tzinfo=guard.IST)
        for offset in (timedelta(), timedelta(minutes=10)):
            self.assertEqual(
                guard.next_daily_restart(now + offset),
                datetime(2027, 1, 1, 3, 0, tzinfo=guard.IST),
            )


class MemoryTest(unittest.TestCase):
    def test_short_spikes_do_not_restart_and_sustained_pressure_does(self):
        policy = guard.MemoryGuard(1000)
        self.assertFalse(policy.should_restart(950, 0, 120))
        self.assertFalse(policy.should_restart(800, 20, 140))
        self.assertFalse(policy.should_restart(950, 30, 150))
        self.assertFalse(policy.should_restart(950, 50, 170))
        self.assertTrue(policy.should_restart(950, 60, 180))

    def test_startup_grace_and_restart_cooldown(self):
        policy = guard.MemoryGuard(1000)
        policy.should_restart(1100, 0, 0)
        self.assertFalse(policy.should_restart(1100, 60, 60))
        self.assertTrue(policy.should_restart(1100, 120, 120))
        policy.restarted(120)
        policy.should_restart(1100, 150, 130)
        self.assertFalse(policy.should_restart(1100, 200, 180))
        self.assertTrue(policy.should_restart(1100, 420, 400))

    def test_cgroup_v2_counts_children_swap_and_ignores_inactive_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.current").write_text("1000")
            (root / "memory.swap.current").write_text("200")
            (root / "memory.stat").write_text("anon 600\ninactive_file 100\n")
            self.assertEqual(guard.read_memory_bytes(root), 1100)

    def test_cgroup_v1_reads_usage_and_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory").mkdir()
            (root / "memory/memory.usage_in_bytes").write_text("1000")
            (root / "memory/memory.stat").write_text("total_swap 200\ntotal_inactive_file 100\n")
            self.assertEqual(guard.read_memory_bytes(root), 1100)


class RestartApiTest(unittest.TestCase):
    def test_only_specific_worker_endpoint_is_used(self):
        response = Mock(status=202)
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch.object(guard, "urlopen", return_value=context) as call:
            self.assertTrue(guard.request_dyno_restart("skybeatznew", "worker.1", "private-key"))
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.heroku.com/apps/skybeatznew/dynos/worker.1")
        self.assertEqual(request.method, "DELETE")
        self.assertEqual(call.call_args.kwargs["timeout"], 10)

    def test_api_failure_allows_fallback_without_leaking_credentials(self):
        with patch.object(guard, "urlopen", side_effect=OSError("private-key")), \
                self.assertLogs("dyno_guard", level="WARNING") as messages:
            self.assertFalse(guard.request_dyno_restart("skybeatznew", "worker.1", "private-key"))
        self.assertNotIn("private-key", " ".join(messages.output))

    def test_invalid_scope_never_sends_a_request(self):
        with patch.object(guard, "urlopen") as call:
            for app, dyno, token in (("skybeatznew", "", "key"),
                                     ("skybeatznew", "web.1", "key"),
                                     ("../other", "worker.1", "key"),
                                     ("skybeatznew", "worker.1", "")):
                self.assertFalse(guard.request_dyno_restart(app, dyno, token))
        call.assert_not_called()


class SupervisorTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX process groups are used on Heroku")
    def test_real_child_process_stops_on_shutdown(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 start_new_session=True)
        try:
            guard.stop_child(child)
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    def test_disabled_or_different_app_runs_normal_bot(self):
        for env in ({}, {"DYNO_GUARD_ENABLED": "1", "DYNO_GUARD_APP": "skybeatznew",
                         "HEROKU_APP_NAME": "another-app", "DYNO": "worker.1"}):
            with patch.dict(os.environ, env, clear=True), patch.object(guard.os, "execv") as run:
                guard.main()
            run.assert_called_once_with(guard.sys.executable, [guard.sys.executable, "-m", "VIVAANXMUSIC"])

    def test_child_crash_relaunches_without_restarting_other_dynos(self):
        class ClockEvent:
            elapsed = 0

            def is_set(self):
                return self.elapsed >= 60

            def set(self):
                self.elapsed = 60

            def wait(self, seconds):
                self.elapsed += seconds
                return self.is_set()

        event = ClockEvent()
        dead = Mock(pid=101, returncode=1)
        dead.poll.return_value = 1
        live = Mock(pid=102)
        live.poll.return_value = None
        env = {"DYNO_GUARD_ENABLED": "1", "DYNO_GUARD_APP": "skybeatznew",
               "HEROKU_APP_NAME": "skybeatznew", "DYNO": "worker.1"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(guard.threading, "Event", return_value=event), \
                patch.object(guard.signal, "signal"), \
                patch.object(guard.time, "monotonic", side_effect=lambda: event.elapsed), \
                patch.object(guard, "read_memory_bytes", return_value=100 * guard.MIB), \
                patch.object(guard.subprocess, "Popen", side_effect=[dead, live]) as spawn, \
                patch.object(guard, "stop_child") as stop, \
                patch.object(guard, "request_dyno_restart") as restart:
            guard.main()
        self.assertEqual(spawn.call_count, 2)
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        self.assertEqual(stop.call_args.args[0], live)
        restart.assert_not_called()

    def test_daily_restart_api_failure_recycles_worker_once(self):
        class ClockEvent:
            elapsed = 0

            def is_set(self):
                return self.elapsed >= 60

            def set(self):
                self.elapsed = 60

            def wait(self, seconds):
                self.elapsed += seconds
                return self.is_set()

        event = ClockEvent()
        child = Mock(pid=101)
        child.poll.return_value = None
        now = datetime.now(timezone.utc)
        env = {"DYNO_GUARD_ENABLED": "1", "DYNO_GUARD_APP": "skybeatznew",
               "HEROKU_APP_NAME": "skybeatznew", "DYNO": "worker.1",
               "HEROKU_API_KEY": "test-only"}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(guard.threading, "Event", return_value=event), \
                patch.object(guard.signal, "signal"), \
                patch.object(guard.time, "monotonic", side_effect=lambda: event.elapsed), \
                patch.object(guard, "next_daily_restart", side_effect=[now - timedelta(seconds=1),
                                                                       now + timedelta(days=1)]), \
                patch.object(guard, "read_memory_bytes", return_value=100 * guard.MIB), \
                patch.object(guard.subprocess, "Popen", return_value=child) as spawn, \
                patch.object(guard, "stop_child") as stop, \
                patch.object(guard, "request_dyno_restart", return_value=False) as restart:
            guard.main()
        self.assertEqual(spawn.call_count, 2)
        restart.assert_called_once_with("skybeatznew", "worker.1", "test-only")
        self.assertEqual(stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()

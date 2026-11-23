"""Supervise a worker independently of the bot's asyncio loop."""

import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen


LOG = logging.getLogger("dyno_guard")
IST = timezone(timedelta(hours=5, minutes=30), "IST")
MIB = 1024 * 1024


def next_daily_restart(now):
    local = now.astimezone(IST)
    target = local.replace(hour=3, minute=0, second=0, microsecond=0)
    return target if target > local else target + timedelta(days=1)


def read_memory_bytes(root=Path("/sys/fs/cgroup")):
    """Read container working memory plus swap, including FFmpeg children."""
    try:
        if (root / "memory.current").exists():
            usage = int((root / "memory.current").read_text())
            swap_file = root / "memory.swap.current"
            swap = int(swap_file.read_text()) if swap_file.exists() else 0
            stat_file = root / "memory.stat"
            inactive_name = "inactive_file"
        else:
            root = root / "memory"
            usage = int((root / "memory.usage_in_bytes").read_text())
            stat_file = root / "memory.stat"
            swap = 0
            inactive_name = "total_inactive_file"
        stats = dict(line.split() for line in stat_file.read_text().splitlines())
        swap = swap or int(stats.get("total_swap", stats.get("swap", 0)))
        return max(0, usage - int(stats.get(inactive_name, 0))) + swap
    except (OSError, ValueError):
        # A process-tree fallback is useful where cgroup files are unavailable.
        try:
            import psutil

            parent = psutil.Process()
            total = 0
            for process in [parent, *parent.children(recursive=True)]:
                try:
                    total += process.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return total
        except (ImportError, OSError):
            return None


class MemoryGuard:
    def __init__(self, quota_bytes, threshold=0.90, sustained_seconds=30, cooldown=300):
        self.quota = quota_bytes
        self.threshold = threshold
        self.sustained = sustained_seconds
        self.cooldown = cooldown
        self.above_since = None
        self.last_restart = float("-inf")

    def should_restart(self, usage, now, uptime):
        if usage is None or usage < self.quota * self.threshold:
            self.above_since = None
            return False
        if self.above_since is None:
            self.above_since = now
        return (
            uptime >= 120
            and now - self.last_restart >= self.cooldown
            and now - self.above_since >= self.sustained
        )

    def restarted(self, now):
        self.last_restart = now
        self.above_since = None


def request_dyno_restart(app, dyno, token):
    # Only the current worker is addressed. Never use the app-wide dynos endpoint.
    if not re.fullmatch(r"[a-z][a-z0-9-]*", app or "") or not re.fullmatch(
        r"worker\.\d+", dyno or ""
    ) or not token:
        LOG.warning("Dyno restart unavailable; using local worker recovery.")
        return False
    request = Request(
        f"https://api.heroku.com/apps/{app}/dynos/{dyno}",
        method="DELETE",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.heroku+json; version=3",
            "User-Agent": "VivaanXMusic-dyno-guard/1",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        # Do not log response bodies, URLs from exceptions, or credentials.
        LOG.warning("Dyno restart API failed (%s); using local recovery.", type(exc).__name__)
        return False


def stop_child(child):
    if child is None:
        return
    # Kill the group even if the main process exited, to reclaim orphaned FFmpeg.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


def main():
    command = [sys.executable, "-m", "VIVAANXMUSIC"]
    enabled = os.getenv("DYNO_GUARD_ENABLED") == "1"
    app = os.getenv("DYNO_GUARD_APP", "")
    if not enabled or app != os.getenv("HEROKU_APP_NAME") or not re.fullmatch(
        r"worker\.\d+", os.getenv("DYNO", "")
    ):
        os.execv(sys.executable, command)
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    quota_mb = int(os.getenv("DYNO_MEMORY_QUOTA_MB", "1024"))
    if quota_mb <= 0:
        raise ValueError("DYNO_MEMORY_QUOTA_MB must be positive")
    guard = MemoryGuard(quota_mb * MIB)
    token = os.getenv("HEROKU_API_KEY", "")
    dyno = os.environ["DYNO"]
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopping.set())

    daily = next_daily_restart(datetime.now(timezone.utc))
    LOG.info(
        "Enabled for %s/%s; quota=%s MiB; memory trigger=90%% for 30s; next daily restart=%s",
        app, dyno, quota_mb, daily.isoformat(),
    )
    initial_memory = read_memory_bytes()
    if initial_memory is not None:
        LOG.info("Container memory at supervisor startup: %.0f MiB.", initial_memory / MIB)
    else:
        LOG.warning("Container memory metrics unavailable; daily and crash recovery remain active.")
    child = None
    launched_at = 0
    launch_after = 0
    crash_delay = 10
    try:
        while not stopping.is_set():
            now = time.monotonic()
            if child is not None and child.poll() is not None:
                runtime = now - launched_at
                LOG.warning("Worker exited (status=%s); relaunching in %ss.", child.returncode, crash_delay)
                stop_child(child)
                child = None
                launch_after = now + crash_delay
                crash_delay = 10 if runtime >= 300 else min(crash_delay * 2, 300)

            if child is None and now >= launch_after:
                child = subprocess.Popen(command, start_new_session=True)
                launched_at = now
                LOG.info("Worker launched; pid=%s.", child.pid)

            wall_now = datetime.now(timezone.utc)
            usage = read_memory_bytes()
            reason = None
            if wall_now >= daily:
                reason = "daily 03:00 IST maintenance"
                daily = next_daily_restart(wall_now)
            elif child is not None and guard.should_restart(usage, now, now - launched_at):
                reason = f"sustained memory pressure ({usage / MIB:.0f}/{quota_mb} MiB)"
                guard.restarted(now)

            if reason:
                LOG.warning("Restart requested: %s.", reason)
                if request_dyno_restart(app, dyno, token):
                    LOG.info("Heroku accepted restart for %s/%s.", app, dyno)
                    if stopping.wait(45):
                        break
                    LOG.warning("Dyno has not stopped after 45s; recycling worker locally.")
                if stopping.is_set():
                    break
                stop_child(child)
                child = None
                launch_after = time.monotonic() + 5
                guard.restarted(time.monotonic())
            stopping.wait(10)
    finally:
        stop_child(child)


if __name__ == "__main__":
    main()

import asyncio
import re
import subprocess
from json import JSONDecodeError
from typing import Dict, List, Optional, Set

from ntgcalls import FFmpegError
from pytgcalls import ffmpeg as pytgcalls_ffmpeg


_PATCHES_APPLIED = False
_SUPPORTED_FLAGS: Dict[str, Set[str]] = {}
_SUPPORTED_FLAGS_LOCKS: Dict[str, asyncio.Lock] = {}


async def _get_supported_flags(executable: str) -> Set[str]:
    cached = _SUPPORTED_FLAGS.get(executable)
    if cached is not None:
        return cached

    lock = _SUPPORTED_FLAGS_LOCKS.setdefault(executable, asyncio.Lock())
    async with lock:
        cached = _SUPPORTED_FLAGS.get(executable)
        if cached is not None:
            return cached

        try:
            proc = await asyncio.create_subprocess_exec(
                executable,
                "-h",
                "full",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise FFmpegError(f"{executable} not installed") from exc

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        except (subprocess.TimeoutExpired, JSONDecodeError):
            proc.kill()
            raise

        supported = set(re.findall(r"(?m)^ *(-\w+).*?\s+", stdout.decode("utf-8")))
        supported.add("-i")
        _SUPPORTED_FLAGS[executable] = supported
        return supported


async def cached_cleanup_commands(
    commands: List[str],
    process_name: Optional[str] = None,
    blacklist: Optional[List[str]] = None,
) -> List[str]:
    if not commands:
        return commands

    supported = await _get_supported_flags(process_name or commands[0])
    blocked = set(blacklist or [])
    new_commands = []
    ignore_next = False

    for value in commands:
        if len(value) > 0:
            if value[0] == "-":
                ignore_next = value not in supported or value in blocked

            if not ignore_next:
                new_commands.append(value)
            elif value[0] != "-":
                ignore_next = False

    return new_commands


def apply_runtime_patches() -> None:
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return

    pytgcalls_ffmpeg.cleanup_commands = cached_cleanup_commands
    _PATCHES_APPLIED = True

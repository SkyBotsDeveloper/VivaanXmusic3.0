import asyncio
import shlex
from typing import Tuple

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

from ..logging import LOGGER
from ..security import build_subprocess_env


def install_req(cmd: str) -> Tuple[str, str, int, int]:
    async def install_requirements():
        args = shlex.split(cmd)
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=build_subprocess_env(),
        )
        stdout, stderr = await process.communicate()
        return (
            stdout.decode("utf-8", "replace").strip(),
            stderr.decode("utf-8", "replace").strip(),
            process.returncode,
            process.pid,
        )

    return asyncio.get_event_loop().run_until_complete(install_requirements())


def git():
    """Git access is optional; always boot the code already deployed on disk."""
    try:
        Repo()
        LOGGER(__name__).info("Git Client Found [VPS DEPLOYER]")
    except (GitCommandError, InvalidGitRepositoryError, OSError):
        LOGGER(__name__).info(
            "Git updates unavailable; starting the existing deployed version."
        )

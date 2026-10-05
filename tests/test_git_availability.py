"""Exercise startup and the actual updater against isolated local Git remotes."""

import ast
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from git import Actor, Repo
from git.exc import GitCommandError, InvalidGitRepositoryError


ROOT = Path(__file__).resolve().parents[1]


def functions(path, **namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class StartupTest(unittest.TestCase):
    def test_git_access_is_optional_at_startup(self):
        for error in (InvalidGitRepositoryError("no .git"),
                      GitCommandError("git", 128), OSError("git unavailable")):
            with self.subTest(error=type(error).__name__):
                repo = Mock(side_effect=error)
                logger = Mock()
                ns = functions("VIVAANXMUSIC/core/git.py", Repo=repo, LOGGER=Mock(return_value=logger),
                               GitCommandError=GitCommandError, InvalidGitRepositoryError=InvalidGitRepositoryError,
                               Tuple=__import__("typing").Tuple)
                ns["git"]()
                repo.init.assert_not_called()
                logger.info.assert_called_once()

    def test_existing_checkout_does_not_contact_private_upstream_at_boot(self):
        repo = Mock()
        ns = functions("VIVAANXMUSIC/core/git.py", Repo=Mock(return_value=repo), LOGGER=Mock(),
                       GitCommandError=GitCommandError, InvalidGitRepositoryError=InvalidGitRepositoryError,
                       Tuple=__import__("typing").Tuple)
        ns["git"]()
        self.assertEqual(repo.mock_calls, [])


class UpdaterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = Repo.init(self.root / "origin.git", bare=True)
        self.repo = Repo.init(self.root / "bot")
        self.file = Path(self.repo.working_tree_dir) / "bot.txt"
        self.file.write_text("deployed version", encoding="utf-8")
        actor = Actor("Test", "test@example.com")
        self.repo.index.add(["bot.txt"])
        self.repo.index.commit("deployed", author=actor, committer=actor)
        self.repo.git.branch("-M", "main")
        remote = self.repo.create_remote("origin", str(self.origin.git_dir))
        remote.push("main:main")
        remote.fetch("main")
        self.repo.head.reference.set_tracking_branch(remote.refs.main)
        self.new = Repo.clone_from(str(self.origin.git_dir), self.root / "new", branch="main")
        (Path(self.new.working_tree_dir) / "bot.txt").write_text("new version", encoding="utf-8")
        self.new.index.add(["bot.txt"])
        self.new.index.commit("new update", author=actor, committer=actor)
        self.new.remote("origin").push("main:main")
        self.response = SimpleNamespace(text="update", edit=AsyncMock())
        self.message = SimpleNamespace(reply_text=AsyncMock(return_value=self.response))
        self.get_active = AsyncMock(return_value=[])
        self.cleanup = Mock()
        self.restart = Mock()
        async def rich_call(method, *args, **kwargs):
            return await method(*args, **kwargs)
        self.ns = functions("VIVAANXMUSIC/plugins/sudo/restart.py", asyncio=asyncio, subprocess=subprocess,
                            os=SimpleNamespace(execv=self.restart), sys=sys, datetime=datetime,
                            Repo=lambda: Repo(self.repo.working_tree_dir), GitCommandError=GitCommandError,
                            InvalidGitRepositoryError=InvalidGitRepositoryError,
                            config=SimpleNamespace(UPSTREAM_BRANCH="main"), HAPP=object(),
                            build_subprocess_env=lambda: {key: os.environ[key] for key in
                                ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE") if key in os.environ},
                            rich_call=rich_call, get_active_chats=self.get_active,
                            remove_active_chat=AsyncMock(), remove_active_video_chat=AsyncMock(),
                            app=SimpleNamespace(send_message=AsyncMock(), mention="Bot"))
        self.ns["is_heroku"] = AsyncMock(return_value=False)
        self.ns["cleanup_storage"] = self.cleanup
        self.locale = {f"server_{i}": f"server_{i}" for i in range(1, 11)}
        self.head = self.repo.head.commit.hexsha

    def tearDown(self):
        self.new.close()
        self.repo.close()
        self.origin.close()

    async def update(self):
        await self.ns["update_"](None, self.message, self.locale)

    def assert_running_unchanged(self, content="deployed version"):
        self.assertEqual(self.repo.head.commit.hexsha, self.head)
        self.assertEqual(self.file.read_text(encoding="utf-8"), content)
        self.get_active.assert_not_awaited()
        self.ns["remove_active_chat"].assert_not_awaited()
        self.ns["app"].send_message.assert_not_awaited()
        self.cleanup.assert_not_called()
        self.restart.assert_not_called()

    async def test_denied_fetch_does_not_apply_stale_updates_or_restart(self):
        self.repo.remote("origin").fetch("main")  # stale refs do contain an update
        self.repo.remote("origin").set_url(str(self.root / "inaccessible-private.git"))
        await self.update()
        self.assert_running_unchanged()
        self.assertIn("keep running", self.response.edit.call_args.args[0])

    async def test_dirty_checkout_pull_failure_preserves_deployed_files_and_playback(self):
        self.file.write_text("local customization", encoding="utf-8")
        await self.update()
        self.assert_running_unchanged("local customization")
        self.assertEqual(self.repo.git.for_each_ref("refs/stash"), "")

    async def test_access_restored_allows_update_and_normal_restart(self):
        self.repo.remote("origin").set_url(str(self.root / "inaccessible-private.git"))
        await self.update()
        self.assert_running_unchanged()
        self.repo.remote("origin").set_url(str(self.origin.git_dir))
        await self.update()
        self.assertEqual(self.file.read_text(encoding="utf-8"), "new version")
        self.get_active.assert_awaited_once()
        self.cleanup.assert_called_once()
        self.restart.assert_called_once_with(sys.executable, [sys.executable, "-m", "VIVAANXMUSIC"])

    async def test_missing_origin_or_git_metadata_skips_update(self):
        self.repo.delete_remote("origin")
        await self.update()
        self.assert_running_unchanged()
        self.ns["Repo"] = Mock(side_effect=InvalidGitRepositoryError("Heroku package without .git"))
        self.ns["is_heroku"].return_value = True
        await self.update()
        self.assert_running_unchanged()

    async def test_missing_branch_does_not_restart(self):
        self.ns["config"].UPSTREAM_BRANCH = "missing-branch"
        await self.update()
        self.assert_running_unchanged()

    async def test_unborn_git_checkout_skips_fetch(self):
        empty = Repo.init(self.root / "empty")
        empty.create_remote("origin", str(self.origin.git_dir))
        self.addCleanup(empty.close)
        self.ns["Repo"] = lambda: empty
        self.ns["_update_git"] = AsyncMock()
        await self.update()
        self.ns["_update_git"].assert_not_awaited()
        self.assert_running_unchanged()

    async def test_update_timeout_is_bounded_and_noninteractive(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 30)) as run:
            await self.update()
        self.assert_running_unchanged()
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")


if __name__ == "__main__":
    unittest.main()

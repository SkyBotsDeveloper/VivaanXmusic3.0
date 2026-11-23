import ast
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


def load_settings(collection):
    source = Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/utils/database.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    methods = {"is_music_enabled", "set_music_enabled", "get_vcnotify"}
    body = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in methods]
    env = dict(music_enabled={}, music_revisions={}, vcnotify={},
               musicsettingsdb=collection, vcnotifydb=collection)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), env)
    return env


class MusicSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_groups_default_music_on_notifications_off(self):
        collection = AsyncMock()
        collection.find_one.return_value = None
        env = load_settings(collection)
        self.assertTrue(await env["is_music_enabled"](-10))
        self.assertFalse(await env["get_vcnotify"](-10))

    async def test_disabled_setting_survives_restart_and_cache_handles_false(self):
        collection = AsyncMock()
        env = load_settings(collection)
        await env["set_music_enabled"](-10, False)
        collection.update_one.assert_awaited_once_with(
            {"chat_id": -10}, {"$set": {"enabled": False}}, upsert=True)
        self.assertFalse(await env["is_music_enabled"](-10))
        collection.find_one.assert_not_awaited()
        collection.find_one.return_value = {"enabled": False}
        restarted = load_settings(collection)
        self.assertFalse(await restarted["is_music_enabled"](-10))

    async def test_database_failure_does_not_change_cached_switch(self):
        collection = AsyncMock()
        collection.update_one.side_effect = RuntimeError("database unavailable")
        env = load_settings(collection)
        env["music_enabled"][-10] = True
        with self.assertRaises(RuntimeError):
            await env["set_music_enabled"](-10, False)
        self.assertTrue(await env["is_music_enabled"](-10))

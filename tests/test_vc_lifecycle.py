"""Exercise production call methods with Telegram/transport I/O replaced."""
import ast
import asyncio
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from pyrogram.enums import ChatMemberStatus
from pyrogram.raw.functions.phone import GetGroupParticipants
from pytgcalls.types import GroupCallConfig

ROOT = Path(__file__).resolve().parents[1]


def load_call_methods():
    tree = ast.parse((ROOT / "VIVAANXMUSIC/core/call.py").read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Call")
    cls.body = [node for node in cls.body if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name != "__init__"]
    for method in cls.body:
        method.decorator_list = [d for d in method.decorator_list if isinstance(d, ast.Name) and d.id == "staticmethod"]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    env = dict(asyncio=asyncio, time=time, ChatMemberStatus=ChatMemberStatus,
               GroupCallConfig=GroupCallConfig, GetGroupParticipants=GetGroupParticipants,
               LOGGER=Mock(), EMPTY_VC_GRACE_SECONDS=300, EMPTY_VC_CHECK_INTERVAL=30,
               empty_vc_since={}, empty_vc_watchdogs={}, vc_join_targets={},
               vc_join_call_map={}, vc_join_snapshots={}, db={})
    for name in ("get_vcnotify", "get_assistant", "group_assistant", "get_autoplay", "is_music_enabled", "_clear_"):
        env[name] = AsyncMock()
    exec(compile(ast.fix_missing_locations(module), str(ROOT / "VIVAANXMUSIC/core/call.py"), "exec"), env)
    call = env["Call"]()
    call.active_calls = set()
    call.idle_notify_calls = set()
    call._stream_locks = {}
    call._vc_presence_suppressed = {}
    call._vc_ban_notices = {}
    call._queue_generations = {}
    return call, env


class VcLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call, self.env = load_call_methods()
        self.app = NS(get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.MEMBER)), send_message=AsyncMock())
        self.env["app"] = self.app
        self.env["UserNotParticipant"] = type("UserNotParticipant", (Exception,), {})
        self.assistant = NS(play=AsyncMock(), leave_call=AsyncMock())
        self.env["group_assistant"].return_value = self.assistant
        self.env["get_assistant"].return_value = NS(id=123)
        self.env["get_vcnotify"].return_value = True
        self.env["assert_music_stream_allowed"] = AsyncMock()
        self.call._resolve_vc_call_id = AsyncMock(return_value=500)
        self.call._ignored_vc_user_ids = lambda: {123, 456}

    async def test_notify_off_never_joins_or_warns(self):
        self.env["get_vcnotify"].return_value = False
        self.assertFalse(await self.call.ensure_vc_notify_presence(-10, -10))
        self.app.get_chat_member.assert_not_awaited()
        self.app.send_message.assert_not_awaited()
        self.assistant.play.assert_not_awaited()

    async def test_banned_assistant_warns_once_per_vc_start_and_keeps_setting(self):
        self.app.get_chat_member.return_value.status = ChatMemberStatus.BANNED
        await self.call.ensure_vc_notify_presence(-10, -10)
        await self.call.ensure_vc_notify_presence(-10, -10)
        self.app.send_message.assert_awaited_once()
        self.call._resolve_vc_call_id.return_value = 501
        await self.call.ensure_vc_notify_presence(-10, -10)
        self.assertEqual(self.app.send_message.await_count, 2)
        self.assistant.play.assert_not_awaited()
        self.assertTrue(self.env["get_vcnotify"].return_value)

    async def test_concurrent_banned_assistant_checks_send_one_notice(self):
        self.app.get_chat_member.return_value.status = ChatMemberStatus.BANNED
        async def send(*args, **kwargs):
            await asyncio.sleep(0)
        self.app.send_message.side_effect = send
        await asyncio.gather(
            self.call.ensure_vc_notify_presence(-10, -10),
            self.call.ensure_vc_notify_presence(-10, -10),
        )
        self.app.send_message.assert_awaited_once()

    async def test_notify_joins_silently_without_creating_vc_or_interrupting_music(self):
        self.assertTrue(await self.call.ensure_vc_notify_presence(-10, -10))
        self.assertIn(-10, self.call.idle_notify_calls)
        args, kwargs = self.assistant.play.call_args
        self.assertEqual(args, (-10, None))
        self.assertFalse(kwargs["config"].auto_start)
        await self.call.ensure_vc_notify_presence(-10, -10)
        self.assistant.play.assert_awaited_once()

    async def test_empty_vc_suppression_lasts_until_a_new_vc(self):
        self.call._vc_presence_suppressed[-10] = 500
        self.assertFalse(await self.call.ensure_vc_notify_presence(-10, -10))
        self.assistant.play.assert_not_awaited()
        self.call._resolve_vc_call_id.return_value = 501
        self.assertTrue(await self.call.ensure_vc_notify_presence(-10, -10))

    async def test_listener_snapshot_ignores_self_bots_but_counts_muted_human(self):
        self.call._resolve_vc_call = AsyncMock(return_value=NS(id=500))
        def participant(user):
            return NS(peer=NS(user_id=user), left=False)
        client = NS(invoke=AsyncMock(return_value=NS(
            users=[NS(id=999, bot=True)], next_offset="",
            participants=[participant(123), participant(456), participant(999)])))
        self.env["get_assistant"].return_value = client
        from pyrogram.raw.types import InputGroupCall
        self.call._resolve_vc_call.return_value = InputGroupCall(id=500, access_hash=7)
        self.assertFalse(await self.call._real_vc_listener_ids(self.assistant, -10))
        client.invoke.return_value.participants.append(participant(777))
        self.assertEqual(await self.call._real_vc_listener_ids(self.assistant, -10), {777})
        self.assistant.play.assert_not_awaited()

    async def test_five_minute_timer_survives_track_changes_and_resets_on_listener(self):
        self.call._real_vc_listener_ids = AsyncMock(return_value=set())
        with patch.object(time, "monotonic", return_value=100):
            self.assertEqual(await self.call._empty_vc_elapsed(self.assistant, -10), (True, 0))
        self.env["db"][-10] = [{"title": "next autoplay track"}]
        with patch.object(time, "monotonic", return_value=400):
            self.assertEqual(await self.call._empty_vc_elapsed(self.assistant, -10), (True, 300))
        self.call._real_vc_listener_ids.return_value = {777}
        self.assertEqual(await self.call._empty_vc_elapsed(self.assistant, -10), (False, 0))
        self.assertNotIn(-10, self.env["empty_vc_since"])

    async def test_watchdog_clears_playback_leaves_and_notifies_source_group(self):
        self.call.active_calls.add(-10)
        self.env["db"][-10] = [{"chat_id": -20}]
        self.call._empty_vc_elapsed = AsyncMock(return_value=(True, 300))
        self.call.stop_stream = AsyncMock()
        self.call._send_empty_vc_stop_notice = AsyncMock()
        await self.call._empty_vc_watchdog_loop(-10)
        self.call.stop_stream.assert_awaited_once_with(-10, leave=True, suppress_notifications=True)
        self.call._send_empty_vc_stop_notice.assert_awaited_once_with(-20)

    async def test_stop_after_empty_vc_never_rejoins_same_call(self):
        self.call.active_calls.add(-10)
        self.call.stop_vc_join_notifier = AsyncMock()
        self.call.maybe_start_vc_join_notifier = AsyncMock()
        await self.call.stop_stream(-10, leave=True, suppress_notifications=True)
        self.env["_clear_"].assert_awaited_once_with(-10)
        self.assistant.leave_call.assert_awaited_once_with(-10)
        self.assertNotIn(-10, self.call.active_calls)
        self.assertEqual(self.call._vc_presence_suppressed[-10], 500)
        self.assertFalse(await self.call.ensure_vc_notify_presence(-10, -10))

    async def test_normal_stop_keeps_silent_assistant_only_when_notify_enabled(self):
        self.call.active_calls.add(-10)
        self.call.stop_vc_join_notifier = AsyncMock()
        self.call.maybe_start_vc_join_notifier = AsyncMock()
        await self.call.stop_stream(-10)
        self.assertIn(-10, self.call.idle_notify_calls)
        self.assertIn(-10, self.call.active_calls)
        self.assistant.leave_call.assert_not_awaited()
        self.assistant.play.assert_awaited_once()
        self.env["get_vcnotify"].return_value = False
        await self.call.stop_stream(-10)
        self.assistant.leave_call.assert_awaited_once_with(-10)
        self.assertNotIn(-10, self.call.active_calls)

    async def test_failed_listener_lookup_resets_timer_without_stopping_music(self):
        self.call.active_calls.add(-10)
        self.env["empty_vc_since"][-10] = 0
        async def failed_lookup(*args):
            self.call.active_calls.clear()
            raise TimeoutError()
        self.call._empty_vc_elapsed = failed_lookup
        self.call.stop_stream = AsyncMock()
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            await self.call._empty_vc_watchdog_loop(-10)
        self.call.stop_stream.assert_not_awaited()
        self.assertFalse(self.env["empty_vc_since"])

    async def test_autoplay_result_cannot_resurrect_call_stopped_during_lookup(self):
        self.call.active_calls.add(-10)
        self.env["get_autoplay"].return_value = True
        self.env["is_music_enabled"].return_value = True
        self.call._allow_autoplay_for_vc_state = AsyncMock(return_value=True)
        async def lookup(*args, **kwargs):
            self.call._queue_generations[-10] = 1
            self.call.active_calls.clear()
            return {"vidid": "new"}
        self.env["YouTube"] = NS(autoplay=AsyncMock(side_effect=lookup))
        self.assertFalse(await self.call._enqueue_autoplay_track(-10, {"vidid": "seed", "seconds": 200}))
        self.assertFalse(self.env["db"])

    async def test_queued_download_cannot_rejoin_after_stop(self):
        self.call._queue_generations[-10] = 1
        with self.assertRaises(asyncio.CancelledError):
            await self.call._play_stream(self.assistant, -10, None, queue_generation=0)
        self.assistant.play.assert_not_awaited()

    async def test_stop_during_transport_connect_leaves_the_obsolete_stream(self):
        async def connect(*args):
            self.call._queue_generations[-10] = 1
        self.assistant.play.side_effect = connect
        with self.assertRaises(asyncio.CancelledError):
            await self.call._play_stream(self.assistant, -10, None, queue_generation=0)
        self.assistant.leave_call.assert_awaited_once_with(-10)


if __name__ == "__main__":
    unittest.main()

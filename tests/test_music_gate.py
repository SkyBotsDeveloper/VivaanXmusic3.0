import asyncio
import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pyrogram.enums import ChatMemberStatus

ROOT = Path(__file__).resolve().parents[1]


class MusicGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = types.ModuleType("VIVAANXMUSIC.utils.database")
        self.db.is_music_enabled = AsyncMock(return_value=False)
        self.db.music_revisions = {}
        self.app = types.SimpleNamespace(get_chat_member=AsyncMock(return_value=
            types.SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)))
        package = types.ModuleType("VIVAANXMUSIC")
        package.app = self.app
        rich = types.ModuleType("VIVAANXMUSIC.utils.rich_buttons")
        rich.rich_call = lambda function, *args, **kwargs: function(*args, **kwargs)
        spec = importlib.util.spec_from_file_location("gate_under_test", ROOT / "VIVAANXMUSIC/utils/music_gate.py")
        self.gate = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"VIVAANXMUSIC": package,
                                      self.db.__name__: self.db, rich.__name__: rich}):
            spec.loader.exec_module(self.gate)
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=-10), reply_text=AsyncMock())

    def query(self, token, user=42, chat=-10):
        return types.SimpleNamespace(data=f"music_once {token}",
            from_user=types.SimpleNamespace(id=user), answer=AsyncMock(),
            message=types.SimpleNamespace(chat=types.SimpleNamespace(id=chat), edit_reply_markup=AsyncMock()))

    async def request(self, action):
        self.assertFalse(await self.gate.check_music_request(self.message, 42, action))
        return next(reversed(self.gate._requests))

    async def test_default_on_has_no_membership_rpc_or_warning(self):
        self.db.is_music_enabled.return_value = True
        self.assertTrue(await self.gate.check_music_request(self.message, 42, AsyncMock()))
        self.app.get_chat_member.assert_not_awaited()
        self.message.reply_text.assert_not_awaited()

    async def test_members_cannot_get_bypass_button(self):
        self.app.get_chat_member.return_value.status = ChatMemberStatus.MEMBER
        self.assertFalse(await self.gate.check_music_request(self.message, 42, AsyncMock()))
        self.assertIsNone(self.message.reply_text.call_args.kwargs["reply_markup"])
        self.assertFalse(self.gate._requests)

    async def test_admin_approval_is_single_use_and_scoped_to_request(self):
        async def play():
            self.assertTrue(await self.gate.music_request_allowed(-10, 42))
            self.assertFalse(await self.gate.music_request_allowed(-11, 42))
            self.assertFalse(await self.gate.music_request_allowed(-10, 43))
            # Spawned autoplay/listening tasks cannot inherit the bypass.
            self.assertFalse(await asyncio.create_task(self.gate.music_request_allowed(-10, 42)))
        action = AsyncMock(side_effect=play)
        token = await self.request(action)
        await self.gate.approve_music_request(self.query(token))
        await self.gate.approve_music_request(self.query(token))
        action.assert_awaited_once()
        self.assertFalse(await self.gate.music_request_allowed(-10, 42))
        self.assertFalse(self.db.is_music_enabled.return_value)

    async def test_wrong_user_chat_or_demoted_admin_is_denied(self):
        action = AsyncMock()
        token = await self.request(action)
        await self.gate.approve_music_request(self.query(token, user=43))
        await self.gate.approve_music_request(self.query(token, chat=-11))
        self.app.get_chat_member.return_value.status = ChatMemberStatus.MEMBER
        await self.gate.approve_music_request(self.query(token))
        action.assert_not_awaited()

    async def test_setting_change_and_expired_button_invalidate_approval(self):
        action = AsyncMock()
        token = await self.request(action)
        self.db.music_revisions[-10] = 1
        await self.gate.approve_music_request(self.query(token))
        action.assert_not_awaited()
        token = await self.request(action)
        self.gate._requests[token]["expires"] = 0
        await self.gate.approve_music_request(self.query(token))
        action.assert_not_awaited()

    async def test_pending_requests_are_bounded(self):
        with patch.object(self.gate, "MAX_REQUESTS", 3):
            for _ in range(10):
                await self.request(AsyncMock())
            self.assertEqual(len(self.gate._requests), 3)

    async def test_old_selection_can_be_approved_without_answering_expired_query(self):
        handler = AsyncMock()
        async def select(client, query):
            await query.answer()
            await handler()
        wrapped = self.gate.music_callback(select)
        original = self.query("unused")
        original.message = self.message
        await wrapped(None, original)
        token = next(iter(self.gate._requests))
        original.answer.side_effect = RuntimeError("QUERY_ID_INVALID")
        await self.gate.approve_music_request(self.query(token))
        handler.assert_awaited_once()

    async def test_all_play_aliases_block_before_delete_source_lookup_or_download(self):
        tree = ast.parse((ROOT / "VIVAANXMUSIC/utils/decorators/play.py").read_text(encoding="utf-8"))
        wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "PlayWrapper")
        NS = types.SimpleNamespace
        youtube = NS(url=AsyncMock())
        env = dict(get_lang=AsyncMock(return_value="en"), get_string=lambda lang: {},
                   is_maintenance=AsyncMock(return_value=True), SUDOERS=set(),
                   check_music_request=self.gate.check_music_request, YouTube=youtube)
        exec(compile(ast.Module(body=[wrapper], type_ignores=[]), "play.py", "exec"), env)
        self.app.get_chat_member.return_value.status = ChatMemberStatus.MEMBER
        handler = AsyncMock()
        decorated = env["PlayWrapper"](handler)
        self.message.sender_chat = None
        self.message.from_user = NS(id=42)
        self.message.delete = AsyncMock()
        for name in ("play", "vplay", "cplay", "cvplay", "playforce", "vplayforce",
                     "cplayforce", "cvplayforce", "fplay", "fvplay"):
            self.message.command = [name, "test"]
            await decorated(None, self.message)
        handler.assert_not_awaited()
        self.message.delete.assert_not_awaited()
        youtube.url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

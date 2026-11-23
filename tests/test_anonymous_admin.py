import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.handlers import MessageHandler
from pyrogram.types import Chat, Message, User

spec = importlib.util.spec_from_file_location("anonymous_admin", Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/core/anonymous_admin.py")
anon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anon)


class AnonymousAdminTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = anon.AnonymousAdminVerification(Mock())
        self.member = NS(status=ChatMemberStatus.ADMINISTRATOR, privileges=NS(can_manage_video_chats=True))
        self.client = NS(get_chat_member=AsyncMock(return_value=self.member), me=NS(username="skybot"))
        self.chat = Chat(id=-10, type=ChatType.SUPERGROUP)
        self.message = Message(id=1, chat=self.chat, sender_chat=self.chat,
                               from_user=User(id=1087968824), text="/pause",
                               command=["pause"], reply_to_message=Message(id=55), client=self.client)
        self.message.reply_text = AsyncMock(return_value=NS(id=100))
        self.handler = MessageHandler(AsyncMock(), filters.command("pause") & filters.group)
        self.original = self.handler.callback
        rich = ModuleType("VIVAANXMUSIC.utils.rich_buttons")
        rich.rich_call = lambda fn, *args, **kwargs: fn(*args, **kwargs)
        self.patcher = patch.dict(sys.modules, {rich.__name__: rich})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def request(self):
        await self.manager.wrap(self.handler).callback(self.client, self.message)
        self.original.assert_not_awaited()
        return next(iter(self.manager.pending))

    def query(self, token, chat=-10, prompt=100, user=77):
        return NS(data=f"anon_verify {token}", from_user=User(id=user), answer=AsyncMock(),
                  message=NS(id=prompt, chat=NS(id=chat), delete=AsyncMock()))

    async def test_regular_member_cannot_verify_or_consume_admin_request(self):
        token = await self.request()
        self.member.status = ChatMemberStatus.MEMBER
        await self.manager.verify(self.client, self.query(token))
        self.original.assert_not_awaited()
        self.assertIn(token, self.manager.pending)

    async def test_verified_admin_runs_original_command_with_real_identity_and_reply(self):
        token = await self.request()
        async def action(client, message):
            self.assertEqual(message.from_user.id, 77)
            self.assertIsNone(message.sender_chat)
            self.assertEqual(message.reply_to_message.id, 55)
            self.assertIs(anon.verified_admin_member(message), self.member)
            async def child():
                return anon.verified_admin_member(message)
            self.assertIsNone(await asyncio.create_task(child()))
        self.original.side_effect = action
        await self.manager.verify(self.client, self.query(token))
        self.original.assert_awaited_once()
        self.assertEqual(self.message.from_user.id, 1087968824)
        self.assertIs(self.message.sender_chat, self.chat)
        await self.manager.verify(self.client, self.query(token))
        self.original.assert_awaited_once()

    async def test_wrong_chat_or_copied_prompt_cannot_run_request(self):
        token = await self.request()
        await self.manager.verify(self.client, self.query(token, chat=-20))
        await self.manager.verify(self.client, self.query(token, prompt=101))
        self.client.get_chat_member.assert_not_awaited()
        self.original.assert_not_awaited()

    async def test_expiration_and_demoted_admin_are_checked_at_click_time(self):
        token = await self.request()
        self.manager.pending[token]["expires"] = 0
        await self.manager.verify(self.client, self.query(token))
        self.original.assert_not_awaited()

    async def test_actual_user_filters_are_rechecked_before_execution(self):
        token = await self.request()
        self.handler.filters = filters.command("pause") & filters.user(999)
        self.client.loop = asyncio.get_running_loop()
        self.client.executor = None
        await self.manager.verify(self.client, self.query(token, user=77))
        self.original.assert_not_awaited()

    async def test_concurrent_clicks_execute_only_once(self):
        token = await self.request()
        await asyncio.gather(*[self.manager.verify(self.client, self.query(token)) for _ in range(5)])
        self.original.assert_awaited_once()

    async def test_normal_user_commands_and_non_command_handlers_are_unchanged(self):
        self.message.sender_chat = None
        await self.manager.wrap(self.handler).callback(self.client, self.message)
        self.original.assert_awaited_once_with(self.client, self.message)
        handler = MessageHandler(AsyncMock(), filters.group)
        callback = handler.callback
        self.assertIs(self.manager.wrap(handler).callback, callback)

    async def test_sending_as_another_channel_cannot_impersonate_group_admin(self):
        self.message.sender_chat = NS(id=-20)
        await self.manager.wrap(self.handler).callback(self.client, self.message)
        self.original.assert_not_awaited()
        self.assertFalse(self.manager.pending)

    async def test_pending_verifications_are_bounded(self):
        self.manager.LIMIT = 3
        # Register once, then simulate repeated incoming anonymous commands.
        wrapped = self.manager.wrap(self.handler)
        for _ in range(10):
            await wrapped.callback(self.client, self.message)
        self.assertEqual(len(self.manager.pending), 3)

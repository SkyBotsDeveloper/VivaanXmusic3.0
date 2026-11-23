import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from pyrogram.enums import ChatType, ChatMemberStatus


source = Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/plugins/admins/vclogger.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
body = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
for node in body:
    node.decorator_list = []


class VcLoggerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = dict(ChatType=ChatType, ChatMemberStatus=ChatMemberStatus,
                        get_vc_logger=AsyncMock(), set_vc_logger=AsyncMock())
        exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), self.env)
        self.client = NS(id=42, get_chat=AsyncMock(return_value=NS(type=ChatType.SUPERGROUP)),
                         get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR,
                             privileges=NS(can_post_messages=True))))

    async def test_destination_requires_bot_admin_and_channel_posting_rights(self):
        await self.env["validate_logger"](self.client, -99)
        self.client.get_chat_member.return_value.status = ChatMemberStatus.MEMBER
        with self.assertRaises(ValueError):
            await self.env["validate_logger"](self.client, -99)
        self.client.get_chat_member.return_value.status = ChatMemberStatus.ADMINISTRATOR
        self.client.get_chat.return_value.type = ChatType.CHANNEL
        self.client.get_chat_member.return_value.privileges.can_post_messages = False
        with self.assertRaises(ValueError):
            await self.env["validate_logger"](self.client, -99)

    async def test_setting_is_saved_only_for_requesting_source_group(self):
        message = NS(chat=NS(id=-10), command=["setlogger", "-99"], reply_text=AsyncMock())
        await self.env["setlogger"](self.client, message, {})
        self.env["set_vc_logger"].assert_awaited_once_with(-10, -99)

    async def test_invalid_or_inaccessible_chat_does_not_replace_existing_setting(self):
        message = NS(chat=NS(id=-10), command=["setlogger", "not-a-chat"], reply_text=AsyncMock())
        await self.env["setlogger"](self.client, message, {})
        message.command = ["setlogger", "-99"]
        self.client.get_chat.side_effect = RuntimeError("unknown chat")
        await self.env["setlogger"](self.client, message, {})
        self.env["set_vc_logger"].assert_not_awaited()

    async def test_off_resets_only_the_current_groups_logger(self):
        message = NS(chat=NS(id=-10), command=["setlogger", "off"], reply_text=AsyncMock())
        await self.env["setlogger"](self.client, message, {})
        self.env["set_vc_logger"].assert_awaited_once_with(-10, None)

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.types import CallbackQuery, Chat, Message, User

spec = importlib.util.spec_from_file_location("admin_check", Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/utils/admin_check.py")
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


class AdminIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_checks_clicker_instead_of_bot_who_sent_menu(self):
        client = NS(get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.MEMBER)))
        message = Message(id=1, chat=Chat(id=-10, type=ChatType.SUPERGROUP),
                          from_user=User(id=42, is_bot=True), client=client)
        query = CallbackQuery(id="1", from_user=User(id=77), chat_instance="1", message=message, client=client)
        self.assertFalse(await admin.is_admin(query))
        client.get_chat_member.assert_awaited_once_with(-10, 77)
        client.get_chat_member.return_value.status = ChatMemberStatus.OWNER
        self.assertTrue(await admin.is_group_owner(query))

    async def test_anonymous_placeholder_id_is_not_an_admin_bypass(self):
        client = NS(get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.MEMBER)))
        message = Message(id=1, chat=Chat(id=-10, type=ChatType.SUPERGROUP),
                          from_user=User(id=1087968824), client=client)
        self.assertFalse(await admin.is_admin(message))
        self.assertFalse(await admin.is_group_owner(message))

    async def test_group_owner_and_current_admin_are_accepted(self):
        client = NS(get_chat_member=AsyncMock(return_value=NS(status=ChatMemberStatus.ADMINISTRATOR)))
        message = Message(id=1, chat=Chat(id=-10, type=ChatType.SUPERGROUP),
                          from_user=User(id=77), client=client)
        self.assertTrue(await admin.is_admin(message))
        self.assertFalse(await admin.is_group_owner(message))

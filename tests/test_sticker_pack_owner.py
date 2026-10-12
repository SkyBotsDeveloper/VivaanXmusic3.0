"""Check the owner type sent by the real sticker handlers to Telegram."""

import ast
import inspect
import os
import traceback
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from pyrogram import raw
from pyrogram.enums import StickerType
from pyrogram.errors import (
    FileReferenceExpired, FloodWait, FromMessageBotDisabled, PeerIdInvalid, RPCError,
    StickerEmojiInvalid, StickersetInvalid, StickersTooMuch,
)
from pyrogram.raw.core import TLObject
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


ROOT = Path(__file__).resolve().parents[1]


async def rich_call(method, *args, **kwargs):
    return await method(*args, **kwargs)


def load_handler(filename, *names):
    tree = ast.parse((ROOT / "VIVAANXMUSIC/plugins/tools" / filename).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    for node in nodes:
        node.decorator_list = []
    namespace = dict(
        raw=raw, inspect=inspect, os=os, traceback=traceback, uuid4=uuid4,
        BOT="test_bot", BOT_USERNAME="test_bot", StickerType=StickerType,
        StickersetInvalid=StickersetInvalid, StickersTooMuch=StickersTooMuch,
        StickerEmojiInvalid=StickerEmojiInvalid, PeerIdInvalid=PeerIdInvalid,
        FloodWait=FloodWait, FileReferenceExpired=FileReferenceExpired, RPCError=RPCError,
        InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
        tempfile=SimpleNamespace(mkdtemp=lambda: "test-cache"),
        shutil=SimpleNamespace(rmtree=Mock()), rich_call=rich_call,
    )
    helpers = ast.parse((ROOT / "VIVAANXMUSIC/utils/sticker_packs.py").read_text(encoding="utf-8"))
    helper_nodes = [node for node in helpers.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    exec(compile(ast.Module(body=helper_nodes, type_ignores=[]), "sticker_packs.py", "exec"), namespace)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class StickerPackOwnerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.peer = raw.types.InputPeerUser(user_id=123, access_hash=456)
        self.chat_peer = raw.types.InputPeerChannel(channel_id=555, access_hash=999)
        self.full_user = raw.types.User(id=123, access_hash=654)
        self.document = SimpleNamespace(
            id=789, access_hash=987, file_reference=b"reference",
            attributes=[raw.types.DocumentAttributeSticker(
                alt="\U0001f914", stickerset=raw.types.InputStickerSetEmpty(),
            )],
        )
        self.notify = SimpleNamespace(edit=AsyncMock())
        self.message = SimpleNamespace(
            command=["kang"], reply_text=AsyncMock(return_value=self.notify),
            id=44, chat=SimpleNamespace(id=-1000000000555),
            from_user=SimpleNamespace(id=123, username="alice", first_name="Alice", last_name=None),
            reply_to_message=SimpleNamespace(sticker=SimpleNamespace(
                set_name="original_pack", emoji="\U0001f914", type=StickerType.REGULAR,
                is_animated=False, is_video=False, needs_repainting=False,
            )),
        )

    def client(self, add_error=None, *, reject_owner=False, reject_all=False):
        created = False

        async def invoke(request):
            nonlocal created
            if isinstance(request, raw.functions.users.GetUsers):
                for owner in request.id:
                    if isinstance(owner, raw.types.InputUserFromMessage):
                        raise FromMessageBotDisabled()
                    if not isinstance(owner, raw.types.InputUser) or owner.user_id != 123:
                        raise PeerIdInvalid()
                    if owner.access_hash not in (0, 654):
                        raise PeerIdInvalid()
                return [self.full_user]
            if isinstance(request, raw.functions.messages.GetStickerSet):
                if add_error is StickersetInvalid and not created:
                    raise StickersetInvalid()
                return SimpleNamespace(documents=[self.document])
            if isinstance(request, raw.functions.messages.UploadMedia):
                return SimpleNamespace(document=self.document)
            if isinstance(request, raw.functions.stickers.AddStickerToSet):
                raise add_error()
            if isinstance(request, raw.functions.stickers.CreateStickerSet):
                if isinstance(request.user_id, raw.types.InputUserFromMessage):
                    raise FromMessageBotDisabled()
                if not isinstance(request.user_id, raw.types.InputUser) or request.user_id.user_id != 123:
                    raise PeerIdInvalid()
                if request.user_id.access_hash not in (0, 654):
                    raise PeerIdInvalid()
                if reject_all or (reject_owner and getattr(request.user_id, "access_hash", None) == 654):
                    raise PeerIdInvalid()
                created = True
                return SimpleNamespace(documents=[self.document])
            raise AssertionError(f"Unexpected RPC: {type(request)}")

        async def resolve_peer(peer_id):
            if peer_id == 123:
                return self.peer
            self.assertEqual(peer_id, self.message.chat.id)
            return self.chat_peer

        return SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(username="Actual_Bot")),
            resolve_peer=AsyncMock(side_effect=resolve_peer), invoke=AsyncMock(side_effect=invoke),
            save_file=AsyncMock(return_value=raw.types.InputFile(
                id=1, parts=1, name="image.png", md5_checksum="0" * 32,
            )),
        )

    def assert_owner(self, client, *, owner_hash=654, count=1):
        requests = [call.args[0] for call in client.invoke.await_args_list]
        creates = [request for request in requests
                   if isinstance(request, raw.functions.stickers.CreateStickerSet)]
        self.assertEqual(len(creates), count)
        owner = TLObject.read(BytesIO(creates[-1].user_id.write()))
        self.assertEqual(owner.user_id, 123)
        self.assertIsInstance(owner, raw.types.InputUser)
        self.assertEqual(owner.access_hash, owner_hash)
        self.assertTrue(creates[-1].short_name.endswith("_by_actual_bot"))
        client.get_me.assert_awaited_once()
        self.notify.edit.assert_awaited_once()
        self.assertIn("reply_markup", self.notify.edit.await_args.kwargs)
        if count > 1:
            self.assertEqual(creates[0].short_name, creates[1].short_name)
            self.assertEqual(creates[0].title, creates[1].title)
            self.assertIs(creates[0].stickers, creates[1].stickers)
        return creates[-1]

    async def kang_creates_pack(self, add_error, *, reject_owner=False, owner_hash=654, count=1):
        namespace = load_handler("kang.py", "_cs_kwargs", "_pack_name", "_pack_title",
                                 "_to_input_doc", "kang")
        namespace["_prepare_media"] = AsyncMock(return_value=("image", "image.png", False, False))
        client = self.client(add_error, reject_owner=reject_owner)
        await namespace["kang"](client, self.message)
        self.assert_owner(client, owner_hash=owner_hash, count=count)
        upload = next(call.args[0] for call in client.invoke.await_args_list
                      if isinstance(call.args[0], raw.functions.messages.UploadMedia))
        self.assertIs(upload.peer, self.chat_peer)

    async def test_kang_new_pack_owner(self):
        await self.kang_creates_pack(StickersetInvalid)

    async def test_kang_full_pack_owner(self):
        await self.kang_creates_pack(StickersTooMuch)

    async def test_packkang_owner_and_title(self):
        namespace = load_handler("sticker.py", "_cs_kwargs", "_pack_title", "pack_clone")
        self.message.command = ["packkang", "Favourite", "Stickers"]
        client = self.client()
        await namespace["pack_clone"](client, self.message)
        request = self.assert_owner(client)
        self.assertEqual(request.title, "Favourite Stickers")
        self.assertEqual(request.stickers[0].document.id, self.document.id)

    async def test_kang_group_rejected_owner_uses_bot_user_id_reference(self):
        await self.kang_creates_pack(StickersetInvalid, reject_owner=True, owner_hash=0, count=2)

    async def test_packkang_group_rejected_owner_uses_bot_user_id_reference(self):
        namespace = load_handler("sticker.py", "_cs_kwargs", "_pack_title", "pack_clone")
        self.message.command = ["packkang"]
        client = self.client(reject_owner=True)
        await namespace["pack_clone"](client, self.message)
        request = self.assert_owner(client, owner_hash=0, count=2)
        self.assertEqual(request.title, "Crafted by @alice")

    async def test_min_user_hash_is_not_reused(self):
        self.full_user = raw.types.User(id=123, access_hash=456, min=True)
        await self.kang_creates_pack(StickersetInvalid, owner_hash=0)

    async def test_basic_group_uses_bot_compatible_owner(self):
        self.message.chat.id = -555
        self.chat_peer = raw.types.InputPeerChat(chat_id=555)
        await self.kang_creates_pack(StickersetInvalid)

    async def test_private_chat_can_retry_bot_user_id_reference(self):
        namespace = load_handler("sticker.py", "_cs_kwargs", "_pack_title", "pack_clone")
        self.message.chat.id = 123
        self.message.command = ["packkang"]
        client = self.client(reject_owner=True)
        await namespace["pack_clone"](client, self.message)
        self.assert_owner(client, owner_hash=0, count=2)
        lookup = next(call.args[0] for call in client.invoke.await_args_list
                      if isinstance(call.args[0], raw.functions.users.GetUsers))
        self.assertEqual(lookup.id[0].access_hash, 0)

    async def test_repeated_peer_error_is_propagated_without_changing_owner(self):
        namespace = load_handler("sticker.py", "_pack_title")
        client = self.client(reject_all=True)
        with self.assertRaises(PeerIdInvalid):
            await namespace["create_sticker_set_for_user"](
                client, self.message, title="Pack", short_name="pack_by_actual_bot", stickers=[],
            )
        creates = [call.args[0] for call in client.invoke.await_args_list
                   if isinstance(call.args[0], raw.functions.stickers.CreateStickerSet)]
        self.assertEqual(len(creates), 2)
        self.assertTrue(all(request.user_id.user_id == 123 for request in creates))

    async def test_unknown_user_is_not_assigned_a_pack(self):
        namespace = load_handler("sticker.py", "_pack_title")
        self.full_user = raw.types.UserEmpty(id=123)
        client = self.client()
        with self.assertRaises(PeerIdInvalid):
            await namespace["create_sticker_set_for_user"](
                client, self.message, title="Pack", short_name="pack_by_actual_bot", stickers=[],
            )
        self.assertFalse(any(isinstance(call.args[0], raw.functions.stickers.CreateStickerSet)
                             for call in client.invoke.await_args_list))


if __name__ == "__main__":
    unittest.main()

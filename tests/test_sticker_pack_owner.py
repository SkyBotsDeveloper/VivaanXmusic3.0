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
    FileReferenceExpired, FloodWait, PeerIdInvalid, RPCError,
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
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class StickerPackOwnerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.peer = raw.types.InputPeerUser(user_id=123, access_hash=456)
        self.document = SimpleNamespace(
            id=789, access_hash=987, file_reference=b"reference",
            attributes=[raw.types.DocumentAttributeSticker(
                alt="\U0001f914", stickerset=raw.types.InputStickerSetEmpty(),
            )],
        )
        self.notify = SimpleNamespace(edit=AsyncMock())
        self.message = SimpleNamespace(
            command=["kang"], reply_text=AsyncMock(return_value=self.notify),
            from_user=SimpleNamespace(id=123, username="alice", first_name="Alice", last_name=None),
            reply_to_message=SimpleNamespace(sticker=SimpleNamespace(
                set_name="original_pack", emoji="\U0001f914", type=StickerType.REGULAR,
                is_animated=False, is_video=False, needs_repainting=False,
            )),
        )

    def client(self, add_error=None):
        created = False

        async def invoke(request):
            nonlocal created
            if isinstance(request, raw.functions.messages.GetStickerSet):
                if add_error is StickersetInvalid and not created:
                    raise StickersetInvalid()
                return SimpleNamespace(documents=[self.document])
            if isinstance(request, raw.functions.messages.UploadMedia):
                return SimpleNamespace(document=self.document)
            if isinstance(request, raw.functions.stickers.AddStickerToSet):
                raise add_error()
            if isinstance(request, raw.functions.stickers.CreateStickerSet):
                created = True
                return SimpleNamespace(documents=[self.document])
            raise AssertionError(f"Unexpected RPC: {type(request)}")

        return SimpleNamespace(
            resolve_peer=AsyncMock(return_value=self.peer), invoke=AsyncMock(side_effect=invoke),
            save_file=AsyncMock(return_value=raw.types.InputFile(
                id=1, parts=1, name="image.png", md5_checksum="0" * 32,
            )),
        )

    def assert_owner(self, client):
        requests = [call.args[0] for call in client.invoke.await_args_list]
        creates = [request for request in requests
                   if isinstance(request, raw.functions.stickers.CreateStickerSet)]
        self.assertEqual(len(creates), 1)
        owner = TLObject.read(BytesIO(creates[0].user_id.write()))
        self.assertIsInstance(owner, raw.types.InputUser)
        self.assertEqual((owner.user_id, owner.access_hash), (123, 456))
        self.notify.edit.assert_awaited_once()
        self.assertIn("reply_markup", self.notify.edit.await_args.kwargs)
        return creates[0]

    async def kang_creates_pack(self, add_error):
        namespace = load_handler("kang.py", "_cs_kwargs", "_pack_name", "_pack_title",
                                 "_to_input_doc", "kang")
        namespace["_prepare_media"] = AsyncMock(return_value=("image", "image.png", False, False))
        client = self.client(add_error)
        await namespace["kang"](client, self.message)
        self.assert_owner(client)
        upload = next(call.args[0] for call in client.invoke.await_args_list
                      if isinstance(call.args[0], raw.functions.messages.UploadMedia))
        self.assertIsInstance(upload.peer, raw.types.InputPeerUser)

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


if __name__ == "__main__":
    unittest.main()

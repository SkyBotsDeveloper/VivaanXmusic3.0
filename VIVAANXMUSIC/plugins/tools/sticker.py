import os
import tempfile
import inspect
from uuid import uuid4

from PIL import Image
from pyrogram import raw, filters
from pyrogram.enums import StickerType
from pyrogram.errors import StickersetInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.rich_buttons import rich_call
from VIVAANXMUSIC.utils.sticker_packs import (
    create_sticker_set_for_user,
    get_sticker_bot_username,
)


def _cs_kwargs(is_anim: bool, is_vid: bool) -> dict:
    params = inspect.signature(raw.functions.stickers.CreateStickerSet).parameters
    kw = {}
    if is_anim and "animated" in params:
        kw["animated"] = True
    if is_vid and "videos" in params:
        kw["videos"] = True
    return kw


def _pack_title(message) -> str:
    title = " ".join(message.command[1:]).strip()
    if title:
        return title[:64]

    user = message.from_user
    creator = f"@{user.username}" if user.username else " ".join(
        part for part in (user.first_name, user.last_name) if part
    )
    return f"Crafted by {creator or user.id}"[:64]


@app.on_message(filters.command("st") & ~filters.reply)
async def send_by_id(client, message):
    if len(message.command) != 2:
        return await message.reply_text("usage: /st <sticker_id>")
    sid = message.command[1]
    try:
        await client.send_sticker(message.chat.id, sid)
    except Exception as e:
        await message.reply_text(f"error: {e}")


@app.on_message(filters.command(["stickerid", "stid"]) & filters.reply)
async def show_ids(_, message):
    st = message.reply_to_message.sticker
    if not st:
        return await message.reply_text("reply to a sticker")
    await message.reply_text(
        f"sticker id: `{st.file_id}`\n"
        f"unique id: `{st.file_unique_id}`"
    )


@app.on_message(filters.command("stdl") & filters.reply)
async def download_sticker(client, message):
    proc = await message.reply_text("➣ downloading…")
    st = message.reply_to_message.sticker
    if not st:
        return await rich_call(proc.edit, "reply to a sticker")
    with tempfile.TemporaryDirectory() as td:
        path = await message.reply_to_message.download(os.path.join(td, "st"))
        if st.is_animated:
            await rich_call(proc.edit, "➣ sending .tgs…")
            await client.send_document(message.chat.id, path, caption="here's your animated sticker!")
        elif st.is_video:
            await rich_call(proc.edit, "➣ sending video…")
            await client.send_video(message.chat.id, path, supports_streaming=True, caption="here's your video sticker!")
        else:
            await rich_call(proc.edit, "➣ converting to png…")
            img = Image.open(path)
            out = f"{path}.png"
            img.save(out, "PNG")
            await client.send_photo(message.chat.id, out, caption="here's your static image!")
    await proc.delete()


@app.on_message(filters.command("packkang") & filters.reply)
async def pack_clone(client, message):
    proc = await message.reply_text("➣ cloning pack…")
    st = message.reply_to_message.sticker
    if not st:
        return await rich_call(proc.edit, "reply to a sticker")
    if not st.set_name:
        return await rich_call(proc.edit, "this sticker is not part of a public pack")
    try:
        sset = await client.invoke(
            raw.functions.messages.GetStickerSet(
                stickerset=raw.types.InputStickerSetShortName(short_name=st.set_name), hash=0
            )
        )
        title = _pack_title(message)
        bot_username = await get_sticker_bot_username(client)
        short = f"pack_{uuid4().hex[:12]}_by_{bot_username}"
        items = []
        for doc in sset.documents:
            attribute = next(
                (
                    item for item in doc.attributes
                    if isinstance(
                        item,
                        (raw.types.DocumentAttributeSticker, raw.types.DocumentAttributeCustomEmoji),
                    )
                ),
                None,
            )
            items.append(
                raw.types.InputStickerSetItem(
                    document=raw.types.InputDocument(
                        id=doc.id, access_hash=doc.access_hash, file_reference=doc.file_reference
                    ),
                    emoji=getattr(attribute, "alt", None) or st.emoji or "\U0001f914",
                    mask_coords=getattr(attribute, "mask_coords", None),
                )
            )
        if not items:
            return await rich_call(proc.edit, "the source sticker pack is empty")

        create_kwargs = _cs_kwargs(st.is_animated, st.is_video)
        params = inspect.signature(raw.functions.stickers.CreateStickerSet).parameters
        if "masks" in params and st.type == StickerType.MASK:
            create_kwargs["masks"] = True
        if "emojis" in params and st.type == StickerType.CUSTOM_EMOJI:
            create_kwargs["emojis"] = True
        if "text_color" in params and st.needs_repainting:
            create_kwargs["text_color"] = True

        await create_sticker_set_for_user(
            client, message,
            title=title,
            short_name=short,
            stickers=items,
            **create_kwargs,
        )
        await rich_call(proc.edit,
            f"cloned {len(items)} stickers!\nPack: {title}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("view pack", url=f"https://t.me/addstickers/{short}")]]),
        )
    except StickersetInvalid:
        await rich_call(proc.edit, "invalid sticker set")
    except Exception as e:
        await rich_call(proc.edit, f"error: {e}")

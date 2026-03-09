import mimetypes
import os
from io import BytesIO

from pyrogram import filters
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import (
    FreeAIError,
    generate_image,
    process_image_bytes,
)


def get_prompt(message: Message) -> str | None:
    if message.reply_to_message:
        replied = (
            message.reply_to_message.text or message.reply_to_message.caption or ""
        ).strip()
        if replied:
            return replied

    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()
    return None


def get_image_target(message: Message):
    replied = message.reply_to_message
    if not replied:
        return None, None

    if replied.photo:
        return replied.photo.file_id, "image/jpeg"

    document = replied.document
    if document and document.mime_type and document.mime_type.startswith("image/"):
        return document.file_id, document.mime_type

    return None, None


@app.on_message(filters.command("upscale"))
async def upscale_image(client, message: Message):
    file_id, mime_type = get_image_target(message)
    if not file_id:
        return await message.reply_text("Please reply to an image.")

    status = await message.reply_text("Enhancing image...")
    file_path = None
    try:
        file_path = await client.download_media(file_id)
        with open(file_path, "rb") as handle:
            image_bytes = handle.read()

        guessed_type, _ = mimetypes.guess_type(file_path)
        result_bytes = await process_image_bytes(
            image_bytes,
            mime_type=mime_type or guessed_type or "image/jpeg",
            mode="enhance",
        )

        document = BytesIO(result_bytes)
        document.name = "enhanced.png"
        await status.delete()
        await message.reply_document(document=document, caption="Enhanced image")
    except FreeAIError as exc:
        await status.edit(str(exc))
    except Exception as exc:
        await status.edit(f"Error: {exc}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


@app.on_message(filters.command("getdraw"))
async def draw_image(_, message: Message):
    query = get_prompt(message)
    if not query:
        return await message.reply_text("Please reply or provide text.")

    status = await message.reply_text("Generating image...")
    try:
        result_bytes = await generate_image(query)
        photo = BytesIO(result_bytes)
        photo.name = "generated.png"
        await status.delete()
        await message.reply_photo(photo, caption=query)
    except FreeAIError as exc:
        await status.edit(str(exc))
    except Exception as exc:
        await status.edit(f"Error: {exc}")

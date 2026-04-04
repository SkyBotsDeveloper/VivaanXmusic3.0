import mimetypes
import os
import random
from io import BytesIO

from PIL import Image
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import FreeAIError, edit_image_bytes


EDIT_STATUS_MESSAGES = (
    "Understanding your edit...",
    "Working on your image...",
    "Applying the changes...",
    "Still editing, don't panic...",
)


def get_prompt(message: Message) -> str | None:
    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()
    return None


async def get_replied_media(client: Client, message: Message) -> list[Message]:
    replied = message.reply_to_message
    if not replied:
        return []

    if replied.media_group_id:
        try:
            media_group = await client.get_media_group(message.chat.id, replied.id)
            return sorted(media_group, key=lambda item: item.id)
        except Exception:
            pass
    return [replied]


def extract_image_items(messages: list[Message]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for item in messages:
        if item.photo:
            results.append((item.photo.file_id, "image/jpeg"))
            continue

        if item.sticker and not item.sticker.is_animated and not item.sticker.is_video:
            results.append((item.sticker.file_id, "image/webp"))
            continue

        document = item.document
        if document and document.mime_type and document.mime_type.startswith("image/"):
            results.append((document.file_id, document.mime_type))
            continue

        if document:
            guessed_type, _ = mimetypes.guess_type(document.file_name or "")
            if guessed_type and guessed_type.startswith("image/"):
                results.append((document.file_id, guessed_type))
    return results[:3]


def normalize_image_bytes(file_path: str, fallback_mime: str) -> tuple[bytes, str]:
    try:
        with Image.open(file_path) as image:
            if image.mode in {"RGBA", "LA", "P"}:
                converted = image.convert("RGBA")
            else:
                converted = image.convert("RGB")

            buffer = BytesIO()
            converted.save(buffer, format="PNG")
            return buffer.getvalue(), "image/png"
    except Exception:
        with open(file_path, "rb") as handle:
            raw = handle.read()
        guessed_type, _ = mimetypes.guess_type(file_path)
        return raw, fallback_mime or guessed_type or "image/jpeg"


@app.on_message(filters.command(["editimg", "imgedit", "nanoedit"]))
async def edit_image_handler(client: Client, message: Message):
    prompt = get_prompt(message)
    if not prompt:
        return await message.reply_text(
            "Reply to an image and add what you want changed.\n"
            "Example: /editimg add sunglasses and make the background neon"
        )

    replied_media = await get_replied_media(client, message)
    image_items = extract_image_items(replied_media)
    if not image_items:
        return await message.reply_text(
            "Reply to an image, static sticker, or a small image album first."
        )

    status = await message.reply_text(random.choice(EDIT_STATUS_MESSAGES))
    await client.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    temp_paths: list[str] = []
    try:
        normalized_images: list[tuple[bytes, str]] = []
        for file_id, mime_type in image_items:
            file_path = await client.download_media(file_id)
            temp_paths.append(file_path)
            normalized_images.append(normalize_image_bytes(file_path, mime_type))

        await status.edit(random.choice(EDIT_STATUS_MESSAGES))
        result = await edit_image_bytes(prompt, images=normalized_images)

        photo = BytesIO(result)
        photo.name = "edited.png"
        await status.delete()
        await message.reply_photo(photo=photo, caption=f"Edited image\n\nPrompt: {prompt}")
    except FreeAIError as exc:
        await status.edit(str(exc))
    except Exception as exc:
        await status.edit(f"Error: {exc}")
    finally:
        for path in temp_paths:
            if path and os.path.exists(path):
                os.remove(path)

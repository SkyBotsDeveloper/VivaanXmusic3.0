import asyncio
import mimetypes
import os
import random
from io import BytesIO

from PIL import Image
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import FreeAIError, generate_video


DEFAULT_IMAGE_ANIMATION_PROMPT = "make this image come alive, smooth cinematic motion"
GENVID_STATUS_MESSAGES = (
    "Your video is being generated...",
    "Still working, don't panic...",
    "Free servers are cooking your video...",
    "Adding motion to your prompt...",
    "Rendering frames in the background...",
    "Almost there, still processing...",
)


def get_command_prompt(message: Message) -> str | None:
    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()
    return None


def get_text_prompt_from_reply(message: Message) -> str | None:
    replied = message.reply_to_message
    if not replied:
        return None

    if replied.photo or replied.sticker or replied.document:
        return None

    replied_text = (replied.text or replied.caption or "").strip()
    if replied_text:
        return replied_text
    return None


def get_image_target(message: Message):
    replied = message.reply_to_message
    if not replied:
        return None, None

    if replied.photo:
        return replied.photo.file_id, "image/jpeg"

    if replied.sticker and not replied.sticker.is_animated and not replied.sticker.is_video:
        return replied.sticker.file_id, "image/webp"

    document = replied.document
    if document:
        if document.mime_type and document.mime_type.startswith("image/"):
            return document.file_id, document.mime_type

        guessed_type, _ = mimetypes.guess_type(document.file_name or "")
        if guessed_type and guessed_type.startswith("image/"):
            return document.file_id, guessed_type

    return None, None


def normalize_reference_image(file_path: str) -> tuple[bytes, str]:
    with Image.open(file_path) as image:
        if image.mode in {"RGBA", "LA", "P"}:
            converted = image.convert("RGBA")
        else:
            converted = image.convert("RGB")

        buffer = BytesIO()
        converted.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


@app.on_message(filters.command("genvid"))
async def genvid_handler(client: Client, message: Message):
    file_id, mime_type = get_image_target(message)
    prompt = get_command_prompt(message)

    if not prompt and not file_id:
        prompt = get_text_prompt_from_reply(message)

    if not prompt and not file_id:
        return await message.reply_text(
            "Usage: /genvid [prompt]\n"
            "You can also reply to an image with /genvid [motion prompt]."
        )

    if not prompt and file_id:
        prompt = DEFAULT_IMAGE_ANIMATION_PROMPT

    if prompt and len(prompt) > 1000:
        return await message.reply_text(
            "Prompt is too long. Please keep it under 1000 characters."
        )

    status = await message.reply_text("Preparing your video request...")
    input_path = None
    output_path = None
    status_task = None
    stop_status_updates = asyncio.Event()

    try:
        image_bytes = None
        detected_mime = mime_type or "image/jpeg"

        if file_id:
            input_path = await client.download_media(file_id)
            try:
                image_bytes, detected_mime = normalize_reference_image(input_path)
            except Exception:
                with open(input_path, "rb") as handle:
                    image_bytes = handle.read()
                guessed_type, _ = mimetypes.guess_type(input_path)
                detected_mime = mime_type or guessed_type or "image/jpeg"

        async def rotate_status():
            last_index = -1
            while not stop_status_updates.is_set():
                choices = [
                    index
                    for index in range(len(GENVID_STATUS_MESSAGES))
                    if index != last_index
                ]
                last_index = random.choice(choices)
                try:
                    await status.edit(GENVID_STATUS_MESSAGES[last_index])
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(
                        stop_status_updates.wait(),
                        timeout=random.randint(5, 8),
                    )
                except asyncio.TimeoutError:
                    continue

        async def update_status(_provider_name: str):
            try:
                await status.edit(random.choice(GENVID_STATUS_MESSAGES))
            except Exception:
                pass

        status_task = asyncio.create_task(rotate_status())
        result = await generate_video(
            prompt or DEFAULT_IMAGE_ANIMATION_PROMPT,
            image_bytes=image_bytes,
            mime_type=detected_mime,
            progress_callback=update_status,
        )
        output_path = result.file_path

        stop_status_updates.set()
        try:
            await status.edit("Uploading your video...")
        except Exception:
            pass
        await client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        display_prompt = prompt or DEFAULT_IMAGE_ANIMATION_PROMPT
        if len(display_prompt) > 850:
            display_prompt = f"{display_prompt[:847]}..."

        await message.reply_video(
            video=output_path,
            caption=f"Prompt: {display_prompt}",
            supports_streaming=True,
        )
        await status.delete()
    except FreeAIError:
        stop_status_updates.set()
        await status.edit(
            "Free video servers are busy right now.\n"
            "Please try again after a little while."
        )
    except Exception as exc:
        stop_status_updates.set()
        await status.edit(f"Error: {exc}")
    finally:
        stop_status_updates.set()
        if status_task:
            status_task.cancel()
            try:
                await status_task
            except asyncio.CancelledError:
                pass
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)

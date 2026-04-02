import mimetypes
import os

from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import FreeAIError, generate_video


DEFAULT_IMAGE_ANIMATION_PROMPT = "make this image come alive, smooth cinematic motion"


def get_prompt(message: Message) -> str | None:
    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()

    if message.reply_to_message:
        replied = (
            message.reply_to_message.text or message.reply_to_message.caption or ""
        ).strip()
        if replied:
            return replied
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


@app.on_message(filters.command("genvid"))
async def genvid_handler(client: Client, message: Message):
    prompt = get_prompt(message)
    file_id, mime_type = get_image_target(message)

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

    status = await message.reply_text("Preparing video request...")
    input_path = None
    output_path = None

    try:
        image_bytes = None
        detected_mime = mime_type or "image/jpeg"

        if file_id:
            input_path = await client.download_media(file_id)
            with open(input_path, "rb") as handle:
                image_bytes = handle.read()
            guessed_type, _ = mimetypes.guess_type(input_path)
            detected_mime = mime_type or guessed_type or "image/jpeg"

        async def update_status(provider_name: str):
            try:
                await status.edit(f"Trying video provider:\n{provider_name}")
            except Exception:
                pass

        result = await generate_video(
            prompt or DEFAULT_IMAGE_ANIMATION_PROMPT,
            image_bytes=image_bytes,
            mime_type=detected_mime,
            progress_callback=update_status,
        )
        output_path = result.file_path

        await client.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        display_prompt = prompt or DEFAULT_IMAGE_ANIMATION_PROMPT
        if len(display_prompt) > 850:
            display_prompt = f"{display_prompt[:847]}..."

        await message.reply_video(
            video=output_path,
            caption=(
                f"Engine: {result.provider}\n"
                f"Prompt: {display_prompt}"
            ),
            supports_streaming=True,
        )
        await status.delete()
    except FreeAIError as exc:
        await status.edit(str(exc))
    except Exception as exc:
        await status.edit(f"Error: {exc}")
    finally:
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)

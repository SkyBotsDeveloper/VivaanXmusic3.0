import mimetypes
import os

from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import (
    FreeAIError,
    generate_chat_response,
    generate_vision_response,
)


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


def format_response(command_name: str, model_name: str, content: str) -> str:
    return (
        f"Command: {command_name}\n"
        f"Engine: {model_name}\n\n"
        f"{content}"
    )


async def send_chunked_reply(message: Message, text: str):
    for start in range(0, len(text), 4096):
        await message.reply_text(
            text[start : start + 4096],
            disable_web_page_preview=True,
        )


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


async def handle_text_model(
    client: Client,
    message: Message,
    *,
    alias: str,
    command_name: str,
):
    prompt = get_prompt(message)
    if not prompt:
        return await message.reply_text("Please provide a prompt after the command.")

    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        result = await generate_chat_response(prompt, alias=alias)
        await send_chunked_reply(
            message,
            format_response(command_name, result.model, result.content),
        )
    except FreeAIError as exc:
        await message.reply_text(str(exc))


@app.on_message(filters.command("bard"))
async def bard_handler(client: Client, message: Message):
    await handle_text_model(client, message, alias="bard", command_name="Bard")


@app.on_message(filters.command("gemini"))
async def gemini_handler(client: Client, message: Message):
    await handle_text_model(client, message, alias="gemini", command_name="Gemini")


@app.on_message(filters.command("gpt"))
async def gpt_handler(client: Client, message: Message):
    await handle_text_model(client, message, alias="gpt", command_name="GPT")


@app.on_message(filters.command("llama"))
async def llama_handler(client: Client, message: Message):
    await handle_text_model(client, message, alias="llama", command_name="LLaMA")


@app.on_message(filters.command("mistral"))
async def mistral_handler(client: Client, message: Message):
    await handle_text_model(client, message, alias="mistral", command_name="Mistral")


@app.on_message(filters.command("geminivision"))
async def geminivision_handler(client: Client, message: Message):
    file_id, mime_type = get_image_target(message)
    if not file_id:
        return await message.reply_text(
            "Please reply to an image with the /geminivision command."
        )

    prompt = get_prompt(message) or "Describe this image."
    await client.send_chat_action(message.chat.id, ChatAction.TYPING)

    file_path = None
    try:
        file_path = await client.download_media(file_id)
        with open(file_path, "rb") as handle:
            image_bytes = handle.read()

        guessed_type, _ = mimetypes.guess_type(file_path)
        result = await generate_vision_response(
            prompt,
            image_bytes,
            mime_type=mime_type or guessed_type or "image/jpeg",
        )
        await send_chunked_reply(
            message,
            format_response("Gemini Vision", result.model, result.content),
        )
    except FreeAIError as exc:
        await message.reply_text(str(exc))
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

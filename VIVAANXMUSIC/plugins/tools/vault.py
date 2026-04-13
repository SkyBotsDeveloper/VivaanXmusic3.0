import secrets
from datetime import datetime

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.errors import MessageIdInvalid, RPCError
from pyrogram.types import Message

import config
from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import (
    delete_vault_message,
    get_vault_message,
    save_vault_message,
)


PM_ONLY_MESSAGE = "This feature only works in PM. Open my DM and use it there."

CODE_WORDS = (
    "nova",
    "river",
    "pixel",
    "storm",
    "shadow",
    "orbit",
    "ember",
    "crystal",
    "falcon",
    "cipher",
    "lotus",
    "matrix",
    "silver",
    "quantum",
    "rocket",
    "echo",
)


def _normalize_code(code: str) -> str:
    return code.strip().lower()


async def _new_vault_code() -> str:
    for _ in range(20):
        code = (
            f"{secrets.choice(CODE_WORDS)}-"
            f"{secrets.randbelow(900000) + 100000}-"
            f"{secrets.choice(CODE_WORDS)}"
        )
        if not await get_vault_message(code):
            return code
    return secrets.token_urlsafe(12).lower().replace("_", "-")


def _thread_id(message: Message):
    return getattr(message, "message_thread_id", None)


def _is_private_chat(message: Message) -> bool:
    return message.chat and message.chat.type == ChatType.PRIVATE


async def _cleanup_vault_content(client, code: str, data: dict):
    try:
        await client.delete_messages(
            chat_id=data["storage_chat_id"],
            message_ids=data["storage_message_id"],
        )
    except RPCError:
        pass
    await delete_vault_message(code)


@app.on_message(filters.command(["encrypt", "enc"]) & ~BANNED_USERS)
async def encrypt_message(client, message: Message):
    if not _is_private_chat(message):
        return await message.reply_text(PM_ONLY_MESSAGE)

    replied = message.reply_to_message
    if not replied:
        return await message.reply_text(
            "Reply to any message, photo, video, sticker, audio, or file with /encrypt."
        )

    code = await _new_vault_code()
    try:
        stored = await client.copy_message(
            chat_id=config.LOGGER_ID,
            from_chat_id=message.chat.id,
            message_id=replied.id,
        )
    except Exception as exc:
        return await message.reply_text(
            "Could not encrypt this content. Make sure the bot can access LOGGER_ID "
            f"and this message is copyable.\nError: <code>{type(exc).__name__}</code>"
        )

    await save_vault_message(
        code,
        {
            "storage_chat_id": config.LOGGER_ID,
            "storage_message_id": stored.id,
            "created_at": datetime.utcnow(),
            "creator_id": message.from_user.id if message.from_user else 0,
            "creator_chat_id": message.chat.id,
            "source_message_id": replied.id,
        },
    )

    await message.reply_text(
        "Encrypted successfully.\n\n"
        f"Code: <code>{code}</code>\n"
        f"Decrypt: <code>/decrypt {code}</code>\n\n"
        "Note: This is a one-time decrypt code. After one successful decrypt, "
        "the saved content will be deleted."
    )


@app.on_message(filters.command(["decrypt", "dec"]) & ~BANNED_USERS)
async def decrypt_message(client, message: Message):
    if not _is_private_chat(message):
        return await message.reply_text(PM_ONLY_MESSAGE)

    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/decrypt code</code>")

    code = _normalize_code(message.text.split(None, 1)[1])
    data = await get_vault_message(code)
    if not data:
        return await message.reply_text("Invalid or expired code.")

    try:
        await client.copy_message(
            chat_id=message.chat.id,
            from_chat_id=data["storage_chat_id"],
            message_id=data["storage_message_id"],
            reply_to_message_id=message.id,
            message_thread_id=_thread_id(message),
        )
    except MessageIdInvalid:
        await delete_vault_message(code)
        return await message.reply_text("Stored content is no longer available.")
    except RPCError as exc:
        return await message.reply_text(
            f"Could not decrypt this content.\nError: <code>{type(exc).__name__}</code>"
        )

    await _cleanup_vault_content(client, code, data)

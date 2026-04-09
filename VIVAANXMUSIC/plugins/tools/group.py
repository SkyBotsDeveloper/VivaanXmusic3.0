from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.errors import (
    ChannelPrivate,
    ChatSendPlainForbidden,
    ChatWriteForbidden,
    Forbidden,
)
from pyrogram.types import Message

from config import OWNER_ID
from VIVAANXMUSIC import app
from VIVAANXMUSIC.core.call import JARVIS


async def _safe_reply_text(message: Message, *args, **kwargs):
    chat = getattr(message, "chat", None)
    if not chat or chat.type == ChatType.CHANNEL:
        return
    try:
        await message.reply_text(*args, **kwargs)
    except (ChatSendPlainForbidden, ChatWriteForbidden, Forbidden, ChannelPrivate):
        pass


@app.on_message(filters.video_chat_started & filters.group)
async def on_voice_chat_started(_, message: Message):
    await _safe_reply_text(message, "Voice chat has started.")


@app.on_message(filters.video_chat_ended & filters.group)
async def on_voice_chat_ended(_, message: Message):
    await JARVIS.stop_vc_join_notifier(message.chat.id)
    await _safe_reply_text(message, "Voice chat ended.")


@app.on_message(filters.video_chat_members_invited & filters.group)
async def on_voice_chat_members_invited(_, message: Message):
    inviter = "Someone"
    if message.from_user:
        try:
            inviter = message.from_user.mention(message.from_user.first_name)
        except Exception:
            inviter = message.from_user.first_name or "Someone"

    invited = []
    vcmi = getattr(message, "video_chat_members_invited", None)
    users = getattr(vcmi, "users", []) if vcmi else []
    for user in users:
        try:
            name = user.first_name or "User"
            invited.append(f"[{name}](tg://user?id={user.id})")
        except Exception:
            continue

    if invited:
        await _safe_reply_text(
            message,
            f"{inviter} invited {', '.join(invited)} to the voice chat.",
        )


@app.on_message(filters.command("leavegroup") & filters.user(OWNER_ID) & filters.group)
async def leave_group(_, message: Message):
    await _safe_reply_text(message, "Leaving this group...")
    try:
        await app.leave_chat(chat_id=message.chat.id, delete=True)
    except (ChatWriteForbidden, Forbidden, ChannelPrivate):
        pass

from pyrogram import filters
from pyrogram.types import Message

from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.core.call import JARVIS
from VIVAANXMUSIC.utils.database import (
    get_cmode,
    get_vcnotify,
    is_active_chat,
    set_vcnotify,
)
from VIVAANXMUSIC.utils.decorators.admins import AdminActual
from VIVAANXMUSIC.utils.inline import close_markup


@app.on_message(filters.command(["vcnotify"]) & filters.group & ~BANNED_USERS)
@AdminActual
async def vcnotify_control(_, message: Message, strings):
    group_chat_id = message.chat.id
    usage = (
        "<b>Example :</b>\n\n"
        "/vcnotify <code>on</code>\n"
        "/vcnotify <code>off</code>"
    )

    if len(message.command) == 1:
        status = "enabled" if await get_vcnotify(group_chat_id) else "disabled"
        return await message.reply_text(
            f"» VC join notifications are currently <code>{status}</code> in this chat.",
            reply_markup=close_markup(strings),
        )

    state = message.text.split(None, 1)[1].strip().lower()
    linked_chat_id = await get_cmode(group_chat_id)

    if state in {"on", "enable", "enabled", "yes"}:
        await set_vcnotify(group_chat_id, True)
        if await is_active_chat(group_chat_id):
            await JARVIS.maybe_start_vc_join_notifier(group_chat_id, group_chat_id)
        if linked_chat_id and await is_active_chat(linked_chat_id):
            await JARVIS.maybe_start_vc_join_notifier(linked_chat_id, group_chat_id)
        return await message.reply_text(
            f"» VC join notifications have been <code>enabled</code> by : {message.from_user.mention}.",
            reply_markup=close_markup(strings),
        )

    if state in {"off", "disable", "disabled", "no"}:
        await set_vcnotify(group_chat_id, False)
        await JARVIS.stop_vc_join_notifier(group_chat_id)
        if linked_chat_id:
            await JARVIS.stop_vc_join_notifier(linked_chat_id)
        return await message.reply_text(
            f"» VC join notifications have been <code>disabled</code> by : {message.from_user.mention}.",
            reply_markup=close_markup(strings),
        )

    return await message.reply_text(usage, reply_markup=close_markup(strings))

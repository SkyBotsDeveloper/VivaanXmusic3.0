from pyrogram import filters
from pyrogram.types import Message

from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import get_autodelete, set_autodelete
from VIVAANXMUSIC.utils.decorators.admins import AdminActual
from VIVAANXMUSIC.utils.inline import close_markup


@app.on_message(filters.command(["autodelete"]) & filters.group & ~BANNED_USERS)
@AdminActual
async def autodelete_control(_, message: Message, strings):
    usage = (
        "<b>Example :</b>\n\n"
        "/autodelete <code>on</code>\n"
        "/autodelete <code>off</code>"
    )

    chat_id = message.chat.id
    if len(message.command) == 1:
        status = "enabled" if await get_autodelete(chat_id) else "disabled"
        return await message.reply_text(
            f"Auto-delete is currently <code>{status}</code> in this chat.",
            reply_markup=close_markup(strings),
        )

    state = message.text.split(None, 1)[1].strip().lower()
    if state in {"on", "enable", "enabled", "yes"}:
        await set_autodelete(chat_id, True)
        return await message.reply_text(
            f"Auto-delete has been <code>enabled</code> by : {message.from_user.mention}.\n\n"
            "Queued-track notices will be deleted when that track starts, and stream cards will be deleted after the track leaves the queue.",
            reply_markup=close_markup(strings),
        )

    if state in {"off", "disable", "disabled", "no"}:
        await set_autodelete(chat_id, False)
        return await message.reply_text(
            f"Auto-delete has been <code>disabled</code> by : {message.from_user.mention}.",
            reply_markup=close_markup(strings),
        )

    return await message.reply_text(usage, reply_markup=close_markup(strings))

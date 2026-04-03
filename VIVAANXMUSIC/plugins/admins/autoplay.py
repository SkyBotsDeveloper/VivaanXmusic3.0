from pyrogram import filters
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import get_autoplay, get_cmode, set_autoplay
from VIVAANXMUSIC.utils.decorators.admins import AdminActual
from VIVAANXMUSIC.utils.inline import close_markup
from config import BANNED_USERS


@app.on_message(filters.command(["autoplay", "cautoplay"]) & filters.group & ~BANNED_USERS)
@AdminActual
async def autoplay_control(_, message: Message, strings):
    usage = strings["admin_49"]
    command = message.command[0].lower()

    if command.startswith("c"):
        chat_id = await get_cmode(message.chat.id)
        if chat_id is None:
            return await message.reply_text(strings["setting_7"])
        try:
            await app.get_chat(chat_id)
        except Exception:
            return await message.reply_text(strings["cplay_4"])
    else:
        chat_id = message.chat.id

    if len(message.command) == 1:
        status = "enabled" if await get_autoplay(chat_id) else "disabled"
        return await message.reply_text(
            strings["admin_52"].format(status),
            reply_markup=close_markup(strings),
        )

    state = message.text.split(None, 1)[1].strip().lower()
    if state in {"on", "enable", "enabled", "yes"}:
        await set_autoplay(chat_id, True)
        return await message.reply_text(
            strings["admin_50"].format(message.from_user.mention),
            reply_markup=close_markup(strings),
        )

    if state in {"off", "disable", "disabled", "no"}:
        await set_autoplay(chat_id, False)
        return await message.reply_text(
            strings["admin_51"].format(message.from_user.mention),
            reply_markup=close_markup(strings),
        )

    return await message.reply_text(usage, reply_markup=close_markup(strings))

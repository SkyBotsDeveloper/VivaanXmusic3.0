from pyrogram import filters

from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.core.call import JARVIS
from VIVAANXMUSIC.utils.database import (
    get_cmode, is_music_enabled, set_music_enabled, set_playtype,
)
from VIVAANXMUSIC.utils.decorators.admins import AdminActual
from VIVAANXMUSIC.utils.music_gate import approve_music_request


@app.on_message(filters.command("music") & filters.group & ~BANNED_USERS)
@AdminActual
async def music_control(client, message, strings):
    args = message.command
    if len(args) == 1:
        state = "on" if await is_music_enabled(message.chat.id) else "off"
        return await message.reply_text(f"Music is {state}. Use /music on or /music off.")
    if len(args) != 2 or args[1].lower() not in {"on", "off"}:
        return await message.reply_text("Use /music on or /music off.")
    enabled = args[1].lower() == "on"
    await set_music_enabled(message.chat.id, enabled)
    if enabled:
        await set_playtype(message.chat.id, "Everyone")
        return await message.reply_text("Music is on. All members and admins can play audio and video.")
    for target in {message.chat.id, await get_cmode(message.chat.id)} - {None}:
        await JARVIS.stop_stream(target)
    await message.reply_text("Music is off. New play requests are blocked; admins can use Play for now for one request.")


@app.on_callback_query(filters.regex(r"^music_once ") & ~BANNED_USERS)
async def music_once(client, query):
    await approve_music_request(query)

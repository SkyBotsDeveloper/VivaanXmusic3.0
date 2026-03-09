import random
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from VIVAANXMUSIC import app
from config import SUPPORT_CHAT

BUTTON = InlineKeyboardMarkup([[InlineKeyboardButton("ꜱᴜᴘᴘᴏʀᴛ", url=SUPPORT_CHAT)]])

MEDIA = {
    "cutie": "https://graph.org/file/24375c6e54609c0e4621c.mp4",
    "horny": "https://graph.org/file/eaa834a1cbfad29bd1fe4.mp4",
    "hot": "https://graph.org/file/745ba3ff07c1270958588.mp4",
    "sexy": "https://graph.org/file/58da22eb737af2f8963e6.mp4",
    "sad": "https://files.catbox.moe/h2z5lm.gif",
    "lesbian": "https://graph.org/file/ff258085cf31f5385db8a.mp4",
    "chill": "https://files.catbox.moe/iip9rf.mp4",
    "kill": "https://files.catbox.moe/1a7pho.mp4",
}

TEMPLATES = {
    "cutie": "🍑 {mention} ɪꜱ {percent}% ᴄᴜᴛᴇ ʙᴀʙʏ🥀",
    "horny": "🔥 {mention} ɪꜱ {percent}% ʜᴏʀɴʏ!",
    "hot": "🔥 {mention} ɪꜱ {percent}% ʜᴏᴛ!",
    "sexy": "💋 {mention} ɪꜱ {percent}% ꜱᴇxʏ!",
    "sad": "🍷 {mention} ɪꜱ {percent}% 𝐬ᴀᴅ!",
    "lesbian": "💜 {mention} ɪꜱ {percent}% ʟᴇꜱʙɪᴀɴ!",
    "chill": "🍒 {mention}ꜱ ɪꜱ {percent}% ᴄʜɪʟʟ!",
    "kill": "🍆 {mention} ᴋɪʟʟ {percent}%!",
}


def get_user_mention(message: Message) -> str:
    user = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    return f"[{user.first_name}](tg://user?id={user.id})"


def get_reply_id(message: Message) -> int | None:
    if not message.reply_to_message:
        return None
    return getattr(message.reply_to_message, "id", None) or getattr(
        message.reply_to_message, "message_id", None
    )


async def handle_percentage_command(_, message: Message):
    command = message.command[0].lower()
    if command not in MEDIA or command not in TEMPLATES:
        return

    mention = get_user_mention(message)
    percent = random.randint(1, 100)
    text = TEMPLATES[command].format(mention=mention, percent=percent)
    media_url = MEDIA[command]

    await app.send_document(
        message.chat.id,
        media_url,
        caption=text,
        reply_markup=BUTTON,
        reply_to_message_id=get_reply_id(message),
    )


for cmd in ["cutie", "horny", "hot", "sexy", "sad", "lesbian", "chill", "kill"]:
    app.on_message(filters.command(cmd))(handle_percentage_command)

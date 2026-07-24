import asyncio

import requests
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from VIVAANXMUSIC import app

NEKOS_BEST_API_BASE = "https://nekos.best/api/v2"
NEKOS_BEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VivaanXMusicBot (https://github.com/VivaanXMusic)",
}

commands = {
    "punch": {"emoji": "💥", "text": "punched"},
    "slap": {"emoji": "😒", "text": "slapped"},
    "hug": {"emoji": "🤗", "text": "hugged"},
    "bite": {"emoji": "😈", "text": "bit"},
    "kiss": {"emoji": "😘", "text": "kissed"},
    "highfive": {"emoji": "🙌", "text": "high-fived"},
    "shoot": {"emoji": "🔫", "text": "shot"},
    "dance": {"emoji": "💃", "text": "danced"},
    "happy": {"emoji": "😊", "text": "was happy"},
    "baka": {"emoji": "😡", "text": "called you a baka"},
    "pat": {"emoji": "👋", "text": "patted"},
    "nod": {"emoji": "👍", "text": "nodded"},
    "nope": {"emoji": "👎", "text": "said nope"},
    "cuddle": {"emoji": "🤗", "text": "cuddled"},
    "feed": {"emoji": "🍴", "text": "fed"},
    "bored": {"emoji": "😴", "text": "was bored"},
    "nom": {"emoji": "😋", "text": "nommed"},
    "yawn": {"emoji": "😪", "text": "yawned"},
    "facepalm": {"emoji": "🤦", "text": "facepalmed"},
    "tickle": {"emoji": "😆", "text": "tickled"},
    "yeet": {"emoji": "💨", "text": "yeeted"},
    "think": {"emoji": "🤔", "text": "thought"},
    "blush": {"emoji": "😊", "text": "blushed"},
    "smug": {"emoji": "😏", "text": "was smug"},
    "wink": {"emoji": "😉", "text": "winked"},
    "peck": {"emoji": "😘", "text": "pecked"},
    "smile": {"emoji": "😄", "text": "smiled"},
    "wave": {"emoji": "👋", "text": "waved"},
    "poke": {"emoji": "👉", "text": "poked"},
    "stare": {"emoji": "👀", "text": "stared"},
    "shrug": {"emoji": "🤷", "text": "shrugged"},
    "sleep": {"emoji": "😴", "text": "slept"},
    "lurk": {"emoji": "👤", "text": "is lurking"}
}


def md_escape(text: str) -> str:
    return text.replace('[', '\\[').replace(']', '\\]')


async def _unused_get_animation(action: str):
    try:
        return None
    except Exception as e:
        print(f"❌ NekoClient error: {e}")
        return None


def _fetch_animation(action: str):
    for endpoint in (action, "happy", "waifu"):
        try:
            response = requests.get(
                f"{NEKOS_BEST_API_BASE}/{endpoint}",
                headers=NEKOS_BEST_HEADERS,
                timeout=12,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            if results and results[0].get("url"):
                return results[0]["url"]
        except Exception:
            continue
    return None


async def get_animation(action: str):
    return await asyncio.to_thread(_fetch_animation, action)


@app.on_message(filters.command(list(commands.keys())) & ~filters.forwarded & ~filters.via_bot)
async def animation_command(client: Client, message: Message):
    command = message.command[0].lower()

    if command not in commands:
        return await message.reply_text("⚠️ That command is not supported.")

    gif_url = await get_animation(command)
    if not gif_url:
        return await message.reply_text("❌ Couldn't fetch the animation. Please try again later.")

    sender_name = md_escape(message.from_user.first_name)
    sender = f"[{sender_name}](tg://user?id={message.from_user.id})"

    if message.reply_to_message:
        target_name = md_escape(message.reply_to_message.from_user.first_name)
        target = f"[{target_name}](tg://user?id={message.reply_to_message.from_user.id})"
    else:
        target = sender

    action_text = commands[command]['text']
    emoji = commands[command]['emoji']

    caption = f"**{sender} {action_text} {target}!** {emoji}"

    await message.reply_animation(
        animation=gif_url,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN
    )

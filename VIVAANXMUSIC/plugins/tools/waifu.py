import asyncio
import requests
from pyrogram import filters
from pyrogram.types import Message
from VIVAANXMUSIC import app

NEKOS_BEST_API_BASE = "https://nekos.best/api/v2"
NEKOS_BEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VivaanXMusicBot (https://github.com/VivaanXMusic)",
}
NEKOS_BEST_TAGS = {
    "waifu",
    "neko",
    "shinobu",
    "megumin",
    "bully",
    "cuddle",
    "cry",
    "hug",
    "awoo",
    "kiss",
    "lick",
    "pat",
    "smug",
    "bonk",
    "yeet",
    "blush",
    "smile",
    "wave",
    "highfive",
    "handhold",
    "nom",
    "bite",
    "glomp",
    "slap",
    "kill",
    "kick",
    "happy",
    "wink",
    "poke",
    "dance",
    "cringe",
}


@app.on_message(filters.command("waifu"))
async def waifu_command_handler(_, message: Message):
    try:
        args = message.text.split(maxsplit=1)
        tag = args[1] if len(args) > 1 else "maid"

        waifu_data = await asyncio.to_thread(get_waifu_data, tag)

        if waifu_data and 'images' in waifu_data and waifu_data['images']:
            image = waifu_data['images'][0]
            await message.reply_photo(
                photo=image["url"],
                caption=f"🌸 ʜᴇʀᴇ'ꜱ ʏᴏᴜʀ ᴡᴀɪꜰᴜ ({tag})"
            )
        else:
            await message.reply_text("❌ ɴᴏ ᴡᴀɪꜰᴜꜱ ꜰᴏᴜɴᴅ ᴡɪᴛʜ ᴛʜᴀᴛ ᴛᴀɢ.")

    except Exception as e:
        await message.reply_text(f"⚠️ ᴇʀʀᴏʀ: `{str(e)}`")


def get_waifu_data(tag):
    normalized_tag = (tag or "waifu").strip().lower() or "waifu"
    tags_to_try = [normalized_tag, "waifu"] if normalized_tag != "waifu" else ["waifu"]

    for current_tag in tags_to_try:
        endpoint_tag = current_tag if current_tag in NEKOS_BEST_TAGS else "waifu"
        try:
            response = requests.get(
                f"{NEKOS_BEST_API_BASE}/{endpoint_tag}",
                headers=NEKOS_BEST_HEADERS,
                timeout=12,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            if results and results[0].get("url"):
                return {
                    "images": [{"url": results[0]["url"]}],
                    "source": "nekos.best",
                }
        except Exception:
            continue

    return None

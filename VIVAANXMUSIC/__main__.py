import asyncio
import importlib

from pyrogram import idle
from pyrogram.types import BotCommand
from pytgcalls.exceptions import NoActiveGroupCall

import config
from VIVAANXMUSIC import LOGGER, app, userbot
from VIVAANXMUSIC.core.call import JARVIS
from VIVAANXMUSIC.misc import sudo
from VIVAANXMUSIC.plugins import ALL_MODULES
from VIVAANXMUSIC.utils.database import get_banned_users, get_gbanned
from config import BANNED_USERS

BOT_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("help", "Open help menu"),
    BotCommand("play", "Play audio in voice chat"),
    BotCommand("vplay", "Play video in voice chat"),
    BotCommand("song", "Download a song"),
    BotCommand("lyrics", "Search and fetch song lyrics"),
    BotCommand("queue", "Show current queue"),
    BotCommand("player", "Open player controls"),
    BotCommand("autoplay", "Toggle similar-song autoplay"),
    BotCommand("gpt", "Ask the AI assistant"),
    BotCommand("claude", "Ask Claude-style AI"),
    BotCommand("geminivision", "Analyze a replied image"),
    BotCommand("editimg", "Edit a replied image with AI"),
    BotCommand("getdraw", "Generate an AI image"),
    BotCommand("genvid", "Generate a short AI video"),
    BotCommand("upscale", "Enhance a replied image"),
    BotCommand("rmbg", "Remove image background"),
    BotCommand("weather", "Get weather info"),
    BotCommand("insta", "Download Instagram media"),
    BotCommand("movie", "Search movie info"),
    BotCommand("settings", "Open group settings"),
    BotCommand("ping", "Check bot status"),
]


async def init():
    if (
        not config.STRING1
        and not config.STRING2
        and not config.STRING3
        and not config.STRING4
        and not config.STRING5
    ):
        LOGGER(__name__).error(
            "Assistant session not filled, please fill a Pyrogram session."
        )
        exit()

    await sudo()

    try:
        users = await get_gbanned()
        for user_id in users:
            BANNED_USERS.add(user_id)
        users = await get_banned_users()
        for user_id in users:
            BANNED_USERS.add(user_id)
    except Exception:
        pass

    await app.start()
    await app.set_bot_commands(BOT_COMMANDS)
    for all_module in ALL_MODULES:
        importlib.import_module("VIVAANXMUSIC.plugins" + all_module)

    LOGGER("VIVAANXMUSIC.plugins").info("Modules loaded.")

    await userbot.start()
    await JARVIS.start()

    try:
        await JARVIS.stream_call(
            "http://docs.evostream.com/sample_content/assets/sintel1m720p.mp4"
        )
    except NoActiveGroupCall:
        LOGGER("VIVAANXMUSIC").error(
            "Please turn on the voice chat of your log group/channel.\n\nBot stopped."
        )
        exit()
    except Exception:
        pass

    await JARVIS.decorators()
    LOGGER("VIVAANXMUSIC").info(
        "\x41\x6e\x6e\x69\x65\x20\x4d\x75\x73\x69\x63\x20\x52\x6f\x62\x6f\x74\x20\x53\x74\x61\x72\x74\x65\x64\x20\x53\x75\x63\x63\x65\x73\x73\x66\x75\x6c\x6c\x79\x2e\x2e\x2e"
    )
    await idle()
    await app.stop()
    await userbot.stop()
    LOGGER("VIVAANXMUSIC").info("Stopping music bot...")


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init())

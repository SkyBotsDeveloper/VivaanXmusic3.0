from urllib.parse import urljoin

import httpx
import pyshorteners
from pyrogram import Client, filters
from pyrogram.enums import ChatAction, ParseMode
from pyrogram.types import InlineKeyboardButton as ikb
from pyrogram.types import InlineKeyboardMarkup as ikm
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.security import SecurityError, validate_public_http_url


shortener = pyshorteners.Shortener()
MAX_REDIRECTS = 5


async def resolve_public_redirects(short_link: str) -> str:
    current_url = validate_public_http_url(short_link)
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=10.0,
        trust_env=False,
    ) as client:
        for _ in range(MAX_REDIRECTS):
            response = await client.get(current_url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise SecurityError("Redirect target is missing.")
                current_url = validate_public_http_url(urljoin(current_url, location))
                continue

            return validate_public_http_url(str(response.url))

    raise SecurityError("Too many redirects.")


@app.on_message(filters.command("short"))
async def short_urls(bot: Client, message: Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    if len(message.command) < 2:
        return await message.reply_text(
            "Please provide a link to shorten.\n\n**Example:** `/short https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )

    try:
        link = validate_public_http_url(message.command[1])
        tiny = shortener.tinyurl.short(link)
        dagd = shortener.dagd.short(link)
        clck = shortener.clckru.short(link)

        markup = ikm(
            [
                [ikb("TinyURL", url=tiny)],
                [ikb("Dagd", url=dagd), ikb("Clck.ru", url=clck)],
            ]
        )
        await message.reply_text("Here are your shortened URLs:", reply_markup=markup)
    except SecurityError as exc:
        await message.reply_text(
            f"Blocked by security policy: `{exc}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await message.reply_text("Failed to shorten the link. It may be invalid.")


@app.on_message(filters.command("unshort"))
async def unshort_url(bot: Client, message: Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    if len(message.command) < 2:
        return await message.reply_text(
            "Please provide a shortened link.\n\n**Example:** `/unshort https://bit.ly/example`",
            parse_mode=ParseMode.MARKDOWN,
        )

    try:
        final_url = await resolve_public_redirects(message.command[1])
        markup = ikm([[ikb("View Final URL", url=final_url)]])
        await message.reply_text(
            f"**Unshortened URL:**\n`{final_url}`",
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN,
        )
    except SecurityError as exc:
        await message.reply_text(
            f"Blocked by security policy: `{exc}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await message.reply_text("Failed to unshorten the link. It may be broken or invalid.")

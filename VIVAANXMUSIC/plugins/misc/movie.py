import httpx
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.movie_lookup import get_movie_info
from VIVAANXMUSIC.utils.rich_buttons import rich_call


@app.on_message(filters.command("movie"))
async def movie_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "Please provide a movie name.\n\nExample: `/movie Inception`",
            parse_mode=ParseMode.MARKDOWN,
        )

    movie_name = " ".join(message.command[1:])
    status = await message.reply_text("Searching for the movie...")

    try:
        info = await get_movie_info(movie_name)
        await rich_call(status.edit_text, info, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except httpx.HTTPError:
        await status.edit_text("Failed to fetch movie information.")

import html

import httpx
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from VIVAANXMUSIC import app


TMDB_API_KEY = "23c3b139c6d59ebb608fe6d5b974d888"
TMDB_BASE = "https://api.themoviedb.org/3"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}


def _escape(text) -> str:
    return html.escape(str(text)) if text not in (None, "") else "N/A"


async def get_movie_info(query: str) -> str:
    async with httpx.AsyncClient(timeout=15.0, headers=HEADERS, trust_env=False) as client:
        search = await client.get(
            f"{TMDB_BASE}/search/movie",
            params={"api_key": TMDB_API_KEY, "query": query, "include_adult": "false"},
        )
        search.raise_for_status()
        search_data = search.json()

        if not search_data.get("results"):
            return "Movie not found."

        movie = search_data["results"][0]
        details = await client.get(
            f"{TMDB_BASE}/movie/{movie['id']}",
            params={"api_key": TMDB_API_KEY, "append_to_response": "credits"},
        )
        details.raise_for_status()
        details_data = details.json()

    credits = details_data.get("credits") or {}
    actors = ", ".join(actor["name"] for actor in credits.get("cast", [])[:5]) or "N/A"
    genres = ", ".join(item["name"] for item in details_data.get("genres", [])[:3]) or "N/A"

    revenue = details_data.get("revenue") or 0
    revenue_str = f"${revenue:,}" if revenue else "Not Available"
    runtime = details_data.get("runtime")
    runtime_str = f"{runtime} min" if runtime else "N/A"

    return (
        f"🎬 <b>Title:</b> {_escape(details_data.get('title') or movie.get('title'))}\n"
        f"📅 <b>Release Date:</b> {_escape(details_data.get('release_date') or movie.get('release_date'))}\n"
        f"⭐ <b>Rating:</b> {_escape(details_data.get('vote_average'))}/10\n"
        f"🎭 <b>Top Cast:</b> {_escape(actors)}\n"
        f"🎞 <b>Genres:</b> {_escape(genres)}\n"
        f"⏱ <b>Runtime:</b> {_escape(runtime_str)}\n"
        f"💰 <b>Box Office:</b> {_escape(revenue_str)}\n\n"
        f"📝 <b>Overview:</b>\n{_escape(details_data.get('overview') or movie.get('overview'))}"
    )


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
        await status.edit_text(info, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except httpx.HTTPError:
        await status.edit_text("Failed to fetch movie information.")

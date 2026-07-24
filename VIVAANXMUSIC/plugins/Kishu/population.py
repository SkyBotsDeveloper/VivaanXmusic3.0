import asyncio
import re
from urllib.parse import quote

import requests
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from VIVAANXMUSIC import app


COUNTRIES_DEV_BASE = "https://countries.dev"
COUNTRIES_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VivaanXMusicBot (https://github.com/VivaanXMusic)",
}


def _normalize_country_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _request_json(url: str):
    response = requests.get(
        url,
        headers=COUNTRIES_HEADERS,
        timeout=12,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def _match_country_from_list(query: str):
    normalized = _normalize_country_key(query)
    if not normalized:
        return None

    countries = _request_json(f"{COUNTRIES_DEV_BASE}/countries")
    if not isinstance(countries, list):
        return None

    for country in countries:
        candidates = (
            country.get("name"),
            country.get("nativeName"),
            country.get("alpha2Code"),
            country.get("alpha3Code"),
            country.get("cioc"),
        )
        if normalized in {_normalize_country_key(item) for item in candidates}:
            return country

    for country in countries:
        name = _normalize_country_key(country.get("name"))
        if normalized and normalized in name:
            return country
    return None


def fetch_country_info(query: str):
    lookup = (query or "").strip()
    if not lookup:
        return None

    if re.fullmatch(r"[A-Za-z]{2,3}", lookup):
        try:
            country = _request_json(
                f"{COUNTRIES_DEV_BASE}/alpha/{quote(lookup.upper())}"
            )
            if isinstance(country, dict) and country.get("name"):
                return country
        except Exception:
            pass

    return _match_country_from_list(lookup)


@app.on_message(filters.command("population"))
async def country_command_handler(client: Client, message: Message):
    if len(message.text.split(maxsplit=1)) < 2:
        return await message.reply_text(
            "Please provide a country code or name. Example: /population IN"
        )

    country_query = message.text.split(maxsplit=1)[1].strip()

    try:
        country_info = await asyncio.to_thread(fetch_country_info, country_query)
        if not country_info:
            response_text = "Country information could not be fetched."
        else:
            country_name = country_info.get("name") or "N/A"
            capital = country_info.get("capital") or "N/A"
            population = country_info.get("population")
            region = country_info.get("region") or "N/A"
            alpha2 = country_info.get("alpha2Code") or "N/A"
            alpha3 = country_info.get("alpha3Code") or "N/A"

            if isinstance(population, int):
                population_text = f"{population:,}"
            else:
                population_text = "N/A"

            response_text = (
                "**Country Information**\n\n"
                f"**Name:** {country_name}\n"
                f"**Capital:** {capital}\n"
                f"**Region:** {region}\n"
                f"**ISO:** {alpha2} / {alpha3}\n"
                f"**Population:** {population_text}"
            )

    except requests.exceptions.HTTPError:
        response_text = "Invalid country code or name. Try `IN`, `US`, or `India`."
    except Exception as err:
        print(f"Population command error: {err}")
        response_text = "Country service is temporarily unavailable. Please try again later."

    await message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)

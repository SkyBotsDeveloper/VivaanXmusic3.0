import html

import httpx
from pyrogram import Client, enums, filters
from pyrogram.types import Message

from VIVAANXMUSIC import app


timeout = httpx.Timeout(20.0)
http = httpx.AsyncClient(http2=True, timeout=timeout, trust_env=False)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def weather_code_to_text(code: int | None) -> str:
    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snowfall",
        73: "Moderate snowfall",
        75: "Heavy snowfall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return mapping.get(code, "Unknown")


def format_location(result: dict) -> str:
    parts = [result.get("name"), result.get("admin1"), result.get("country")]
    return ", ".join(part for part in parts if part)


@app.on_message(filters.command("weather"))
async def weather_command(client: Client, message: Message):
    if len(message.command) == 1:
        return await message.reply_text(
            "<b>Usage:</b> <code>/weather city</code>\nExample: <code>/weather delhi</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    query = message.text.split(maxsplit=1)[1].strip()

    try:
        geo_response = await http.get(
            GEOCODING_URL,
            params={
                "name": query,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        geo_response.raise_for_status()
        geo_data = geo_response.json()
        results = geo_data.get("results") or []

        if not results:
            return await message.reply_text(
                "Location not found. Please try a different city.",
                parse_mode=enums.ParseMode.HTML,
            )

        place = results[0]
        weather_response = await http.get(
            WEATHER_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": (
                    "temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "wind_speed_10m,weather_code"
                ),
                "timezone": "auto",
            },
        )
        weather_response.raise_for_status()
        current = weather_response.json().get("current") or {}

        if not current:
            return await message.reply_text(
                "Weather data is not available right now.",
                parse_mode=enums.ParseMode.HTML,
            )

        location_name = html.escape(format_location(place))
        condition = html.escape(weather_code_to_text(current.get("weather_code")))
        weather_text = (
            f"<b>{location_name}</b> 🌍\n\n"
            f"🌡️ <b>Temperature:</b> <code>{current.get('temperature_2m', 'N/A')} °C</code>\n"
            f"🥵 <b>Feels like:</b> <code>{current.get('apparent_temperature', 'N/A')} °C</code>\n"
            f"💧 <b>Humidity:</b> <code>{current.get('relative_humidity_2m', 'N/A')}%</code>\n"
            f"💨 <b>Wind:</b> <code>{current.get('wind_speed_10m', 'N/A')} km/h</code>\n"
            f"☁️ <b>Condition:</b> <i>{condition}</i>"
        )

        await message.reply_text(weather_text, parse_mode=enums.ParseMode.HTML)
    except httpx.HTTPError:
        await message.reply_text(
            "An error occurred while fetching the weather. Please try again later.",
            parse_mode=enums.ParseMode.HTML,
        )

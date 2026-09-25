import asyncio
import socket
from datetime import datetime

import requests
import whois
from pyrogram import filters

from VIVAANXMUSIC import app


def get_domain_info(domain_name):
    try:
        return whois.whois(domain_name)
    except Exception as exc:
        print(f"[WHOIS Error] {exc}")
        return None


def _clean_whois_value(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def get_domain_age(creation_date):
    creation_date = _clean_whois_value(creation_date)
    if not isinstance(creation_date, datetime):
        return None
    now = datetime.now(creation_date.tzinfo) if creation_date.tzinfo else datetime.now()
    return (now - creation_date).days // 365


def format_domain_date(value):
    value = _clean_whois_value(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value) if value else "N/A"


def get_ip_location(ip):
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        if response.ok:
            data = response.json()
            return data if data.get("status") == "success" else None
    except Exception as exc:
        print(f"[IP Geo Error] {exc}")
    return None


def format_info(info):
    domain = _clean_whois_value(info.domain_name)
    registrar = _clean_whois_value(info.registrar) or "N/A"
    creation = _clean_whois_value(info.creation_date)
    expiry = _clean_whois_value(info.expiration_date)
    nameservers = ", ".join(info.name_servers) if info.name_servers else "N/A"
    age = get_domain_age(creation)

    try:
        ip = socket.gethostbyname(domain)
    except Exception:
        ip = "Unavailable"

    location_data = get_ip_location(ip)
    location = (
        f"{location_data['country']}, {location_data['city']}"
        if location_data
        else "Unavailable"
    )

    return (
        f"**Domain Name**: {domain or 'N/A'}\n"
        f"**Registrar**: {registrar}\n"
        f"**Creation Date**: {format_domain_date(creation)}\n"
        f"**Expiration Date**: {format_domain_date(expiry)}\n"
        f"**Domain Age**: {age if age is not None else 'N/A'} years\n"
        f"**IP Address**: `{ip}`\n"
        f"**Location**: {location}\n"
        f"**Nameservers**: {nameservers}\n"
    )


def build_domain_response(domain_name: str) -> str | None:
    data = get_domain_info(domain_name)
    if not data:
        return None
    return format_info(data)


@app.on_message(filters.command("domain"))
async def domain_lookup(_, message):
    if len(message.command) < 2:
        return await message.reply(
            "Please provide a domain name. Example: `/domain heroku.com`"
        )

    domain_name = message.text.split(maxsplit=1)[1].strip()
    response = await asyncio.to_thread(build_domain_response, domain_name)

    if not response:
        return await message.reply("Failed to retrieve WHOIS data.")

    await message.reply(response)

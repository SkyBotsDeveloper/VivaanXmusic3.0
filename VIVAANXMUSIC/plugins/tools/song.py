import os
import re
import httpx
from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAudio,
    InputMediaVideo,
    Message,
)

from VIVAANXMUSIC import app, YouTube
from config import (
    BANNED_USERS,
    SONG_DOWNLOAD_DURATION,
    SONG_DOWNLOAD_DURATION_LIMIT,
)
from VIVAANXMUSIC.utils.decorators.language import language, languageCB
from VIVAANXMUSIC.utils.errors import capture_err, capture_callback_err
from VIVAANXMUSIC.utils.formatters import convert_bytes, time_to_seconds
from VIVAANXMUSIC.utils.inline.song import song_markup

SONG_COMMAND = ["song"]
APPLE_SPOTIFY_COMMANDS = ["apple", "spotify"]
SPOTIFY_TRACK_URL = re.compile(r"^https://open\.spotify\.com/track/", re.IGNORECASE)
APPLE_TRACK_URL = re.compile(r"^https://music\.apple\.com/.+", re.IGNORECASE)
SPOTIFY_OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SPOTIFY_OG_DESC = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
APPLE_TRACK_ID = re.compile(r"(?:[?&]i=|/song/[^/]+/)(\d+)", re.IGNORECASE)


class InlineKeyboardBuilder(list):
    def row(self, *buttons):
        self.append(list(buttons))


async def _handle_song_audio_request(message: Message, lang):
    mystic = await message.reply_text(lang["play_1"])

    url = await YouTube.url(message)
    query = url or (message.text.split(None, 1)[1] if len(message.command) > 1 else None)
    if not query:
        return await mystic.edit_text(lang["song_2"])

    if url and not await YouTube.exists(url):
        return await mystic.edit_text(lang["song_5"])

    try:
        title, dur_min, dur_sec, _thumb, vidid = await YouTube.details(query)
    except Exception:
        return await mystic.edit_text(lang["play_3"])

    if not dur_min:
        return await mystic.edit_text(lang["song_3"])
    if int(dur_sec) > SONG_DOWNLOAD_DURATION_LIMIT:
        return await mystic.edit_text(lang["play_4"].format(SONG_DOWNLOAD_DURATION, dur_min))

    file_path = None
    try:
        await mystic.edit_text(lang["song_8"])
        file_path, _ = await YouTube.download(vidid, mystic, videoid=True)
        if not file_path:
            raise RuntimeError("no audio file")

        await app.send_chat_action(message.chat.id, ChatAction.UPLOAD_AUDIO)
        await message.reply_audio(
            file_path,
            caption=title,
            title=title,
        )
        await mystic.delete()
    except Exception:
        await mystic.edit_text(lang["song_10"])
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


async def _resolve_spotify_query(link: str) -> str | None:
    if not SPOTIFY_TRACK_URL.search(link or ""):
        return None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        trust_env=False,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        },
    ) as client:
        response = await client.get(
            "https://open.spotify.com/oembed",
            params={"url": link},
        )
        response.raise_for_status()
    payload = response.json()
    title = re.sub(
        r"\s*\|\s*Spotify\s*$",
        "",
        str(payload.get("title") or "").strip(),
        flags=re.IGNORECASE,
    )
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    return title or None


async def _resolve_apple_query(link: str) -> str | None:
    if not APPLE_TRACK_URL.search(link or ""):
        return None
    match = APPLE_TRACK_ID.search(link)
    if not match:
        return None
    track_id = match.group(1)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        trust_env=False,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        response = await client.get(
            "https://itunes.apple.com/lookup",
            params={"id": track_id, "entity": "song"},
        )
        response.raise_for_status()
        payload = response.json()
    results = payload.get("results") or []
    if not results:
        return None
    song = next(
        (
            item
            for item in results
            if str(item.get("wrapperType") or "").lower() == "track"
            or str(item.get("kind") or "").lower() == "song"
        ),
        None,
    )
    if not song:
        song = results[0]
    track_name = str(song.get("trackName") or "").strip()
    artist_name = str(song.get("artistName") or "").strip()
    query = f"{track_name} {artist_name}".strip()
    return query or None


async def _resolve_link_query(query: str) -> str | None:
    query = str(query or "").strip()
    if not query:
        return None
    if SPOTIFY_TRACK_URL.search(query):
        return await _resolve_spotify_query(query)
    if APPLE_TRACK_URL.search(query):
        return await _resolve_apple_query(query)
    return query


async def _handle_platform_song_request(message: Message, lang, platform_name: str):
    mystic = await message.reply_text(lang["play_1"])
    query = message.text.split(None, 1)[1] if len(message.command) > 1 else None
    if not query:
        return await mystic.edit_text(f"Usage: /{platform_name} [link]")

    try:
        resolved_query = await _resolve_link_query(query)
    except Exception:
        resolved_query = None

    if not resolved_query:
        return await mystic.edit_text(f"Could not read that {platform_name} link.")

    try:
        title, dur_min, dur_sec, _thumb, vidid = await YouTube.details(resolved_query)
    except Exception:
        return await mystic.edit_text(lang["play_3"])

    if not dur_min:
        return await mystic.edit_text(lang["song_3"])
    if int(dur_sec) > SONG_DOWNLOAD_DURATION_LIMIT:
        return await mystic.edit_text(lang["play_4"].format(SONG_DOWNLOAD_DURATION, dur_min))

    file_path = None
    try:
        await mystic.edit_text(lang["song_8"])
        file_path, _ = await YouTube.download(vidid, mystic, videoid=True)
        if not file_path:
            raise RuntimeError("no audio file")

        await app.send_chat_action(message.chat.id, ChatAction.UPLOAD_AUDIO)
        await message.reply_audio(
            file_path,
            caption=title,
            title=title,
        )
        await mystic.delete()
    except Exception:
        await mystic.edit_text(lang["song_10"])
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ───────────────────────────── COMMANDS ───────────────────────────── #
@app.on_message(filters.command(SONG_COMMAND) & filters.group & ~BANNED_USERS)
@capture_err
@language
async def song_command_group(client, message: Message, lang):
    await _handle_song_audio_request(message, lang)


@app.on_message(filters.command(SONG_COMMAND) & filters.private & ~BANNED_USERS)
@capture_err
@language
async def song_command_private(client, message: Message, lang):
    try:
        await message.delete()
    except Exception:
        pass
    await _handle_song_audio_request(message, lang)


@app.on_message(filters.command(APPLE_SPOTIFY_COMMANDS) & ~BANNED_USERS)
@capture_err
@language
async def apple_spotify_song_command(client, message: Message, lang):
    command = ((message.command or [""])[0] or "").lower()
    platform_name = "spotify" if command == "spotify" else "apple"
    try:
        if message.chat.type.name.lower() == "private":
            await message.delete()
    except Exception:
        pass
    await _handle_platform_song_request(message, lang, platform_name)


# ───────────────────────────── CALLBACKS ───────────────────────────── #
@app.on_callback_query(filters.regex(r"song_back") & ~BANNED_USERS)
@capture_callback_err
@languageCB
async def songs_back_helper(client, cq, lang):
    _ignored, req = cq.data.split(None, 1)
    stype, vidid = req.split("|")
    await cq.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(song_markup(lang, vidid))
    )


@app.on_callback_query(filters.regex(r"song_helper") & ~BANNED_USERS)
@capture_callback_err
@languageCB
async def song_helper_cb(client, cq, lang):
    _ignored, req = cq.data.split(None, 1)
    stype, vidid = req.split("|")

    try:
        await cq.answer(lang["song_6"], show_alert=True)
    except Exception:
        pass

    try:
        formats, _ = await YouTube.formats(vidid)
    except Exception:
        return await cq.edit_message_text(lang["song_7"])

    kb = InlineKeyboardBuilder()
    seen = set()

    if stype == "audio":
        for f in formats:
            if "audio" not in f.get("format", "") or not f.get("filesize"):
                continue
            label = (f.get("format_note") or "").title() or "Audio"
            if label in seen:
                continue
            seen.add(label)
            kb.row(
                InlineKeyboardButton(
                    text=f"{label} • {convert_bytes(f['filesize'])}",
                    callback_data=f"song_download {stype}|{f['format_id']}|{vidid}",
                )
            )
    else:
        allowed = {160, 133, 134, 135, 136, 137, 298, 299, 264, 304, 266}
        for f in formats:
            try:
                fmt_id = int(f.get("format_id", 0))
            except Exception:
                continue
            if not f.get("filesize") or fmt_id not in allowed:
                continue
            note = (f.get("format_note") or "").strip()
            res = note or f.get("format", "").split("-")[-1].strip() or str(fmt_id)
            kb.row(
                InlineKeyboardButton(
                    text=f"{res} • {convert_bytes(f['filesize'])}",
                    callback_data=f"song_download {stype}|{f['format_id']}|{vidid}",
                )
            )

    kb.row(
        InlineKeyboardButton(lang["BACK_BUTTON"], callback_data=f"song_back {stype}|{vidid}"),
        InlineKeyboardButton(lang["CLOSE_BUTTON"], callback_data="close"),
    )
    await cq.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))


@app.on_callback_query(filters.regex(r"song_download") & ~BANNED_USERS)
@capture_callback_err
@languageCB
async def song_download_cb(client, cq, lang):
    try:
        await cq.answer("Downloading…")
    except Exception:
        pass

    _ignored, req = cq.data.split(None, 1)
    stype, fmt_id, vidid = req.split("|")
    yturl = f"https://www.youtube.com/watch?v={vidid}"

    mystic = await cq.edit_message_text(lang["song_8"])

    file_path = None
    try:
        info, _ = await YouTube.track(yturl)
        raw_title = info.get("title") or "Song"
        title = re.sub(r"\s+", " ", re.sub(r"[^\w\s\-\.\(\)\[\]]+", " ", raw_title)).strip()[:200]
        duration_sec = time_to_seconds(info.get("duration_min")) if info.get("duration_min") else None

        if stype == "audio":
            file_path, _ = await YouTube.download(
                yturl, mystic, songaudio=True, format_id=fmt_id, title=title
            )
            if not file_path:
                raise RuntimeError("no audio file")
            await app.send_chat_action(cq.message.chat.id, ChatAction.UPLOAD_AUDIO)
            await cq.edit_message_media(
                InputMediaAudio(
                    media=file_path,
                    caption=title,
                    title=title,
                    performer=info.get("uploader"),
                )
            )
        else:
            file_path, _ = await YouTube.download(
                yturl, mystic, songvideo=True, format_id=fmt_id, title=title
            )
            if not file_path:
                raise RuntimeError("no video file")
            await app.send_chat_action(cq.message.chat.id, ChatAction.UPLOAD_VIDEO)
            w = getattr(getattr(cq.message, "photo", None), "width", None)
            h = getattr(getattr(cq.message, "photo", None), "height", None)
            await cq.edit_message_media(
                InputMediaVideo(
                    media=file_path,
                    duration=duration_sec,
                    width=w,
                    height=h,
                    caption=title,
                    supports_streaming=True,
                )
            )

    except Exception:
        await mystic.edit_text(lang["song_10"])
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

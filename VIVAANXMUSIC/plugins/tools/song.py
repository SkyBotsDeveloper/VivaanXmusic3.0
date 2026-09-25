import asyncio
import os
import re
import shutil
import tempfile
from html import unescape
from pathlib import Path

import httpx
import yt_dlp
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
SPOTIFY_TRACK_URL = re.compile(
    r"^https://open\.spotify\.com/(?:intl-[a-z-]+/)?track/",
    re.IGNORECASE,
)
APPLE_TRACK_URL = re.compile(r"^https://music\.apple\.com/.+", re.IGNORECASE)
META_TAG = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
META_ATTR = re.compile(r"([a-zA-Z_:.-]+)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)
SPOTIFY_OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SPOTIFY_OG_DESC = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
APPLE_TRACK_ID = re.compile(r"(?:[?&]i=|/song/[^/]+/)(\d+)", re.IGNORECASE)
SONG_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
SONG_HTTP_LIMITS = httpx.Limits(
    max_connections=8,
    max_keepalive_connections=3,
    keepalive_expiry=20.0,
)
SONG_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
_song_http_client: httpx.AsyncClient | None = None
_song_http_lock = asyncio.Lock()
_song_download_semaphore = asyncio.Semaphore(3)


class InlineKeyboardBuilder(list):
    def row(self, *buttons):
        self.append(list(buttons))


async def _get_song_http_client() -> httpx.AsyncClient:
    global _song_http_client
    async with _song_http_lock:
        if _song_http_client is None or _song_http_client.is_closed:
            _song_http_client = httpx.AsyncClient(
                timeout=SONG_HTTP_TIMEOUT,
                headers=SONG_HTTP_HEADERS,
                follow_redirects=True,
                trust_env=False,
                limits=SONG_HTTP_LIMITS,
            )
        return _song_http_client


async def close_song_http_client() -> None:
    global _song_http_client
    async with _song_http_lock:
        if _song_http_client and not _song_http_client.is_closed:
            await _song_http_client.aclose()
        _song_http_client = None


def _safe_song_title(title: str | None, fallback: str = "song") -> str:
    cleaned = re.sub(r"[\\/*?:\"<>|]+", "_", str(title or fallback))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or fallback)[:120]


def _valid_file(path: str | None) -> bool:
    return bool(path and os.path.exists(path) and os.path.getsize(path) > 0)


def _meta_content(page: str, keys: set[str]) -> str | None:
    for tag in META_TAG.findall(page or ""):
        attrs = {
            key.lower(): unescape(value)
            for key, _quote, value in META_ATTR.findall(tag)
        }
        meta_key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = re.sub(r"\s+", " ", attrs.get("content") or "").strip()
        if meta_key in keys and content:
            return content
    return None


def _clean_apple_metadata_text(text: str | None) -> str:
    cleaned = unescape(str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s*[-|]\s*Apple Music\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+on Apple Music\.?\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^Listen to\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -|")


def _apple_slug_query(link: str) -> str | None:
    match = re.search(r"/(?:song|album)/([^/?#]+)", link or "", re.IGNORECASE)
    if not match:
        return None
    slug = unescape(match.group(1)).replace("-", " ").replace("_", " ")
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug or None


def _query_from_itunes_song(song: dict) -> str | None:
    track_name = str(song.get("trackName") or "").strip()
    artist_name = str(song.get("artistName") or "").strip()
    query = f"{track_name} {artist_name}".strip()
    return query or None


async def _lookup_itunes_track(client: httpx.AsyncClient, track_id: str) -> str | None:
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
    return _query_from_itunes_song(song or results[0])


async def _search_itunes_track(client: httpx.AsyncClient, term: str) -> str | None:
    response = await client.get(
        "https://itunes.apple.com/search",
        params={"term": term, "entity": "song", "limit": 1},
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") or []
    if not results:
        return None
    return _query_from_itunes_song(results[0])


def _apple_query_from_page(page: str) -> str | None:
    title = _clean_apple_metadata_text(
        _meta_content(page, {"og:title", "twitter:title"})
    )
    description = _clean_apple_metadata_text(
        _meta_content(page, {"og:description", "description"})
    )
    for text in (description, title):
        match = re.search(
            r"(.+?)\s+by\s+(.+?)(?:\s+on Apple Music|\.|$)",
            text or "",
            re.IGNORECASE,
        )
        if match:
            song_name = re.sub(
                r"\s*-\s*(?:Song|Single|Album|EP)\s*$",
                "",
                match.group(1).strip(),
                flags=re.IGNORECASE,
            )
            return f"{song_name} {match.group(2).strip()}".strip()
    return title or None


async def _get_song_query(message: Message) -> tuple[str | None, bool]:
    url = await YouTube.url(message)
    if url:
        return url.strip(), True

    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip(), False

    replied = message.reply_to_message
    if replied:
        replied_text = (replied.text or replied.caption or "").strip()
        if replied_text:
            return replied_text, False

    return None, False


async def _download_audio_with_ytdlp(vidid: str, title: str) -> tuple[str | None, str | None]:
    temp_dir = tempfile.mkdtemp(prefix="vivaan_song_")
    safe_title = _safe_song_title(title, vidid)
    outtmpl = os.path.join(temp_dir, f"{safe_title}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={vidid}"

    def run_download():
        options = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "geo_bypass": True,
            "nocheckcertificate": True,
            "retries": 2,
            "socket_timeout": 25,
            "prefer_ffmpeg": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

    try:
        await asyncio.to_thread(run_download)
        for path in Path(temp_dir).glob("*"):
            if path.is_file() and path.suffix.lower() == ".mp3" and path.stat().st_size > 0:
                return str(path), temp_dir
    except Exception:
        pass

    shutil.rmtree(temp_dir, ignore_errors=True)
    return None, None


async def _download_song_audio(vidid: str, title: str, mystic) -> tuple[str | None, str | None]:
    async with _song_download_semaphore:
        try:
            result = await YouTube.download(vidid, mystic, videoid=True)
            file_path = result[0] if isinstance(result, tuple) else result
            if _valid_file(file_path):
                return file_path, None
        except Exception:
            pass
        return await _download_audio_with_ytdlp(vidid, title)


async def _handle_song_audio_request(message: Message, lang):
    mystic = await message.reply_text(lang["play_1"])

    query, is_url = await _get_song_query(message)
    if not query:
        return await mystic.edit_text(lang["song_2"])

    resolved_query = query
    if is_url and not await YouTube.exists(query):
        try:
            resolved_query = await _resolve_link_query(query)
        except Exception:
            resolved_query = None
        if not resolved_query or resolved_query == query:
            return await mystic.edit_text(lang["song_5"])
    elif not is_url:
        try:
            resolved_query = await _resolve_link_query(query)
        except Exception:
            resolved_query = query

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
        file_path, cleanup_dir = await _download_song_audio(vidid, title, mystic)
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
        if "cleanup_dir" in locals() and cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


async def _resolve_spotify_query(link: str) -> str | None:
    if not SPOTIFY_TRACK_URL.search(link or ""):
        return None
    client = await _get_song_http_client()
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
    client = await _get_song_http_client()

    match = APPLE_TRACK_ID.search(link)
    if match:
        try:
            query = await _lookup_itunes_track(client, match.group(1))
            if query:
                return query
        except Exception:
            pass

    try:
        response = await client.get(link)
        if response.status_code < 400:
            query = _apple_query_from_page(response.text)
            if query:
                return query
    except Exception:
        pass

    slug_query = _apple_slug_query(link)
    if slug_query:
        try:
            query = await _search_itunes_track(client, slug_query)
            if query:
                return query
        except Exception:
            pass
    return slug_query


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
    query, _is_url = await _get_song_query(message)
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
        file_path, cleanup_dir = await _download_song_audio(vidid, title, mystic)
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
        if "cleanup_dir" in locals() and cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


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

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.errors import capture_callback_err, capture_err
from VIVAANXMUSIC.utils.lyrics import (
    LyricsCandidate,
    LyricsError,
    LyricsResult,
    fetch_lyrics,
    search_lyrics_candidates,
)


LYRICS_CACHE_TTL = 30 * 60
LYRICS_CACHE_LIMIT = 100
LYRICS_CHUNK_SIZE = 3500
LYRICS_RESULTS_CACHE: dict[str, "LyricsSearchSession"] = {}


@dataclass(slots=True)
class LyricsSearchSession:
    requester_id: int
    query: str
    created_at: float
    candidates: list[LyricsCandidate]


def _cleanup_cache():
    now = time.time()
    expired = [
        key
        for key, value in LYRICS_RESULTS_CACHE.items()
        if (now - value.created_at) > LYRICS_CACHE_TTL
    ]
    for key in expired:
        LYRICS_RESULTS_CACHE.pop(key, None)

    if len(LYRICS_RESULTS_CACHE) <= LYRICS_CACHE_LIMIT:
        return

    overflow = len(LYRICS_RESULTS_CACHE) - LYRICS_CACHE_LIMIT
    oldest = sorted(
        LYRICS_RESULTS_CACHE.items(),
        key=lambda item: item[1].created_at,
    )[:overflow]
    for key, _ in oldest:
        LYRICS_RESULTS_CACHE.pop(key, None)


def _new_session_token() -> str:
    while True:
        token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10]
        if token and token not in LYRICS_RESULTS_CACHE:
            return token


def _get_query(message: Message) -> str | None:
    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()

    if message.reply_to_message:
        replied = (
            message.reply_to_message.text or message.reply_to_message.caption or ""
        ).strip()
        if replied:
            return replied
    return None


def _truncate_label(value: str, limit: int = 34) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _result_label(candidate: LyricsCandidate) -> str:
    title = _truncate_label(candidate.title, 22)
    artist = _truncate_label(candidate.artist, 14)
    if artist:
        return f"{title} • {artist}"
    return title or "Unknown Track"


def _build_results_markup(token: str, session: LyricsSearchSession) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                _result_label(candidate),
                callback_data=f"lyrics_pick:{token}:{index}",
            )
        ]
        for index, candidate in enumerate(session.candidates[:10])
    ]
    rows.append([InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")])
    return InlineKeyboardMarkup(rows)


def _build_lyrics_markup(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("ʙᴀᴄᴋ", callback_data=f"lyrics_back:{token}"),
                InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close"),
            ]
        ]
    )


def _format_results_text(query: str, candidates: list[LyricsCandidate]) -> str:
    lines = [
        "Lyrics search results",
        f"Query: {query}",
        "",
        "Tap the matching song below.",
    ]
    top = candidates[:5]
    if top:
        lines.append("")
        lines.extend(
            f"{index + 1}. {candidate.title} - {candidate.artist}"
            for index, candidate in enumerate(top)
        )
    return "\n".join(lines)


def _chunk_lyrics(result: LyricsResult) -> list[str]:
    body = result.lyrics.strip()
    if not body:
        return []

    header = [
        f"Lyrics: {result.title}",
        f"Artist: {result.artist}",
    ]
    if result.album:
        header.append(f"Album: {result.album}")
    header.append(f"Source: {result.source}")
    header.append("")
    prefix = "\n".join(header)

    chunks: list[str] = []
    remaining = body
    first_limit = max(1200, LYRICS_CHUNK_SIZE - len(prefix))
    limits = [first_limit]

    while remaining:
        limit = limits[-1] if len(limits) == 1 and not chunks else LYRICS_CHUNK_SIZE
        if len(remaining) <= limit:
            piece = remaining
            remaining = ""
        else:
            split_at = remaining.rfind("\n", 0, limit)
            if split_at < int(limit * 0.55):
                split_at = remaining.rfind(" ", 0, limit)
            if split_at < int(limit * 0.55):
                split_at = limit
            piece = remaining[:split_at].rstrip()
            remaining = remaining[split_at:].lstrip()

        if not chunks:
            chunks.append(f"{prefix}{piece}")
        else:
            chunks.append(piece)

    return chunks


async def _send_lyrics_chunks(message: Message, result: LyricsResult):
    chunks = _chunk_lyrics(result)
    if not chunks:
        raise LyricsError("Lyrics are temporarily unavailable for that selection.")

    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        text = chunk if total == 1 else f"Part {index}/{total}\n\n{chunk}"
        await message.reply_text(
            text,
            disable_web_page_preview=True,
        )


@app.on_message(filters.command("lyrics") & ~BANNED_USERS)
@capture_err
async def lyrics_command(client, message: Message):
    query = _get_query(message)
    if not query:
        return await message.reply_text(
            "Use /lyrics song name or /lyrics some line from the song."
        )

    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
    search_message = await message.reply_text("Searching matching songs...")

    try:
        candidates = await search_lyrics_candidates(query)
    except LyricsError as exc:
        return await search_message.edit_text(str(exc))

    _cleanup_cache()
    token = _new_session_token()
    requester_id = message.from_user.id if message.from_user else message.chat.id
    session = LyricsSearchSession(
        requester_id=requester_id,
        query=query,
        created_at=time.time(),
        candidates=candidates,
    )
    LYRICS_RESULTS_CACHE[token] = session
    await search_message.edit_text(
        _format_results_text(query, candidates),
        reply_markup=_build_results_markup(token, session),
        disable_web_page_preview=True,
    )


@app.on_callback_query(filters.regex(r"^lyrics_pick:") & ~BANNED_USERS)
@capture_callback_err
async def lyrics_pick_callback(client, callback_query: CallbackQuery):
    _cleanup_cache()
    try:
        _, token, index = callback_query.data.split(":")
    except ValueError:
        return await callback_query.answer("Invalid lyrics selection.", show_alert=True)

    session = LYRICS_RESULTS_CACHE.get(token)
    if not session:
        return await callback_query.answer(
            "This lyrics search has expired. Search again.",
            show_alert=True,
        )

    if callback_query.from_user.id != session.requester_id:
        return await callback_query.answer(
            "Only the user who searched can use these buttons.",
            show_alert=True,
        )

    try:
        candidate = session.candidates[int(index)]
    except Exception:
        return await callback_query.answer("Song selection is invalid.", show_alert=True)

    await callback_query.answer("Fetching lyrics...")
    await client.send_chat_action(callback_query.message.chat.id, ChatAction.TYPING)

    try:
        result = await fetch_lyrics(candidate)
    except LyricsError as exc:
        return await callback_query.answer(str(exc), show_alert=True)

    await callback_query.message.edit_text(
        (
            f"Selected: {result.title} - {result.artist}\n"
            f"Source: {result.source}\n\n"
            "Lyrics sent below."
        ),
        reply_markup=_build_lyrics_markup(token),
        disable_web_page_preview=True,
    )
    await _send_lyrics_chunks(callback_query.message, result)


@app.on_callback_query(filters.regex(r"^lyrics_back:") & ~BANNED_USERS)
@capture_callback_err
async def lyrics_back_callback(client, callback_query: CallbackQuery):
    _cleanup_cache()
    try:
        _, token = callback_query.data.split(":")
    except ValueError:
        return await callback_query.answer("Invalid request.", show_alert=True)

    session = LYRICS_RESULTS_CACHE.get(token)
    if not session:
        return await callback_query.answer(
            "This lyrics search has expired. Search again.",
            show_alert=True,
        )

    if callback_query.from_user.id != session.requester_id:
        return await callback_query.answer(
            "Only the user who searched can use these buttons.",
            show_alert=True,
        )

    await callback_query.edit_message_text(
        _format_results_text(session.query, session.candidates),
        reply_markup=_build_results_markup(token, session),
        disable_web_page_preview=True,
    )

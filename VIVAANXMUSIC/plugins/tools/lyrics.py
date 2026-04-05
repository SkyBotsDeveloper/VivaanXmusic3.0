from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass

from pyrogram import filters
from pyrogram.enums import ChatAction, ParseMode
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
LYRICS_RESULTS_CACHE: dict[str, "LyricsSearchSession"] = {}
LYRICS_VIEW_CACHE: dict[str, "LyricsViewState"] = {}


@dataclass(slots=True)
class LyricsSearchSession:
    requester_id: int
    query: str
    created_at: float
    candidates: list[LyricsCandidate]


@dataclass(slots=True)
class LyricsViewState:
    requester_id: int
    created_at: float
    token: str
    selected_index: int
    chunks: list[str]


def _cleanup_cache():
    now = time.time()
    expired_tokens = [
        key
        for key, value in LYRICS_RESULTS_CACHE.items()
        if (now - value.created_at) > LYRICS_CACHE_TTL
    ]
    for key in expired_tokens:
        LYRICS_RESULTS_CACHE.pop(key, None)

    expired_views = [
        key
        for key, value in LYRICS_VIEW_CACHE.items()
        if (now - value.created_at) > LYRICS_CACHE_TTL
    ]
    for key in expired_views:
        LYRICS_VIEW_CACHE.pop(key, None)

    if len(LYRICS_RESULTS_CACHE) > LYRICS_CACHE_LIMIT:
        overflow = len(LYRICS_RESULTS_CACHE) - LYRICS_CACHE_LIMIT
        oldest = sorted(
            LYRICS_RESULTS_CACHE.items(),
            key=lambda item: item[1].created_at,
        )[:overflow]
        for key, _ in oldest:
            LYRICS_RESULTS_CACHE.pop(key, None)

    valid_tokens = set(LYRICS_RESULTS_CACHE)
    for key in list(LYRICS_VIEW_CACHE):
        token = LYRICS_VIEW_CACHE[key].token
        if token not in valid_tokens:
            LYRICS_VIEW_CACHE.pop(key, None)


def _new_session_token() -> str:
    while True:
        token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10]
        if token and token not in LYRICS_RESULTS_CACHE:
            return token


def _view_key(token: str, selected_index: int) -> str:
    return f"{token}:{selected_index}"


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
    return f"{text[: limit - 1].rstrip()}..."


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
    rows.append([InlineKeyboardButton("Close", callback_data="close")])
    return InlineKeyboardMarkup(rows)


def _build_lyrics_markup(token: str, selected_index: int, page: int, total: int) -> InlineKeyboardMarkup:
    nav_row: list[InlineKeyboardButton] = []
    if total > 1 and page > 0:
        nav_row.append(
            InlineKeyboardButton(
                "‹ Prev",
                callback_data=f"lyrics_page:{token}:{selected_index}:{page - 1}",
            )
        )
    if total > 1 and page < (total - 1):
        nav_row.append(
            InlineKeyboardButton(
                "Next ›",
                callback_data=f"lyrics_page:{token}:{selected_index}:{page + 1}",
            )
        )

    rows: list[list[InlineKeyboardButton]] = []
    if nav_row:
        rows.append(nav_row)
    rows.append(
        [
            InlineKeyboardButton("Back", callback_data=f"lyrics_back:{token}"),
            InlineKeyboardButton("Close", callback_data="close"),
        ]
    )
    return InlineKeyboardMarkup(rows)


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
    first_limit = max(1200, 3500 - len(prefix))

    while remaining:
        limit = first_limit if not chunks else 3500
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


def _fallback_result(candidate: LyricsCandidate) -> LyricsResult | None:
    lyrics = (candidate.plain_lyrics or "").strip()
    if len(lyrics) < 80:
        return None
    return LyricsResult(
        title=candidate.title or "Unknown Track",
        artist=candidate.artist or "Unknown Artist",
        album=candidate.album,
        lyrics=lyrics,
        source=(candidate.source or "FALLBACK").upper(),
    )


def _render_chunk(chunks: list[str], page: int) -> str:
    total = len(chunks)
    chunk = chunks[page]
    if total == 1:
        return chunk
    return f"Part {page + 1}/{total}\n\n{chunk}"


async def _edit_lyrics_message(
    callback_query: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> bool:
    attempts = [
        {"parse_mode": ParseMode.DISABLED},
        {"parse_mode": None},
    ]
    for extra in attempts:
        try:
            await callback_query.edit_message_text(
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                **extra,
            )
            return True
        except Exception:
            continue
    return False


async def _resolve_result(candidate: LyricsCandidate) -> LyricsResult | None:
    fallback = _fallback_result(candidate)
    if fallback:
        return fallback
    try:
        return await asyncio.wait_for(fetch_lyrics(candidate), timeout=15)
    except Exception:
        return fallback


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
    LYRICS_RESULTS_CACHE[token] = LyricsSearchSession(
        requester_id=requester_id,
        query=query,
        created_at=time.time(),
        candidates=candidates,
    )
    await search_message.edit_text(
        _format_results_text(query, candidates),
        reply_markup=_build_results_markup(token, LYRICS_RESULTS_CACHE[token]),
        disable_web_page_preview=True,
    )


@app.on_callback_query(filters.regex(r"^lyrics_pick:") & ~BANNED_USERS)
@capture_callback_err
async def lyrics_pick_callback(client, callback_query: CallbackQuery):
    _cleanup_cache()
    try:
        _, token, index_text = callback_query.data.split(":")
        selected_index = int(index_text)
    except Exception:
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
        candidate = session.candidates[selected_index]
    except Exception:
        return await callback_query.answer("Song selection is invalid.", show_alert=True)

    await callback_query.answer("Fetching lyrics...")
    await client.send_chat_action(callback_query.message.chat.id, ChatAction.TYPING)

    result = await _resolve_result(candidate)
    if not result:
        return await callback_query.answer(
            "Lyrics are temporarily unavailable for that selection.",
            show_alert=True,
        )

    chunks = _chunk_lyrics(result)
    if not chunks:
        return await callback_query.answer(
            "Lyrics are temporarily unavailable for that selection.",
            show_alert=True,
        )

    key = _view_key(token, selected_index)
    LYRICS_VIEW_CACHE[key] = LyricsViewState(
        requester_id=session.requester_id,
        created_at=time.time(),
        token=token,
        selected_index=selected_index,
        chunks=chunks,
    )

    ok = await _edit_lyrics_message(
        callback_query,
        _render_chunk(chunks, 0),
        _build_lyrics_markup(token, selected_index, 0, len(chunks)),
    )
    if not ok:
        return await callback_query.answer(
            "Lyrics delivery failed. Try another result.",
            show_alert=True,
        )


@app.on_callback_query(filters.regex(r"^lyrics_page:") & ~BANNED_USERS)
@capture_callback_err
async def lyrics_page_callback(client, callback_query: CallbackQuery):
    _cleanup_cache()
    try:
        _, token, index_text, page_text = callback_query.data.split(":")
        selected_index = int(index_text)
        page = int(page_text)
    except Exception:
        return await callback_query.answer("Invalid lyrics page.", show_alert=True)

    session = LYRICS_RESULTS_CACHE.get(token)
    view = LYRICS_VIEW_CACHE.get(_view_key(token, selected_index))
    if not session or not view:
        return await callback_query.answer(
            "This lyrics view has expired. Search again.",
            show_alert=True,
        )

    if callback_query.from_user.id != view.requester_id:
        return await callback_query.answer(
            "Only the user who searched can use these buttons.",
            show_alert=True,
        )

    if page < 0 or page >= len(view.chunks):
        return await callback_query.answer("Invalid lyrics page.", show_alert=True)

    ok = await _edit_lyrics_message(
        callback_query,
        _render_chunk(view.chunks, page),
        _build_lyrics_markup(token, selected_index, page, len(view.chunks)),
    )
    if not ok:
        return await callback_query.answer(
            "Unable to open that lyrics page.",
            show_alert=True,
        )


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

    ok = await _edit_lyrics_message(
        callback_query,
        _format_results_text(session.query, session.candidates),
        _build_results_markup(token, session),
    )
    if not ok:
        return await callback_query.answer(
            "Unable to return to results.",
            show_alert=True,
        )

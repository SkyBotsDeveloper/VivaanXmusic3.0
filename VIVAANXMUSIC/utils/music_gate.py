"""Group playback switch and short-lived, single-request admin approvals."""

import asyncio
import secrets
import time
from contextvars import ContextVar
from functools import wraps

from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import is_music_enabled, music_revisions
from VIVAANXMUSIC.utils.rich_buttons import rich_call

_approval = ContextVar("music_request_approval", default=None)
_stream_request = ContextVar("music_stream_request", default=None)
_requests = {}
REQUEST_TTL = 120
MAX_REQUESTS = 128
OFF_TEXT = "Music is off in this group. An admin can use /music on to enable it."


async def is_group_admin(chat_id, user_id):
    try:
        member = await app.get_chat_member(chat_id, user_id)
        return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}
    except Exception:
        return False


async def music_request_allowed(chat_id, user_id):
    return await is_music_enabled(chat_id) or _approval.get() == (
        chat_id, user_id, music_revisions.get(chat_id, 0), asyncio.current_task()
    )


def has_music_approval(chat_id, user_id):
    return _approval.get() == (
        chat_id, user_id, music_revisions.get(chat_id, 0), asyncio.current_task()
    )


def _prune_requests():
    now = time.monotonic()
    for key, request in list(_requests.items()):
        if now >= request["expires"]:
            _requests.pop(key, None)
    while len(_requests) >= MAX_REQUESTS:
        _requests.pop(next(iter(_requests)))


async def check_music_request(message, user_id, action):
    chat_id = message.chat.id
    if await music_request_allowed(chat_id, user_id):
        return True
    markup = None
    if await is_group_admin(chat_id, user_id):
        _prune_requests()
        token = secrets.token_urlsafe(12)
        _requests[token] = {
            "chat_id": chat_id, "user_id": user_id, "action": action,
            "revision": music_revisions.get(chat_id, 0),
            "expires": time.monotonic() + REQUEST_TTL,
        }
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Play for now", callback_data=f"music_once {token}")
        ]])
    await rich_call(message.reply_text, OFF_TEXT, reply_markup=markup)
    return False


async def approve_music_request(query):
    _prune_requests()
    token = query.data.partition(" ")[2]
    request = _requests.get(token)
    if not request:
        return await query.answer("Request expired. Send the play command again.", show_alert=True)
    chat_id, user_id = request["chat_id"], request["user_id"]
    if (query.message.chat.id != chat_id or query.from_user.id != user_id
            or not await is_group_admin(chat_id, user_id)):
        return await query.answer("Only the requesting group admin can approve this play.", show_alert=True)
    # Re-check after the awaited membership lookup; concurrent clicks consume once.
    if (_requests.get(token) is not request
            or time.monotonic() >= request["expires"]
            or request["revision"] != music_revisions.get(chat_id, 0)):
        return await query.answer("Request expired. Send the play command again.", show_alert=True)
    _requests.pop(token)
    await query.answer("Playing this request. Music remains off for other requests.")
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    approval = _approval.set((chat_id, user_id, request["revision"], asyncio.current_task()))
    try:
        return await request["action"]()
    finally:
        _approval.reset(approval)


def music_callback(handler):
    @wraps(handler)
    async def wrapped(client, query, *args, **kwargs):
        if not await check_music_request(
            query.message, query.from_user.id,
            lambda: wrapped(client, _ApprovedQuery(query), *args, **kwargs),
        ):
            await query.answer()
            return
        return await handler(client, query, *args, **kwargs)
    return wrapped


class _ApprovedQuery:
    """Replay a stored selection without answering an expired Telegram query."""
    def __init__(self, query):
        self._query = query

    def __getattr__(self, name):
        return getattr(self._query, name)

    async def answer(self, *args, **kwargs):
        return None


def guard_music_stream(handler):
    @wraps(handler)
    async def wrapped(strings, mystic, user_id, result, chat_id, user_name,
                      original_chat_id, *args, **kwargs):
        request = _stream_request.set((original_chat_id, user_id, asyncio.current_task()))
        try:
            return await handler(strings, mystic, user_id, result, chat_id,
                                 user_name, original_chat_id, *args, **kwargs)
        finally:
            _stream_request.reset(request)
    return wrapped


async def assert_music_stream_allowed():
    request = _stream_request.get()
    if (request and request[2] is asyncio.current_task()
            and not await music_request_allowed(request[0], request[1])):
        from VIVAANXMUSIC.utils.exceptions import AssistantErr
        raise AssistantErr(OFF_TEXT)

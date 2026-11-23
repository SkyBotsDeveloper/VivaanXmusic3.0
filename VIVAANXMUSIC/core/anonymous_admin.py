"""Single-use authorization of anonymous group commands by a real admin."""
import asyncio
import copy
import secrets
import time
from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps
from html import escape

from pyrogram.enums import ChatMemberStatus
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_verified = ContextVar("verified_anonymous_admin", default=None)


def verified_admin_member(message):
    value = _verified.get()
    if (value and value[:2] == (message.chat.id, getattr(message.from_user, "id", None))
            and value[2] is asyncio.current_task()):
        return value[3]
    return None


def has_command_filter(expression):
    if expression is None:
        return False
    if type(expression).__name__ == "CommandFilter":
        return True
    return any(has_command_filter(getattr(expression, child, None)) for child in ("base", "other"))


class AnonymousAdminVerification:
    TTL = 120
    LIMIT = 128

    def __init__(self, logger):
        self.pending = OrderedDict()
        self.logger = logger

    def prune(self):
        now = time.monotonic()
        for token, request in list(self.pending.items()):
            if request["expires"] <= now:
                self.pending.pop(token, None)

    def wrap(self, handler):
        if not isinstance(handler, MessageHandler) or not has_command_filter(handler.filters):
            return handler
        original = handler.callback

        @wraps(original)
        async def gateway(client, message):
            sender_chat = getattr(message, "sender_chat", None)
            if sender_chat is None or not getattr(message, "command", None):
                return await original(client, message)
            if sender_chat.id != message.chat.id:
                return await message.reply_text("Send this command as yourself or as this group's anonymous admin.")
            return await self.request(client, message, original, handler)

        handler.callback = gateway
        return handler

    async def request(self, client, message, callback, handler):
        from VIVAANXMUSIC.utils.rich_buttons import rich_call

        self.prune()
        while len(self.pending) >= self.LIMIT:
            self.pending.popitem(last=False)
        token = secrets.token_urlsafe(12)
        request = {
            "chat_id": message.chat.id, "message": copy.copy(message),
            "callback": callback, "handler": handler,
            "expires": time.monotonic() + self.TTL, "prompt_id": None,
        }
        self.pending[token] = request
        command = escape(str(message.text or message.caption or "")[:600])
        try:
            prompt = await rich_call(message.reply_text,
                "Anonymous admin: verify your admin permissions to run this command.\n"
                f"<code>{command}</code>",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Verify admin and run", callback_data=f"anon_verify {token}")
                ]]),
            )
            request["prompt_id"] = prompt.id
        except Exception:
            self.pending.pop(token, None)
            raise

    async def verify(self, client, query):
        self.prune()
        token = query.data.partition(" ")[2]
        request = self.pending.get(token)
        if request is None:
            return await query.answer("Verification expired. Send the command again.", show_alert=True)
        if (request["chat_id"] != query.message.chat.id
                or request["prompt_id"] != query.message.id):
            return await query.answer("This verification belongs to a different command.", show_alert=True)
        try:
            member = await client.get_chat_member(request["chat_id"], query.from_user.id)
        except Exception:
            return await query.answer("Could not check your admin permissions. Try again.", show_alert=True)
        if member.status not in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
            return await query.answer("Only a current group admin can verify this command.", show_alert=True)
        if self.pending.get(token) is not request or request["expires"] <= time.monotonic():
            return await query.answer("This command was already used or expired.", show_alert=True)
        message = copy.copy(request["message"])
        message.from_user = query.from_user
        message.sender_chat = None
        try:
            allowed = await request["handler"].check(client, message)
        except Exception:
            return await query.answer("Could not verify command permissions. Try again.", show_alert=True)
        if not allowed:
            return await query.answer("Your account cannot use this command.", show_alert=True)
        # Filter checks may await; claim only after rechecking the token.
        if self.pending.get(token) is not request or request["expires"] <= time.monotonic():
            return await query.answer("This command was already used or expired.", show_alert=True)
        self.pending.pop(token)
        await query.answer("Admin verified. Running the command.")
        try:
            await query.message.delete()
        except Exception:
            pass
        verified = _verified.set((message.chat.id, query.from_user.id, asyncio.current_task(), member))
        try:
            return await request["callback"](client, message)
        except Exception:
            self.logger.exception("Verified anonymous command failed | chat_id=%s", message.chat.id)
            await message.reply_text("The command could not finish. Please try again.")
        finally:
            _verified.reset(verified)

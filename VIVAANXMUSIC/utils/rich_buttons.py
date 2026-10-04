"""Native Rich HTML delivery for audited text keyboards on Kurigram 2.2.24.

Keyboard builders remain the source of labels, actions, styles and row conditions.
Unsupported interactions use the original bound method before any RPC is sent.
See RICH_BUTTON_MIGRATION.md for the intentionally inline workflows.
"""

import inspect
import re
from html import escape

from pyrogram import Client, raw
from pyrogram.enums import ChatType, MessageEntityType
from pyrogram.parser import Parser
from pyrogram.parser.utils import add_surrogates, remove_surrogates
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InputRichMessage, Message, MessageEntity, ReplyParameters


class UnsupportedRichKeyboard(ValueError):
    """The original interaction cannot be represented without changing behavior."""


def _attr(name, value):
    return f' {name}="{escape(str(value), quote=True)}"'


def keyboard_html(markup, *, align=None):
    """One full-width, equal-column Rich block per existing keyboard row."""
    if not isinstance(markup, InlineKeyboardMarkup) or getattr(markup, "force_reply", False):
        raise UnsupportedRichKeyboard("Not a plain inline keyboard")
    if align not in (None, "left", "center", "right"):
        raise ValueError("Unsupported Rich button alignment")
    rows = []
    for row in markup.inline_keyboard:
        if not 1 <= len(row) <= 8:
            raise UnsupportedRichKeyboard("Rich rows require 1-8 buttons; never reflow rows")
        buttons = []
        for button in row:
            if any(getattr(button, key, None) for key in (
                "pay", "callback_game", "requires_password", "icon_custom_emoji_id"
            )):
                raise UnsupportedRichKeyboard("Payment/game/password/icon semantics require inline delivery")
            actions = [key for key in (
                "callback_data", "url", "user_id", "web_app", "login_url",
                "switch_inline_query", "switch_inline_query_current_chat",
                "switch_inline_query_chosen_chat", "copy_text", "disabled",
            ) if getattr(button, key, None) is not None]
            if len(actions) != 1:
                raise UnsupportedRichKeyboard("A Rich button needs exactly one action")
            action = actions[0]
            value = getattr(button, action)
            if action == "callback_data":
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise UnsupportedRichKeyboard("Binary callback data is not Rich HTML text") from exc
                if not 1 <= len(value.encode("utf-8")) <= 64:
                    raise UnsupportedRichKeyboard("Invalid callback byte length")
                attrs = _attr("type", action) + _attr("data", value)
            elif action in ("url", "user_id", "web_app"):
                url = value.url if action == "web_app" else f"tg://user?id={value}" if action == "user_id" else value
                attrs = _attr("type", "web_app" if action == "web_app" else "url") + _attr("url", url)
            elif action == "login_url":
                if value.bot_username:
                    raise UnsupportedRichKeyboard("Rich HTML cannot select a different login bot")
                attrs = _attr("type", action) + _attr("url", value.url)
                if value.forward_text is not None:
                    attrs += _attr("forward-text", value.forward_text)
                if value.request_write_access:
                    attrs += " request-write-access"
            elif action == "copy_text":
                attrs = _attr("type", action) + _attr("text", getattr(value, "text", value))
            elif action == "switch_inline_query_chosen_chat":
                attrs = _attr("type", action) + _attr("query", value.query or "")
                for key in ("allow_user_chats", "allow_bot_chats", "allow_group_chats", "allow_channel_chats"):
                    if getattr(value, key, False):
                        attrs += " " + key.replace("_", "-")
            elif action == "disabled":
                attrs = _attr("type", "disabled")
            else:
                attrs = _attr("type", action) + _attr("query", value)
            style = getattr(button.style, "name", "DEFAULT").lower()
            if style != "default":
                if style not in ("primary", "success", "danger", "link") or (style == "link" and action != "callback_data"):
                    raise UnsupportedRichKeyboard("Unsupported Rich button style")
                attrs += _attr("style", style)
            buttons.append(f"<tg-button{attrs}>{escape(button.text)}</tg-button>")
        # No alignment flag = full-width columns, per Telegram's PageBlockButtonRow.
        rows.append("<tg-button-row" + (_attr("align", align) if align else "") + ">" + "".join(buttons) + "</tg-button-row>")
    if not rows:
        raise UnsupportedRichKeyboard("Empty keyboard")
    return "".join(rows)


async def text_html(text, parse_mode=None, entities=None):
    """Preserve Kurigram's parsed text/entities, escaping every literal segment."""
    if entities is None:
        parsed = await Parser(None).parse(text, parse_mode)
        text = parsed["message"]
        entities = []
        for entity in parsed["entities"] or []:
            if isinstance(entity, raw.types.InputMessageEntityMentionName):
                entity = MessageEntity(type=MessageEntityType.TEXT_LINK, offset=entity.offset,
                                       length=entity.length, url=f"tg://user?id={entity.user_id}")
            else:
                entity = MessageEntity._parse(None, entity, {})
            entities.append(entity)
    text = add_surrogates(str(text or ""))
    blocks = {MessageEntityType.PRE, MessageEntityType.BLOCKQUOTE}
    # Kurigram may emit CODE and PRE for the same span; the block must be outermost.
    entities = sorted(entities, key=lambda e: (e.offset, -e.length, e.type not in blocks))

    def tags(entity):
        kind = entity.type
        simple = {MessageEntityType.BOLD: "b", MessageEntityType.ITALIC: "i",
                  MessageEntityType.UNDERLINE: "u", MessageEntityType.STRIKETHROUGH: "s",
                  MessageEntityType.CODE: "code", MessageEntityType.SPOILER: "tg-spoiler"}
        if kind in simple:
            tag = simple[kind]
            return f"<{tag}>", f"</{tag}>"
        if kind == MessageEntityType.PRE:
            if entity.language:
                return '<pre><code' + _attr("class", f"language-{entity.language}") + '>', '</code></pre>'
            return "<pre>", "</pre>"
        if kind == MessageEntityType.BLOCKQUOTE:
            return "<blockquote expandable>" if entity.expandable else "<blockquote>", "</blockquote>"
        if kind in (MessageEntityType.TEXT_LINK, MessageEntityType.TEXT_MENTION):
            url = entity.url if kind == MessageEntityType.TEXT_LINK else f"tg://user?id={entity.user.id}"
            return "<a" + _attr("href", url) + ">", "</a>"
        if kind == MessageEntityType.CUSTOM_EMOJI:
            return "<tg-emoji" + _attr("emoji-id", entity.custom_emoji_id) + ">", "</tg-emoji>"
        if kind == MessageEntityType.DATE_TIME:
            attrs = _attr("unix", entity.unix_time)
            if entity.date_time_format:
                attrs += _attr("format", entity.date_time_format)
            return "<tg-time" + attrs + ">", "</tg-time>"
        # Telegram performs the same automatic URL/mention/hashtag detection.
        if kind in (MessageEntityType.URL, MessageEntityType.MENTION, MessageEntityType.HASHTAG,
                    MessageEntityType.CASHTAG, MessageEntityType.BOT_COMMAND, MessageEntityType.EMAIL,
                    MessageEntityType.PHONE_NUMBER, MessageEntityType.BANK_CARD):
            return "", ""
        raise UnsupportedRichKeyboard(f"Unsupported text entity: {kind}")

    def render(start, end, items, *, top=False, pre=False):
        parts, paragraph = [], []
        cursor, index = start, 0

        def literal(begin, finish):
            value = escape(remove_surrogates(text[begin:finish]), quote=False)
            return value if pre else value.replace("\n", "<br>")

        def flush():
            if paragraph:
                parts.append("<p>" + "".join(paragraph) + "</p>" if top else "".join(paragraph))
                paragraph.clear()

        while index < len(items):
            entity = items[index]
            finish = entity.offset + entity.length
            if entity.offset < cursor or finish > end or entity.length <= 0:
                raise UnsupportedRichKeyboard("Overlapping or invalid text entity ranges")
            paragraph.append(literal(cursor, entity.offset))
            children = []
            index += 1
            while index < len(items) and items[index].offset < finish:
                children.append(items[index])
                index += 1
            opening, closing = tags(entity)
            is_block = entity.type in blocks
            if is_block and not top:
                raise UnsupportedRichKeyboard("Nested block entity needs original formatting")
            content = opening + render(entity.offset, finish, children, pre=pre or entity.type == MessageEntityType.PRE) + closing
            if is_block:
                flush()
                parts.append(content)
            else:
                paragraph.append(content)
            cursor = finish
        paragraph.append(literal(cursor, end))
        flush()
        return "".join(parts)

    return render(0, len(text), entities, top=True)


async def rich_call(method, *args, **kwargs):
    """Deliver an audited text UI natively, preserving the original call as fallback.

    Do not use for a workflow that later reads/edits only message.reply_markup.
    RPC errors propagate to the caller's existing error handling; no duplicate sends.
    """
    owner = getattr(method, "__self__", None)
    function = getattr(method, "__func__", None)
    sends = (Message.reply_text, Message.reply, Client.send_message)
    edits = (Message.edit_text, Message.edit, CallbackQuery.edit_message_text, Client.edit_message_text)
    if function not in sends + edits:
        return await method(*args, **kwargs)
    params = dict(inspect.signature(method).bind(*args, **kwargs).arguments)
    markup = params.get("reply_markup")
    if not isinstance(markup, InlineKeyboardMarkup):
        return await method(*args, **kwargs)
    sending = function in sends
    message = owner.message if isinstance(owner, CallbackQuery) else owner if isinstance(owner, Message) else None
    if isinstance(owner, CallbackQuery) and (owner.inline_message_id or message is None):
        return await method(*args, **kwargs)
    if not sending and message is not None and (
        message.caption is not None or message.media is not None
    ):
        return await method(*args, **kwargs)
    client = owner if isinstance(owner, Client) else owner._client
    rich_options = set(inspect.signature(Client.send_rich_message if sending else Client.edit_message_text).parameters)
    handled = {"text", "parse_mode", "entities", "reply_markup", "quote", "disable_web_page_preview", "link_preview_options"}
    if any(value is not None and key not in rich_options | handled for key, value in params.items()):
        return await method(*args, **kwargs)
    preview = params.get("link_preview_options") or client.link_preview_options
    if params.get("disable_web_page_preview") is False or (preview and not preview.is_disabled):
        return await method(*args, **kwargs)
    previews_disabled = params.get("disable_web_page_preview") is True or (preview and preview.is_disabled)
    # Rich content cannot retain a classic automatic webpage card. Keep URL-bearing
    # bodies inline unless the caller already disables previews (button URLs are fine).
    if not previews_disabled and re.search(
        r"https?://|www\.|[\w-]+\.[a-zA-Z]{2,}(?:[/?:]|\b)", str(params.get("text") or "")
    ):
        return await method(*args, **kwargs)
    try:
        rows = keyboard_html(markup)
        content = await text_html(params.get("text"), params.get("parse_mode") or client.parse_mode, params.get("entities"))
    except UnsupportedRichKeyboard:
        return await method(*args, **kwargs)
    options = {key: value for key, value in params.items() if key in rich_options and key not in handled}
    options["rich_message"] = InputRichMessage(html=content + rows)
    if message is not None:
        options["chat_id"] = message.chat.id
        if sending:
            options["business_connection_id"] = message.business_connection_id
            options["message_thread_id"] = params.get("message_thread_id") or message.message_thread_id
            options["direct_messages_topic_id"] = params.get("direct_messages_topic_id") or message.direct_messages_topic_id
            if params.get("reply_parameters") is None:
                options["reply_parameters"] = ReplyParameters(message_id=message.id)
            # Match the installed Message.reply's deprecated quote behavior.
            if params.get("quote") is not None and message.chat.type == ChatType.PRIVATE:
                options["reply_parameters"] = None
        else:
            options["message_id"] = message.id
            if isinstance(owner, Message):
                options["business_connection_id"] = message.business_connection_id
    return await (client.send_rich_message if sending else client.edit_message_text)(**options)

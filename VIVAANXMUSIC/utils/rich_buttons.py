"""Native Rich button, media and full-view delivery on Kurigram 2.2.26.

Keyboard builders remain the source of labels, actions, styles and row conditions.
Normal chat keyboards never fall back to old inline delivery.
See RICH_BUTTON_MIGRATION.md for the runtime audit and validation.
"""

import inspect
import copy
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from html import escape

from pyrogram import Client, raw, types
from pyrogram.enums import ChatType, MessageEntityType, ParseMode
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
                entity = await MessageEntity._parse(None, entity, {})
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


def keyboard_blocks(markup):
    """Keep each descriptor row intact, using native full-width button blocks."""
    if markup is None:
        return []
    if not isinstance(markup, InlineKeyboardMarkup):
        raise UnsupportedRichKeyboard("Expected an inline keyboard descriptor")
    rows = []
    action_names = inspect.signature(types.RichMessageButton).parameters.keys() - {"text", "style"}
    for row in markup.inline_keyboard:
        if not 1 <= len(row) <= 8:
            raise UnsupportedRichKeyboard("Telegram Rich rows require 1-8 buttons")
        buttons = []
        for button in row:
            if any(getattr(button, key, None) for key in ("pay", "callback_game", "requires_password")):
                raise UnsupportedRichKeyboard("Telegram Rich buttons do not support payments/games/password callbacks")
            values = {key: getattr(button, key) for key in action_names if getattr(button, key, None) is not None}
            if button.user_id is not None:
                values["url"] = f"tg://user?id={button.user_id}"
            if isinstance(values.get("copy_text"), str):
                values["copy_text"] = types.CopyTextButton(text=values["copy_text"])
            text = button.text
            if button.icon_custom_emoji_id:
                text = [types.RichTextCustomEmoji(custom_emoji_id=button.icon_custom_emoji_id, alternative_text=""), text]
            buttons.append(types.RichMessageButton(text=text, style=button.style, **values))
        rows.append(types.InputRichBlockButtons(buttons=buttons))
    return rows


class _TextBlocks(HTMLParser):
    """Translate our escaped entity HTML into native Rich text/block objects."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.stack[-1][2].append("\n")
        else:
            self.stack.append((tag, dict(attrs), []))

    def handle_data(self, data):
        self.stack[-1][2].append(data)

    def handle_endtag(self, tag):
        name, attrs, parts = self.stack.pop()
        if name != tag:
            raise ValueError("Unbalanced Rich entity HTML")
        if tag == "p":
            self.blocks.append(types.InputRichBlockParagraph(text=parts))
            return
        if tag == "pre":
            language = None
            if len(parts) == 1 and isinstance(parts[0], types.RichTextCode):
                language = getattr(parts[0], "_language", None)
                parts = parts[0].text
            self.blocks.append(types.InputRichBlockPreformatted(text=parts, language=language))
            return
        if tag == "blockquote":
            self.blocks.append(
                types.InputRichBlockExpandableBlockQuotation(text=parts)
                if "expandable" in attrs else
                types.InputRichBlockBlockQuotation(blocks=[types.InputRichBlockParagraph(text=parts)])
            )
            return
        simple = {"b": types.RichTextBold, "i": types.RichTextItalic,
                  "u": types.RichTextUnderline, "s": types.RichTextStrikethrough,
                  "code": types.RichTextCode, "tg-spoiler": types.RichTextSpoiler}
        if tag in simple:
            value = simple[tag](text=parts)
            if tag == "code" and attrs.get("class", "").startswith("language-"):
                value._language = attrs["class"][9:]
        elif tag == "a":
            url = attrs["href"]
            if url.startswith("tg://user?id="):
                value = types.RichTextTextMention(text=parts, user=types.User(id=int(url.split("=")[-1])))
            else:
                value = types.RichTextUrl(text=parts, url=url)
        elif tag == "tg-emoji":
            value = types.RichTextCustomEmoji(custom_emoji_id=attrs["emoji-id"], alternative_text="".join(parts))
        elif tag == "tg-time":
            value = types.RichTextDateTime(text=parts, date=datetime.fromtimestamp(int(attrs["unix"]), timezone.utc), date_time_format=attrs.get("format"))
        else:
            raise UnsupportedRichKeyboard(f"Unsupported Rich text tag: {tag}")
        self.stack[-1][2].append(value)


async def text_blocks(text, parse_mode=None, entities=None):
    return _TextBlocks(await text_html(text or "", parse_mode, entities)).blocks


_MEDIA = {
    "photo": (types.InputMediaPhoto, types.InputRichBlockPhoto),
    "video": (types.InputMediaVideo, types.InputRichBlockVideo),
    "animation": (types.InputMediaAnimation, types.InputRichBlockAnimation),
    "document": (types.InputMediaDocument, types.InputRichBlockDocument),
    "audio": (types.InputMediaAudio, types.InputRichBlockAudio),
    "voice_note": (types.InputMediaVoiceNote, types.InputRichBlockVoiceNote),
}


def media_block(media):
    for key, (media_type, block_type) in _MEDIA.items():
        if isinstance(media, media_type):
            return block_type(**{key: media})
    raise UnsupportedRichKeyboard(f"Unsupported Rich media: {type(media).__name__}")


def _input_block(block):
    """Rehydrate Telegram's received blocks; no process-local menu cache required."""
    if isinstance(block, types.InputRichBlock):
        return copy.copy(block)
    target = getattr(types, "Input" + type(block).__name__, None)
    if target is None:
        raise UnsupportedRichKeyboard(f"Cannot rehydrate {type(block).__name__}")
    values = {}
    for key in inspect.signature(target).parameters:
        value = getattr(block, key, None)
        if key in _MEDIA:
            media_type = _MEDIA[key][0]
            media_values = {"media": value.file_id}
            if "has_spoiler" in inspect.signature(media_type).parameters:
                media_values["has_spoiler"] = getattr(block, "has_spoiler", None)
            # Preserve audio/video/document attributes, including their names.
            for name in inspect.signature(media_type).parameters:
                if name not in ("media", "caption", "parse_mode", "caption_entities", "thumb"):
                    attr = getattr(value, name, None)
                    if attr is not None:
                        media_values[name] = attr
            value = media_type(**media_values)
        elif key == "blocks":
            value = [_input_block(item) for item in value]
        elif key == "align":
            value = None  # Full-width columns, consistently, including legacy Rich pages.
        values[key] = value
    return target(**values)


async def _message_blocks(message, client):
    rich = getattr(message, "rich_message", None)
    if rich:
        return [_input_block(block) for block in rich.blocks]
    snapshot = getattr(message, "_rich_ui_blocks", None)
    if snapshot is not None:
        return [copy.copy(block) for block in snapshot]
    blocks = []
    for key, (media_type, _) in _MEDIA.items():
        original = getattr(message, "voice" if key == "voice_note" else key, None)
        if original is not None:
            blocks.append(media_block(media_type(media=original.file_id)))
            break
    text = message.caption if message.caption is not None else message.text
    entities = message.caption_entities if message.caption is not None else message.entities
    if text:
        blocks.extend(await text_blocks(text, ParseMode.DISABLED, entities or []))
    return blocks


def _plain(text):
    if isinstance(text, str):
        return text
    if isinstance(text, (list, tuple)):
        return "".join(_plain(item) for item in text)
    return _plain(getattr(text, "text", getattr(text, "alternative_text", "")))


def rich_text(message):
    if message.text or message.caption:
        return message.text or message.caption
    blocks = getattr(getattr(message, "rich_message", None), "blocks", None) or getattr(message, "_rich_ui_blocks", [])
    return "\n".join(_plain(block.text) for block in blocks if hasattr(block, "text") and not isinstance(block, (types.RichBlockButtons, types.InputRichBlockButtons)))


def rich_markup(message):
    """Return descriptors for UI code that previously read message.reply_markup."""
    blocks = getattr(getattr(message, "rich_message", None), "blocks", None) or getattr(message, "_rich_ui_blocks", [])
    rows = []
    for block in blocks:
        if isinstance(block, (types.RichBlockButtons, types.InputRichBlockButtons)):
            row = []
            for button in block.buttons:
                keys = inspect.signature(types.InlineKeyboardButton).parameters.keys() - {"text", "style"}
                values = {key: getattr(button, key) for key in keys if getattr(button, key, None) is not None}
                if isinstance(values.get("copy_text"), types.CopyTextButton):
                    values["copy_text"] = values["copy_text"].text
                row.append(types.InlineKeyboardButton(text=_plain(button.text), style=button.style, **values))
            rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else message.reply_markup


def rich_media(message, kind):
    """Read media metadata from either a classic message or a Rich media block."""
    original = getattr(message, kind, None)
    if original is not None:
        return original
    blocks = getattr(getattr(message, "rich_message", None), "blocks", None) or getattr(message, "_rich_ui_blocks", [])
    return next((getattr(block, kind) for block in blocks if hasattr(block, kind)), None)


async def rich_inline_photo(*, client, photo_url, caption, reply_markup, **metadata):
    """Keep inline result metadata, but send native Rich content instead of a caption keyboard."""
    html = f'<img src="{escape(photo_url, quote=True)}"/>'
    html += await text_html(caption, client.parse_mode)
    html += keyboard_html(reply_markup)
    return types.InlineQueryResultPhoto(
        photo_url=photo_url, **metadata,
        input_message_content=types.InputRichMessageContent(rich_message=InputRichMessage(html=html)),
    )


async def rich_call(method, *args, **kwargs):
    """Send/edit complete native Rich views. Never deliver an old keyboard fallback.

    Markup updates retain the received body/media, so callbacks work after restart.
    Calls without buttons or an existing Rich view remain ordinary native calls.
    """
    owner = getattr(method, "__self__", None)
    function = getattr(method, "__func__", None)
    name = getattr(function, "__name__", "")
    is_message = isinstance(owner, Message)
    is_callback = isinstance(owner, CallbackQuery)
    message = owner.message if is_callback else owner if is_message else None
    client = owner if isinstance(owner, Client) else getattr(owner, "_client", None)
    if client is None:
        raise TypeError("Rich delivery requires a bound Kurigram method")
    # 2.2.26 removed deprecated arguments from Message shortcuts. Normalize them
    # here rather than patching Kurigram or changing the commands' reply behavior.
    signature = inspect.signature(method)
    legacy = {key: value for key, value in kwargs.items() if key not in signature.parameters}
    if legacy.keys() - {"quote", "reply_to_message_id", "disable_web_page_preview"}:
        raise TypeError(f"Unsupported {name} arguments: {sorted(legacy)}")
    accepted = {key: value for key, value in kwargs.items() if key in signature.parameters}
    params = dict(signature.bind(*args, **accepted).arguments)
    params.update(legacy)
    sending = name.startswith(("send_", "reply"))
    markup_only = "reply_markup" in name
    media_edit = name in ("edit_media", "edit_message_media", "edit_inline_media")
    if not sending and message is None and not (is_callback and owner.inline_message_id):
        message = await client.get_messages(params["chat_id"], params["message_id"])
    has_rich = message is not None and (getattr(message, "rich_message", None) or hasattr(message, "_rich_ui_blocks"))
    markup = params.get("reply_markup")
    enabled = isinstance(markup, InlineKeyboardMarkup) or (has_rich and not sending)
    options = dict(params)
    if sending and is_message:
        options["chat_id"] = message.chat.id
        options.setdefault("message_thread_id", message.message_thread_id)
        options.setdefault("direct_messages_topic_id", message.direct_messages_topic_id)
        reply = options.get("reply_parameters") or ReplyParameters(message_id=message.id)
        if options.get("quote") is not None and message.chat.type == ChatType.PRIVATE:
            reply = None  # Preserve 2.2.24's deprecated quote behavior.
        if options.get("reply_to_message_id") is not None:
            reply = ReplyParameters(message_id=options.pop("reply_to_message_id"))
        options["reply_parameters"] = reply
        options.pop("quote", None)
    if sending and options.get("reply_to_message_id") is not None:
        options["reply_parameters"] = ReplyParameters(message_id=options.pop("reply_to_message_id"))
    if not enabled:
        if legacy and sending and is_message:
            if "disable_web_page_preview" in options:
                options["link_preview_options"] = types.LinkPreviewOptions(is_disabled=options.pop("disable_web_page_preview"))
            tail = "message" if name in ("reply", "reply_text") else name.removeprefix("reply_")
            return await getattr(client, "send_" + tail)(**options)
        if "disable_web_page_preview" in legacy:
            kwargs["link_preview_options"] = types.LinkPreviewOptions(is_disabled=kwargs.pop("disable_web_page_preview"))
        return await method(*args, **kwargs)

    previous = await _message_blocks(message, client) if not sending and message is not None else []
    media_blocks = [block for block in previous if isinstance(block, tuple(cls for _, cls in _MEDIA.values()))]
    if markup_only:
        blocks = [block for block in previous if not isinstance(block, types.InputRichBlockButtons)]
    else:
        parse_mode = options.get("parse_mode") or client.parse_mode
        text = options.get("caption", options.get("text", ""))
        entities = options.get("caption_entities", options.get("entities"))
        if media_edit:
            media = options["media"]
            text, parse_mode, entities = media.caption, media.parse_mode or client.parse_mode, media.caption_entities
            media_blocks = [media_block(media)]
        elif sending:
            for key, (media_type, _) in _MEDIA.items():
                parameter = "voice" if key == "voice_note" else key
                if parameter in options:
                    media_args = {k: v for k, v in options.items() if k in inspect.signature(media_type).parameters and k not in ("caption", "parse_mode", "caption_entities")}
                    media_args["media"] = options[parameter]
                    media_blocks = [media_block(media_type(**media_args))]
                    break
        blocks = media_blocks + await text_blocks(text, parse_mode, entities)
    blocks.extend(keyboard_blocks(markup))
    rich_message = InputRichMessage(blocks=blocks)
    if sending:
        for key in ("schedule_date", "repeat_period", "paid_message_star_count", "ttl_seconds", "view_once", "business_connection_id"):
            if options.get(key) is not None:
                raise UnsupportedRichKeyboard(f"Kurigram send_rich_message cannot preserve {key}")
        allowed = inspect.signature(Client.send_rich_message).parameters.keys() - {"self", "rich_message", "reply_markup"}
        delivery = {key: value for key, value in options.items() if key in allowed}
        result = await client.send_rich_message(**delivery, rich_message=rich_message)
    elif is_callback and owner.inline_message_id:
        result = await client.edit_inline_text(inline_message_id=owner.inline_message_id, rich_message=rich_message)
    else:
        delivery = {"chat_id": message.chat.id, "message_id": message.id}
        for key in ("schedule_date", "business_connection_id"):
            if options.get(key) is not None:
                delivery[key] = options[key]
        result = await client.edit_message_text(**delivery, rich_message=rich_message)
    # Pin uploaded media to Telegram file IDs even when a sparse send response
    # omits its blocks. Player thumbnails may be deleted locally after sending.
    if sending and media_blocks and isinstance(result, Message) and not result.rich_message:
        received = await client.get_messages(result.chat.id, result.id)
        if received.rich_message:
            result.rich_message = received.rich_message
            blocks = await _message_blocks(received, client)
    # Text-only sparse responses can retain an inexpensive rendering snapshot.
    for target in (message if not sending else None, result if isinstance(result, Message) else None):
        if target is not None:
            target._rich_ui_blocks = blocks
            if not sending:
                target.rich_message = getattr(result, "rich_message", None)
    return result


async def restore_welcome(message, caption, buttons, media):
    """All Home/Back paths use the same video and full-width welcome layout."""
    return await rich_call(
        message.edit_media, types.InputMediaVideo(media=media, caption=caption),
        reply_markup=InlineKeyboardMarkup(buttons),
    )

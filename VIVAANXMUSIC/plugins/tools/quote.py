import base64
import textwrap
from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message
from VIVAANXMUSIC import app
from httpx import AsyncClient, Timeout
from PIL import Image, ImageDraw, ImageFont

# -----------------------------------------------------------------
fetch = AsyncClient(
    http2=True,
    verify=False,
    headers={
        "Accept-Language": "id-ID",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                       AppleWebKit/537.36 (KHTML, like Gecko) \
                       Chrome/107.0.0.0 Safari/537.36 Edge/107.0.1418.42",
    },
    timeout=Timeout(20),
)
QUOTE_JSON_ENDPOINTS = (
    "https://quote.yuri.ly/generate",
    "https://bot.lyo.su/quote/generate",
)
QUOTE_BINARY_ENDPOINTS = (
    "https://quote.yuri.ly/generate.webp",
    "https://bot.lyo.su/quote/generate.png",
)
# ------------------------------------------------------------------------
class QuotlyException(Exception):
    pass
# --------------------------------------------------------------------------
def _load_quote_font(size: int, *, bold: bool = False):
    names = (
        "arialbd.ttf" if bold else "arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _quote_text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text or " ", font=font)
    return box[2] - box[0], box[3] - box[1]


def _wrap_quote_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    source = " ".join(str(text or "").split()) or " "
    lines: list[str] = []
    for paragraph in source.splitlines() or [source]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            width, _ = _quote_text_size(draw, candidate, font)
            if width <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            if _quote_text_size(draw, word, font)[0] <= max_width:
                current = word
            else:
                chunks = textwrap.wrap(word, width=22) or [word]
                lines.extend(chunks[:-1])
                current = chunks[-1]
        if current:
            lines.append(current)
    return lines or [" "]


def _quote_color(seed: int):
    palette = (
        "#7c3aed",
        "#0891b2",
        "#16a34a",
        "#dc2626",
        "#d97706",
        "#2563eb",
    )
    return palette[abs(int(seed or 1)) % len(palette)]


def _quote_initials(name: str):
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "?"
    return "".join(part[0].upper() for part in parts[:2])


async def _render_quote_locally(messages, is_reply):
    if not isinstance(messages, list):
        messages = [messages]

    width = 940
    padding = 36
    avatar_size = 74
    gap = 22
    content_width = width - (padding * 2) - avatar_size - gap
    name_font = _load_quote_font(30, bold=True)
    text_font = _load_quote_font(32)
    reply_font = _load_quote_font(23)
    initial_font = _load_quote_font(27, bold=True)
    dummy = Image.new("RGB", (width, 10))
    draw = ImageDraw.Draw(dummy)

    rows = []
    total_height = padding
    for message in messages:
        name = await get_message_sender_name(message) or "Unknown"
        text = await get_text_or_caption(message) or "[message]"
        sender_id = await get_message_sender_id(message)
        text_lines = _wrap_quote_text(draw, text, text_font, content_width)

        reply_lines = []
        reply_name = ""
        if is_reply and message.reply_to_message:
            reply_name = await get_message_sender_name(message.reply_to_message) or "Reply"
            reply_text = await get_text_or_caption(message.reply_to_message) or "[message]"
            reply_lines = _wrap_quote_text(draw, reply_text, reply_font, content_width - 24)[:2]

        row_height = 24 + 36 + (len(text_lines) * 42) + 24
        if reply_lines:
            row_height += 28 + (len(reply_lines) * 30) + 16
        row_height = max(row_height, avatar_size + 38)
        rows.append(
            {
                "name": name,
                "sender_id": sender_id,
                "text_lines": text_lines,
                "reply_name": reply_name,
                "reply_lines": reply_lines,
                "height": row_height,
            }
        )
        total_height += row_height + 18
    total_height += padding - 18

    image = Image.new("RGB", (width, max(total_height, 220)), "#161020")
    draw = ImageDraw.Draw(image)
    y = padding
    for row in rows:
        card_box = (padding // 2, y - 10, width - padding // 2, y + row["height"])
        draw.rounded_rectangle(card_box, radius=28, fill="#241a34")

        avatar_x = padding
        avatar_y = y + 18
        color = _quote_color(row["sender_id"])
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill=color,
        )
        initials = _quote_initials(row["name"])
        iw, ih = _quote_text_size(draw, initials, initial_font)
        draw.text(
            (
                avatar_x + (avatar_size - iw) / 2,
                avatar_y + (avatar_size - ih) / 2 - 2,
            ),
            initials,
            fill="#ffffff",
            font=initial_font,
        )

        text_x = padding + avatar_size + gap
        cursor_y = y + 20
        draw.text((text_x, cursor_y), row["name"], fill="#ffffff", font=name_font)
        cursor_y += 42

        if row["reply_lines"]:
            reply_box = (
                text_x,
                cursor_y,
                width - padding,
                cursor_y + 36 + len(row["reply_lines"]) * 30,
            )
            draw.rounded_rectangle(reply_box, radius=14, fill="#332744")
            draw.rectangle(
                (text_x, cursor_y + 8, text_x + 5, reply_box[3] - 8),
                fill="#a78bfa",
            )
            draw.text(
                (text_x + 18, cursor_y + 8),
                row["reply_name"],
                fill="#c4b5fd",
                font=reply_font,
            )
            reply_y = cursor_y + 36
            for line in row["reply_lines"]:
                draw.text((text_x + 18, reply_y), line, fill="#d9d2e8", font=reply_font)
                reply_y += 30
            cursor_y = reply_box[3] + 18

        for line in row["text_lines"]:
            draw.text((text_x, cursor_y), line, fill="#f8fafc", font=text_font)
            cursor_y += 42

        y += row["height"] + 18

    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=92, method=6)
    return buffer.getvalue()


async def get_message_sender_id(ctx: Message):
    if ctx.forward_date:
        if ctx.forward_sender_name:
            return 1
        elif ctx.forward_from:
            return ctx.forward_from.id
        elif ctx.forward_from_chat:
            return ctx.forward_from_chat.id
        else:
            return 1
    elif ctx.from_user:
        return ctx.from_user.id
    elif ctx.sender_chat:
        return ctx.sender_chat.id
    else:
        return 1
# -----------------------------------------------------------------------------------------
async def get_message_sender_name(ctx: Message):
    if ctx.forward_date:
        if ctx.forward_sender_name:
            return ctx.forward_sender_name
        elif ctx.forward_from:
            return (
                f"{ctx.forward_from.first_name} {ctx.forward_from.last_name}"
                if ctx.forward_from.last_name
                else ctx.forward_from.first_name
            )
        elif ctx.forward_from_chat:
            return ctx.forward_from_chat.title
        else:
            return ""
    elif ctx.from_user:
        if ctx.from_user.last_name:
            return f"{ctx.from_user.first_name} {ctx.from_user.last_name}"
        else:
            return ctx.from_user.first_name
    elif ctx.sender_chat:
        return ctx.sender_chat.title
    else:
        return ""
# ---------------------------------------------------------------------------------------------------
async def get_custom_emoji(ctx: Message):
    if ctx.forward_date:
        return (
            ""
            if ctx.forward_sender_name
            or not ctx.forward_from
            and ctx.forward_from_chat
            or not ctx.forward_from
            else ctx.forward_from.emoji_status.custom_emoji_id
        )

    return ctx.from_user.emoji_status.custom_emoji_id if ctx.from_user else ""

# ---------------------------------------------------------------------------------------------------
async def get_message_sender_username(ctx: Message):
    if ctx.forward_date:
        if (
            not ctx.forward_sender_name
            and not ctx.forward_from
            and ctx.forward_from_chat
            and ctx.forward_from_chat.username
        ):
            return ctx.forward_from_chat.username
        elif (
            not ctx.forward_sender_name
            and not ctx.forward_from
            and ctx.forward_from_chat
            or ctx.forward_sender_name
            or not ctx.forward_from
        ):
            return ""
        else:
            return ctx.forward_from.username or ""
    elif ctx.from_user and ctx.from_user.username:
        return ctx.from_user.username
    elif (
        ctx.from_user
        or ctx.sender_chat
        and not ctx.sender_chat.username
        or not ctx.sender_chat
    ):
        return ""
    else:
        return ctx.sender_chat.username
# ------------------------------------------------------------------------
async def get_message_sender_photo(ctx: Message):
    if ctx.forward_date:
        if (
            not ctx.forward_sender_name
            and not ctx.forward_from
            and ctx.forward_from_chat
            and ctx.forward_from_chat.photo
        ):
            return {
                "small_file_id": ctx.forward_from_chat.photo.small_file_id,
                "small_photo_unique_id": ctx.forward_from_chat.photo.small_photo_unique_id,
                "big_file_id": ctx.forward_from_chat.photo.big_file_id,
                "big_photo_unique_id": ctx.forward_from_chat.photo.big_photo_unique_id,
            }
        elif (
            not ctx.forward_sender_name
            and not ctx.forward_from
            and ctx.forward_from_chat
            or ctx.forward_sender_name
            or not ctx.forward_from
        ):
            return ""
        else:
            return (
                {
                    "small_file_id": ctx.forward_from.photo.small_file_id,
                    "small_photo_unique_id": ctx.forward_from.photo.small_photo_unique_id,
                    "big_file_id": ctx.forward_from.photo.big_file_id,
                    "big_photo_unique_id": ctx.forward_from.photo.big_photo_unique_id,
                }
                if ctx.forward_from.photo
                else ""
            )
# ---------------------------------------------------------------------------------
    elif ctx.from_user and ctx.from_user.photo:
        return {
            "small_file_id": ctx.from_user.photo.small_file_id,
            "small_photo_unique_id": ctx.from_user.photo.small_photo_unique_id,
            "big_file_id": ctx.from_user.photo.big_file_id,
            "big_photo_unique_id": ctx.from_user.photo.big_photo_unique_id,
        }
    elif (
        ctx.from_user
        or ctx.sender_chat
        and not ctx.sender_chat.photo
        or not ctx.sender_chat
    ):
        return ""
    else:
        return {
            "small_file_id": ctx.sender_chat.photo.small_file_id,
            "small_photo_unique_id": ctx.sender_chat.photo.small_photo_unique_id,
            "big_file_id": ctx.sender_chat.photo.big_file_id,
            "big_photo_unique_id": ctx.sender_chat.photo.big_photo_unique_id,
        }
# ---------------------------------------------------------------------------------------------------
async def get_text_or_caption(ctx: Message):
    if ctx.text:
        return ctx.text
    elif ctx.caption:
        return ctx.caption
    else:
        return ""
# ---------------------------------------------------------------------------------------------------
async def pyrogram_to_quotly(messages, is_reply):
    if not isinstance(messages, list):
        messages = [messages]
    payload = {
        "type": "quote",
        "format": "webp",
        "backgroundColor": "#1b1429",
        "width": 512,
        "scale": 2,
        "emojiBrand": "apple",
        "messages": [],
    }
# ------------------------------------------------------------------------------------------------------------
    for message in messages:
        the_message_dict_to_append = {}
        if message.entities:
            the_message_dict_to_append["entities"] = [
                {
                    "type": entity.type.name.lower(),
                    "offset": entity.offset,
                    "length": entity.length,
                }
                for entity in message.entities
            ]
        elif message.caption_entities:
            the_message_dict_to_append["entities"] = [
                {
                    "type": entity.type.name.lower(),
                    "offset": entity.offset,
                    "length": entity.length,
                }
                for entity in message.caption_entities
            ]
        else:
            the_message_dict_to_append["entities"] = []
        the_message_dict_to_append["chatId"] = await get_message_sender_id(message)
        the_message_dict_to_append["text"] = await get_text_or_caption(message)
        the_message_dict_to_append["avatar"] = True
        the_message_dict_to_append["from"] = {}
        the_message_dict_to_append["from"]["id"] = await get_message_sender_id(message)
        the_message_dict_to_append["from"]["name"] = await get_message_sender_name(
            message
        )
        the_message_dict_to_append["from"][
            "username"
        ] = await get_message_sender_username(message)
        the_message_dict_to_append["from"]["type"] = message.chat.type.name.lower()
        the_message_dict_to_append["from"]["photo"] = await get_message_sender_photo(
            message
        )
        if message.reply_to_message and is_reply:
            the_message_dict_to_append["replyMessage"] = {
                "name": await get_message_sender_name(message.reply_to_message),
                "text": await get_text_or_caption(message.reply_to_message),
                "chatId": await get_message_sender_id(message.reply_to_message),
            }
        else:
            the_message_dict_to_append["replyMessage"] = {}
        payload["messages"].append(the_message_dict_to_append)
    errors = []

    for endpoint in QUOTE_BINARY_ENDPOINTS:
        try:
            r = await fetch.post(endpoint, json=payload)
            content_type = (r.headers.get("content-type") or "").lower()
            if not r.is_error and (
                content_type.startswith("image/")
                or r.read().startswith((b"RIFF", b"\x89PNG", b"\xff\xd8"))
            ):
                return r.read()
            try:
                errors.append(f"{endpoint}: {r.json()}")
            except Exception:
                errors.append(f"{endpoint}: HTTP {r.status_code}")
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")

    for endpoint in QUOTE_JSON_ENDPOINTS:
        try:
            r = await fetch.post(endpoint, json=payload)
            if not r.is_error:
                data = r.json()
                image_data = (
                    ((data.get("result") or {}).get("image") or data.get("image") or "")
                    .strip()
                )
                if image_data:
                    return base64.b64decode(image_data)
                errors.append(f"{endpoint}: returned no image")
            else:
                try:
                    errors.append(f"{endpoint}: {r.json()}")
                except Exception:
                    errors.append(f"{endpoint}: HTTP {r.status_code}")
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")

    try:
        return await _render_quote_locally(messages, is_reply)
    except Exception as exc:
        errors.append(f"local renderer failed: {exc}")

    raise QuotlyException("; ".join(errors[-3:]))
# ------------------------------------------------------------------------------------------

# Helper function to check if an argument is an integer
def isArgInt(txt) -> list:
    count = txt
    try:
        count = int(count)
        return [True, count]
    except ValueError:
        return [False, 0]

# ---------------------------------------------------------------------------------------------------
@app.on_message(filters.command("q") & filters.reply)
async def msg_quotly_cmd(self: Client, ctx: Message):
    args = ctx.text.split()[1:]

    is_reply = False
    count = 1

    for arg in args:
        if arg.lower() == 'r':
            is_reply = True
        else:
            check_arg = isArgInt(arg)
            if check_arg[0]:
                count = check_arg[1]
            else:
                continue  # Ignore invalid arguments

    if count < 1 or count > 10:
        return await ctx.reply_text("Invalid range", delete_after=6)
    
    # Send processing message
    processing_msg = await ctx.reply_text("❄️")
    try:
        if count == 1:
            messages = [ctx.reply_to_message]
        else:
            message_ids = range(ctx.reply_to_message.id, ctx.reply_to_message.id + count)
            messages = [
                i
                for i in await self.get_messages(
                    chat_id=ctx.chat.id,
                    message_ids=message_ids,
                    replies=-1,
                )
                if not i.empty and not i.media
            ]
    except Exception:
        await processing_msg.delete()
        return await ctx.reply_text("🤷🏻‍♂️")
    try:
        make_quotly = await pyrogram_to_quotly(messages, is_reply=is_reply)
        bio_sticker = BytesIO(make_quotly)
        bio_sticker.name = "misskatyquote_sticker.webp"
        await ctx.reply_sticker(bio_sticker)
    except Exception as e:
        await ctx.reply_text(f"ERROR: {e}")
    finally:
        await processing_msg.delete()
# ---------------------------------------------------------------------------------

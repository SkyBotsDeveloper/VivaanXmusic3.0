import asyncio
import random
import time
from html import escape

from pyrogram import filters, raw
from pyrogram.enums import ButtonStyle, ChatType, MessageEntityType
from pyrogram.parser import Parser
from pyrogram.parser.utils import add_surrogates, remove_surrogates
from pyrogram.types import (
    InputRichMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    ReplyParameters,
)
from youtubesearchpython.future import VideosSearch

import config
from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import _boot_
from VIVAANXMUSIC.plugins.sudo.sudoers import sudoers_list
from VIVAANXMUSIC.utils import bot_sys_stats
from VIVAANXMUSIC.utils.database import (
    add_served_chat,
    add_served_user,
    blacklisted_chats,
    get_lang,
    get_served_chats,
    get_served_users,
    is_banned_user,
    is_on_off,
)
from VIVAANXMUSIC.utils.decorators.language import LanguageStart
from VIVAANXMUSIC.utils.formatters import get_readable_time
from VIVAANXMUSIC.button_styles import primary_button, success_button
from VIVAANXMUSIC.utils.inline.start import private_panel, start_panel
from VIVAANXMUSIC.utils.inline.help import first_page
from config import BANNED_USERS, AYUV, HELP_IMG_URL, START_VIDS, STICKERS
from strings import get_string


# Set False to restore the original /start media and inline keyboards.
START_RICH_BUTTONS = True


async def _send_start_message(
    message, media, caption, buttons, *, photo=False, reply=True, full_width=False
):
    if not START_RICH_BUTTONS:
        markup = InlineKeyboardMarkup(buttons)
        if photo:
            if reply:
                return await message.reply_photo(
                    photo=media, caption=caption, reply_markup=markup
                )
            return await app.send_photo(
                chat_id=message.chat.id, photo=media, caption=caption, reply_markup=markup
            )
        return await message.reply_video(media, caption=caption, reply_markup=markup)

    # Preserve the old combined Markdown/HTML caption formatting, including mentions.
    parsed = await Parser(None).parse(caption, app.parse_mode)
    entities = []
    for entity in parsed["entities"] or []:
        if isinstance(entity, raw.types.InputMessageEntityMentionName):
            entities.append(
                MessageEntity(
                    type=MessageEntityType.TEXT_LINK,
                    offset=entity.offset,
                    length=entity.length,
                    url=f"tg://user?id={entity.user_id}",
                )
            )
        else:
            entities.append(MessageEntity._parse(None, entity, {}))
    text = add_surrogates(parsed["message"])
    if entities:
        start = min(entity.offset for entity in entities)
        end = max(entity.offset + entity.length for entity in entities)
        for entity in entities:
            entity.offset -= start
        caption_html = (
            escape(remove_surrogates(text[:start]))
            + Parser.unparse(remove_surrogates(text[start:end]), entities, True)
            + escape(remove_surrogates(text[end:]))
        )
    else:
        caption_html = escape(parsed["message"])
    caption_html = caption_html.replace("\n", "<br>")

    # 2.2.24 exposes Rich HTML input, rather than the newer rich button/block types.
    # https://core.telegram.org/bots/api#rich-message-formatting-options
    rows = []
    for row in buttons:
        rich_buttons = []
        for button in row:
            style = button.style
            style_attr = (
                f' style="{style.name.lower()}"'
                if style in (ButtonStyle.PRIMARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER)
                else ""
            )
            if button.callback_data is not None:
                action = f'type="callback_data" data="{escape(button.callback_data, quote=True)}"'
            else:
                url = button.url if button.user_id is None else f"tg://user?id={button.user_id}"
                action = f'type="url" url="{escape(url, quote=True)}"'
            rich_buttons.append(
                f'<tg-button {action}{style_attr}>{escape(button.text)}</tg-button>'
            )
        # Unset alignment uses Telegram's full-width, equal-column button layout.
        # https://github.com/tdlib/td/blob/master/td/generate/scheme/td_api.tl
        row_tag = '<tg-button-row>' if full_width else '<tg-button-row align="center">'
        rows.append(row_tag + "".join(rich_buttons) + '</tg-button-row>')

    media_tag = "img" if photo else "video"
    media_html = f'<{media_tag} src="{escape(media, quote=True)}"/>'
    return await app.send_rich_message(
        chat_id=message.chat.id,
        rich_message=InputRichMessage(html=media_html + f"<p>{caption_html}</p>" + "".join(rows)),
        reply_parameters=ReplyParameters(message_id=message.id) if reply else None,
        message_thread_id=message.message_thread_id if reply else None,
        direct_messages_topic_id=message.direct_messages_topic_id if reply else None,
    )


async def delete_sticker_after_delay(message: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


@app.on_message(filters.command(["start"]) & filters.private & ~BANNED_USERS)
@LanguageStart
async def start_pm(client, message: Message, _):
    try:
        await add_served_user(message.from_user.id)
    except Exception:
        pass

    if len(message.text.split()) > 1:
        name = message.text.split(None, 1)[1]

        if name.startswith("help"):
            keyboard = first_page(_)
            return await _send_start_message(
                message,
                HELP_IMG_URL,
                caption=_["help_1"].format(config.SUPPORT_CHAT),
                buttons=keyboard.inline_keyboard,
                photo=True,
            )

        if name.startswith("sud"):
            await sudoers_list(client=client, message=message, _=_)
            if await is_on_off(2):
                username = f"@{message.from_user.username}" if message.from_user.username else "(none)"
                await app.send_message(
                    chat_id=config.LOGGER_ID,
                    text=(
                        f"{message.from_user.mention} ᴊᴜsᴛ sᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ᴄʜᴇᴄᴋ <b>sᴜᴅᴏʟɪsᴛ</b>.\n\n"
                        f"<b>ᴜsᴇʀ ɪᴅ :</b> <code>{message.from_user.id}</code>\n"
                        f"<b>ᴜsᴇʀɴᴀᴍᴇ :</b> {username}"
                    ),
                )
            return

        if name.startswith("inf"):
            m = await message.reply_text("🔎")
            try:
                vid_id = str(name).replace("info_", "", 1)
                query = f"https://www.youtube.com/watch?v={vid_id}"
                results = VideosSearch(query, limit=1)
                data = await results.next()
                result = (data.get("result") or [None])[0]
                if not result:
                    await m.edit_text("No results found.")
                    return

                title = result.get("title") or "Unknown"
                duration = result.get("duration") or "Unknown"
                views = (result.get("viewCount") or {}).get("short") or "Unknown"
                thumbnail = ((result.get("thumbnails") or [{}])[0].get("url") or "").split("?")[0]
                channellink = (result.get("channel") or {}).get("link") or "https://youtube.com"
                channel = (result.get("channel") or {}).get("name") or "Unknown"
                link = result.get("link") or query
                published = result.get("publishedTime") or "Unknown"

                searched_text = _["start_6"].format(title, duration, views, published, channellink, channel, app.mention)
                key = InlineKeyboardMarkup(
                    [[
                        primary_button(text=_["S_B_6"], url=link),
                        success_button(text=_["S_B_4"], url=config.SUPPORT_CHAT),
                    ]]
                )

                await m.delete()

                await _send_start_message(
                    message,
                    thumbnail or HELP_IMG_URL,
                    caption=searched_text,
                    buttons=key.inline_keyboard,
                    photo=True,
                    reply=False,
                )

                if await is_on_off(2):
                    username = f"@{message.from_user.username}" if message.from_user.username else "(none)"
                    await app.send_message(
                        chat_id=config.LOGGER_ID,
                        text=(
                            f"{message.from_user.mention} ᴊᴜsᴛ sᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ᴄʜᴇᴄᴋ <b>ᴛʀᴀᴄᴋ ɪɴғᴏʀᴍᴀᴛɪᴏɴ</b>.\n\n"
                            f"<b>ᴜsᴇʀ ɪᴅ :</b> <code>{message.from_user.id}</code>\n"
                            f"<b>ᴜsᴇʀɴᴀᴍᴇ :</b> {username}"
                        ),
                    )
            except Exception as e:
                await m.edit_text(f"Error: {e}")
            return

    out = private_panel(_)
    sticker_message = await message.reply_sticker(sticker=random.choice(STICKERS))
    asyncio.create_task(delete_sticker_after_delay(sticker_message, 2))

    served_chats_coro = get_served_chats()
    served_users_coro = get_served_users()
    stats_coro = bot_sys_stats()
    served_chats, served_users, (UP, CPU, RAM, DISK) = await asyncio.gather(
        served_chats_coro, served_users_coro, stats_coro
    )

    await _send_start_message(
        message,
        random.choice(START_VIDS),
        caption=random.choice(AYUV).format(
            message.from_user.mention, app.mention, UP, DISK, CPU, RAM, len(served_users), len(served_chats)
        ),
        buttons=out,
        full_width=True,
    )

    if await is_on_off(2):
        username = f"@{message.from_user.username}" if message.from_user.username else "(none)"
        await app.send_message(
            chat_id=config.LOGGER_ID,
            text=(
                f"{message.from_user.mention} ᴊᴜsᴛ sᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ.\n\n"
                f"<b>ᴜsᴇʀ ɪᴅ :</b> <code>{message.from_user.id}</code>\n"
                f"<b>ᴜsᴇʀɴᴀᴍᴇ :</b> {username}"
            ),
        )


@app.on_message(filters.command(["start"]) & filters.group & ~BANNED_USERS)
@LanguageStart
async def start_gp(client, message: Message, _):
    out = start_panel(_)
    uptime = int(time.time() - _boot_)
    try:
        await _send_start_message(
            message,
            random.choice(START_VIDS),
            caption=_["start_1"].format(app.mention, get_readable_time(uptime)),
            buttons=out,
        )
    except:
        pass
    return await add_served_chat(message.chat.id)


@app.on_message(filters.new_chat_members, group=-1)
async def welcome(client, message: Message):
    for member in message.new_chat_members:
        try:
            language = await get_lang(message.chat.id)
            _ = get_string(language)

            if await is_banned_user(member.id):
                try:
                    await message.chat.ban_member(member.id)
                except Exception:
                    pass

            if member.id == app.id:
                if message.chat.type != ChatType.SUPERGROUP:
                    await message.reply_text(_["start_4"])
                    return await app.leave_chat(message.chat.id)

                if message.chat.id in await blacklisted_chats():
                    await message.reply_text(
                        _["start_5"].format(
                            app.mention,
                            f"https://t.me/{app.username}?start=sudolist",
                            config.SUPPORT_CHAT,
                        ),
                        disable_web_page_preview=True,
                    )
                    return await app.leave_chat(message.chat.id)

                out = start_panel(_)
                await message.reply_video(
                    random.choice(START_VIDS),
                    caption=_["start_3"].format(
                        message.from_user.mention,
                        app.mention,
                        message.chat.title,
                        app.mention,
                    ),
                    reply_markup=InlineKeyboardMarkup(out),
                )
                await add_served_chat(message.chat.id)
                await message.stop_propagation()

        except Exception as ex:
            print(ex)

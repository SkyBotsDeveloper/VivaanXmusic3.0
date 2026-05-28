from pyrogram.enums import ParseMode
from html import escape

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import is_on_off
from config import LOGGER_ID


def _clip(value, limit=180):
    text = " ".join(str(value or "-").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _safe(value, limit=180):
    return escape(_clip(value, limit), quote=False)


async def play_logs(message, streamtype, query: str = None, source: str = None):
    if await is_on_off(2):
        if query is None:
            try:
                query = message.text.split(None, 1)[1]
            except Exception:
                query = "-"

        source_line = f"\n<b>sᴏᴜʀᴄᴇ :</b> {source}" if source else ""
        logger_text = f"""
<b>{app.mention} ᴘʟᴀʏ ʟᴏɢ</b>

<b>ᴄʜᴀᴛ ɪᴅ :</b> <code>{message.chat.id}</code>
<b>ᴄʜᴀᴛ ɴᴀᴍᴇ :</b> {message.chat.title}
<b>ᴄʜᴀᴛ ᴜsᴇʀɴᴀᴍᴇ :</b> @{message.chat.username}

<b>ᴜsᴇʀ ɪᴅ :</b> <code>{message.from_user.id}</code>
<b>ɴᴀᴍᴇ :</b> {message.from_user.mention}
<b>ᴜsᴇʀɴᴀᴍᴇ :</b> @{message.from_user.username}

<b>ǫᴜᴇʀʏ :</b> {query}
<b>sᴛʀᴇᴀᴍᴛʏᴘᴇ :</b> {streamtype}{source_line}"""
        if message.chat.id != LOGGER_ID:
            try:
                await app.send_message(
                    chat_id=LOGGER_ID,
                    text=logger_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
        return


async def failure_logs(
    message,
    area: str,
    reason: str,
    query: str = None,
    streamtype: str = None,
    source: str = None,
    user=None,
):
    if not await is_on_off(2):
        return
    if message.chat.id == LOGGER_ID:
        return

    actor = user or message.from_user
    user_line = (
        f"{actor.mention} (<code>{actor.id}</code>)"
        if actor
        else "N/A"
    )
    query_line = f"\n<b>ǫᴜᴇʀʏ :</b> {_safe(query)}" if query else ""
    stream_line = f"\n<b>sᴛʀᴇᴀᴍᴛʏᴘᴇ :</b> {_safe(streamtype)}" if streamtype else ""
    source_line = f"\n<b>sᴏᴜʀᴄᴇ :</b> {_safe(source)}" if source else ""
    text = f"""
<b>{app.mention} ғᴀɪʟᴜʀᴇ ʟᴏɢ</b>

<b>ᴀʀᴇᴀ :</b> {_safe(area, 80)}
<b>ʀᴇᴀsᴏɴ :</b> {_safe(reason, 220)}{query_line}{stream_line}{source_line}

<b>ᴄʜᴀᴛ :</b> {_safe(message.chat.title, 120)} (<code>{message.chat.id}</code>)
<b>ᴜsᴇʀ :</b> {user_line}"""
    try:
        await app.send_message(
            chat_id=LOGGER_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

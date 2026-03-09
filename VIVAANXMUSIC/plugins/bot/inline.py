from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultPhoto,
)
from youtubesearchpython.future import VideosSearch

from VIVAANXMUSIC.utils.inlinequery import answer
from VIVAANXMUSIC.utils.button_styles import primary_button
from config import BANNED_USERS
from VIVAANXMUSIC import app


@app.on_inline_query(~BANNED_USERS)
async def inline_query_handler(client, query):
    text = query.query.strip().lower()
    answers = []
    if text.strip() == "":
        try:
            await client.answer_inline_query(query.id, results=answer, cache_time=10)
        except:
            return
    else:
        a = VideosSearch(text, limit=20)
        result = (await a.next()).get("result") or []
        for item in result[:15]:
            title = (item.get("title") or "").title()
            duration = item.get("duration") or "Unknown"
            views = (item.get("viewCount") or {}).get("short") or "Unknown"
            thumbnail = ((item.get("thumbnails") or [{}])[0].get("url") or "").split("?")[0]
            channellink = (item.get("channel") or {}).get("link") or "https://youtube.com"
            channel = (item.get("channel") or {}).get("name") or "Unknown"
            link = item.get("link") or "https://youtube.com"
            published = item.get("publishedTime") or "Unknown"
            description = f"{views} | {duration} ᴍɪɴᴜᴛᴇs | {channel}  | {published}"
            buttons = InlineKeyboardMarkup(
                [
                    [
                        primary_button(
                            text="ʏᴏᴜᴛᴜʙᴇ 🎄",
                            url=link,
                        )
                    ],
                ]
            )
            searched_text = f"""
❄ <b>ᴛɪᴛʟᴇ :</b> <a href={link}>{title}</a>

⏳ <b>ᴅᴜʀᴀᴛɪᴏɴ :</b> {duration} ᴍɪɴᴜᴛᴇs
👀 <b>ᴠɪᴇᴡs :</b> <code>{views}</code>
🎥 <b>ᴄʜᴀɴɴᴇʟ :</b> <a href={channellink}>{channel}</a>
⏰ <b>ᴘᴜʙʟɪsʜᴇᴅ ᴏɴ :</b> {published}


<u><b>➻ ɪɴʟɪɴᴇ sᴇᴀʀᴄʜ ᴍᴏᴅᴇ ʙʏ {app.name}</b></u>"""
            answers.append(
                InlineQueryResultPhoto(
                    photo_url=thumbnail,
                    title=title,
                    thumb_url=thumbnail,
                    description=description,
                    caption=searched_text,
                    reply_markup=buttons,
                )
            )
        try:
            return await client.answer_inline_query(query.id, results=answers)
        except:
            return

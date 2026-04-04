import asyncio

from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup

from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import db
from VIVAANXMUSIC.utils.thumbnails import get_thumb


async def _deliver_stream_card(
    chat_id: int,
    original_chat_id: int,
    videoid,
    user_id,
    caption: str,
    button,
    markup: str = "stream",
):
    try:
        queue = db.get(chat_id)
        if not queue or queue[0].get("vidid") != videoid:
            return

        img = await get_thumb(videoid, user_id)

        queue = db.get(chat_id)
        if not queue or queue[0].get("vidid") != videoid:
            return

        try:
            run = await app.send_photo(
                original_chat_id,
                photo=img,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(button),
            )
        except FloodWait as exc:
            await asyncio.sleep(exc.value)
            run = await app.send_photo(
                original_chat_id,
                photo=img,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(button),
            )

        queue = db.get(chat_id)
        if not queue or queue[0].get("vidid") != videoid:
            try:
                await run.delete()
            except Exception:
                pass
            return

        db[chat_id][0]["mystic"] = run
        db[chat_id][0]["markup"] = markup
    except Exception:
        return


def schedule_stream_card(
    chat_id: int,
    original_chat_id: int,
    videoid,
    user_id,
    caption: str,
    button,
    markup: str = "stream",
):
    asyncio.create_task(
        _deliver_stream_card(
            chat_id=chat_id,
            original_chat_id=original_chat_id,
            videoid=videoid,
            user_id=user_id,
            caption=caption,
            button=button,
            markup=markup,
        )
    )

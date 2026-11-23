from pyrogram import filters
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.core.call import JARVIS
from VIVAANXMUSIC.core.call import vc_join_targets
from VIVAANXMUSIC.utils.database import get_vcnotify

welcome = 20
close = 30


@app.on_message(filters.video_chat_started, group=welcome)
@app.on_message(filters.video_chat_ended, group=close)
async def welcome(_, message: Message):
    chat_id = message.chat.id
    notify_chat_id = vc_join_targets.get(chat_id, chat_id)
    if message.video_chat_ended:
        await JARVIS.stop_stream(chat_id, leave=True)
        return
    if not await get_vcnotify(notify_chat_id):
        return
    JARVIS._vc_presence_suppressed.pop(chat_id, None)
    await JARVIS.maybe_start_vc_join_notifier(chat_id, notify_chat_id)
    await JARVIS.ensure_vc_notify_presence(chat_id, notify_chat_id)

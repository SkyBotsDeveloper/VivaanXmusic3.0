import os

from config import autoclean
from VIVAANXMUSIC.utils.stream.autodelete import delete_track_messages


async def auto_clean(popped):
    try:
        chat_id = popped.get("chat_id")
        if chat_id is not None:
            await delete_track_messages(chat_id, popped)
        rem = popped["file"]
        autoclean.remove(rem)
        count = autoclean.count(rem)
        if count == 0:
            if "vid_" not in rem or "live_" not in rem or "index_" not in rem:
                try:
                    os.remove(rem)
                except:
                    pass
    except:
        pass

from VIVAANXMUSIC.logging import LOGGER
from VIVAANXMUSIC.misc import db
from VIVAANXMUSIC.utils.database import get_autodelete


QUEUE_REF_KEYS = ("queue_chat_id", "queue_msg_id")
PLAYER_REF_KEYS = ("player_chat_id", "player_msg_id", "mystic")


def _message_chat_id(message):
    chat = getattr(message, "chat", None)
    return getattr(chat, "id", None)


def _message_id(message):
    return getattr(message, "id", None) or getattr(message, "message_id", None)


def remember_queue_message(chat_id: int, message, index: int = -1) -> bool:
    try:
        queue = db.get(chat_id)
        if not queue:
            return False

        item = queue[index]
        chat = _message_chat_id(message)
        msg_id = _message_id(message)
        if not chat or not msg_id:
            return False

        item["queue_chat_id"] = int(chat)
        item["queue_msg_id"] = int(msg_id)
        return True
    except Exception:
        return False


def remember_player_message(chat_id: int, message) -> bool:
    try:
        queue = db.get(chat_id)
        if not queue or not isinstance(queue[0], dict):
            return False

        chat = _message_chat_id(message)
        msg_id = _message_id(message)
        if not chat or not msg_id:
            return False

        queue[0]["player_chat_id"] = int(chat)
        queue[0]["player_msg_id"] = int(msg_id)
        return True
    except Exception:
        return False


def _setting_chat_id(chat_id: int, track: dict | None) -> int:
    if isinstance(track, dict):
        try:
            return int(track.get("chat_id") or chat_id)
        except (TypeError, ValueError):
            return int(chat_id)
    return int(chat_id)


async def _delete_by_ref(message=None, chat_id=None, message_id=None) -> bool:
    if message is not None:
        try:
            await message.delete()
            return True
        except Exception:
            pass

    if not chat_id or not message_id:
        return False

    try:
        from VIVAANXMUSIC import app

        await app.delete_messages(int(chat_id), int(message_id))
        return True
    except Exception:
        return False


async def _delete_tracked_message(track: dict, keys: tuple[str, ...]) -> bool:
    message = track.get("mystic") if "mystic" in keys else None
    chat_id = None
    message_id = None
    if "queue_chat_id" in keys:
        chat_id = track.get("queue_chat_id")
        message_id = track.get("queue_msg_id")
    elif "player_chat_id" in keys:
        chat_id = track.get("player_chat_id")
        message_id = track.get("player_msg_id")

    deleted = await _delete_by_ref(message, chat_id, message_id)
    for key in keys:
        track.pop(key, None)
    return deleted


async def delete_queue_message(chat_id: int, track: dict | None) -> bool:
    if not isinstance(track, dict):
        return False
    if not await get_autodelete(_setting_chat_id(chat_id, track)):
        return False
    deleted = await _delete_tracked_message(track, QUEUE_REF_KEYS)
    if deleted:
        LOGGER(__name__).info("Auto-deleted queued-track notice | chat_id=%s", chat_id)
    return deleted


async def delete_player_message(chat_id: int, track: dict | None) -> bool:
    if not isinstance(track, dict):
        return False
    if not await get_autodelete(_setting_chat_id(chat_id, track)):
        return False
    deleted = await _delete_tracked_message(track, PLAYER_REF_KEYS)
    if deleted:
        LOGGER(__name__).info("Auto-deleted stream card | chat_id=%s", chat_id)
    return deleted


async def delete_track_messages(chat_id: int, track: dict | None) -> None:
    if not isinstance(track, dict):
        return
    if not await get_autodelete(_setting_chat_id(chat_id, track)):
        return
    await _delete_tracked_message(track, PLAYER_REF_KEYS)
    await _delete_tracked_message(track, QUEUE_REF_KEYS)

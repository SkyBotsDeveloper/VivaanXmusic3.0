"""Small, expiring Mongo checkpoints for resuming YouTube playback after dyno restarts."""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from pymongo import DeleteOne, ReplaceOne

from VIVAANXMUSIC.core.mongo import mongodb
from VIVAANXMUSIC.misc import db
from VIVAANXMUSIC.utils.database import is_music_enabled


LOGGER = logging.getLogger("playback_recovery")
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _setting_int(name, default, minimum):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        value = default
    return max(minimum, value)


CHECKPOINT_SECONDS = _setting_int("PLAYBACK_CHECKPOINT_SECONDS", 10, 5)
RETENTION_SECONDS = _setting_int("PLAYBACK_CHECKPOINT_TTL_SECONDS", 86400, 3600)
COLLECTION = mongodb.playback_recovery


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _stored_track(track):
    """Keep only compact metadata and a stable YouTube ID, never expiring URLs/messages."""
    if not isinstance(track, dict):
        return None
    video_id = str(track.get("vidid") or "").strip()
    queued_file = str(track.get("file") or "")
    live = queued_file.startswith("live_")
    if not (live or queued_file.startswith("vid_")):
        return None
    prefix_length = 5 if live else 4
    if not YOUTUBE_ID.fullmatch(video_id) or queued_file[prefix_length:] != video_id:
        return None

    seconds = _safe_int(track.get("old_second") or track.get("seconds"), 0)
    if seconds <= 0 and not live:
        return None
    duration = str(track.get("old_dur") or track.get("dur") or "").strip()
    if not duration and not live:
        return None
    if live and not duration:
        duration = "Live"

    played = max(_safe_int(track.get("played"), 0), 0)
    speed = str(track.get("speed") or "1.0")
    # Playback offsets on speed-adjusted files use output time; checkpoints resume
    # against the original YouTube source, so translate back to source time.
    speed_factors = {"0.5": 0.5, "0.75": 0.75, "1.5": 1.5, "2.0": 2.0}
    played = int(round(played * speed_factors.get(speed, 1.0)))
    return {
        "vidid": video_id,
        "title": str(track.get("title") or "Unknown Title")[:256],
        "dur": duration[:32],
        "seconds": seconds,
        "played": min(played, seconds),
        "live": live,
        "streamtype": "video" if str(track.get("streamtype")) == "video" else "audio",
        "by": str(track.get("by") or "Unknown")[:128],
        "user_id": _safe_int(track.get("user_id"), 0),
        "chat_id": _safe_int(track.get("chat_id"), 0),
    }


def _restore_queue(tracks):
    result = []
    for track in tracks or []:
        if not isinstance(track, dict):
            continue
        video_id = str(track.get("vidid") or "").strip()
        seconds = _safe_int(track.get("seconds"), 0)
        live = bool(track.get("live"))
        if not YOUTUBE_ID.fullmatch(video_id) or (seconds <= 0 and not live):
            continue
        result.append({
            "title": str(track.get("title") or "Unknown Title"),
            "dur": str(track.get("dur") or ""),
            "streamtype": "video" if track.get("streamtype") == "video" else "audio",
            "by": str(track.get("by") or "Unknown"),
            "user_id": _safe_int(track.get("user_id"), 0),
            "chat_id": _safe_int(track.get("chat_id"), 0),
            "file": f"live_{video_id}" if live else f"vid_{video_id}",
            "vidid": video_id,
            "seconds": seconds,
            "played": min(max(_safe_int(track.get("played"), 0), 0), seconds),
            "live": live,
        })
    return result


class PlaybackRecovery:
    def __init__(self, controller):
        self.controller = controller
        self.task = None
        self.start_task = None
        self._pending = set()
        self._pending_task = None
        self._last_warning = 0.0

    async def start(self):
        try:
            await COLLECTION.create_index(
                "expires_at", expireAfterSeconds=0, name="playback_recovery_ttl"
            )
        except Exception as exc:
            LOGGER.warning("Playback recovery TTL index setup failed (%s).", type(exc).__name__)
        try:
            await COLLECTION.delete_many({"expires_at": {"$lte": datetime.now(timezone.utc)}})
        except Exception as exc:
            self._warn("expired cleanup", exc)
        await self.restore()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._checkpoint_loop())

    def schedule(self, chat_id):
        """Debounce queue mutations so callbacks do not block on Mongo writes."""
        try:
            self._pending.add(int(chat_id))
        except (TypeError, ValueError):
            return
        if self._pending_task is None or self._pending_task.done():
            self._pending_task = asyncio.create_task(self._flush_pending())

    async def _flush_pending(self):
        await asyncio.sleep(1)
        chat_ids = tuple(self._pending)
        self._pending.clear()
        for chat_id in chat_ids:
            await self.save_chat(chat_id)

    async def clear(self, chat_id):
        try:
            await COLLECTION.delete_one({"_id": int(chat_id)})
        except Exception as exc:
            self._warn("delete", exc)

    async def save_chat(self, chat_id):
        chat_id = int(chat_id)
        try:
            document = self._make_document(chat_id, datetime.now(timezone.utc))
            if document is None:
                await self.clear(chat_id)
            else:
                await COLLECTION.replace_one({"_id": chat_id}, document, upsert=True)
        except Exception as exc:
            self._warn("save", exc)

    def _make_document(self, chat_id, now):
        if chat_id not in self.controller.active_calls:
            return None
        queue = db.get(chat_id) or []
        if not queue or not _stored_track(queue[0]):
            return None
        stored = [_stored_track(track) for track in queue]
        stored = [track for track in stored if track]
        if not stored:
            return None
        from VIVAANXMUSIC.utils.database import pause

        return {
            "_id": int(chat_id),
            "queue": stored,
            "paused": not bool(pause.get(chat_id, False)),
            "updated_at": now,
            "expires_at": now + timedelta(seconds=RETENTION_SECONDS),
        }

    async def _checkpoint_loop(self):
        while True:
            await asyncio.sleep(CHECKPOINT_SECONDS)
            now = datetime.now(timezone.utc)
            operations = []
            for chat_id in tuple(self.controller.active_calls):
                document = self._make_document(chat_id, now)
                if document is None:
                    operations.append(DeleteOne({"_id": int(chat_id)}))
                else:
                    operations.append(
                        ReplaceOne({"_id": int(chat_id)}, document, upsert=True)
                    )
            if operations:
                try:
                    await COLLECTION.bulk_write(operations, ordered=False)
                except Exception as exc:
                    self._warn("save batch", exc)

    def _warn(self, action, exc):
        now = asyncio.get_running_loop().time()
        if now - self._last_warning >= 60:
            self._last_warning = now
            LOGGER.warning("Playback checkpoint %s failed (%s).", action, type(exc).__name__)

    async def restore(self):
        now = datetime.now(timezone.utc)
        try:
            cursor = COLLECTION.find({"expires_at": {"$gt": now}})
            async for record in cursor:
                await self._restore_record(record)
        except Exception as exc:
            self._warn("restore", exc)

    async def _restore_record(self, record):
        chat_id = _safe_int(record.get("_id"), 0)
        queue = _restore_queue(record.get("queue"))
        if not chat_id or not queue:
            await self.clear(chat_id)
            return

        paused = bool(record.get("paused"))

        original_chat_id = _safe_int(queue[0].get("chat_id"), chat_id) or chat_id
        try:
            if not await is_music_enabled(original_chat_id):
                await self.clear(chat_id)
                return
            call_id = await self.controller._resolve_vc_call_id(chat_id)
            if not call_id:
                await self.clear(chat_id)
                return
            listeners = await self.controller._real_vc_listener_ids(None, chat_id)
            if not listeners:
                await self.clear(chat_id)
                return

            db[chat_id] = queue
            await self.controller.resume_saved_playback(chat_id, paused=paused)
            self.schedule(chat_id)
            LOGGER.info(
                "Resumed saved playback | chat_id=%s | title=%s | offset=%ss",
                chat_id,
                queue[0].get("title"),
                queue[0].get("played", 0),
            )
        except Exception as exc:
            if chat_id not in self.controller.active_calls:
                db.pop(chat_id, None)
            await self.clear(chat_id)
            self._warn("resume", exc)

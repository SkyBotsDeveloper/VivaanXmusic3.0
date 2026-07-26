import asyncio
import os

from VIVAANXMUSIC.logging import LOGGER
from VIVAANXMUSIC.misc import db


MIN_CACHED_MEDIA_BYTES = 128 * 1024
PRECACHE_LOOKAHEAD = 2
_precache_tasks: dict[tuple[int, str, str], asyncio.Task] = {}


class _PrecacheMystic:
    async def edit_text(self, *args, **kwargs):
        return None

    async def delete(self, *args, **kwargs):
        return None


def _cache_path(videoid: str, streamtype: str) -> str:
    ext = "mp4" if str(streamtype) == "video" else "mp3"
    return os.path.join("downloads", f"{videoid}.{ext}")


def _cache_ready(path: str) -> bool:
    try:
        return os.path.exists(path) and os.path.getsize(path) >= MIN_CACHED_MEDIA_BYTES
    except OSError:
        return False


def _youtube_queue_candidates(chat_id: int, lookahead: int):
    queue = db.get(chat_id) or []
    for item in queue[1 : 1 + lookahead]:
        if not isinstance(item, dict):
            continue
        queued = str(item.get("file") or "")
        if not queued.startswith("vid_"):
            continue
        videoid = str(item.get("vidid") or "").strip()
        if not videoid or videoid in {"telegram", "soundcloud"}:
            continue
        streamtype = str(item.get("streamtype") or "audio")
        if streamtype not in {"audio", "video"}:
            continue
        yield videoid, streamtype, str(item.get("title") or videoid)


async def _precache_youtube_queue_item(
    chat_id: int,
    videoid: str,
    streamtype: str,
    title: str,
) -> bool:
    path = _cache_path(videoid, streamtype)
    if _cache_ready(path):
        return True

    try:
        from VIVAANXMUSIC import YouTube

        await YouTube.download(
            videoid,
            _PrecacheMystic(),
            videoid=True,
            video=(streamtype == "video"),
            stream=True,
            title=title,
        )
        task = getattr(YouTube, "_background_cache_tasks", {}).get(path)
        if task:
            await task
        ready = _cache_ready(path)
        if ready:
            LOGGER(__name__).info(
                "YouTube queue pre-cache ready | chat_id=%s | video_id=%s | media=%s",
                chat_id,
                videoid,
                streamtype,
            )
        return ready
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        LOGGER(__name__).warning(
            "YouTube queue pre-cache failed | chat_id=%s | video_id=%s | media=%s | reason=%s",
            chat_id,
            videoid,
            streamtype,
            exc,
        )
        return False


def schedule_youtube_precache_for_chat(
    chat_id: int,
    *,
    lookahead: int = PRECACHE_LOOKAHEAD,
) -> int:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0

    scheduled = 0
    for videoid, streamtype, title in _youtube_queue_candidates(chat_id, lookahead):
        path = _cache_path(videoid, streamtype)
        if _cache_ready(path):
            continue

        key = (int(chat_id), videoid, streamtype)
        existing = _precache_tasks.get(key)
        if existing and not existing.done():
            continue

        task = loop.create_task(
            _precache_youtube_queue_item(chat_id, videoid, streamtype, title)
        )
        _precache_tasks[key] = task
        task.add_done_callback(lambda _task, task_key=key: _precache_tasks.pop(task_key, None))
        scheduled += 1

    if scheduled:
        LOGGER(__name__).info(
            "Scheduled %s YouTube queue pre-cache task(s) | chat_id=%s",
            scheduled,
            chat_id,
        )
    return scheduled

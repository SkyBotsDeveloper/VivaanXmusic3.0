from collections import OrderedDict


MAX_SOURCE_STATUS = 500
_youtube_source_status: OrderedDict[str, str] = OrderedDict()


def set_youtube_source_status(video_id: str, text: str) -> None:
    video_id = str(video_id or "").strip()
    text = str(text or "").strip()
    if not video_id or not text:
        return

    _youtube_source_status[video_id] = text
    _youtube_source_status.move_to_end(video_id)
    while len(_youtube_source_status) > MAX_SOURCE_STATUS:
        _youtube_source_status.popitem(last=False)


def get_youtube_source_status(video_id: str) -> str | None:
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    return _youtube_source_status.get(video_id)

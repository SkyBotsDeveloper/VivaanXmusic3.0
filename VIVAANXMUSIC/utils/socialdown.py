from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from VIVAANXMUSIC.security import SecurityError, validate_public_http_url


API_TIMEOUT = httpx.Timeout(18.0, connect=6.0)
DOWNLOAD_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
HTTP_HEADERS = {
    "User-Agent": (
        "VivaanXDownloader/1.0 "
        "(+https://github.com/SkyBotsDeveloper/VivaanXmusic3.0)"
    )
}
MAX_MEDIA_FILES = 8
MAX_DOWNLOAD_BYTES = 95 * 1024 * 1024
FAILURE_COOLDOWN_SECONDS = 420
TRACKER_CACHE_TTL_SECONDS = 900
PYBALT_API_URL = "https://dwnld.nichind.dev/"
LEGACY_COBALT_API_URL = "https://downloadapi.stuff.solutions/api/json"
FIXTWEET_API_URL = "https://api.fxtwitter.com"
COBALT_INSTANCE_TRACKER_URL = "https://instances.cobalt.best/instances.json"
TIKWM_API_URL = "https://www.tikwm.com/api/"
X_OEMBED_URL = "https://publish.twitter.com/oembed"
YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed"

INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",
}
X_HOSTS = {
    "x.com",
    "www.x.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "fb.watch",
    "www.fb.watch",
}
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
SNAPCHAT_HOSTS = {
    "snapchat.com",
    "www.snapchat.com",
    "story.snapchat.com",
}
TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}

PLATFORM_HOSTS = {
    "instagram": INSTAGRAM_HOSTS,
    "x": X_HOSTS,
    "facebook": FACEBOOK_HOSTS,
    "youtube": YOUTUBE_HOSTS,
    "snapchat": SNAPCHAT_HOSTS,
    "tiktok": TIKTOK_HOSTS,
}
PLATFORM_SERVICE_KEYS = {
    "x": "twitter",
}

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}
X_STATUS_PATTERN = re.compile(r"/status(?:es)?/(\d+)", re.IGNORECASE)
CONTENT_DISPOSITION_FILENAME = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)')
META_TAG_PATTERN = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*['\"]([^'\"]+)['\"][^>]+content\s*=\s*['\"]([^'\"]*)['\"]",
    re.IGNORECASE,
)
TITLE_TAG_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TRACKER_CACHE: list[dict] = []
_TRACKER_CACHE_AT = 0.0
_STRATEGY_COOLDOWNS: dict[str, float] = {}


class SocialDownloadError(RuntimeError):
    pass


@dataclass(slots=True)
class SocialMediaItem:
    url: str
    kind: str
    filename_hint: str = ""
    content: str = ""


@dataclass(slots=True)
class SocialDownloadBundle:
    title: str
    source: str
    items: list[SocialMediaItem]
    note_text: str = ""


def _service_works(value) -> bool:
    if value is True:
        return True
    text = str(value or "").strip().lower()
    if not text:
        return False
    return "error" not in text and "couldn't" not in text and "could not" not in text


def _prune_cooldowns():
    now = time.monotonic()
    expired = [key for key, until in _STRATEGY_COOLDOWNS.items() if until <= now]
    for key in expired:
        _STRATEGY_COOLDOWNS.pop(key, None)


def _on_cooldown(key: str) -> bool:
    _prune_cooldowns()
    return _STRATEGY_COOLDOWNS.get(key, 0.0) > time.monotonic()


def _mark_cooldown(key: str, seconds: int = FAILURE_COOLDOWN_SECONDS):
    _STRATEGY_COOLDOWNS[key] = time.monotonic() + seconds


def _clean_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _safe_filename(value: str | None, default: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]+', "_", _clean_text(value) or default).strip(" .")
    return (cleaned or default)[:160]


def _clean_html_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return _clean_text(unescape(text))


def _guess_kind(filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in VIDEO_EXTENSIONS or content_type.startswith("video/"):
        return "video"
    if suffix in PHOTO_EXTENSIONS or content_type.startswith("image/"):
        return "photo"
    if suffix in AUDIO_EXTENSIONS or content_type.startswith("audio/"):
        return "audio"
    return "document"


def _extract_filename(headers: httpx.Headers, url: str, fallback: str) -> str:
    disposition = headers.get("content-disposition") or ""
    match = CONTENT_DISPOSITION_FILENAME.search(disposition)
    if match:
        return _safe_filename(unquote(match.group(1).strip().strip('"')), fallback)

    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if name:
        return _safe_filename(name, fallback)
    return _safe_filename(fallback, "media.bin")


def _validate_source_url(url: str, platform: str) -> str:
    hosts = PLATFORM_HOSTS.get(platform)
    if not hosts:
        raise SocialDownloadError("Unsupported platform.")
    return validate_public_http_url(
        url,
        allowed_hosts=hosts,
        allow_subdomains=True,
    )


def _extract_x_status_id(url: str) -> str:
    match = X_STATUS_PATTERN.search(url)
    if not match:
        raise SocialDownloadError("Invalid X/Twitter status URL.")
    return match.group(1)


def _extract_x_screen_name(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[1].lower() == "status":
        handle = path_parts[0].lstrip("@")
        if handle and handle.lower() != "i":
            return handle
    return ""


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout | float | None = None,
    **kwargs,
):
    if timeout is not None and "timeout" not in kwargs:
        kwargs["timeout"] = timeout
    response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


def _bundle_from_cobalt_payload(payload, source_name: str) -> SocialDownloadBundle | None:
    if not isinstance(payload, dict):
        return None

    status = str(payload.get("status") or "").lower()
    if status == "error":
        error = payload.get("error") or {}
        message = error.get("code") or payload.get("text") or "Downloader API failed."
        raise SocialDownloadError(str(message))

    title = _safe_filename(
        payload.get("filename")
        or (payload.get("output") or {}).get("filename")
        or f"{source_name} Media",
        f"{source_name} Media",
    )

    if status in {"tunnel", "redirect"}:
        media_url = payload.get("url")
        if media_url:
            return SocialDownloadBundle(
                title=title,
                source=source_name,
                items=[SocialMediaItem(url=str(media_url), kind="document", filename_hint=title)],
            )

    if status == "picker":
        picker = payload.get("picker") or []
        items: list[SocialMediaItem] = []
        for item in picker[:MAX_MEDIA_FILES]:
            media_url = item.get("url")
            media_type = str(item.get("type") or "document").lower()
            if media_url:
                items.append(
                    SocialMediaItem(
                        url=str(media_url),
                        kind="video" if media_type in {"video", "gif"} else "photo",
                        filename_hint=title,
                    )
                )
        if items:
            return SocialDownloadBundle(title=title, source=source_name, items=items)

    if status == "local-processing":
        tunnels = payload.get("tunnel") or []
        output = payload.get("output") or {}
        output_name = output.get("filename") or title
        output_type = output.get("type") or ""
        if tunnels:
            return SocialDownloadBundle(
                title=_safe_filename(output_name, title),
                source=source_name,
                items=[
                    SocialMediaItem(
                        url=str(tunnels[0]),
                        kind=_guess_kind(str(output_name), str(output_type)),
                        filename_hint=str(output_name),
                    )
                ],
            )

    return None


def _extract_html_metadata(html: str) -> tuple[str, str, str]:
    snippet = html[:350000]
    metas: dict[str, str] = {}
    for key, value in META_TAG_PATTERN.findall(snippet):
        normalized = str(key or "").strip().lower()
        if normalized and normalized not in metas:
            metas[normalized] = _clean_html_text(value)

    title_match = TITLE_TAG_PATTERN.search(snippet)
    title = (
        metas.get("og:title")
        or metas.get("twitter:title")
        or _clean_html_text(title_match.group(1) if title_match else "")
    )
    description = (
        metas.get("og:description")
        or metas.get("twitter:description")
        or metas.get("description")
    )
    site_name = metas.get("og:site_name") or metas.get("application-name") or ""
    return title, description, site_name


async def _build_page_note(client: httpx.AsyncClient, source_url: str) -> str:
    try:
        response = await client.get(
            source_url,
            timeout=API_TIMEOUT,
            headers={
                **HTTP_HEADERS,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response.raise_for_status()
    except Exception:
        return ""

    content_type = str(response.headers.get("content-type") or "").lower()
    if "html" not in content_type:
        return ""

    title, description, site_name = _extract_html_metadata(response.text)
    lines: list[str] = []
    if site_name:
        lines.append(f"Platform: {site_name}")
    lines.append(f"Source URL: {source_url}")
    if title:
        lines.append(f"Title: {title}")
    if description and description != title:
        lines.append("")
        lines.append(description)

    note_text = "\n".join(line for line in lines if line is not None).strip()
    return note_text if len(note_text) >= 20 else ""


def _append_note(bundle: SocialDownloadBundle, note_text: str) -> SocialDownloadBundle:
    note = str(note_text or "").strip()
    if not note:
        return bundle
    if bundle.note_text:
        return bundle
    return SocialDownloadBundle(title=bundle.title, source=bundle.source, items=bundle.items, note_text=note)


async def _build_youtube_oembed_note(client: httpx.AsyncClient, source_url: str) -> str:
    try:
        data = await _request_json(
            client,
            "GET",
            YOUTUBE_OEMBED_URL,
            timeout=API_TIMEOUT,
            headers=HTTP_HEADERS,
            params={"url": source_url, "format": "json"},
        )
    except Exception:
        return ""

    title = _clean_text(data.get("title"))
    author_name = _clean_text(data.get("author_name"))
    author_url = _clean_text(data.get("author_url"))
    provider_name = _clean_text(data.get("provider_name"))
    lines: list[str] = []
    if provider_name:
        lines.append(f"Platform: {provider_name}")
    lines.append(f"Source URL: {source_url}")
    if title:
        lines.append(f"Title: {title}")
    if author_name:
        lines.append(f"Author: {author_name}")
    if author_url:
        lines.append(f"Author URL: {author_url}")
    return "\n".join(lines).strip()


async def _fetch_via_cobalt_api(
    client: httpx.AsyncClient,
    source_url: str,
    *,
    endpoint: str,
    source_name: str,
) -> SocialDownloadBundle:
    payload = {
        "url": source_url,
        "filenameStyle": "pretty",
        "downloadMode": "auto",
        "videoQuality": "1080",
        "youtubeVideoCodec": "h264",
        "youtubeVideoContainer": "mp4",
        "audioFormat": "mp3",
        "youtubeBetterAudio": True,
    }
    data = await _request_json(
        client,
        "POST",
        endpoint,
        timeout=API_TIMEOUT,
        headers={
            **HTTP_HEADERS,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    bundle = _bundle_from_cobalt_payload(data, source_name)
    if bundle:
        return bundle
    raise SocialDownloadError(f"{source_name} returned no downloadable media.")


async def _get_tracker_instances(client: httpx.AsyncClient) -> list[dict]:
    global _TRACKER_CACHE, _TRACKER_CACHE_AT
    now = time.monotonic()
    if _TRACKER_CACHE and now - _TRACKER_CACHE_AT < TRACKER_CACHE_TTL_SECONDS:
        return _TRACKER_CACHE

    tracker = await _request_json(
        client,
        "GET",
        COBALT_INSTANCE_TRACKER_URL,
        timeout=API_TIMEOUT,
        headers=HTTP_HEADERS,
    )
    if not isinstance(tracker, list):
        raise SocialDownloadError("Cobalt tracker returned an unexpected response.")

    tracker.sort(key=lambda item: int((item or {}).get("score") or 0), reverse=True)
    _TRACKER_CACHE = tracker
    _TRACKER_CACHE_AT = now
    return tracker


async def _fetch_via_tracker_instances(
    client: httpx.AsyncClient,
    source_url: str,
    *,
    platform: str,
    excluded_endpoints: set[str] | None = None,
) -> SocialDownloadBundle:
    excluded = {item.rstrip("/") for item in (excluded_endpoints or set())}
    tracker = await _get_tracker_instances(client)
    failures: list[str] = []
    tried = 0

    for item in tracker:
        if not isinstance(item, dict):
            continue
        if not item.get("online"):
            continue
        info = item.get("info") or {}
        if info.get("auth"):
            continue

        services = item.get("services") or {}
        service_key = PLATFORM_SERVICE_KEYS.get(platform, platform)
        if not _service_works(services.get(service_key)):
            continue

        proto = str(item.get("protocol") or "https").strip()
        api_host = str(item.get("api") or "").strip().strip("/")
        if not api_host:
            continue

        endpoint_candidates = [
            f"{proto}://{api_host}",
            f"{proto}://{api_host}/api/json",
        ]
        for endpoint in endpoint_candidates:
            normalized = endpoint.rstrip("/")
            if normalized in excluded:
                continue
            if _on_cooldown(f"tracker:{normalized}"):
                continue
            tried += 1
            try:
                return await _fetch_via_cobalt_api(
                    client,
                    source_url,
                    endpoint=endpoint,
                    source_name=f"Public Instance {api_host}",
                )
            except Exception as exc:
                _mark_cooldown(f"tracker:{normalized}")
                failures.append(f"{api_host}: {exc}")
            if tried >= 4:
                break
        if tried >= 4:
            break

    details = "\n".join(failures[:3])
    raise SocialDownloadError(details or "No public no-auth cobalt instance responded.")


def _bundle_from_fixtweet_payload(data, endpoint_name: str, status_id: str) -> SocialDownloadBundle:
    if int(data.get("code") or 0) != 200:
        raise SocialDownloadError(str(data.get("message") or f"{endpoint_name} lookup failed."))

    tweet = data.get("tweet") or {}
    media = tweet.get("media") or {}
    author = tweet.get("author") or {}
    title = _safe_filename(tweet.get("text") or f"X {status_id}", f"X {status_id}")
    raw_text = (
        ((tweet.get("raw_text") or {}).get("text"))
        or tweet.get("text")
        or ""
    ).strip()
    author_name = _clean_text(author.get("name")) or "Unknown"
    author_handle = _clean_text(author.get("screen_name"))
    author_line = author_name
    if author_handle:
        author_line += f" (@{author_handle})"
    post_url = _clean_text(tweet.get("url")) or f"https://x.com/i/status/{status_id}"
    note_text = (
        f"Author: {author_line}\n"
        f"Post URL: {post_url}\n\n"
        f"{raw_text}\n"
    ).strip() if raw_text else ""
    items: list[SocialMediaItem] = []
    seen_urls: set[str] = set()

    def add_item(media_url: str | None, kind: str):
        url = str(media_url or "").strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        items.append(SocialMediaItem(url=url, kind=kind, filename_hint=title))

    for photo in media.get("photos") or []:
        add_item(photo.get("url"), "photo")

    for video in media.get("videos") or []:
        add_item(video.get("url"), "video")

    for item in media.get("all") or []:
        media_type = str(item.get("type") or "document").lower()
        add_item(item.get("url"), "video" if media_type == "video" else "photo")

    external = media.get("external") or {}
    add_item(external.get("url"), "video")

    if not items:
        if raw_text:
            return SocialDownloadBundle(
                title=title,
                source=endpoint_name,
                items=[
                    SocialMediaItem(
                        url="",
                        kind="text",
                        filename_hint=f"{title}.txt",
                        content=note_text,
                    )
                ],
                note_text=note_text,
            )
        raise SocialDownloadError(f"No direct media found in that X post via {endpoint_name}.")
    return SocialDownloadBundle(
        title=title,
        source=endpoint_name,
        items=items[:MAX_MEDIA_FILES],
        note_text=note_text,
    )


async def _fetch_x_via_fixtweet(
    client: httpx.AsyncClient,
    source_url: str,
    *,
    screen_name: str | None = None,
) -> SocialDownloadBundle:
    status_id = _extract_x_status_id(source_url)
    endpoint = f"{FIXTWEET_API_URL}/i/status/{status_id}"
    if screen_name:
        endpoint = f"{FIXTWEET_API_URL}/{screen_name}/status/{status_id}"
    data = await _request_json(
        client,
        "GET",
        endpoint,
        timeout=API_TIMEOUT,
        headers=HTTP_HEADERS,
    )
    return _bundle_from_fixtweet_payload(data, "FixTweet", status_id)


async def _fetch_x_via_fixtweet_video(
    client: httpx.AsyncClient,
    source_url: str,
) -> SocialDownloadBundle:
    status_id = _extract_x_status_id(source_url)
    data = await _request_json(
        client,
        "GET",
        f"{FIXTWEET_API_URL}/video/status/{status_id}",
        timeout=API_TIMEOUT,
        headers=HTTP_HEADERS,
    )
    return _bundle_from_fixtweet_payload(data, "FixTweet Video", status_id)


async def _fetch_x_via_oembed(
    client: httpx.AsyncClient,
    source_url: str,
) -> SocialDownloadBundle:
    data = await _request_json(
        client,
        "GET",
        X_OEMBED_URL,
        timeout=API_TIMEOUT,
        headers=HTTP_HEADERS,
        params={"url": source_url, "omit_script": 1, "dnt": 1},
    )
    author_name = _clean_text(data.get("author_name")) or "Unknown"
    post_url = _clean_text(data.get("url")) or source_url
    html = str(data.get("html") or "")
    text_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    post_text = _clean_html_text(text_match.group(1) if text_match else "")
    title = _safe_filename(post_text or f"X {post_url.rsplit('/', 1)[-1]}", "X Post")
    note_text = (
        f"Author: {author_name}\n"
        f"Post URL: {post_url}\n\n"
        f"{post_text}\n"
    ).strip()
    if not post_text:
        raise SocialDownloadError("X oEmbed returned no readable post text.")
    return SocialDownloadBundle(
        title=title,
        source="X oEmbed",
        items=[
            SocialMediaItem(
                url="",
                kind="text",
                filename_hint=f"{title}.txt",
                content=note_text,
            )
        ],
        note_text=note_text,
    )


async def _fetch_tiktok_via_tikwm(
    client: httpx.AsyncClient,
    source_url: str,
) -> SocialDownloadBundle:
    response = await client.post(
        TIKWM_API_URL,
        timeout=API_TIMEOUT,
        headers={
            **HTTP_HEADERS,
            "User-Agent": "Mozilla/5.0",
        },
        data={"url": source_url},
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get("code") or -1) != 0:
        raise SocialDownloadError(str(payload.get("msg") or "TikWM lookup failed."))

    data = payload.get("data") or {}
    title = _safe_filename(data.get("title") or "TikTok Video", "TikTok Video")
    author = data.get("author") or {}
    author_name = _clean_text(author.get("nickname"))
    author_handle = _clean_text(author.get("unique_id"))
    author_line = author_name or "Unknown"
    if author_handle:
        author_line += f" (@{author_handle})"
    duration = data.get("duration")
    note_lines = [
        f"Author: {author_line}",
        f"Post URL: {source_url}",
    ]
    if duration:
        note_lines.append(f"Duration: {duration}s")
    if title:
        note_lines.extend(["", title])
    note_text = "\n".join(note_lines).strip()

    items: list[SocialMediaItem] = []
    images = data.get("images") or []
    for image_url in images[:MAX_MEDIA_FILES]:
        if image_url:
            items.append(
                SocialMediaItem(
                    url=str(image_url),
                    kind="photo",
                    filename_hint=title,
                )
            )

    play_url = str(data.get("play") or "").strip()
    wmplay_url = str(data.get("wmplay") or "").strip()
    music_url = str(data.get("music") or "").strip()

    if not items:
        if play_url:
            items.append(SocialMediaItem(url=play_url, kind="video", filename_hint=title))
        elif wmplay_url:
            items.append(SocialMediaItem(url=wmplay_url, kind="video", filename_hint=title))

    if not items and music_url:
        items.append(SocialMediaItem(url=music_url, kind="audio", filename_hint=title))

    if not items:
        raise SocialDownloadError("TikWM returned no downloadable TikTok media.")

    return SocialDownloadBundle(
        title=title,
        source="TikWM",
        items=items[:MAX_MEDIA_FILES],
        note_text=note_text,
    )


async def get_social_bundle(platform: str, url: str) -> SocialDownloadBundle:
    safe_url = _validate_source_url(url, platform)
    failures: list[str] = []
    screen_name = _extract_x_screen_name(safe_url) if platform == "x" else ""

    async with httpx.AsyncClient(
        timeout=API_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        strategies = []
        if platform == "x":
            if screen_name:
                strategies.append(
                    (
                        "FixTweet",
                        f"fixtweet:{screen_name}",
                        lambda: _fetch_x_via_fixtweet(
                            client,
                            safe_url,
                            screen_name=screen_name,
                        ),
                    )
                )
            strategies.extend(
                [
                    ("FixTweet", "fixtweet:generic", lambda: _fetch_x_via_fixtweet(client, safe_url)),
                    ("FixTweet Video", "fixtweet:video", lambda: _fetch_x_via_fixtweet_video(client, safe_url)),
                    ("X oEmbed", "x:oembed", lambda: _fetch_x_via_oembed(client, safe_url)),
                ]
            )
        elif platform == "tiktok":
            strategies.append(
                ("TikWM", "tiktok:tikwm", lambda: _fetch_tiktok_via_tikwm(client, safe_url))
            )

        strategies.extend(
            [
                (
                    "Pybalt",
                    "cobalt:pybalt",
                    lambda: _fetch_via_cobalt_api(
                        client,
                        safe_url,
                        endpoint=PYBALT_API_URL,
                        source_name="Pybalt",
                    ),
                ),
                (
                    "Public Cobalt Pool",
                    "cobalt:tracker_pool",
                    lambda: _fetch_via_tracker_instances(
                        client,
                        safe_url,
                        platform=platform,
                        excluded_endpoints={PYBALT_API_URL, LEGACY_COBALT_API_URL},
                    ),
                ),
                (
                    "Legacy API",
                    "cobalt:legacy",
                    lambda: _fetch_via_cobalt_api(
                        client,
                        safe_url,
                        endpoint=LEGACY_COBALT_API_URL,
                        source_name="Legacy API",
                    ),
                ),
            ]
        )

        for label, cooldown_key, runner in strategies:
            if _on_cooldown(cooldown_key):
                continue
            try:
                bundle = await runner()
                if platform == "youtube":
                    bundle = _append_note(bundle, await _build_youtube_oembed_note(client, safe_url))
                elif platform != "x":
                    bundle = _append_note(bundle, await _build_page_note(client, safe_url))
                return bundle
            except Exception as exc:
                _mark_cooldown(cooldown_key)
                failures.append(f"{label}: {exc}")

        page_note = await _build_page_note(client, safe_url)
        if page_note:
            fallback_title = _safe_filename(
                page_note.splitlines()[0].replace("Title: ", "").replace("Platform: ", "") or f"{platform.title()} Post",
                f"{platform.title()} Post",
            )
            return SocialDownloadBundle(
                title=fallback_title,
                source="Page Metadata",
                items=[
                    SocialMediaItem(
                        url="",
                        kind="text",
                        filename_hint=f"{fallback_title}.txt",
                        content=page_note,
                    )
                ],
                note_text=page_note,
            )

    details = "\n".join(failures[:3])
    raise SocialDownloadError(
        "Downloader services are temporarily unavailable.\n"
        f"{details}"
    )


async def download_bundle_files(bundle: SocialDownloadBundle) -> tuple[str, list[tuple[str, str]]]:
    temp_dir = tempfile.mkdtemp(prefix="vivaan_social_")
    downloads: list[tuple[str, str]] = []

    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        try:
            for index, item in enumerate(bundle.items[:MAX_MEDIA_FILES], start=1):
                if item.kind == "text" and item.content:
                    filename = _safe_filename(
                        item.filename_hint or f"{bundle.title}_{index}.txt",
                        f"{bundle.title}_{index}.txt",
                    )
                    if not filename.lower().endswith(".txt"):
                        filename += ".txt"
                    file_path = os.path.join(temp_dir, filename)
                    with open(file_path, "w", encoding="utf-8") as handle:
                        handle.write(item.content)
                    downloads.append((file_path, "document"))
                    continue

                safe_remote = validate_public_http_url(item.url, allow_subdomains=True)
                async with client.stream("GET", safe_remote) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length") or 0)
                    if total_size and total_size > MAX_DOWNLOAD_BYTES:
                        raise SocialDownloadError("Remote media is too large to send.")

                    fallback_name = f"{bundle.title}_{index}"
                    filename = _extract_filename(response.headers, safe_remote, fallback_name)
                    file_path = os.path.join(temp_dir, filename)

                    downloaded = 0
                    with open(file_path, "wb") as handle:
                        async for chunk in response.aiter_bytes(65536):
                            if not chunk:
                                continue
                            downloaded += len(chunk)
                            if downloaded > MAX_DOWNLOAD_BYTES:
                                raise SocialDownloadError("Downloaded media is too large to send.")
                            handle.write(chunk)

                    media_kind = item.kind
                    if media_kind == "document":
                        media_kind = _guess_kind(
                            filename,
                            str(response.headers.get("content-type") or ""),
                        )
                    downloads.append((file_path, media_kind))

            if not downloads:
                raise SocialDownloadError("No media could be downloaded from that link.")
            return temp_dir, downloads
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

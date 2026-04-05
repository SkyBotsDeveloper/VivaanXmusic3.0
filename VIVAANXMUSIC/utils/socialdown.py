from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
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


@dataclass(slots=True)
class SocialDownloadBundle:
    title: str
    source: str
    items: list[SocialMediaItem]


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
    title = _safe_filename(tweet.get("text") or f"X {status_id}", f"X {status_id}")
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
        raise SocialDownloadError(f"No direct media found in that X post via {endpoint_name}.")
    return SocialDownloadBundle(title=title, source=endpoint_name, items=items[:MAX_MEDIA_FILES])


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
                ]
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
                return await runner()
            except Exception as exc:
                _mark_cooldown(cooldown_key)
                failures.append(f"{label}: {exc}")

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

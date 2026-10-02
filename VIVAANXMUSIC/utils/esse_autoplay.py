"""Small, fail-safe client for ESSE autoplay recommendations."""

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import httpx
from config import ESSE_API_KEY, ESSE_API_URL, ESSE_TIMEOUT

logger = logging.getLogger(__name__)


def is_playable_autoplay_metadata(
    title, videoid, duration_sec, thumbnail, current_videoid, duration_limit, max_duration
):
    return bool(
        isinstance(title, str)
        and title.strip()
        and isinstance(videoid, str)
        and videoid.strip()
        and videoid != current_videoid
        and isinstance(duration_sec, int)
        and duration_sec > 0
        and duration_sec <= duration_limit
        and (not max_duration or duration_sec <= max_duration)
        and isinstance(thumbnail, str)
        and thumbnail.strip()
    )


def _configuration():
    api_key = (ESSE_API_KEY or "").strip()
    base_url = (ESSE_API_URL or "").strip().rstrip("/")
    try:
        timeout = float(ESSE_TIMEOUT)
        if timeout <= 0:
            timeout = 20.0
    except (TypeError, ValueError):
        timeout = 20.0
    return api_key, base_url, timeout


def is_configured():
    return bool(ESSE_API_KEY and ESSE_API_KEY.strip())


async def get_recommendations(song: str, artist: Optional[str] = None):
    """Return validated public ESSE candidates, or None on any safe failure."""
    api_key, base_url, timeout = _configuration()
    if not api_key or not song or not base_url:
        return None

    body = {"song": song, "limit": 5}
    if artist:
        body["artist"] = artist

    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{base_url}/v1/recommend",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("ESSE autoplay unavailable (HTTP %s)", exc.response.status_code)
        return None
    except (httpx.TimeoutException, TimeoutError):
        logger.warning("ESSE autoplay unavailable (timeout)")
        return None
    except (httpx.HTTPError, ValueError):
        logger.warning("ESSE autoplay unavailable (network or invalid JSON)")
        return None
    except Exception:
        logger.warning("ESSE autoplay unavailable (request failure)")
        return None

    if not isinstance(payload, dict):
        logger.warning("ESSE autoplay unavailable (invalid response)")
        return None
    recommendations = payload.get("recommendations")
    count = payload.get("count")
    seed = payload.get("seed")
    if (
        not isinstance(seed, dict)
        or not isinstance(seed.get("title"), str)
        or not seed["title"].strip()
        or not isinstance(recommendations, list)
        or len(recommendations) > 5
        or type(count) is not int
        or count != len(recommendations)
    ):
        logger.warning("ESSE autoplay unavailable (invalid response)")
        return None

    clean = []
    for item in recommendations:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("title"), str)
            or not item["title"].strip()
            or not isinstance(item.get("artist"), str)
            or not item["artist"].strip()
        ):
            logger.warning("ESSE autoplay unavailable (invalid recommendation)")
            return None
        clean.append({"title": item["title"].strip(), "artist": item["artist"].strip()})
    return clean


async def select_playable_recommendation(
    song: str,
    artist: Optional[str],
    resolver: Callable[[dict], Awaitable[Optional[dict]]],
):
    """Try ESSE candidates in rank order; unresolved items leave fallback to caller."""
    recommendations = await get_recommendations(song, artist)
    for recommendation in recommendations or []:
        try:
            track = await resolver(recommendation)
        except Exception:
            logger.warning("ESSE autoplay candidate could not be resolved")
            continue
        if track:
            return track
    return None


async def select_or_fallback(song, artist, resolver, fallback):
    """Keep playback available when ESSE or YouTube resolution cannot help."""
    try:
        track = await select_playable_recommendation(song, artist, resolver)
    except Exception:
        logger.warning("ESSE autoplay unavailable; using legacy autoplay")
        track = None
    if track:
        return track
    return await fallback()

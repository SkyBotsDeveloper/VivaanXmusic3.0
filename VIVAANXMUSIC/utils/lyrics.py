from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import quote

import httpx


HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
HTTP_HEADERS = {"User-Agent": "VivaanXLyrics/1.0"}
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRCLIB_GET_URL = "https://lrclib.net/api/get"
LYRICS_OVH_SUGGEST_URL = "https://api.lyrics.ovh/suggest/"
LYRICS_OVH_LYRICS_URL = "https://api.lyrics.ovh/v1"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

MAX_SEARCH_RESULTS = 10
SOURCE_BASE_SCORES = {
    "lrclib": 95.0,
    "lyricsovh": 82.0,
    "itunes": 68.0,
}
BRACKET_PATTERN = re.compile(r"[\(\[\{].*?[\)\]\}]")
SPACE_PATTERN = re.compile(r"\s+")
NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
FEAT_SPLIT_PATTERN = re.compile(r"\b(?:feat\.?|ft\.?|featuring|with)\b", re.IGNORECASE)


class LyricsError(RuntimeError):
    pass


@dataclass(slots=True)
class LyricsCandidate:
    title: str
    artist: str
    album: str = ""
    source: str = ""
    source_id: str | None = None
    preview_url: str | None = None
    link: str | None = None
    plain_lyrics: str = ""
    popularity: float = 0.0
    instrumental: bool = False
    score: float = 0.0


@dataclass(slots=True)
class LyricsResult:
    title: str
    artist: str
    album: str
    lyrics: str
    source: str


def _clean_text(value: str | None) -> str:
    return SPACE_PATTERN.sub(" ", str(value or "").strip())


def _clean_lyrics_text(value: str | None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [SPACE_PATTERN.sub(" ", line).strip() for line in text.split("\n")]
    merged = "\n".join(line for line in lines).strip()
    return re.sub(r"\n{3,}", "\n\n", merged)


def _normalize_key(value: str | None) -> str:
    text = _clean_text(value).lower()
    text = BRACKET_PATTERN.sub(" ", text)
    text = NON_WORD_PATTERN.sub(" ", text)
    return SPACE_PATTERN.sub(" ", text).strip()


def _compact_title(value: str | None) -> str:
    text = _clean_text(value)
    text = BRACKET_PATTERN.sub(" ", text)
    return SPACE_PATTERN.sub(" ", text).strip(" -")


def _primary_artist(value: str | None) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    parts = FEAT_SPLIT_PATTERN.split(text, maxsplit=1)
    cleaned = parts[0].strip(" ,-/")
    return cleaned or text


def _tokenize_query(query: str) -> list[str]:
    return [part for part in _normalize_key(query).split() if len(part) > 2]


def _query_variants(query: str) -> list[str]:
    cleaned = _clean_text(query)
    tokens = _tokenize_query(cleaned)
    variants: list[str] = []

    def add(value: str):
        value = _clean_text(value)
        if value and value not in variants:
            variants.append(value)

    add(cleaned)
    if len(tokens) >= 4:
        add(" ".join(tokens[:5]))
    if len(tokens) >= 6:
        add(" ".join(tokens[-5:]))
    if len(tokens) >= 8:
        mid = max(0, (len(tokens) // 2) - 2)
        add(" ".join(tokens[mid : mid + 5]))
    return variants[:3]


def _best_texts(candidate: LyricsCandidate) -> tuple[str, str]:
    title = _compact_title(candidate.title)
    artist = _primary_artist(candidate.artist)
    return title or candidate.title, artist or candidate.artist


def _text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _score_candidate(query: str, candidate: LyricsCandidate, index: int) -> float:
    query_key = _normalize_key(query)
    query_tokens = _tokenize_query(query)
    title_key = _normalize_key(candidate.title)
    artist_key = _normalize_key(candidate.artist)
    album_key = _normalize_key(candidate.album)
    text_blob = " ".join(part for part in (title_key, artist_key, album_key) if part)
    lyrics_key = _normalize_key(candidate.plain_lyrics[:800] if candidate.plain_lyrics else "")
    title_similarity = _text_similarity(query_key, title_key)
    blob_similarity = _text_similarity(query_key, text_blob)

    score = SOURCE_BASE_SCORES.get(candidate.source, 50.0) - float(index * 2)
    popularity_multiplier = 0.0

    if query_key and query_key in title_key:
        score += 140
    elif query_key and query_key in text_blob:
        score += 90

    if query_key and lyrics_key and query_key in lyrics_key:
        score += 180

    if query_tokens:
        title_hits = sum(1 for token in query_tokens if token in title_key)
        text_hits = sum(1 for token in query_tokens if token in text_blob)
        lyrics_hits = sum(1 for token in query_tokens if token in lyrics_key)
        score += title_hits * 18
        score += max(0, text_hits - title_hits) * 8
        score += lyrics_hits * 6
        if title_hits == len(query_tokens):
            score += 65
        elif text_hits == len(query_tokens):
            score += 28

        if len(query_tokens) >= 5 and candidate.source == "lyricsovh":
            score += 150
        if len(query_tokens) >= 5 and lyrics_hits >= max(2, len(query_tokens) // 2):
            score += 45
        popularity_multiplier = max(
            title_hits / len(query_tokens),
            (text_hits / len(query_tokens)) * 0.85,
            title_similarity,
            blob_similarity * 0.7,
        )

    score += title_similarity * 45
    score += blob_similarity * 18
    if candidate.popularity > 0 and popularity_multiplier >= 0.2:
        score += (min(candidate.popularity, 900000.0) / 1500.0) * popularity_multiplier
    if candidate.instrumental:
        score -= 90
    if not artist_key:
        score -= 70
    if candidate.source == "lrclib" and not candidate.plain_lyrics:
        score -= 35
    return score


async def _request_json(client: httpx.AsyncClient, url: str, **kwargs):
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


async def _search_lrclib(client: httpx.AsyncClient, query: str) -> list[LyricsCandidate]:
    payload = await _request_json(
        client,
        LRCLIB_SEARCH_URL,
        params={"q": query},
    )
    candidates: list[LyricsCandidate] = []
    for item in payload[:12]:
        candidates.append(
            LyricsCandidate(
                title=_clean_text(item.get("trackName") or item.get("name")),
                artist=_clean_text(item.get("artistName")),
                album=_clean_text(item.get("albumName")),
                source="lrclib",
                source_id=str(item.get("id")) if item.get("id") is not None else None,
                plain_lyrics=_clean_lyrics_text(item.get("plainLyrics")),
                instrumental=bool(item.get("instrumental")),
            )
        )
    return candidates


async def _search_lyricsovh(client: httpx.AsyncClient, query: str) -> list[LyricsCandidate]:
    payload = await _request_json(
        client,
        f"{LYRICS_OVH_SUGGEST_URL}{quote(query)}",
    )
    data = payload.get("data") or []
    candidates: list[LyricsCandidate] = []
    for item in data[:12]:
        artist_data = item.get("artist") or {}
        album_data = item.get("album") or {}
        candidates.append(
            LyricsCandidate(
                title=_clean_text(item.get("title_short") or item.get("title")),
                artist=_clean_text(artist_data.get("name")),
                album=_clean_text(album_data.get("title")),
                source="lyricsovh",
                preview_url=item.get("preview"),
                link=item.get("link"),
                popularity=float(item.get("rank") or 0),
            )
        )
    return candidates


async def _search_itunes(client: httpx.AsyncClient, query: str) -> list[LyricsCandidate]:
    payload = await _request_json(
        client,
        ITUNES_SEARCH_URL,
        params={"term": query, "entity": "song", "limit": 10},
    )
    results = payload.get("results") or []
    candidates: list[LyricsCandidate] = []
    for item in results[:10]:
        candidates.append(
            LyricsCandidate(
                title=_clean_text(item.get("trackName")),
                artist=_clean_text(item.get("artistName")),
                album=_clean_text(item.get("collectionName")),
                source="itunes",
                preview_url=item.get("previewUrl"),
                link=item.get("trackViewUrl"),
            )
        )
    return candidates


def _dedupe_candidates(candidates: Iterable[LyricsCandidate]) -> list[LyricsCandidate]:
    merged: dict[str, LyricsCandidate] = {}
    for candidate in candidates:
        key = f"{_normalize_key(candidate.artist)}|{_normalize_key(candidate.title)}"
        if not key.strip("|"):
            continue

        existing = merged.get(key)
        if not existing:
            merged[key] = candidate
            continue

        if candidate.source == "lrclib" and not existing.source_id and candidate.source_id:
            existing.source_id = candidate.source_id
        if candidate.album and not existing.album:
            existing.album = candidate.album
        if candidate.preview_url and not existing.preview_url:
            existing.preview_url = candidate.preview_url
        if candidate.link and not existing.link:
            existing.link = candidate.link
        if candidate.plain_lyrics and not existing.plain_lyrics:
            existing.plain_lyrics = candidate.plain_lyrics
        if SOURCE_BASE_SCORES.get(candidate.source, 0) > SOURCE_BASE_SCORES.get(existing.source, 0):
            existing.source = candidate.source
    return list(merged.values())


def _is_candidate_relevant(query: str, candidate: LyricsCandidate) -> bool:
    query_key = _normalize_key(query)
    query_tokens = _tokenize_query(query)
    if not query_tokens:
        return True

    title_key = _normalize_key(candidate.title)
    artist_key = _normalize_key(candidate.artist)
    album_key = _normalize_key(candidate.album)
    text_blob = " ".join(part for part in (title_key, artist_key, album_key) if part)
    lyrics_key = _normalize_key(candidate.plain_lyrics[:800] if candidate.plain_lyrics else "")

    token_hits = sum(1 for token in query_tokens if token in text_blob)
    if query_key and (query_key in title_key or query_key in text_blob or query_key in lyrics_key):
        return True
    if token_hits:
        return True
    if len(query_tokens) >= 5 and candidate.source == "lyricsovh":
        return True
    return False


async def search_lyrics_candidates(query: str) -> list[LyricsCandidate]:
    text = _clean_text(query)
    if not text:
        raise LyricsError("Please provide a song name or some lyrics to search.")

    variants = _query_variants(text)
    tasks = []
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        for variant in variants:
            tasks.extend(
                (
                    _search_lrclib(client, variant),
                    _search_lyricsovh(client, variant),
                    _search_itunes(client, variant),
                )
            )
        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

    failures = [str(item) for item in results if isinstance(item, Exception)]
    collected: list[LyricsCandidate] = []
    for item in results:
        if isinstance(item, Exception):
            continue
        collected.extend(item)

    candidates = [
        candidate
        for candidate in _dedupe_candidates(collected)
        if _is_candidate_relevant(text, candidate)
    ]
    for index, candidate in enumerate(candidates):
        candidate.score = _score_candidate(text, candidate, index)

    candidates.sort(key=lambda item: item.score, reverse=True)
    shortlisted = candidates[:MAX_SEARCH_RESULTS]
    if shortlisted:
        return shortlisted

    detail = failures[0] if failures else "No matching songs found."
    raise LyricsError(detail)


async def _lrclib_fetch_by_id(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    if not candidate.source_id:
        return None
    response = await client.get(f"{LRCLIB_GET_URL}/{candidate.source_id}")
    if response.status_code != 200:
        return None
    payload = response.json()
    lyrics = _clean_lyrics_text(payload.get("plainLyrics")) or _clean_lyrics_text(payload.get("syncedLyrics"))
    if not lyrics:
        return None
    return LyricsResult(
        title=_clean_text(payload.get("trackName") or candidate.title),
        artist=_clean_text(payload.get("artistName") or candidate.artist),
        album=_clean_text(payload.get("albumName") or candidate.album),
        lyrics=lyrics,
        source="LRCLIB",
    )


async def _lrclib_fetch_by_names(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    title, artist = _best_texts(candidate)
    if not title or not artist:
        return None

    params = {
        "track_name": title,
        "artist_name": artist,
    }
    album = _compact_title(candidate.album)
    if album:
        params["album_name"] = album

    response = await client.get(LRCLIB_GET_URL, params=params)
    if response.status_code != 200:
        return None
    payload = response.json()
    lyrics = _clean_lyrics_text(payload.get("plainLyrics")) or _clean_lyrics_text(payload.get("syncedLyrics"))
    if not lyrics:
        return None
    return LyricsResult(
        title=_clean_text(payload.get("trackName") or candidate.title),
        artist=_clean_text(payload.get("artistName") or candidate.artist),
        album=_clean_text(payload.get("albumName") or candidate.album),
        lyrics=lyrics,
        source="LRCLIB",
    )


async def _lyricsovh_fetch(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    title_variants = []
    artist_variants = []

    for raw_title in (candidate.title, _compact_title(candidate.title)):
        cleaned = _clean_text(raw_title)
        if cleaned and cleaned not in title_variants:
            title_variants.append(cleaned)

    for raw_artist in (candidate.artist, _primary_artist(candidate.artist)):
        cleaned = _clean_text(raw_artist)
        if cleaned and cleaned not in artist_variants:
            artist_variants.append(cleaned)

    for artist in artist_variants:
        for title in title_variants:
            response = await client.get(
                f"{LYRICS_OVH_LYRICS_URL}/{quote(artist)}/{quote(title)}"
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            lyrics = _clean_lyrics_text(payload.get("lyrics"))
            if not lyrics:
                continue
            return LyricsResult(
                title=title,
                artist=artist,
                album=candidate.album,
                lyrics=lyrics,
                source="Lyrics.ovh",
            )
    return None


async def fetch_lyrics(candidate: LyricsCandidate) -> LyricsResult:
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        for fetcher in (_lrclib_fetch_by_id, _lrclib_fetch_by_names, _lyricsovh_fetch):
            result = await fetcher(client, candidate)
            if result:
                return result

    if candidate.plain_lyrics:
        return LyricsResult(
            title=candidate.title,
            artist=candidate.artist,
            album=candidate.album,
            lyrics=candidate.plain_lyrics,
            source=candidate.source.upper(),
        )

    raise LyricsError("Lyrics are temporarily unavailable for that selection.")

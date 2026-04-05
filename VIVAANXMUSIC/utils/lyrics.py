from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import quote, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from youtubesearchpython.future import VideosSearch


HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRCLIB_GET_URL = "https://lrclib.net/api/get"
LYRICS_OVH_SUGGEST_URL = "https://api.lyrics.ovh/suggest/"
LYRICS_OVH_LYRICS_URL = "https://api.lyrics.ovh/v1"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
LYRICSCOM_SEARCH_URL = "https://www.lyrics.com/lyrics"
DUCKDUCKGO_HTML_SEARCH_URL = "https://html.duckduckgo.com/html/"
LYRICSBOGIE_SEARCH_URL = "https://www.lyricsbogie.com/wp-json/wp/v2/search"

MAX_SEARCH_RESULTS = 10
SOURCE_BASE_SCORES = {
    "lrclib": 95.0,
    "lyricsbogie": 150.0,
    "lyricscom": 88.0,
    "allthelyrics": 86.0,
    "letras": 84.0,
    "lyricsovh": 82.0,
    "youtube": 76.0,
    "itunes": 68.0,
}
BRACKET_PATTERN = re.compile(r"[\(\[\{].*?[\)\]\}]")
SPACE_PATTERN = re.compile(r"\s+")
NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
FEAT_SPLIT_PATTERN = re.compile(r"\b(?:feat\.?|ft\.?|featuring|with)\b", re.IGNORECASE)
YOUTUBE_NOISE_PATTERN = re.compile(
    r"\b(?:official|video|audio|lyrics?|lyrical|fullscreen|4k|hd|hq|remix|status|song|songs|music|feat\.?|ft\.?|prod\.?|visualizer|lofi|slowed|reverb)\b",
    re.IGNORECASE,
)
LYRICS_NOISE_PATTERN = re.compile(
    r"\b(?:lofi|slowed|reverb|remix|cover|version|edit|status|mashup|dj|ai)\b",
    re.IGNORECASE,
)


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
    page_url: str | None = None
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


def _clean_youtube_title(value: str | None) -> str:
    text = _clean_text(value)
    text = BRACKET_PATTERN.sub(" ", text)
    text = YOUTUBE_NOISE_PATTERN.sub(" ", text)
    text = text.replace("|", " ").replace("—", " ").replace("–", " ")
    text = NON_WORD_PATTERN.sub(" ", text.lower())
    return SPACE_PATTERN.sub(" ", text).strip().title()


def _looks_generic_artist(value: str | None) -> bool:
    text = _normalize_key(value)
    if not text:
        return True
    generic_tokens = {
        "lyrics",
        "lyrical",
        "music",
        "official",
        "records",
        "records",
        "video",
        "songs",
        "song",
        "lover",
        "channel",
        "wave",
        "studio",
        "production",
    }
    return any(token in text.split() for token in generic_tokens)


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
    if len(tokens) >= 2:
        add(" ".join(tokens[:2]))
    if len(tokens) >= 3:
        add(" ".join(tokens[:3]))
    if len(tokens) >= 4:
        add(" ".join(tokens[:5]))
    if len(tokens) >= 6:
        add(" ".join(tokens[-5:]))
    if len(tokens) >= 8:
        mid = max(0, (len(tokens) // 2) - 2)
        add(" ".join(tokens[mid : mid + 5]))
    return variants[:5]


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
    title_words = title_key.split()
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

        if len(query_tokens) >= 5 and candidate.source == "lyricsovh" and candidate.plain_lyrics:
            score += 150
        if len(query_tokens) >= 5 and lyrics_hits >= max(2, len(query_tokens) // 2):
            score += 45
        if title_hits >= min(2, len(query_tokens)) and len(title_words) <= 5:
            score += 70
        if title_hits >= 2 and len(title_words) <= 3:
            score += 35
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
    if candidate.source_id:
        score += 55
    if candidate.page_url:
        score += 18
    if candidate.source == "lrclib" and not candidate.plain_lyrics:
        score -= 35
    if candidate.plain_lyrics:
        score += 6
    if LYRICS_NOISE_PATTERN.search(f"{candidate.title} {candidate.artist} {candidate.album}"):
        score -= 120
    return score


async def _request_json(client: httpx.AsyncClient, url: str, **kwargs):
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


async def _request_text(client: httpx.AsyncClient, url: str, **kwargs) -> str:
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response.text


def _soup_text(node) -> str:
    if not node:
        return ""
    for br in node.find_all("br"):
        br.replace_with("\n")
    for block in node.find_all(["p", "div", "li", "pre"]):
        if block.name != "br":
            block.append("\n")
    return _clean_lyrics_text(node.get_text("\n"))


def _normalize_result_url(url: str | None) -> str | None:
    value = _clean_text(url)
    if not value:
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    if "duckduckgo.com/l/?" in value and "uddg=" in value:
        match = re.search(r"[?&]uddg=([^&]+)", value)
        if match:
            value = unquote(match.group(1))
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return value
    return None


async def _fetch_candidate_page(
    client: httpx.AsyncClient,
    url: str,
    source: str,
) -> LyricsCandidate | None:
    page_url = _normalize_result_url(url)
    if not page_url:
        return None

    response = await client.get(page_url)
    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    if source == "allthelyrics":
        title_tag = soup.find("title")
        title_text = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
        artist = ""
        title = title_text
        match = re.match(r"(.+?)\s+[–-]\s+(.+?)\s+\|\s+All The Lyrics", title_text)
        if match:
            artist = _clean_text(match.group(1))
            title = _clean_text(match.group(2))
        lyrics_node = soup.find("div", class_="content-text-inner")
        lyrics = _soup_text(lyrics_node)
        album = ""
        album_node = soup.find("div", class_="content-text-album")
        if album_node:
            album = _clean_text(album_node.get_text(" ", strip=True).replace("Album:", ""))
        if not title or not lyrics:
            return None
        return LyricsCandidate(
            title=title,
            artist=artist,
            album=album,
            source=source,
            page_url=page_url,
            plain_lyrics=lyrics,
        )

    if source == "letras":
        title_tag = soup.find("title")
        title_text = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
        title = ""
        artist = ""
        match = re.match(r"(.+?)\s+-\s+(.+?)\s+-\s+LETRAS\.COM", title_text, re.IGNORECASE)
        if match:
            title = _clean_text(match.group(1))
            artist = _clean_text(match.group(2))
        lyrics_node = soup.find("div", class_="lyric-original")
        lyrics = _soup_text(lyrics_node)
        if not title and not artist:
            og_title = soup.find("meta", attrs={"property": "og:title"})
            og_text = _clean_text(og_title.get("content") if og_title else "")
            match = re.match(r"(.+?)\s+-\s+(.+?)\s+-\s+LETRAS\.COM", og_text, re.IGNORECASE)
            if match:
                title = _clean_text(match.group(1))
                artist = _clean_text(match.group(2))
        if not title or not lyrics:
            return None
        return LyricsCandidate(
            title=title,
            artist=artist,
            source=source,
            page_url=page_url,
            plain_lyrics=lyrics,
        )

    if source == "lyricsbogie":
        title = _clean_text(
            (soup.find("meta", attrs={"property": "og:title"}) or {}).get("content")
        )
        if not title:
            title = _clean_text(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
            title = re.sub(r"\s+Lyrics$", "", title, flags=re.IGNORECASE).strip()

        artist = ""
        subtitle = soup.find("h2", class_="lyrics-subtitle")
        subtitle_text = _clean_text(subtitle.get_text(" ", strip=True) if subtitle else "")
        match = re.match(r".+?Lyrics\s+[–-]\s+(.+)$", subtitle_text, re.IGNORECASE)
        if match:
            artist = _clean_text(match.group(1))

        album = ""
        movie_row = soup.find(string=re.compile(r"Movie:", re.IGNORECASE))
        if movie_row:
            album = _clean_text(str(movie_row).replace("Movie:", ""))

        lyrics_node = soup.select_one("div.wp-block-ub-tabbed-content-tab-content-wrap.active")
        if not lyrics_node:
            lyrics_node = soup.select_one("div.wp-block-ub-tabbed-content-tabs-content")
        if not lyrics_node:
            return None

        lyrics_node = BeautifulSoup(str(lyrics_node), "html.parser")
        for junk in lyrics_node.select("script, style, [rel='domain'], .ad, .code-block"):
            junk.decompose()
        for br in lyrics_node.find_all("br"):
            br.replace_with("\n")

        lyrics = _clean_lyrics_text(
            lyrics_node.get_text("\n").replace("lyricsbogie.com", " ")
        )
        if not title or not lyrics:
            return None
        return LyricsCandidate(
            title=title,
            artist=artist,
            album=album,
            source=source,
            page_url=page_url,
            plain_lyrics=lyrics,
        )

    return None


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


async def _search_youtube_titles(query: str) -> list[LyricsCandidate]:
    results = VideosSearch(query, limit=6)
    data = await results.next()
    candidates: list[LyricsCandidate] = []
    for item in data.get("result") or []:
        raw_title = _clean_text(item.get("title"))
        title = _clean_youtube_title(raw_title)
        artist = _clean_text((item.get("channel") or {}).get("name"))
        if " - " in raw_title:
            left, right = [part.strip() for part in raw_title.split(" - ", 1)]
            clean_left = _clean_youtube_title(left)
            clean_right = _clean_youtube_title(right)
            if clean_left and clean_right:
                title = clean_left
                if not _looks_generic_artist(clean_right):
                    artist = clean_right
        if not title:
            continue
        candidates.append(
            LyricsCandidate(
                title=title,
                artist=artist,
                source="youtube",
                link=item.get("link"),
            )
        )
    return candidates


async def _expand_youtube_candidates(
    client: httpx.AsyncClient,
    query: str,
) -> list[LyricsCandidate]:
    youtube_candidates = await _search_youtube_titles(query)
    expanded: list[LyricsCandidate] = list(youtube_candidates)
    seen_queries: set[str] = set()
    tasks = []

    for candidate in youtube_candidates[:3]:
        parts = [candidate.title]
        if candidate.artist and not _looks_generic_artist(candidate.artist):
            parts.append(candidate.artist)
        search_query = _clean_text(" ".join(parts))
        if not search_query or search_query in seen_queries:
            continue
        seen_queries.add(search_query)
        tasks.extend(
            (
                _search_lrclib(client, search_query),
                _search_lyricsovh(client, search_query),
                _search_itunes(client, search_query),
                _search_lyricscom(client, search_query),
            )
        )

    if not tasks:
        return expanded

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item in results:
        if isinstance(item, Exception):
            continue
        expanded.extend(item)
    return expanded


async def _search_lyricscom(client: httpx.AsyncClient, query: str) -> list[LyricsCandidate]:
    page = await _request_text(
        client,
        f"{LYRICSCOM_SEARCH_URL}/{quote(query)}",
    )
    soup = BeautifulSoup(page, "html.parser")
    candidates: list[LyricsCandidate] = []
    for block in soup.select("div.sec-lyric")[:12]:
        title_link = block.select_one("p.lyric-meta-title a")
        artist_link = block.select_one("p.lyric-meta-album-artist a")
        snippet_node = block.select_one("pre.lyric-body")
        href = title_link.get("href") if title_link else None
        page_url = _normalize_result_url(f"https://www.lyrics.com/{href.lstrip('/')}" if href else "")
        candidates.append(
            LyricsCandidate(
                title=_clean_text(title_link.get_text(" ", strip=True) if title_link else ""),
                artist=_clean_text(artist_link.get_text(" ", strip=True) if artist_link else ""),
                source="lyricscom",
                page_url=page_url,
                plain_lyrics=_clean_lyrics_text(
                    html.unescape(snippet_node.get_text("\n", strip=True) if snippet_node else "")
                ),
            )
        )
    return candidates


async def _search_lyricsbogie(client: httpx.AsyncClient, query: str) -> list[LyricsCandidate]:
    payload = await _request_json(
        client,
        LYRICSBOGIE_SEARCH_URL,
        params={"search": query, "per_page": 8},
    )

    urls: list[str] = []
    for item in payload:
        if item.get("subtype") != "post":
            continue
        title = _clean_text(html.unescape(item.get("title")))
        page_url = _normalize_result_url(item.get("url"))
        if not title or not page_url:
            continue
        if "lyrics" not in title.lower():
            continue
        if page_url not in urls:
            urls.append(page_url)
        if len(urls) >= 4:
            break

    if not urls:
        return []

    fetched = await asyncio.gather(
        *[_fetch_candidate_page(client, page_url, "lyricsbogie") for page_url in urls],
        return_exceptions=True,
    )
    candidates: list[LyricsCandidate] = []
    for item in fetched:
        if isinstance(item, LyricsCandidate):
            candidates.append(item)
    return candidates


async def _search_duckduckgo_site(
    client: httpx.AsyncClient,
    query: str,
    domain: str,
    source: str,
) -> list[LyricsCandidate]:
    page = await _request_text(
        client,
        DUCKDUCKGO_HTML_SEARCH_URL,
        params={"q": f'{query} lyrics site:{domain}'},
    )
    soup = BeautifulSoup(page, "html.parser")
    result_urls: list[str] = []
    for link in soup.select("a.result__a"):
        href = _normalize_result_url(link.get("href"))
        if not href or domain not in href.lower():
            continue
        if href not in result_urls:
            result_urls.append(href)
        if len(result_urls) >= 3:
            break

    if not result_urls:
        return []

    fetched = await asyncio.gather(
        *[_fetch_candidate_page(client, result_url, source) for result_url in result_urls],
        return_exceptions=True,
    )
    candidates: list[LyricsCandidate] = []
    for item in fetched:
        if isinstance(item, LyricsCandidate):
            candidates.append(item)
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
        if candidate.page_url and not existing.page_url:
            existing.page_url = candidate.page_url
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
                    _search_lyricsbogie(client, variant),
                    _search_lyricsovh(client, variant),
                    _search_itunes(client, variant),
                    _search_lyricscom(client, variant),
                )
            )
        tasks.append(_expand_youtube_candidates(client, text))
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


async def _lyricscom_fetch(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    if not candidate.page_url:
        return None
    response = await client.get(candidate.page_url)
    if response.status_code != 200:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    lyrics_node = soup.find("pre", id="lyric-body-text") or soup.find("pre", class_="lyric-body")
    lyrics = _soup_text(lyrics_node)
    if not lyrics:
        return None
    title = candidate.title
    artist = candidate.artist
    if not title or not artist:
        title_tag = soup.find("title")
        title_text = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
        match = re.match(r"(.+?)\s+Lyrics\s+by\s+(.+)", title_text, re.IGNORECASE)
        if match:
            title = title or _clean_text(match.group(1))
            artist = artist or _clean_text(match.group(2))
    return LyricsResult(
        title=title or candidate.title,
        artist=artist or candidate.artist,
        album=candidate.album,
        lyrics=lyrics,
        source="Lyrics.com",
    )


async def _lyricscom_search_fetch(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    parts = [candidate.title]
    if candidate.artist and not _looks_generic_artist(candidate.artist):
        parts.append(candidate.artist)
    query = _clean_text(" ".join(parts))
    if not query:
        return None
    search_results = await _search_lyricscom(client, query)
    if not search_results:
        return None
    for item in search_results[:3]:
        result = await _lyricscom_fetch(client, item)
        if result:
            return result
    return None


async def _lyricsbogie_fetch(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    if not candidate.page_url:
        return None
    refreshed = await _fetch_candidate_page(client, candidate.page_url, "lyricsbogie")
    if not refreshed or not refreshed.plain_lyrics:
        return None
    return LyricsResult(
        title=refreshed.title or candidate.title,
        artist=refreshed.artist or candidate.artist,
        album=refreshed.album or candidate.album,
        lyrics=refreshed.plain_lyrics,
        source="LyricsBogie",
    )


async def _allthelyrics_fetch(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    if candidate.page_url and (candidate.plain_lyrics or candidate.title):
        response = await client.get(candidate.page_url)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        lyrics_node = soup.find("div", class_="content-text-inner")
        lyrics = _soup_text(lyrics_node)
        if not lyrics:
            return None
        title = candidate.title
        artist = candidate.artist
        title_tag = soup.find("title")
        title_text = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
        match = re.match(r"(.+?)\s+[–-]\s+(.+?)\s+\|\s+All The Lyrics", title_text)
        if match:
            artist = artist or _clean_text(match.group(1))
            title = title or _clean_text(match.group(2))
        album = candidate.album
        album_node = soup.find("div", class_="content-text-album")
        if album_node:
            album = _clean_text(album_node.get_text(" ", strip=True).replace("Album:", ""))
        return LyricsResult(
            title=title,
            artist=artist,
            album=album,
            lyrics=lyrics,
            source="All The Lyrics",
        )
    return None


async def _letras_fetch(
    client: httpx.AsyncClient,
    candidate: LyricsCandidate,
) -> LyricsResult | None:
    if not candidate.page_url:
        return None
    response = await client.get(candidate.page_url)
    if response.status_code != 200:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    lyrics_node = soup.find("div", class_="lyric-original")
    lyrics = _soup_text(lyrics_node)
    if not lyrics:
        return None
    title = candidate.title
    artist = candidate.artist
    title_tag = soup.find("title")
    title_text = _clean_text(title_tag.get_text(" ", strip=True) if title_tag else "")
    match = re.match(r"(.+?)\s+-\s+(.+?)\s+-\s+LETRAS\.COM", title_text, re.IGNORECASE)
    if match:
        title = title or _clean_text(match.group(1))
        artist = artist or _clean_text(match.group(2))
    return LyricsResult(
        title=title,
        artist=artist,
        album=candidate.album,
        lyrics=lyrics,
        source="Letras.com",
    )


async def fetch_lyrics(candidate: LyricsCandidate) -> LyricsResult:
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        if candidate.source == "lyricsbogie":
            result = await _lyricsbogie_fetch(client, candidate)
            if result:
                return result
        for fetcher in (
            _lrclib_fetch_by_id,
            _lrclib_fetch_by_names,
            _lyricsbogie_fetch,
            _lyricscom_fetch,
            _lyricscom_search_fetch,
            _allthelyrics_fetch,
            _letras_fetch,
            _lyricsovh_fetch,
        ):
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

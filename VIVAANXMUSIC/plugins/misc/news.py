import html
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from VIVAANXMUSIC import app


NEWS_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
NEWS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}
GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"
)
MAX_RESULTS = 5
FETCH_LIMIT = 25
TRUSTED_SOURCES = {
    "Reuters": 100,
    "Associated Press": 100,
    "AP News": 100,
    "BBC News": 96,
    "NPR": 95,
    "Bloomberg": 95,
    "The Wall Street Journal": 94,
    "WSJ": 94,
    "Financial Times": 94,
    "The New York Times": 93,
    "The Washington Post": 93,
    "CNBC": 91,
    "CNN": 90,
    "CBS News": 90,
    "ABC News": 90,
    "PBS NewsHour": 89,
    "The Guardian": 88,
    "Al Jazeera English": 87,
    "CoinDesk": 84,
    "TechCrunch": 82,
    "The Verge": 81,
    "Ars Technica": 81,
    "The Hindu": 82,
    "The Indian Express": 81,
    "India Today": 79,
    "NDTV": 79,
    "NDTV Profit": 79,
    "Hindustan Times": 78,
    "The Times of India": 77,
    "The Economic Times": 77,
    "Business Standard": 76,
    "Mint": 76,
    "News18": 73,
    "The Tribune India": 72,
}
SOURCE_ALIASES = {
    "BBC": "BBC News",
    "AP": "AP News",
    "Wall Street Journal": "WSJ",
    "Guardian": "The Guardian",
    "BBC.com": "BBC News",
    "The Hindu BusinessLine": "The Hindu",
    "The Economic Times on MSN.com": "The Economic Times",
    "The Times of India on MSN.com": "The Times of India",
}
TRUSTED_QUERY_GROUPS = [
    [
        "Reuters",
        "\"AP News\"",
        "\"BBC News\"",
        "Bloomberg",
        "CNBC",
        "NPR",
        "CNN",
    ],
    [
        "WSJ",
        "\"The New York Times\"",
        "\"The Washington Post\"",
        "\"The Guardian\"",
        "\"CBS News\"",
        "\"ABC News\"",
        "\"PBS NewsHour\"",
    ],
    [
        "CoinDesk",
        "TechCrunch",
        "\"The Verge\"",
        "\"Ars Technica\"",
        "Reuters",
        "Bloomberg",
        "CNBC",
    ],
]
TITLE_SOURCE_SPLIT = re.compile(r"\s+-\s+([^-\n]+)$")
WORD_RE = re.compile(r"[a-z0-9]{3,}")
TOPIC_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "what",
    "when",
    "where",
    "latest",
    "news",
}
COUNTRY_ALIASES = {
    "india": ("en-IN", "IN", "IN:en"),
    "indian": ("en-IN", "IN", "IN:en"),
    "pakistan": ("en-PK", "PK", "PK:en"),
    "pakistani": ("en-PK", "PK", "PK:en"),
    "bangladesh": ("en-BD", "BD", "BD:en"),
    "bangladeshi": ("en-BD", "BD", "BD:en"),
    "nepal": ("en-NP", "NP", "NP:en"),
    "nepali": ("en-NP", "NP", "NP:en"),
    "sri lanka": ("en-LK", "LK", "LK:en"),
    "sri lankan": ("en-LK", "LK", "LK:en"),
    "uae": ("en-AE", "AE", "AE:en"),
    "united arab emirates": ("en-AE", "AE", "AE:en"),
    "saudi arabia": ("en-SA", "SA", "SA:en"),
    "qatar": ("en-QA", "QA", "QA:en"),
    "kuwait": ("en-KW", "KW", "KW:en"),
    "oman": ("en-OM", "OM", "OM:en"),
    "bahrain": ("en-BH", "BH", "BH:en"),
    "united states": ("en-US", "US", "US:en"),
    "usa": ("en-US", "US", "US:en"),
    "america": ("en-US", "US", "US:en"),
    "uk": ("en-GB", "GB", "GB:en"),
    "united kingdom": ("en-GB", "GB", "GB:en"),
    "britain": ("en-GB", "GB", "GB:en"),
    "england": ("en-GB", "GB", "GB:en"),
    "canada": ("en-CA", "CA", "CA:en"),
    "australia": ("en-AU", "AU", "AU:en"),
    "new zealand": ("en-NZ", "NZ", "NZ:en"),
    "singapore": ("en-SG", "SG", "SG:en"),
    "malaysia": ("en-MY", "MY", "MY:en"),
    "philippines": ("en-PH", "PH", "PH:en"),
    "indonesia": ("id", "ID", "ID:id"),
    "japan": ("ja", "JP", "JP:ja"),
    "japanese": ("ja", "JP", "JP:ja"),
    "south korea": ("ko", "KR", "KR:ko"),
    "korea": ("ko", "KR", "KR:ko"),
    "china": ("zh-CN", "CN", "CN:zh-CN"),
    "taiwan": ("zh-TW", "TW", "TW:zh-TW"),
    "hong kong": ("zh-HK", "HK", "HK:zh-HK"),
    "germany": ("de", "DE", "DE:de"),
    "german": ("de", "DE", "DE:de"),
    "france": ("fr", "FR", "FR:fr"),
    "french": ("fr", "FR", "FR:fr"),
    "spain": ("es", "ES", "ES:es"),
    "italy": ("it", "IT", "IT:it"),
    "netherlands": ("nl", "NL", "NL:nl"),
    "sweden": ("sv", "SE", "SE:sv"),
    "norway": ("no", "NO", "NO:no"),
    "denmark": ("da", "DK", "DK:da"),
    "finland": ("fi", "FI", "FI:fi"),
    "ireland": ("en-IE", "IE", "IE:en"),
    "south africa": ("en-ZA", "ZA", "ZA:en"),
    "nigeria": ("en-NG", "NG", "NG:en"),
    "kenya": ("en-KE", "KE", "KE:en"),
    "brazil": ("pt-BR", "BR", "BR:pt-419"),
    "mexico": ("es-419", "MX", "MX:es-419"),
    "argentina": ("es-419", "AR", "AR:es-419"),
    "turkey": ("tr", "TR", "TR:tr"),
    "turkiye": ("tr", "TR", "TR:tr"),
    "russia": ("ru", "RU", "RU:ru"),
    "ukraine": ("uk", "UA", "UA:uk"),
    "poland": ("pl", "PL", "PL:pl"),
    "israel": ("en-IL", "IL", "IL:en"),
}
DEFAULT_LOCALE = ("en-US", "US", "US:en")


@dataclass(slots=True)
class NewsItem:
    title: str
    source: str
    published: str
    sort_key: float
    trusted_weight: int


class NewsFetchError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class NewsLocale:
    hl: str
    gl: str
    ceid: str


def _normalize_source(source: str) -> str:
    cleaned = " ".join(str(source or "").split()).strip()
    return SOURCE_ALIASES.get(cleaned, cleaned)


def _split_title_and_source(raw_title: str) -> tuple[str, str]:
    title = " ".join(str(raw_title or "").split()).strip()
    match = TITLE_SOURCE_SPLIT.search(title)
    if not match:
        return title, ""
    source = _normalize_source(match.group(1))
    headline = title[: match.start()].strip(" -")
    return headline or title, source


def _parse_pub_date(value: str | None) -> tuple[str, float]:
    if not value:
        return "Unknown", 0.0
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=None)
        published = dt.strftime("%d %b %Y %H:%M UTC")
        return published, dt.timestamp()
    except Exception:
        return str(value), 0.0


def _detect_locale(topic: str) -> NewsLocale:
    text = f" {topic.lower()} "
    for alias, config in sorted(COUNTRY_ALIASES.items(), key=lambda item: -len(item[0])):
        if f" {alias} " in text:
            return NewsLocale(*config)
    return NewsLocale(*DEFAULT_LOCALE)


def _query_variants(topic: str) -> list[str]:
    base = " ".join(topic.split()).strip()
    if not base:
        return []
    variants = [
        f"{base} when:7d",
    ]
    for group in TRUSTED_QUERY_GROUPS:
        source_expr = " OR ".join(group)
        variants.append(f"{base} ({source_expr}) when:30d")
        variants.append(f"\"{base}\" ({source_expr}) when:30d")
    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered


def _parse_google_feed(xml_text: str) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    parsed: list[NewsItem] = []
    seen_titles: set[str] = set()
    for item in root.findall("./channel/item"):
        raw_title = item.findtext("title") or ""
        headline, source = _split_title_and_source(raw_title)
        if not headline:
            continue
        key = headline.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        source = source or "Unknown Source"
        published, sort_key = _parse_pub_date(item.findtext("pubDate"))
        parsed.append(
            NewsItem(
                title=headline,
                source=source,
                published=published,
                sort_key=sort_key,
                trusted_weight=TRUSTED_SOURCES.get(source, 0),
            )
        )
        if len(parsed) >= FETCH_LIMIT:
            break
    return parsed


def _topic_tokens(topic: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in WORD_RE.findall(topic.lower()):
        if token in TOPIC_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _relevance_score(item: NewsItem, topic_tokens: list[str]) -> int:
    if not topic_tokens:
        return 0
    haystack = f"{item.title} {item.source}".lower()
    return sum(1 for token in topic_tokens if token in haystack)


def _select_news_items(items: list[NewsItem], topic: str) -> list[NewsItem]:
    topic_tokens = _topic_tokens(topic)
    trusted = [item for item in items if item.trusted_weight > 0]
    trusted.sort(
        key=lambda item: (
            -_relevance_score(item, topic_tokens),
            -item.sort_key,
            -item.trusted_weight,
            item.title.lower(),
        )
    )
    if topic_tokens:
        positive = [item for item in trusted if _relevance_score(item, topic_tokens) > 0]
        if positive:
            trusted = positive
    return trusted[:MAX_RESULTS]


def _select_local_fallback_items(items: list[NewsItem], topic: str) -> list[NewsItem]:
    topic_tokens = _topic_tokens(topic)
    ranked = items[:]
    ranked.sort(
        key=lambda item: (
            -_relevance_score(item, topic_tokens),
            -item.sort_key,
            -item.trusted_weight,
            item.title.lower(),
        )
    )
    if topic_tokens:
        positive = [item for item in ranked if _relevance_score(item, topic_tokens) > 0]
        if positive:
            ranked = positive
    return ranked[:MAX_RESULTS]


async def fetch_latest_news(topic: str) -> list[NewsItem]:
    variants = _query_variants(topic)
    if not variants:
        raise NewsFetchError("Please provide a topic after /news.")

    collected: list[NewsItem] = []
    seen_titles: set[str] = set()
    locale = _detect_locale(topic)
    locale_candidates = [locale]
    default_locale = NewsLocale(*DEFAULT_LOCALE)
    if locale != default_locale:
        locale_candidates.append(default_locale)

    async with httpx.AsyncClient(
        timeout=NEWS_TIMEOUT,
        headers=NEWS_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        for feed_locale in locale_candidates:
            for query in variants:
                url = GOOGLE_NEWS_RSS.format(
                    query=quote_plus(query),
                    hl=feed_locale.hl,
                    gl=feed_locale.gl,
                    ceid=feed_locale.ceid,
                )
                response = await client.get(url)
                response.raise_for_status()
                for item in _parse_google_feed(response.text):
                    key = item.title.lower()
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    collected.append(item)
                if len(_select_news_items(collected, topic)) >= MAX_RESULTS:
                    break
            if len(_select_news_items(collected, topic)) >= MAX_RESULTS:
                break

    selected = _select_news_items(collected, topic)
    if not selected and collected:
        selected = _select_local_fallback_items(collected, topic)
    if not selected:
        raise NewsFetchError(
            "No recent coverage from reliable sources was found for that topic."
        )
    return selected


def build_news_message(topic: str, items: list[NewsItem]) -> str:
    lines = [
        f"📰 <b>Latest News:</b> <code>{html.escape(topic)}</code>",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"<b>{index}. {html.escape(item.title)}</b>")
        lines.append(f"Source: <i>{html.escape(item.source)}</i>")
        lines.append(f"Published: <code>{html.escape(item.published)}</code>")
        lines.append("")
    return "\n".join(lines).strip()


@app.on_message(filters.command("news"))
async def news_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "Please provide a topic.\n\nExample: <code>/news bitcoin</code>",
            parse_mode=ParseMode.HTML,
        )

    topic = message.text.split(maxsplit=1)[1].strip()
    status = await message.reply_text("Fetching the latest news...")

    try:
        items = await fetch_latest_news(topic)
        await status.edit_text(
            build_news_message(topic, items),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except (httpx.HTTPError, ET.ParseError):
        await status.edit_text("Failed to fetch the latest news right now.")
    except NewsFetchError as exc:
        await status.edit_text(str(exc))

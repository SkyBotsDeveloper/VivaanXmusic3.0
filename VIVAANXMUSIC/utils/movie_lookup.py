"""Public movie metadata; no TMDB key or account is required."""

import html
import re

import httpx


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "VivaanXMusicBot/1.0 (https://github.com/SkyBotsDeveloper/VivaanXmusic3.0)"}


def _claim_values(entity, property_id):
    return [
        claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        for claim in entity.get("claims", {}).get(property_id, [])
        if claim.get("rank") != "deprecated"
        and claim.get("mainsnak", {}).get("datavalue", {}).get("value") is not None
    ]


async def _entities(client, ids, props):
    response = await client.get(WIKIDATA_API, params={
        "action": "wbgetentities", "ids": "|".join(ids), "props": props,
        "languages": "en", "format": "json",
    })
    response.raise_for_status()
    return response.json().get("entities", {})


async def get_movie_info(query: str) -> str:
    if not query.strip():
        return "Movie not found."
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20, connect=8), headers=HEADERS,
        follow_redirects=True, trust_env=False,
    ) as client:
        response = await client.get(WIKIPEDIA_API, params={
            "action": "query", "generator": "search", "gsrsearch": f"{query} film",
            "gsrnamespace": 0, "gsrlimit": 5, "prop": "extracts|pageprops",
            "exintro": 1, "explaintext": 1, "exsentences": 6,
            "format": "json", "formatversion": 2,
        })
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise httpx.HTTPError("Movie search is temporarily unavailable.")
        pages = sorted(payload.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
        title_query = re.sub(r"\s*\(?\d{4}\)?$", "", query.strip()).casefold()
        query_words = re.findall(r"\w+", title_query)
        movie = next((page for page in pages
                      if "disambiguation" not in page.get("pageprops", {})
                      and all(word in re.findall(r"\w+", page.get("title", "").casefold()) for word in query_words)
                      and re.search(r"\b(film|movie)\b", page.get("extract", "")[:600], re.I)), None)
        if not movie:
            return "Movie not found."

        entity = {}
        labels = {}
        entity_id = movie.get("pageprops", {}).get("wikibase_item")
        if entity_id:
            try:
                entity = (await _entities(client, [entity_id], "claims|labels")).get(entity_id, {})
                item_ids = [value["id"] for prop in ("P161", "P136")
                            for value in _claim_values(entity, prop)[:5]
                            if isinstance(value, dict) and value.get("id")]
                if item_ids:
                    labels = await _entities(client, list(dict.fromkeys(item_ids)), "labels")
            except (httpx.HTTPError, ValueError):
                # Wikipedia's overview remains usable if optional enrichment fails.
                pass

    def names(prop, limit):
        values = _claim_values(entity, prop)[:limit]
        return ", ".join(labels.get(value.get("id"), {}).get("labels", {}).get("en", {}).get("value", "")
                         for value in values if isinstance(value, dict)
                         and labels.get(value.get("id"), {}).get("labels", {}).get("en", {}).get("value")) or "N/A"

    def escape(value):
        return html.escape(str(value)) if value not in (None, "") else "N/A"

    release = _claim_values(entity, "P577")
    release_date = release[0].get("time", "").lstrip("+").split("T")[0] if release else "N/A"
    runtime = "N/A"
    for value in _claim_values(entity, "P2047"):
        if isinstance(value, dict) and value.get("unit", "").endswith("Q7727"):
            runtime = f"{float(value['amount']):g} min"
            break
    revenue = "Not Available"
    for value in _claim_values(entity, "P2142"):
        if isinstance(value, dict) and value.get("unit", "").endswith("Q4917"):
            revenue = f"${float(value['amount']):,.0f}"
            break
    title = re.sub(r"\s*\((?:\d{4} )?film\)$", "", movie["title"])
    return (
        f"🎬 <b>Title:</b> {escape(title)}\n"
        f"📅 <b>Release Date:</b> {escape(release_date)}\n"
        "⭐ <b>Rating:</b> N/A\n"
        f"🎭 <b>Top Cast:</b> {escape(names('P161', 5))}\n"
        f"🎞 <b>Genres:</b> {escape(names('P136', 3))}\n"
        f"⏱ <b>Runtime:</b> {escape(runtime)}\n"
        f"💰 <b>Box Office:</b> {escape(revenue)}\n\n"
        f"📝 <b>Overview:</b>\n{escape((movie.get('extract') or '')[:2200])}"
    )

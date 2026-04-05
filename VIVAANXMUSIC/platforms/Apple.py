import re
from typing import List, Union, Optional

import aiohttp
from bs4 import BeautifulSoup
from youtubesearchpython.future import VideosSearch


class AppleAPI:
    def __init__(self):
        self.regex = r"^https:\/\/music\.apple\.com\/.+"
        self.base = "https://music.apple.com/in/playlist/"
        self.track_id_regex = re.compile(r"(?:[?&]i=|/song/[^/]+/)(\d+)", re.IGNORECASE)

    async def valid(self, link: str) -> bool:
        return bool(re.search(self.regex, link or ""))

    async def track(self, url: str, playid: Union[bool, str] = None):
        if playid:
            url = self.base + url

        title_query: Optional[str] = None
        track_match = self.track_id_regex.search(url or "")

        async with aiohttp.ClientSession() as session:
            if track_match:
                track_id = track_match.group(1)
                async with session.get(
                    "https://itunes.apple.com/lookup",
                    params={"id": track_id, "entity": "song"},
                ) as response:
                    if response.status == 200:
                        payload = await response.json(content_type=None)
                        results = payload.get("results") or []
                        song = next(
                            (
                                item
                                for item in results
                                if str(item.get("wrapperType") or "").lower() == "track"
                                or str(item.get("kind") or "").lower() == "song"
                            ),
                            None,
                        )
                        if song:
                            track_name = str(song.get("trackName") or "").strip()
                            artist_name = str(song.get("artistName") or "").strip()
                            title_query = f"{track_name} {artist_name}".strip()

            if not title_query:
                async with session.get(url) as response:
                    if response.status != 200:
                        return False
                    html = await response.text()

                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all("meta"):
                    if tag.get("property") == "og:title":
                        title_query = tag.get("content")
                        break

        if not title_query:
            return False

        results = VideosSearch(title_query, limit=1)
        data = await results.next()
        if not data.get("result"):
            return False

        r = data["result"][0]
        track_details = {
            "title": r.get("title", ""),
            "link": r.get("link", ""),
            "vidid": r.get("id", ""),
            "duration_min": r.get("duration"),
            "thumb": r.get("thumbnails", [{}])[0].get("url", "").split("?")[0],
        }
        return track_details, track_details["vidid"]

    async def playlist(self, url: str, playid: Union[bool, str] = None):
        if playid:
            url = self.base + url

        try:
            playlist_id = url.split("playlist/")[1]
        except Exception:
            return False

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return False
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        applelinks = soup.find_all("meta", attrs={"property": "music:song"})
        results: List[str] = []
        for item in applelinks:
            try:
                slug = item["content"].split("album/")[1].split("/")[0]
                results.append(slug.replace("-", " "))
            except Exception:
                continue

        return results, playlist_id

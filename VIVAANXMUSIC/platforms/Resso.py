import re
from typing import Union

import aiohttp
from bs4 import BeautifulSoup
from youtubesearchpython.future import VideosSearch


class RessoAPI:
    def __init__(self):
        self.regex = r"^(https:\/\/m\.resso\.com\/)(.*)$"
        self.base = "https://m.resso.com/"

    async def valid(self, link: str):
        return bool(re.search(self.regex, link or ""))

    async def track(self, url, playid: Union[bool, str] = None):
        if playid:
            url = self.base + url

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return False
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        title = ""
        des = ""
        for tag in soup.find_all("meta"):
            if tag.get("property", None) == "og:title":
                title = str(tag.get("content", None) or "").strip()
            if tag.get("property", None) == "og:description":
                des = str(tag.get("content", None) or "").strip()
                try:
                    des = des.split("·")[0].strip()
                except Exception:
                    pass

        query = f"{title} {des}".strip() or title
        if not query:
            return False

        results = VideosSearch(query, limit=1)
        data = await results.next()
        if not data.get("result"):
            return False

        result = data["result"][0]
        track_details = {
            "title": result["title"],
            "link": result["link"],
            "vidid": result["id"],
            "duration_min": result["duration"],
            "thumb": result["thumbnails"][0]["url"].split("?")[0],
        }
        return track_details, track_details["vidid"]

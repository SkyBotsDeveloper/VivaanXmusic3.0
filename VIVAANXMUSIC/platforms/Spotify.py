import re

import httpx
import spotipy
from bs4 import BeautifulSoup
from spotipy.oauth2 import SpotifyClientCredentials
from youtubesearchpython.future import VideosSearch

import config


SPOTIFY_WEB_HEADERS = {
    "Accept": "text/html,application/json",
    "User-Agent": "Mozilla/5.0",
}


class SpotifyAPI:
    def __init__(self):
        self.regex = r"^https:\/\/open\.spotify\.com\/.+"
        self.client_id = config.SPOTIFY_CLIENT_ID
        self.client_secret = config.SPOTIFY_CLIENT_SECRET
        self.og_title = re.compile(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        self.og_desc = re.compile(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        if self.client_id and self.client_secret:
            self.client_credentials_manager = SpotifyClientCredentials(
                self.client_id, self.client_secret
            )
            self.spotify = spotipy.Spotify(
                client_credentials_manager=self.client_credentials_manager
            )
        else:
            self.spotify = None

    def _resource_id(self, url: str, kind: str) -> str:
        match = re.search(rf"/{kind}/([A-Za-z0-9]+)", url or "")
        return match.group(1) if match else url

    async def _scrape_tracks(self, url: str, *, fallback_artist: str = ""):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
            trust_env=False,
            headers=SPOTIFY_WEB_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        if not fallback_artist:
            og_title = soup.find("meta", attrs={"property": "og:title"})
            fallback_artist = re.sub(
                r"\s*\|\s*Spotify\s*$",
                "",
                str((og_title or {}).get("content") or "").strip(),
                flags=re.IGNORECASE,
            )

        tracks: list[str] = []
        for row in soup.select('[data-testid="track-row"]'):
            title = row.get("aria-label") or ""
            title_node = row.select_one('[data-encore-id="listRowTitle"]')
            if title_node:
                title = title_node.get_text(" ", strip=True) or title
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue

            artists: list[str] = []
            details = row.select_one('[data-encore-id="listRowDetails"]')
            if details:
                for link in details.find_all("a"):
                    artist_name = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
                    if artist_name and artist_name not in artists:
                        artists.append(artist_name)
            if not artists and fallback_artist and "/artist/" in url:
                artists.append(fallback_artist)

            query = f"{title} {' '.join(artists)}".strip()
            if query and query not in tracks:
                tracks.append(query)

        if not tracks:
            raise RuntimeError("Could not resolve Spotify public track list")
        return tracks

    async def valid(self, link: str) -> bool:
        return bool(re.search(self.regex, link or ""))

    async def track(self, link: str):
        info = ""
        if self.spotify:
            try:
                track = self.spotify.track(link)
                info = track["name"]
                for artist in track["artists"]:
                    fetched = f' {artist["name"]}'
                    if "Various Artists" not in fetched:
                        info += fetched
            except Exception:
                info = ""

        if not info:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                trust_env=False,
                headers=SPOTIFY_WEB_HEADERS,
            ) as client:
                try:
                    response = await client.get(
                        "https://open.spotify.com/oembed",
                        params={"url": link},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    title = re.sub(
                        r"\s*\|\s*Spotify\s*$",
                        "",
                        str(payload.get("title") or "").strip(),
                        flags=re.IGNORECASE,
                    )
                    info = re.sub(r"\s+", " ", title).strip()
                except Exception:
                    response = await client.get(link)
                    response.raise_for_status()
                    html = response.text
                    title_match = self.og_title.search(html)
                    desc_match = self.og_desc.search(html)
                    if not title_match:
                        raise RuntimeError("Could not resolve Spotify track details")
                    title = re.sub(r"\s+", " ", title_match.group(1)).strip()
                    artist = ""
                    if desc_match:
                        desc = re.sub(r"\s+", " ", desc_match.group(1)).strip()
                        artist = desc.split("·", 1)[0].strip()
                    info = f"{title} {artist}".strip()

        if not info:
            raise RuntimeError("Could not resolve Spotify track details")

        results = VideosSearch(info, limit=1)
        data = await results.next()
        r = data["result"][0]
        track_details = {
            "title": r["title"],
            "link": r["link"],
            "vidid": r["id"],
            "duration_min": r["duration"],
            "thumb": r["thumbnails"][0]["url"].split("?")[0],
        }
        return track_details, track_details["vidid"]

    async def playlist(self, url):
        playlist_id = self._resource_id(url, "playlist")
        if self.spotify:
            try:
                playlist = self.spotify.playlist(url)
                playlist_id = playlist["id"]
                results = []
                for item in playlist["tracks"]["items"]:
                    music_track = item["track"]
                    info = music_track["name"]
                    for artist in music_track["artists"]:
                        fetched = f' {artist["name"]}'
                        if "Various Artists" not in fetched:
                            info += fetched
                    results.append(info)
                if results:
                    return results, playlist_id
            except Exception:
                pass
        return await self._scrape_tracks(url), playlist_id

    async def album(self, url):
        album_id = self._resource_id(url, "album")
        if self.spotify:
            try:
                album = self.spotify.album(url)
                album_id = album["id"]
                results = []
                for item in album["tracks"]["items"]:
                    info = item["name"]
                    for artist in item["artists"]:
                        fetched = f' {artist["name"]}'
                        if "Various Artists" not in fetched:
                            info += fetched
                    results.append(info)
                if results:
                    return results, album_id
            except Exception:
                pass
        return await self._scrape_tracks(url), album_id

    async def artist(self, url):
        artist_id = self._resource_id(url, "artist")
        if self.spotify:
            try:
                artistinfo = self.spotify.artist(url)
                artist_id = artistinfo["id"]
                results = []
                artisttoptracks = self.spotify.artist_top_tracks(url)
                for item in artisttoptracks["tracks"]:
                    info = item["name"]
                    for artist in item["artists"]:
                        fetched = f' {artist["name"]}'
                        if "Various Artists" not in fetched:
                            info += fetched
                    results.append(info)
                if results:
                    return results, artist_id
            except Exception:
                pass
        return await self._scrape_tracks(url), artist_id

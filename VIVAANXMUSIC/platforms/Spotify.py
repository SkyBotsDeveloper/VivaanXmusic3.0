import re

import httpx
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from youtubesearchpython.future import VideosSearch

import config


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
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                },
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
        if not self.spotify:
            raise RuntimeError("Spotify credentials not configured")
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
        return results, playlist_id

    async def album(self, url):
        if not self.spotify:
            raise RuntimeError("Spotify credentials not configured")
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
        return results, album_id

    async def artist(self, url):
        if not self.spotify:
            raise RuntimeError("Spotify credentials not configured")
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
        return results, artist_id

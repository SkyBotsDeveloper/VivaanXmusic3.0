import asyncio
import json
import os
import re
import shlex
from concurrent.futures import ThreadPoolExecutor
from typing import Union
import string
import requests
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from youtubesearchpython.future import VideosSearch
import base64
from VIVAANXMUSIC import LOGGER
from VIVAANXMUSIC.utils.database import is_on_off
from VIVAANXMUSIC.utils.formatters import time_to_seconds
from VIVAANXMUSIC.utils.security import build_subprocess_env
from config import YT_API_KEY, YTPROXY_URL as YTPROXY

logger = LOGGER(__name__)

# Worker fallback API (kept configurable through env for production overrides)
WORKER_FALLBACK_API_URL = os.getenv(
    "WORKER_FALLBACK_API_URL",
    "https://youtubenewapi.skybotsdeveloper.workers.dev",
)
WORKER_FALLBACK_API_KEY = os.getenv("WORKER_FALLBACK_API_KEY", "itsmesid")

def build_yt_dlp_args(args: list[str]) -> list[str]:
    return list(args)


async def check_file_size(link):
    async def get_format_info(link):
        args = build_yt_dlp_args(["yt-dlp"])
        args.extend(["-J", link])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=build_subprocess_env(),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f'Error:\n{stderr.decode()}')
            return None
        return json.loads(stdout.decode())

    def parse_size(formats):
        total_size = 0
        for format in formats:
            if 'filesize' in format:
                total_size += format['filesize']
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None
    
    formats = info.get('formats', [])
    if not formats:
        print("No formats found.")
        return None
    
    total_size = parse_size(formats)
    return total_size

async def shell_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        args = [str(item) for item in cmd]
    else:
        args = shlex.split(str(cmd))
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=build_subprocess_env(),
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self.dl_stats = {
            "total_requests": 0,
            "okflix_downloads": 0,
            "cookie_downloads": 0,
            "existing_files": 0
        }

    def _has_disallowed_url_chars(self, link: str) -> bool:
        return any(char in link for char in [";", "&", "|", "$", "\n", "\r", "`"])


    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]


        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
            
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        args = build_yt_dlp_args(["yt-dlp"])
        args.extend(
            [
                "-g",
                "-f",
                "best[height<=?720][width<=?1280]",
                f"{link}",
            ]
        )
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=build_subprocess_env(),
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        if self._has_disallowed_url_chars(link):
            return []
        args = build_yt_dlp_args(
            [
                "yt-dlp",
                "-i",
                "--get-id",
                "--flat-playlist",
                "--playlist-end",
                str(limit),
                "--skip-download",
                link,
            ]
        )
        playlist = await shell_cmd(args)
        try:
            result = playlist.split("\n")
            for key in result:
                if key == "":
                    result.remove(key)
        except:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except:
                    continue
                if not "dash" in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        try:
            results = []
            search = VideosSearch(link, limit=10)
            search_results = (await search.next()).get("result", [])

            # Filter videos longer than 1 hour
            for result in search_results:
                duration_str = result.get("duration", "0:00")
                try:
                    parts = duration_str.split(":")
                    duration_secs = 0
                    if len(parts) == 3:
                        duration_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration_secs = int(parts[0]) * 60 + int(parts[1])

                    if duration_secs <= 3600:
                        results.append(result)
                except (ValueError, IndexError):
                    continue

            if not results or query_type >= len(results):
                raise ValueError("No suitable videos found within duration limit")

            selected = results[query_type]
            return (
                selected["title"],
                selected["duration"],
                selected["thumbnails"][0]["url"].split("?")[0],
                selected["id"]
            )

        except Exception as e:
            LOGGER(__name__).error(f"Error in slider: {str(e)}")
            raise ValueError("Failed to fetch video details")

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            vid_id = link
            link = self.base + link
        loop = asyncio.get_running_loop()

        def create_session():
            session = requests.Session()
            retries = Retry(total=3, backoff_factor=0.1)
            session.mount('http://', HTTPAdapter(max_retries=retries))
            session.mount('https://', HTTPAdapter(max_retries=retries))
            return session

        async def download_with_ytdlp(url, filepath, headers=None, max_retries=3):
            default_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.youtube.com/",
            }
            merged_headers = default_headers.copy()
            if headers:
                merged_headers.update(headers)

            # yt-dlp handles direct media URLs, reuse the running loop to avoid blocking the event loop.
            def run_download():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "outtmpl": filepath,
                    "force_overwrites": True,
                    "nopart": True,
                    "retries": max_retries,
                    "http_headers": merged_headers,
                    "concurrent_fragment_downloads": 8,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                await loop.run_in_executor(None, run_download)
                if os.path.exists(filepath):
                    return filepath
            except Exception as e:
                logger.error(f"yt-dlp download failed: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None

        async def download_with_requests_fallback(url, filepath, headers=None):
            session = None
            try:
                session = create_session()
                
                # Use headers for authentication (including x-api-key)
                response = session.get(url, headers=headers, stream=True, timeout=60)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                chunk_size = 1024 * 1024 
                
                with open(filepath, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)
                
                return filepath
                
            except Exception as e:
                logger.error(f"Requests download failed: {str(e)}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return None
            finally:
                if session:
                    session.close()

        async def download_from_source(url, filepath, headers=None):
            result = await download_with_ytdlp(url, filepath, headers)
            if result:
                return result
            return await download_with_requests_fallback(url, filepath, headers)

        def fetch_worker_fallback_link_sync(vid_id, media_format):
            if not WORKER_FALLBACK_API_URL or not WORKER_FALLBACK_API_KEY:
                logger.warning("Worker fallback API URL/key not set. Skipping worker fallback.")
                return None

            session = None
            try:
                session = create_session()
                api_url = f"{WORKER_FALLBACK_API_URL.rstrip('/')}/api"
                payload = {
                    "key": WORKER_FALLBACK_API_KEY,
                    "url": f"https://youtube.com/watch?v={vid_id}",
                    "format": media_format,
                }

                response = session.get(api_url, params=payload, timeout=75)
                response.raise_for_status()
                data = response.json()

                if not data.get("success"):
                    logger.error(f"Worker fallback API error: {data.get('error', 'Unknown error')}")
                    return None

                return data.get("directLink") or data.get("streamLink") or data.get("downloads")
            except Exception as e:
                logger.error(f"Worker fallback request failed: {str(e)}")
                return None
            finally:
                if session:
                    session.close()

        async def get_worker_fallback_link(vid_id, media_format):
            return await loop.run_in_executor(
                None, fetch_worker_fallback_link_sync, vid_id, media_format
            )

        async def audio_dl(vid_id):
            filepath = os.path.join("downloads", f"{vid_id}.mp3")
            if os.path.exists(filepath):
                return filepath

            headers = {
                "x-api-key": f"{YT_API_KEY}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            paid_audio_url = None

            if YT_API_KEY and YTPROXY:
                session = None
                try:
                    session = create_session()
                    get_audio = session.get(f"{YTPROXY}/info/{vid_id}", headers=headers, timeout=60)
                    song_data = get_audio.json()
                    status = song_data.get('status')

                    if status == 'success':
                        paid_audio_url = song_data.get('audio_url')
                    elif status == 'error':
                        logger.error(
                            f"Paid API Error: {song_data.get('message', 'Unknown error from API.')}"
                        )
                    else:
                        logger.error("Paid API returned unexpected response while fetching audio.")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Network error while fetching paid audio info: {str(e)}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid paid API response for audio: {str(e)}")
                except Exception as e:
                    logger.error(f"Error in paid audio flow: {str(e)}")
                finally:
                    if session:
                        session.close()
            else:
                logger.warning("Paid API key/endpoint not configured. Using worker fallback for audio.")

            if paid_audio_url:
                result = await download_from_source(paid_audio_url, filepath, headers)
                if result:
                    return result
                logger.warning("Paid audio URL download failed, trying worker fallback.")

            fallback_audio_url = await get_worker_fallback_link(vid_id, "mp3")
            if fallback_audio_url:
                result = await download_from_source(fallback_audio_url, filepath)
                if result:
                    return result

            logger.error("Audio download failed on both paid API and worker fallback.")
            return None
        
        
        async def video_dl(vid_id):
            filepath = os.path.join("downloads", f"{vid_id}.mp4")
            if os.path.exists(filepath):
                return filepath

            headers = {
                "x-api-key": f"{YT_API_KEY}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            paid_video_url = None

            if YT_API_KEY and YTPROXY:
                session = None
                try:
                    session = create_session()
                    get_video = session.get(f"{YTPROXY}/info/{vid_id}", headers=headers, timeout=60)
                    video_data = get_video.json()
                    status = video_data.get('status')

                    if status == 'success':
                        paid_video_url = video_data.get('video_url')
                    elif status == 'error':
                        logger.error(
                            f"Paid API Error: {video_data.get('message', 'Unknown error from API.')}"
                        )
                    else:
                        logger.error("Paid API returned unexpected response while fetching video.")
                except requests.exceptions.RequestException as e:
                    logger.error(f"Network error while fetching paid video info: {str(e)}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid paid API response for video: {str(e)}")
                except Exception as e:
                    logger.error(f"Error in paid video flow: {str(e)}")
                finally:
                    if session:
                        session.close()
            else:
                logger.warning("Paid API key/endpoint not configured. Using worker fallback for video.")

            if paid_video_url:
                result = await download_from_source(paid_video_url, filepath, headers)
                if result:
                    return result
                logger.warning("Paid video URL download failed, trying worker fallback.")

            fallback_video_url = await get_worker_fallback_link(vid_id, "mp4")
            if fallback_video_url:
                result = await download_from_source(fallback_video_url, filepath)
                if result:
                    return result

            logger.error("Video download failed on both paid API and worker fallback.")
            return None
        
        def song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            ydl_optssx = {
                "format": formats,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        def song_audio_dl():
            fpath = f"downloads/{title}.%(ext)s"
            ydl_optssx = {
                "format": format_id,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = f"downloads/{title}.mp4"
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = f"downloads/{title}.mp3"
            return fpath
        elif video:
            direct = True
            downloaded_file = await video_dl(vid_id)
        else:
            direct = True
            downloaded_file = await audio_dl(vid_id)
        
        return downloaded_file, direct

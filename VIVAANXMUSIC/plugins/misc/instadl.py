import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.security import SecurityError, validate_public_http_url


INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",
}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_MEDIA_FILES = 10


def _validate_instagram_url(url: str) -> str:
    return validate_public_http_url(
        url,
        allowed_hosts=INSTAGRAM_HOSTS,
        allow_subdomains=True,
    )


def _download_instagram_media(instagram_url: str) -> tuple[str, list[str], str, bool]:
    safe_url = _validate_instagram_url(instagram_url)
    temp_dir = tempfile.mkdtemp(prefix="vivaan_insta_")
    output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "outtmpl": output_template,
        "format": "best",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(safe_url, download=True)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    files = []
    for item in sorted(Path(temp_dir).iterdir(), key=lambda path: path.stat().st_mtime):
        if not item.is_file():
            continue
        if item.suffix.lower() in {".part", ".ytdl", ".json"}:
            continue
        files.append(str(item))

    if not files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("No downloadable media was found for that Instagram link.")

    title = info.get("title") or "Instagram Media"
    truncated = len(files) > MAX_MEDIA_FILES
    return temp_dir, files[:MAX_MEDIA_FILES], title, truncated


async def _send_instagram_file(message: Message, file_path: str, caption: str | None):
    ext = Path(file_path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        await message.reply_video(file_path, caption=caption)
    elif ext in PHOTO_EXTENSIONS:
        await message.reply_photo(file_path, caption=caption)
    else:
        await message.reply_document(file_path, caption=caption)


@app.on_message(filters.command(["ig", "insta"]))
async def insta_download(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /insta [Instagram URL]")

    processing_message = await message.reply_text("Processing Instagram media...")
    temp_dir = None

    try:
        instagram_url = message.command[1]
        temp_dir, file_paths, title, truncated = await asyncio.to_thread(
            _download_instagram_media,
            instagram_url,
        )

        for index, file_path in enumerate(file_paths):
            caption = None
            if index == 0:
                caption = f"Downloaded from Instagram\n{title}"
                if truncated:
                    caption += "\nShowing the first 10 media files."
            await _send_instagram_file(message, file_path, caption)

        await processing_message.delete()
    except SecurityError as exc:
        await processing_message.edit(f"Blocked by security policy: {exc}")
    except Exception as exc:
        await processing_message.edit(f"Error downloading Instagram media: {exc}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

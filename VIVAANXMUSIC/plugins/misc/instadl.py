import os
import shutil
from pathlib import Path

from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.security import SecurityError
from VIVAANXMUSIC.utils.socialdown import (
    SocialDownloadError,
    download_bundle_files,
    get_social_bundle,
)


COMMAND_PLATFORMS = {
    "ig": "instagram",
    "insta": "instagram",
    "facebook": "facebook",
    "fb": "facebook",
    "snap": "snapchat",
    "snapchat": "snapchat",
    "youtube": "youtube",
    "yt": "youtube",
    "x": "x",
    "twitter": "x",
    "tiktok": "tiktok",
    "tt": "tiktok",
}

USAGE_TEXT = {
    "instagram": "Usage: /insta [Instagram URL]",
    "facebook": "Usage: /facebook [Facebook URL]",
    "snapchat": "Usage: /snap [Snapchat URL]",
    "youtube": "Usage: /youtube [YouTube URL]",
    "x": "Usage: /x [X/Twitter post URL]",
    "tiktok": "Usage: /tiktok [TikTok URL]",
}


async def _send_downloaded_file(message: Message, file_path: str, media_kind: str, caption: str | None):
    suffix = Path(file_path).suffix.lower()
    if media_kind == "video":
        return await message.reply_video(file_path, caption=caption, supports_streaming=True)
    if media_kind == "photo":
        return await message.reply_photo(file_path, caption=caption)
    if media_kind == "audio":
        return await message.reply_audio(file_path, caption=caption)
    if suffix in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"}:
        return await message.reply_audio(file_path, caption=caption)
    return await message.reply_document(file_path, caption=caption)


@app.on_message(
    filters.command(
        [
            "ig",
            "insta",
            "facebook",
            "fb",
            "snap",
            "snapchat",
            "youtube",
            "yt",
            "x",
            "twitter",
            "tiktok",
            "tt",
        ]
    )
)
async def social_download(_, message: Message):
    command = ((message.command or [""])[0] or "").lower()
    platform = COMMAND_PLATFORMS.get(command)
    if not platform:
        return

    if len(message.command) < 2:
        return await message.reply_text(USAGE_TEXT[platform])

    source_url = message.command[1].strip()
    status = await message.reply_text(f"Fetching {platform} media...")
    temp_dir = None

    try:
        await app.send_chat_action(message.chat.id, ChatAction.TYPING)
        bundle = await get_social_bundle(platform, source_url)
        temp_dir, downloaded = await download_bundle_files(bundle)

        total = len(downloaded)
        for index, (file_path, media_kind) in enumerate(downloaded, start=1):
            caption = None
            if index == 1:
                title = bundle.title or f"{platform.title()} Media"
                caption = f"Downloaded from {platform.title()}\n{title}"
                if total > 1:
                    caption += f"\nShowing {total} media items."
            await _send_downloaded_file(message, file_path, media_kind, caption)

        await status.delete()
    except SecurityError as exc:
        await status.edit_text(f"Blocked by security policy: {exc}")
    except (SocialDownloadError, Exception) as exc:
        await status.edit_text(f"Error downloading {platform} media: {exc}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

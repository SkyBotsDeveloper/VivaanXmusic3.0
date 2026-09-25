import os
import re
import shutil
from pathlib import Path

from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import YouTube, app
from VIVAANXMUSIC.security import SecurityError
from VIVAANXMUSIC.utils.socialdown import (
    SocialDownloadError,
    SocialDownloadBundle,
    download_bundle_files,
    get_social_bundle,
)

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


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


def _chunk_text(text: str, limit: int = 3500) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < max(400, limit // 3):
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < max(200, limit // 4):
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _send_bundle_text(message: Message, bundle: SocialDownloadBundle, platform: str):
    text_items = [item.content for item in bundle.items if item.kind == "text" and item.content]
    export_text = "\n\n".join(part.strip() for part in text_items if part.strip()) or bundle.note_text
    export_text = str(export_text or "").strip()
    if not export_text:
        raise SocialDownloadError(f"No readable {platform} post text was found.")

    for chunk in _chunk_text(export_text):
        await message.reply_text(chunk, disable_web_page_preview=True)


def _prepare_media_caption(
    platform: str,
    bundle: SocialDownloadBundle,
    total: int,
    limit: int = 900,
) -> tuple[str | None, str]:
    header_parts = [f"Downloaded from {platform.title()}"]
    if total > 1:
        header_parts.append(f"Showing {total} media items.")
    header = "\n".join(part for part in header_parts if part).strip()

    note_text = str(bundle.note_text or "").strip()
    title_text = str(bundle.title or "").strip()
    text_body = note_text or title_text

    if not text_body:
        return (header or None), ""

    if header:
        combined = f"{header}\n\n{text_body}".strip()
    else:
        combined = text_body

    if len(combined) <= limit:
        return combined, ""

    if len(header) <= limit:
        available = max(0, limit - len(header) - 2)
        if available > 80:
            split_at = text_body.rfind("\n", 0, available)
            if split_at < max(120, available // 3):
                split_at = text_body.rfind(" ", 0, available)
            if split_at < max(80, available // 4):
                split_at = available
            first_part = text_body[:split_at].strip()
            remainder = text_body[split_at:].strip()
            caption = f"{header}\n\n{first_part}".strip() if first_part else header
            return caption, remainder

    return header[:limit].strip() or None, text_body


async def _download_youtube_video(source_url: str) -> tuple[str, str]:
    if not await YouTube.exists(source_url):
        raise SocialDownloadError("Invalid YouTube URL.")

    details, video_id = await YouTube.track(source_url)
    file_path, _ = await YouTube.download(
        video_id,
        None,
        video=True,
        videoid=True,
    )
    if not file_path or not os.path.exists(file_path):
        raise SocialDownloadError("YouTube video could not be downloaded.")

    title = (details or {}).get("title") or "YouTube Video"
    return file_path, title


def _extract_source_url(message: Message) -> str | None:
    candidates = [
        message.text or message.caption or "",
    ]
    if message.reply_to_message:
        candidates.append(
            message.reply_to_message.text
            or message.reply_to_message.caption
            or ""
        )

    for text in candidates:
        match = URL_PATTERN.search(str(text or ""))
        if match:
            return match.group(0).strip().rstrip(").,]")
    return None


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

    source_url = _extract_source_url(message)
    if not source_url:
        return await message.reply_text(USAGE_TEXT[platform])

    status = await message.reply_text(f"Fetching {platform} media...")
    temp_dir = None
    youtube_file_path = None

    try:
        await app.send_chat_action(message.chat.id, ChatAction.TYPING)
        if platform == "youtube":
            file_path, title = await _download_youtube_video(source_url)
            youtube_file_path = file_path
            await message.reply_video(
                file_path,
                caption=f"Downloaded from YouTube\n{title}",
                supports_streaming=True,
            )
            return await status.delete()

        bundle = await get_social_bundle(platform, source_url)
        media_items = [item for item in bundle.items if item.kind != "text"]

        if not media_items:
            await _send_bundle_text(message, bundle, platform)
            return await status.delete()

        media_bundle = SocialDownloadBundle(
            title=bundle.title,
            source=bundle.source,
            items=media_items,
            note_text=bundle.note_text,
        )
        temp_dir, downloaded = await download_bundle_files(media_bundle)

        total = len(downloaded)
        first_caption, overflow_text = _prepare_media_caption(platform, bundle, total)
        for index, (file_path, media_kind) in enumerate(downloaded, start=1):
            caption = first_caption if index == 1 else None
            await _send_downloaded_file(message, file_path, media_kind, caption)

        if overflow_text:
            for chunk in _chunk_text(overflow_text):
                await message.reply_text(chunk, disable_web_page_preview=True)

        await status.delete()
    except SecurityError as exc:
        await status.edit_text(f"Blocked by security policy: {exc}")
    except SocialDownloadError as exc:
        await status.edit_text(f"Error downloading {platform} media: {exc}")
    except Exception as exc:
        await status.edit_text(f"Error downloading {platform} media: {exc}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        if youtube_file_path and os.path.exists(youtube_file_path):
            try:
                os.remove(youtube_file_path)
            except Exception:
                pass

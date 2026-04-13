import os

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.file_upload import upload_file_with_fallbacks


@app.on_message(filters.command(["tgm", "tgt", "telegraph"]))
async def telegraph_handler(_, message: Message):
    if not message.reply_to_message or not (
        message.reply_to_message.photo
        or message.reply_to_message.video
        or message.reply_to_message.document
    ):
        return await message.reply_text(
            "**Please reply to an image/video/document to upload.**"
        )

    media = message.reply_to_message
    file = media.photo or media.video or media.document

    if getattr(file, "file_size", 0) and file.file_size > 200 * 1024 * 1024:
        return await message.reply_text("**File too large. Max size is 200MB.**")

    status = await message.reply("**Downloading your media...**")
    local_path = None

    try:
        local_path = await media.download()
        await status.edit("**Uploading to Telegraph...**")
        result = await upload_file_with_fallbacks(local_path)

        if result.ok:
            await status.edit(
                "**Uploaded successfully!**\n"
                f"[Click to View]({result.url})",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Open Telegraph", url=result.url)]]
                ),
            )
        else:
            await status.edit(f"**Upload failed:**\n`{result.error}`")

    except Exception as exc:
        await status.edit(f"**Failed to process media:**\n`{exc}`")

    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

import asyncio
import tempfile
from pathlib import Path

from pyrogram import filters
from pyrogram.types import Message

from VIVAANXMUSIC import LOGGER, app
from VIVAANXMUSIC.utils.mmf import MemeError, media_kind, memify_media


logger = LOGGER(__name__)
_MMF_JOBS = asyncio.Semaphore(2)


async def _process(source, text, kind, work_dir):
    job = asyncio.create_task(asyncio.to_thread(memify_media, source, text, kind, work_dir))
    try:
        return await asyncio.shield(job)
    except asyncio.CancelledError:
        # Cancelling an await doesn't stop its thread. Wait before cleaning files.
        try:
            await job
        except Exception:
            logger.exception("Cancelled /mmf processing failed")
        raise


@app.on_message(filters.command("mmf"))
async def mmf(_, message: Message):
    if len((message.text or "").split()) < 2:
        return await message.reply_text("**Give me text after /mmf to memify.**")
    replied = message.reply_to_message
    kind = media_kind(replied)
    if kind is None:
        return await message.reply_text("**Reply to an image or sticker to memify.**")

    status = await message.reply_text("❄️")
    stage = "download"
    try:
        async with _MMF_JOBS:
            with tempfile.TemporaryDirectory(prefix="vivaan_mmf_") as directory:
                extension = {"static": ".image", "tgs": ".tgs", "video": ".webm"}[kind]
                source = await app.download_media(replied, file_name=str(Path(directory) / ("source" + extension)))
                if not source:
                    raise MemeError("Failed to download media.")
                stage = "process"
                output = await _process(source, message.text.split(None, 1)[1], kind, directory)
                stage = "send"
                if kind == "static":
                    await app.send_document(message.chat.id, document=str(output))
                else:
                    await app.send_sticker(message.chat.id, sticker=str(output))
        try:
            await status.delete()
        except Exception:
            logger.warning("Could not remove /mmf progress message", exc_info=True)
    except Exception as exc:
        logger.exception("/mmf failed during %s (%s)", stage, kind)
        if isinstance(exc, MemeError):
            error = str(exc)
        elif stage == "download":
            error = "Failed to download media. Please try again."
        elif stage == "send":
            error = "Failed to send the meme. Please try again."
        else:
            error = {"static": "Failed to decode the image.",
                     "tgs": "Failed to render the animated sticker.",
                     "video": "Failed to process the video sticker."}[kind]
        await status.edit_text(error)

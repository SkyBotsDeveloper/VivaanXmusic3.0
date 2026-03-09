import mimetypes
import os
from io import BytesIO

from pyrogram import filters

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import FreeAIError, process_image_bytes


def get_image_target(message):
    replied = message.reply_to_message
    if not replied:
        return None, None

    if replied.photo:
        return replied.photo.file_id, "image/jpeg"

    document = replied.document
    if document and document.mime_type and document.mime_type.startswith("image/"):
        return document.file_id, document.mime_type

    return None, None


@app.on_message(filters.command("rmbg"))
async def remove_bg_command(client, message):
    status = await message.reply("Processing your image...")
    file_id, mime_type = get_image_target(message)
    if not file_id:
        return await status.edit("Please reply to a photo to remove its background.")

    file_path = None
    try:
        file_path = await client.download_media(file_id)
        with open(file_path, "rb") as handle:
            image_bytes = handle.read()

        guessed_type, _ = mimetypes.guess_type(file_path)
        result_bytes = await process_image_bytes(
            image_bytes,
            mime_type=mime_type or guessed_type or "image/jpeg",
            mode="removebg",
        )

        photo = BytesIO(result_bytes)
        photo.name = "no_bg.png"
        document = BytesIO(result_bytes)
        document.name = "no_bg.png"

        await message.reply_photo(photo=photo, caption="Here is your image without background.")
        await message.reply_document(document=document)
        await status.delete()
    except FreeAIError as exc:
        await status.edit(str(exc))
    except Exception as exc:
        await status.edit(f"Failed to process the image.\nError: {exc}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

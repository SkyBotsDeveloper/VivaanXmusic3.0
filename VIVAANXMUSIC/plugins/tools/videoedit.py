import asyncio
import os
import subprocess
import tempfile

from pydub import AudioSegment
from pyrogram import filters
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.security import build_subprocess_env

MAX_SIZE_MB = 50
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024


@app.on_message(filters.command("remove") & filters.reply)
async def remove_media(_, message: Message):
    replied = message.reply_to_message

    if not (replied and replied.video):
        return await message.reply_text("Please reply to a video message.")
    if len(message.command) < 2:
        return await message.reply_text(
            "Use `/remove audio` or `/remove video`.",
            quote=True,
        )

    if replied.video.file_size > MAX_SIZE_BYTES:
        return await message.reply_text(
            f"File is too large ({replied.video.file_size // (1024 * 1024)} MB).\n"
            f"Maximum allowed size is {MAX_SIZE_MB} MB."
        )

    command = message.command[1].lower()
    if command not in {"audio", "video"}:
        return await message.reply_text(
            "Invalid command. Use `/remove audio` or `/remove video`."
        )

    processing_msg = await message.reply_text("Processing media...")

    file_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="vivaan_remove_") as work_dir:
            file_path = await replied.download(
                file_name=os.path.join(work_dir, "media_input.mp4")
            )

            if command == "audio":
                output_video = os.path.join(work_dir, "output_video.mp4")

                def process_video():
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-i",
                            file_path,
                            "-c",
                            "copy",
                            "-an",
                            output_video,
                        ],
                        env=build_subprocess_env(),
                        check=True,
                    )

                await asyncio.to_thread(process_video)
                await app.send_video(
                    message.chat.id,
                    output_video,
                    caption="Video with audio removed.",
                )

            else:
                output_audio = os.path.join(work_dir, "output_audio.mp3")

                def process_audio():
                    audio = AudioSegment.from_file(file_path)
                    audio = audio.set_channels(1)
                    audio.export(output_audio, format="mp3")

                await asyncio.to_thread(process_audio)
                await app.send_audio(
                    message.chat.id,
                    output_audio,
                    caption="Audio extracted after removing video.",
                )

    except Exception as exc:
        await message.reply_text(f"Error: {exc}")

    finally:
        await processing_msg.delete()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

import asyncio
from pyrogram import filters
from pyrogram.types import Message
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.anime_images import get_waifu_data


@app.on_message(filters.command("waifu"))
async def waifu_command_handler(_, message: Message):
    try:
        args = message.text.split(maxsplit=1)
        tag = args[1] if len(args) > 1 else "maid"

        waifu_data = await asyncio.to_thread(get_waifu_data, tag)

        if waifu_data and 'images' in waifu_data and waifu_data['images']:
            image = waifu_data['images'][0]
            send_media = message.reply_animation if image.get("format") == "gif" else message.reply_photo
            field = "animation" if image.get("format") == "gif" else "photo"
            await send_media(
                **{field: image["url"]},
                caption=f"🌸 ʜᴇʀᴇ'ꜱ ʏᴏᴜʀ ᴡᴀɪꜰᴜ ({image.get('tag', tag)})"
            )
        else:
            await message.reply_text("❌ ɴᴏ ᴡᴀɪꜰᴜꜱ ꜰᴏᴜɴᴅ ᴡɪᴛʜ ᴛʜᴀᴛ ᴛᴀɢ.")

    except Exception as e:
        await message.reply_text(f"⚠️ ᴇʀʀᴏʀ: `{str(e)}`")

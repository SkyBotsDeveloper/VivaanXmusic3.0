from pyrogram import filters
from pyrogram.enums import ChatType, ChatMemberStatus

from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import get_vc_logger, set_vc_logger
from VIVAANXMUSIC.utils.decorators.admins import AdminActual


async def validate_logger(client, destination):
    chat = await client.get_chat(destination)
    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL, ChatType.FORUM}:
        raise ValueError("Choose a group or channel chat ID.")
    member = await client.get_chat_member(destination, client.id)
    if member.status != ChatMemberStatus.ADMINISTRATOR:
        raise ValueError("Make the bot an admin in the logging group/channel first.")
    if chat.type == ChatType.CHANNEL and not getattr(member.privileges, "can_post_messages", False):
        raise ValueError("Give the bot permission to post messages in the logging channel.")


@app.on_message(filters.command("setlogger") & filters.group & ~BANNED_USERS)
@AdminActual
async def setlogger(client, message, strings):
    if len(message.command) == 1:
        current = await get_vc_logger(message.chat.id)
        return await message.reply_text(
            f"VC logger: <code>{current or message.chat.id}</code>\n"
            "Use /setlogger -100xxxx or /setlogger off. The bot must be an admin in the destination."
        )
    if len(message.command) != 2:
        return await message.reply_text("Use /setlogger -100xxxx or /setlogger off.")
    arg = message.command[1].lower()
    if arg in {"off", "reset"}:
        await set_vc_logger(message.chat.id, None)
        return await message.reply_text("External VC logging removed. VC notifications will appear here when /vcnotify is on.")
    try:
        destination = int(arg)
        if destination >= 0:
            raise ValueError("Use a negative group/channel chat ID, for example -1001234567890.")
        await validate_logger(client, destination)
    except ValueError as err:
        return await message.reply_text(str(err))
    except Exception:
        return await message.reply_text("I cannot verify that chat. Add the bot there as an admin and check the chat ID.")
    await set_vc_logger(message.chat.id, destination)
    await message.reply_text(
        f"VC logger set to <code>{destination}</code>. When /vcnotify is on, VC notifications will go there."
    )

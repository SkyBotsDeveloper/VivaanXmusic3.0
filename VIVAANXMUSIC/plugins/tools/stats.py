import platform
from html import escape
from io import BytesIO
from sys import version as pyver

import psutil
from pyrogram import __version__ as pyrover
from pyrogram import filters
from pyrogram.errors import MessageIdInvalid
from pyrogram.types import InputMediaVideo, Message
from pytgcalls.__version__ import __version__ as pytgver

import config
from VIVAANXMUSIC import app
from VIVAANXMUSIC.core.userbot import assistants
from VIVAANXMUSIC.misc import SUDOERS, mongodb
from VIVAANXMUSIC.plugins import ALL_MODULES
from VIVAANXMUSIC.utils.database import get_served_chats, get_served_users, get_sudoers
from VIVAANXMUSIC.utils.decorators.language import language, languageCB
from VIVAANXMUSIC.utils.inline.stats import back_stats_buttons, stats_buttons
from config import BANNED_USERS


@app.on_message(filters.command(["stats", "gstats"]) & ~BANNED_USERS)
@language
async def stats_global(client, message: Message, _):
    upl = stats_buttons(_, True if message.from_user.id in SUDOERS else False)
    await message.reply_video(
        video=config.STATS_VID_URL,
        caption=_["gstats_2"].format(app.mention),
        reply_markup=upl,
    )


@app.on_callback_query(filters.regex("stats_back") & ~BANNED_USERS)
@languageCB
async def home_stats(client, CallbackQuery, _):
    upl = stats_buttons(_, True if CallbackQuery.from_user.id in SUDOERS else False)
    await CallbackQuery.edit_message_text(
        text=_["gstats_2"].format(app.mention),
        reply_markup=upl,
    )


@app.on_callback_query(filters.regex("TopOverall") & ~BANNED_USERS)
@languageCB
async def overall_stats(client, CallbackQuery, _):
    await CallbackQuery.answer()
    upl = back_stats_buttons(_)
    try:
        await CallbackQuery.answer()
    except:
        pass
    await CallbackQuery.edit_message_text(_["gstats_1"].format(app.mention))
    served_chats = len(await get_served_chats())
    served_users = len(await get_served_users())
    text = _["gstats_3"].format(
        app.mention,
        len(assistants),
        len(BANNED_USERS),
        served_chats,
        served_users,
        len(ALL_MODULES),
        len(SUDOERS),
        config.AUTO_LEAVING_ASSISTANT,
        config.DURATION_LIMIT_MIN,
    )
    med = InputMediaVideo(media=config.STATS_VID_URL, caption=text)
    try:
        await CallbackQuery.edit_message_media(media=med, reply_markup=upl)
    except MessageIdInvalid:
        await CallbackQuery.message.reply_video(
            video=config.STATS_VID_URL, caption=text, reply_markup=upl
        )


def _format_bytes(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


async def _safe_count(collection_name):
    try:
        return await mongodb[collection_name].count_documents({})
    except Exception as exc:
        return f"error: {exc}"


async def _mongo_stats_report():
    stats = await mongodb.command("dbstats")
    collection_names = sorted(await mongodb.list_collection_names())
    try:
        database_names = sorted(await mongodb.client.list_database_names())
    except Exception:
        database_names = []

    known_counts = {
        "All chat docs": await mongodb.chats.count_documents({}),
        "Valid served chats": await mongodb.chats.count_documents({"chat_id": {"$lt": 0}}),
        "All user docs": await mongodb.tgusersdb.count_documents({}),
        "Valid served users": await mongodb.tgusersdb.count_documents({"user_id": {"$gt": 0}}),
        "Blacklisted chats": await mongodb.blacklistChat.count_documents({}),
        "Blocked users": await mongodb.blockedusers.count_documents({}),
        "Gbanned users": await mongodb.gban.count_documents({}),
        "Sudo config docs": await mongodb.sudoers.count_documents({}),
        "Assistant assignments": await mongodb.assistants.count_documents({}),
        "Auth chats": await mongodb.adminauth.count_documents({}),
        "Auth user docs": await mongodb.authuser.count_documents({}),
        "Language docs": await mongodb.language.count_documents({}),
        "Autoplay docs": await mongodb.autoplay.count_documents({}),
        "VC notify docs": await mongodb.vcnotify.count_documents({}),
    }

    lines = [
        "📊 ᴍᴏɴɢᴏ sᴛᴀᴛs ʀᴇᴘᴏʀᴛ",
        "",
        f"ᴅᴀᴛᴀʙᴀsᴇ: {escape(str(stats.get('db', 'Vivaan')))}",
        f"ᴄᴏʟʟᴇᴄᴛɪᴏɴs: {stats.get('collections', 0):,}",
        f"ᴏʙᴊᴇᴄᴛs: {stats.get('objects', 0):,}",
        f"ᴅᴀᴛᴀ sɪᴢᴇ: {_format_bytes(stats.get('dataSize', 0))}",
        f"sᴛᴏʀᴀɢᴇ sɪᴢᴇ: {_format_bytes(stats.get('storageSize', 0))}",
        f"ɪɴᴅᴇx sɪᴢᴇ: {_format_bytes(stats.get('indexSize', 0))}",
        f"ᴛᴏᴛᴀʟ sɪᴢᴇ: {_format_bytes(stats.get('totalSize', 0))}",
    ]
    if database_names:
        lines.append(f"ᴀᴠᴀɪʟᴀʙʟᴇ ᴅʙs: {escape(', '.join(database_names))}")
    lines.extend(["", "ᴠɪsɪʙʟᴇ sᴛᴀᴛ ᴄʜᴇᴄᴋ"])

    for label, count in known_counts.items():
        lines.append(f"{label}: {count:,}")

    lines.extend(["", "ᴄᴏʟʟᴇᴄᴛɪᴏɴ ᴅᴏᴄᴜᴍᴇɴᴛs"])
    for collection_name in collection_names:
        count = await _safe_count(collection_name)
        if isinstance(count, int):
            count_text = f"{count:,}"
        else:
            count_text = escape(str(count))
        lines.append(f"{collection_name}: {count_text}")

    return "\n".join(lines)


@app.on_message(filters.command(["fetchstats", "mongostats", "dbstats", "fullstats"]) & filters.user(config.OWNER_ID))
async def mongo_stats_dump(client, message: Message):
    status = await message.reply_text("Fetching Mongo stats...")
    try:
        report = await _mongo_stats_report()
    except Exception as exc:
        return await status.edit_text(f"Failed to fetch Mongo stats:\n<code>{escape(str(exc))}</code>")

    if len(report) <= 3900:
        return await status.edit_text(f"<pre>{report}</pre>")

    bio = BytesIO(report.encode("utf-8"))
    bio.name = "mongo_stats.txt"
    await message.reply_document(
        document=bio,
        caption="Mongo stats report",
    )
    await status.delete()


@app.on_callback_query(filters.regex("bot_stats_sudo"))
@languageCB
async def bot_stats(client, CallbackQuery, _):
    if CallbackQuery.from_user.id not in SUDOERS:
        return await CallbackQuery.answer(_["gstats_4"], show_alert=True)
    upl = back_stats_buttons(_)
    try:
        await CallbackQuery.answer()
    except:
        pass
    await CallbackQuery.edit_message_text(_["gstats_1"].format(app.mention))
    p_core = psutil.cpu_count(logical=False)
    t_core = psutil.cpu_count(logical=True)
    ram = str(round(psutil.virtual_memory().total / (1024.0**3))) + " ɢʙ"
    try:
        cpu_freq = psutil.cpu_freq().current
        if cpu_freq >= 1000:
            cpu_freq = f"{round(cpu_freq / 1000, 2)}ɢʜᴢ"
        else:
            cpu_freq = f"{round(cpu_freq, 2)}ᴍʜᴢ"
    except:
        cpu_freq = "ғᴀɪʟᴇᴅ ᴛᴏ ғᴇᴛᴄʜ"
    hdd = psutil.disk_usage("/")
    total = hdd.total / (1024.0**3)
    used = hdd.used / (1024.0**3)
    free = hdd.free / (1024.0**3)
    call = await mongodb.command("dbstats")
    datasize = call["dataSize"] / 1024
    storage = call["storageSize"] / 1024
    served_chats = len(await get_served_chats())
    served_users = len(await get_served_users())
    text = _["gstats_5"].format(
        app.mention,
        len(ALL_MODULES),
        platform.system(),
        ram,
        p_core,
        t_core,
        cpu_freq,
        pyver.split()[0],
        pyrover,
        pytgver,
        str(total)[:4],
        str(used)[:4],
        str(free)[:4],
        served_chats,
        served_users,
        len(BANNED_USERS),
        len(await get_sudoers()),
        str(datasize)[:6],
        storage,
        call["collections"],
        call["objects"],
    )
    med = InputMediaVideo(media=config.STATS_VID_URL, caption=text)
    try:
        await CallbackQuery.edit_message_media(media=med, reply_markup=upl)
    except MessageIdInvalid:
        await CallbackQuery.message.reply_video(
            video=config.STATS_VID_URL, caption=text, reply_markup=upl
        )

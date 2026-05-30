import asyncio
from html import escape
from io import BytesIO

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatMembersFilter, ChatType
from pyrogram.errors import FloodWait

from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import SUDOERS
from VIVAANXMUSIC.utils.database import (
    add_served_chat,
    add_served_user,
    get_active_chats,
    get_authuser_names,
    get_client,
    get_served_chats,
    get_served_users,
    remove_served_chat,
    remove_served_user,
)
from VIVAANXMUSIC.utils.decorators.language import language
from VIVAANXMUSIC.utils.formatters import alpha_to_int
from config import OWNER_ID, adminlist

IS_BROADCASTING = False
SCAN_CHAT_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL}
if getattr(ChatType, "FORUM", None):
    SCAN_CHAT_TYPES.add(ChatType.FORUM)
ACTIVE_BOT_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}
if getattr(ChatMemberStatus, "RESTRICTED", None):
    ACTIVE_BOT_STATUSES.add(ChatMemberStatus.RESTRICTED)
TRACKED_CHAT_IDS = set()
TRACKED_USER_IDS = set()


def _chat_title(chat):
    title = getattr(chat, "title", None) or getattr(chat, "first_name", None)
    return escape(str(title or "Unknown"))


def _chat_username(chat):
    username = getattr(chat, "username", None)
    return f"@{escape(username)}" if username else "@Private"


def _chat_report_line(chat):
    return f"{chat.id} | {_chat_title(chat)} | {_chat_username(chat)}"


def _is_broadcast_chat(chat):
    return bool(chat and chat.type in SCAN_CHAT_TYPES and int(chat.id) < 0)


async def _remember_broadcast_chat(chat):
    if not _is_broadcast_chat(chat):
        return
    chat_id = int(chat.id)
    if chat_id in TRACKED_CHAT_IDS:
        return
    await add_served_chat(chat_id)
    TRACKED_CHAT_IDS.add(chat_id)


async def _remember_private_user(user):
    if not user or getattr(user, "is_bot", False):
        return
    user_id = int(user.id)
    if user_id in TRACKED_USER_IDS:
        return
    await add_served_user(user_id)
    TRACKED_USER_IDS.add(user_id)


async def _send_scan_report(message, status, report):
    if len(report) <= 3900:
        return await status.edit_text(f"<pre>{report}</pre>")

    bio = BytesIO(report.encode("utf-8"))
    bio.name = "bot_chat_scan.txt"
    await message.reply_document(document=bio, caption="Bot chat scan report")
    await status.delete()


@app.on_message((filters.group | filters.channel), group=-50)
async def remember_seen_chat(_, message):
    await _remember_broadcast_chat(message.chat)


@app.on_message(filters.private, group=-50)
async def remember_seen_user(_, message):
    await _remember_private_user(message.from_user)


@app.on_chat_member_updated(group=-50)
async def remember_bot_membership(client, update):
    old = update.old_chat_member
    new = update.new_chat_member
    member_user = getattr(new, "user", None) or getattr(old, "user", None)
    if not member_user or member_user.id != app.id:
        return

    chat = update.chat
    if not _is_broadcast_chat(chat):
        return

    new_status = getattr(new, "status", None)
    chat_id = int(chat.id)
    if new_status in ACTIVE_BOT_STATUSES:
        await _remember_broadcast_chat(chat)
        return

    await remove_served_chat(chat_id)
    TRACKED_CHAT_IDS.discard(chat_id)


@app.on_message(filters.command(["syncchats", "scanchats", "scanbroadcast"]) & filters.user(OWNER_ID))
async def scan_broadcast_chats(client, message):
    command_text = message.text or ""
    clean_stale = "-clean" in command_text
    check_users = clean_stale or "-users" in command_text
    status = await message.reply_text("Validating Mongo broadcast targets...")

    db_docs = await get_served_chats()
    user_docs = await get_served_users()
    db_chat_ids = {
        int(chat["chat_id"])
        for chat in db_docs
        if chat.get("chat_id") is not None
    }
    db_user_ids = {
        int(user["user_id"])
        for user in user_docs
        if user.get("user_id") is not None
    }

    stale_chats = []
    reachable_chats = []
    for chat_id in sorted(db_chat_ids):
        try:
            chat = await client.get_chat(chat_id)
            if chat.type in SCAN_CHAT_TYPES:
                reachable_chats.append(chat)
            else:
                stale_chats.append((chat_id, f"unexpected chat type: {chat.type}"))
        except Exception as exc:
            stale_chats.append((chat_id, str(exc)))
        await asyncio.sleep(0.05)

    stale_users = []
    reachable_users = []
    if check_users:
        for user_id in sorted(db_user_ids):
            try:
                user = await client.get_users(user_id)
                reachable_users.append(user)
            except Exception as exc:
                stale_users.append((user_id, str(exc)))
            await asyncio.sleep(0.05)

    cleaned_chats = 0
    cleaned_users = 0
    if clean_stale:
        for chat_id, _ in stale_chats:
            try:
                await remove_served_chat(chat_id)
                cleaned_chats += 1
            except Exception:
                pass
        for user_id, _ in stale_users:
            try:
                await remove_served_user(user_id)
                cleaned_users += 1
            except Exception:
                pass

    active_chats = len(db_chat_ids) - cleaned_chats
    active_users = len(db_user_ids) - cleaned_users
    lines = [
        "BOT BROADCAST TARGET REPORT",
        "",
        "Note: Telegram does not allow bot accounts to fetch full dialog lists.",
        "This command validates Mongo targets. New chats/users are auto-synced from activity and bot membership updates.",
        "",
        f"Mongo chat/channel targets: {len(db_docs)}",
        f"Mongo private user targets: {len(user_docs)}",
        f"Reachable chat/channel targets: {len(reachable_chats)}",
        f"Private user validation: {'checked' if check_users else 'skipped'}",
        f"Reachable private user targets: {len(reachable_users)}",
        f"Stale/inaccessible Mongo chats: {len(stale_chats)}",
        f"Stale/inaccessible Mongo users: {len(stale_users)}",
        f"Cleaned stale chats: {cleaned_chats}",
        f"Cleaned stale users: {cleaned_users}",
        f"Broadcast chat/channel targets after scan: {active_chats}",
        f"Broadcast private user targets after scan: {active_users}",
    ]
    if (stale_chats or stale_users) and not clean_stale:
        lines.append("Use /syncchats -clean to remove stale/inaccessible targets from Mongo.")
    if not check_users:
        lines.append("Use /syncchats -users to validate private users too.")

    if stale_chats:
        lines.extend(["", "STALE / INACCESSIBLE CHATS"])
        for chat_id, reason in stale_chats[:80]:
            lines.append(f"{chat_id} | {escape(reason[:160])}")
        if len(stale_chats) > 80:
            lines.append(f"...and {len(stale_chats) - 80} more")

    if stale_users:
        lines.extend(["", "STALE / INACCESSIBLE USERS"])
        for user_id, reason in stale_users[:80]:
            lines.append(f"{user_id} | {escape(reason[:160])}")
        if len(stale_users) > 80:
            lines.append(f"...and {len(stale_users) - 80} more")

    await _send_scan_report(message, status, "\n".join(lines))


@app.on_message(filters.command("broadcast") & SUDOERS)
@language
async def braodcast_message(client, message, _):
    global IS_BROADCASTING
    if message.reply_to_message:
        x = message.reply_to_message.id
        y = message.chat.id
    else:
        if len(message.command) < 2:
            return await message.reply_text(_["broad_2"])
        query = message.text.split(None, 1)[1]
        if "-pin" in query:
            query = query.replace("-pin", "")
        if "-nobot" in query:
            query = query.replace("-nobot", "")
        if "-pinloud" in query:
            query = query.replace("-pinloud", "")
        if "-assistant" in query:
            query = query.replace("-assistant", "")
        if "-user" in query:
            query = query.replace("-user", "")
        if query == "":
            return await message.reply_text(_["broad_8"])

    IS_BROADCASTING = True
    await message.reply_text(_["broad_1"])

    if "-nobot" not in message.text:
        sent = 0
        pin = 0
        chats = []
        schats = await get_served_chats()
        for chat in schats:
            chats.append(int(chat["chat_id"]))
        for i in chats:
            try:
                m = (
                    await app.forward_messages(i, y, x)
                    if message.reply_to_message
                    else await app.send_message(i, text=query)
                )
                if "-pin" in message.text:
                    try:
                        await m.pin(disable_notification=True)
                        pin += 1
                    except:
                        continue
                elif "-pinloud" in message.text:
                    try:
                        await m.pin(disable_notification=False)
                        pin += 1
                    except:
                        continue
                sent += 1
                await asyncio.sleep(0.2)
            except FloodWait as fw:
                flood_time = int(fw.value)
                if flood_time > 200:
                    continue
                await asyncio.sleep(flood_time)
            except:
                continue
        try:
            await message.reply_text(_["broad_3"].format(sent, pin))
        except:
            pass

    if "-user" in message.text:
        susr = 0
        served_users = []
        susers = await get_served_users()
        for user in susers:
            served_users.append(int(user["user_id"]))
        for i in served_users:
            try:
                m = (
                    await app.forward_messages(i, y, x)
                    if message.reply_to_message
                    else await app.send_message(i, text=query)
                )
                susr += 1
                await asyncio.sleep(0.2)
            except FloodWait as fw:
                flood_time = int(fw.value)
                if flood_time > 200:
                    continue
                await asyncio.sleep(flood_time)
            except:
                pass
        try:
            await message.reply_text(_["broad_4"].format(susr))
        except:
            pass

    if "-assistant" in message.text:
        aw = await message.reply_text(_["broad_5"])
        text = _["broad_6"]
        from VIVAANXMUSIC.core.userbot import assistants

        for num in assistants:
            sent = 0
            client = await get_client(num)
            async for dialog in client.get_dialogs():
                try:
                    await client.forward_messages(
                        dialog.chat.id, y, x
                    ) if message.reply_to_message else await client.send_message(
                        dialog.chat.id, text=query
                    )
                    sent += 1
                    await asyncio.sleep(3)
                except FloodWait as fw:
                    flood_time = int(fw.value)
                    if flood_time > 200:
                        continue
                    await asyncio.sleep(flood_time)
                except:
                    continue
            text += _["broad_7"].format(num, sent)
        try:
            await aw.edit_text(text)
        except:
            pass
    IS_BROADCASTING = False


async def auto_clean():
    while not await asyncio.sleep(10):
        try:
            served_chats = await get_active_chats()
            for chat_id in served_chats:
                if chat_id not in adminlist:
                    adminlist[chat_id] = []
                    async for user in app.get_chat_members(
                        chat_id, filter=ChatMembersFilter.ADMINISTRATORS
                    ):
                        if getattr(user.privileges, 'can_manage_video_chats', False):
                            adminlist[chat_id].append(user.user.id)
                    authusers = await get_authuser_names(chat_id)
                    for user in authusers:
                        user_id = await alpha_to_int(user)
                        adminlist[chat_id].append(user_id)
        except:
            continue


asyncio.create_task(auto_clean())

import asyncio
import re
from html import escape
from io import BytesIO

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatMembersFilter, ChatType
from pyrogram.errors import FloodWait

from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import SUDOERS, mongodb
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
from config import LOGGER_ID, OWNER_ID, adminlist

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
CHAT_ID_RE = re.compile(r"(?<!\d)-(?:100)?\d{7,}(?!\d)")
CHAT_ID_KEYS = {"chat_id", "chat_id_toggle", "channel_id", "cid"}
USER_ID_KEYS = {"user_id", "uid", "user1", "user2", "from_user_id", "added_by"}
USER_LIST_KEYS = {"sudoers"}
MONGO_SYNC_SKIP_COLLECTIONS = {"blacklistChat", "blockedusers", "gban"}


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


def _history_scan_limit(command_text):
    parts = command_text.split()
    for flag in ("-logs", "-limit"):
        if flag not in parts:
            continue
        try:
            value = int(parts[parts.index(flag) + 1])
        except (IndexError, ValueError):
            continue
        return max(100, min(value, 50000))
    return 10000


def _extract_chat_ids(text):
    if not text:
        return set()
    return {
        int(match.group(0))
        for match in CHAT_ID_RE.finditer(text)
        if int(match.group(0)) != LOGGER_ID
    }


def _to_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.lstrip("-").isdigit():
            return int(value)
    return None


def _iter_int_values(value):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            int_value = _to_int(item)
            if int_value is not None:
                yield int_value
        return

    int_value = _to_int(value)
    if int_value is not None:
        yield int_value


def _collect_ids_from_document(document, chat_ids, user_ids):
    if not isinstance(document, dict):
        return

    for key, value in document.items():
        key_name = str(key)
        key_lower = key_name.lower()

        if key_lower in CHAT_ID_KEYS:
            for chat_id in _iter_int_values(value):
                if chat_id < 0:
                    chat_ids.add(chat_id)
                elif chat_id > 0:
                    user_ids.add(chat_id)
            continue

        if key_lower == "_id":
            int_id = _to_int(value)
            if int_id is not None and int_id < 0:
                chat_ids.add(int_id)
            continue

        if key_lower in USER_ID_KEYS or key_lower in USER_LIST_KEYS:
            for user_id in _iter_int_values(value):
                if user_id > 0:
                    user_ids.add(user_id)
            continue

        if isinstance(value, dict):
            _collect_ids_from_document(value, chat_ids, user_ids)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _collect_ids_from_document(item, chat_ids, user_ids)


async def _sync_targets_from_mongo():
    collection_names = sorted(await mongodb.list_collection_names())
    existing_chats = {
        int(chat["chat_id"])
        for chat in await get_served_chats()
        if chat.get("chat_id") is not None
    }
    existing_users = {
        int(user["user_id"])
        for user in await get_served_users()
        if user.get("user_id") is not None
    }

    found_chats = set()
    found_users = set()
    source_counts = []
    scanned_docs = 0

    for collection_name in collection_names:
        if collection_name in MONGO_SYNC_SKIP_COLLECTIONS:
            continue

        collection_chat_ids = set()
        collection_user_ids = set()
        cursor = mongodb[collection_name].find({})
        async for document in cursor:
            scanned_docs += 1
            _collect_ids_from_document(
                document, collection_chat_ids, collection_user_ids
            )
            if scanned_docs % 500 == 0:
                await asyncio.sleep(0)

        found_chats.update(collection_chat_ids)
        found_users.update(collection_user_ids)
        if collection_chat_ids or collection_user_ids:
            source_counts.append(
                (
                    collection_name,
                    len(collection_chat_ids),
                    len(collection_user_ids),
                )
            )

    new_chats = sorted(found_chats - existing_chats)
    new_users = sorted(found_users - existing_users)

    for chat_id in new_chats:
        await mongodb.chats.update_one(
            {"chat_id": chat_id}, {"$set": {"chat_id": chat_id}}, upsert=True
        )
        TRACKED_CHAT_IDS.add(chat_id)

    for user_id in new_users:
        await mongodb.tgusersdb.update_one(
            {"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True
        )
        TRACKED_USER_IDS.add(user_id)

    return {
        "collections": len(collection_names),
        "scanned_docs": scanned_docs,
        "found_chats": len(found_chats),
        "found_users": len(found_users),
        "new_chats": len(new_chats),
        "new_users": len(new_users),
        "source_counts": source_counts,
        "skipped_collections": sorted(MONGO_SYNC_SKIP_COLLECTIONS),
    }


async def _recover_chats_from_log_history(client, limit):
    recovered = []
    failed = []
    seen_ids = set()
    scanned_messages = 0

    async for log_message in client.get_chat_history(LOGGER_ID, limit=limit):
        scanned_messages += 1
        text = log_message.text or log_message.caption or ""
        for chat_id in _extract_chat_ids(text):
            if chat_id in seen_ids:
                continue
            seen_ids.add(chat_id)
            try:
                chat = await client.get_chat(chat_id)
                if not _is_broadcast_chat(chat):
                    continue
                await add_served_chat(chat_id)
                TRACKED_CHAT_IDS.add(chat_id)
                recovered.append(chat)
            except FloodWait as fw:
                await asyncio.sleep(int(fw.value))
            except Exception as exc:
                failed.append((chat_id, str(exc)))
            await asyncio.sleep(0.03)

    return scanned_messages, recovered, failed


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
    await _remember_private_user(message.from_user)


@app.on_message(filters.private, group=-50)
async def remember_seen_user(_, message):
    await _remember_private_user(message.from_user)


@app.on_callback_query(group=-50)
async def remember_callback_activity(_, callback):
    await _remember_private_user(callback.from_user)
    if callback.message:
        await _remember_broadcast_chat(callback.message.chat)


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
    recover_from_logs = "-logs" in command_text
    status = await message.reply_text("Syncing broadcast targets from Vivaan DB...")

    mongo_sync = {
        "collections": 0,
        "scanned_docs": 0,
        "found_chats": 0,
        "found_users": 0,
        "new_chats": 0,
        "new_users": 0,
        "source_counts": [],
        "skipped_collections": sorted(MONGO_SYNC_SKIP_COLLECTIONS),
    }
    mongo_sync_error = None
    try:
        mongo_sync = await _sync_targets_from_mongo()
    except Exception as exc:
        mongo_sync_error = str(exc)

    log_messages_scanned = 0
    log_recovered_chats = []
    log_failed_chats = []
    log_scan_error = None
    if recover_from_logs:
        try:
            await status.edit_text("Recovering targets from log history...")
        except Exception:
            pass
        try:
            log_messages_scanned, log_recovered_chats, log_failed_chats = (
                await _recover_chats_from_log_history(
                    client, _history_scan_limit(command_text)
                )
            )
        except Exception as exc:
            log_scan_error = str(exc)

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
        "This command syncs broadcast targets directly from the Vivaan Mongo database.",
        "",
        f"Mongo collections scanned: {mongo_sync['collections']}",
        f"Mongo documents scanned: {mongo_sync['scanned_docs']}",
        f"Chat/channel IDs found in Vivaan DB: {mongo_sync['found_chats']}",
        f"Private user IDs found in Vivaan DB: {mongo_sync['found_users']}",
        f"New chat/channel targets imported: {mongo_sync['new_chats']}",
        f"New private user targets imported: {mongo_sync['new_users']}",
        f"Skipped deny-list collections: {', '.join(mongo_sync['skipped_collections'])}",
        f"Log history scan: {'enabled' if recover_from_logs else 'skipped'}",
        f"Log messages scanned: {log_messages_scanned}",
        f"Chat/channel targets recovered from logs: {len(log_recovered_chats)}",
        f"Log chat IDs not reachable: {len(log_failed_chats)}",
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
    if mongo_sync_error:
        lines.extend(["", f"MONGO SYNC ERROR: {escape(mongo_sync_error)}"])
    if log_scan_error:
        lines.extend(["", f"LOG HISTORY SCAN ERROR: {escape(log_scan_error)}"])

    if mongo_sync["source_counts"]:
        lines.extend(["", "MONGO SOURCES"])
        for collection_name, chat_count, user_count in mongo_sync["source_counts"][:80]:
            lines.append(f"{collection_name}: chats={chat_count}, users={user_count}")
        if len(mongo_sync["source_counts"]) > 80:
            lines.append(f"...and {len(mongo_sync['source_counts']) - 80} more")

    if log_recovered_chats:
        lines.extend(["", "RECOVERED FROM LOG HISTORY"])
        lines.extend(_chat_report_line(chat) for chat in log_recovered_chats[:80])
        if len(log_recovered_chats) > 80:
            lines.append(f"...and {len(log_recovered_chats) - 80} more")

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

    if log_failed_chats:
        lines.extend(["", "LOG CHAT IDS NOT REACHABLE"])
        for chat_id, reason in log_failed_chats[:80]:
            lines.append(f"{chat_id} | {escape(reason[:160])}")
        if len(log_failed_chats) > 80:
            lines.append(f"...and {len(log_failed_chats) - 80} more")

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

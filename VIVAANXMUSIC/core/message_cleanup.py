"""One bounded, persistent cleanup worker for this bot's outgoing messages."""
import asyncio
import time
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone

from pyrogram import utils
from pyrogram.errors import FloodWait
from pymongo import UpdateOne

SEND_REQUESTS = {
    "SendMessage", "SendMedia", "SendMultiMedia", "ForwardMessages",
    "SendInlineBotResult", "SendRichMessage",
}


def sent_message_ids(query, result):
    if type(query).__name__ not in SEND_REQUESTS:
        return []
    refs = set()
    if type(result).__name__ == "UpdateShortSentMessage":
        peer = getattr(query, "peer", None) or getattr(query, "to_peer", None)
        if peer:
            refs.add((utils.get_peer_id(peer), result.id))
    updates = list(getattr(result, "updates", None) or ())
    if getattr(result, "update", None) is not None:
        updates.append(result.update)
    for update in updates:
        if type(update).__name__ not in {"UpdateNewMessage", "UpdateNewChannelMessage"}:
            continue
        message = update.message
        if getattr(message, "out", False) or getattr(message, "post", False):
            refs.add((utils.get_peer_id(message.peer_id), message.id))
    return [(chat_id, message_id) for chat_id, message_id in refs if chat_id < 0]


class OutgoingMessageCleanup:
    DELAY = 300
    BUFFER_LIMIT = 20000
    BATCH_SIZE = 500

    def __init__(self, logger):
        self.logger = logger
        self.enabled = set()
        self.pending = OrderedDict()
        self.discard_chats = set()
        self.wake = asyncio.Event()
        self.task = None
        self.client = self.collection = None
        self.last_overflow_warning = -60
        self.delete_after = 0.0
        self.settings_loader = None
        self.settings_loaded = False
        self.setting_changes = {}

    def set_enabled(self, chat_id, enabled):
        self.setting_changes[chat_id] = bool(enabled)
        if enabled:
            self.enabled.add(chat_id)
        else:
            self.enabled.discard(chat_id)
            self.discard_chats.add(chat_id)
            for key, record in list(self.pending.items()):
                if record["chat_id"] == chat_id:
                    self.pending.pop(key, None)
        self.wake.set()

    def capture(self, query, result, bot_id):
        if not bot_id or not self.enabled or type(query).__name__ not in SEND_REQUESTS:
            return
        now = datetime.now(timezone.utc)
        for chat_id, message_id in sent_message_ids(query, result):
            if chat_id not in self.enabled:
                continue
            key = f"{bot_id}:{chat_id}:{message_id}"
            self.pending[key] = {
                "_id": key, "bot_id": bot_id, "chat_id": chat_id,
                "message_id": message_id, "due_at": now + timedelta(seconds=self.DELAY),
                "expires_at": now + timedelta(hours=47),
            }
            if len(self.pending) > self.BUFFER_LIMIT:
                self.pending.popitem(last=False)
                if time.monotonic() - self.last_overflow_warning >= 60:
                    self.logger.warning("Cleanup backlog reached its memory limit; check MongoDB availability.")
                    self.last_overflow_warning = time.monotonic()
        if len(self.pending) >= 100:
            self.wake.set()

    async def start(self, client, collection, enabled_chats):
        self.client, self.collection = client, collection
        self.settings_loader = enabled_chats
        try:
            await self.load_settings()
        except Exception as err:
            self.logger.warning("Cleanup settings will reload in the background: %s", type(err).__name__)
        self.task = asyncio.create_task(self.run())

    async def load_settings(self):
        enabled = {chat_id async for chat_id in self.settings_loader()}
        for chat_id, state in self.setting_changes.items():
            if state:
                enabled.add(chat_id)
            else:
                enabled.discard(chat_id)
        self.enabled = enabled
        self.settings_loaded = True

    async def flush(self):
        bot_id = getattr(self.client, "id", None)
        if not bot_id:
            return
        for chat_id in list(self.discard_chats):
            await self.collection.delete_many({"bot_id": bot_id, "chat_id": chat_id})
            self.discard_chats.discard(chat_id)
        batch = list(self.pending.items())[:self.BATCH_SIZE]
        if not batch:
            return
        await self.collection.bulk_write([
            UpdateOne({"_id": key}, {"$setOnInsert": record}, upsert=True)
            for key, record in batch
        ], ordered=False)
        for key, record in batch:
            if self.pending.get(key) is record:
                self.pending.pop(key, None)
        if len(self.pending) >= self.BATCH_SIZE:
            self.wake.set()

    async def sweep(self):
        if not self.enabled or time.monotonic() < self.delete_after or not getattr(self.client, "id", None):
            return
        now = datetime.now(timezone.utc)
        cursor = self.collection.find({"bot_id": self.client.id, "due_at": {"$lte": now}}).sort("due_at", 1).limit(500)
        by_chat = defaultdict(list)
        async for record in cursor:
            by_chat[record["chat_id"]].append(record)
        for chat_id, records in by_chat.items():
            if chat_id not in self.enabled:
                await self.collection.delete_many({"_id": {"$in": [r["_id"] for r in records]}})
                continue
            for offset in range(0, len(records), 100):
                batch = records[offset:offset + 100]
                # Only exact IDs returned by this bot's send requests are stored.
                if chat_id not in self.enabled:
                    break
                try:
                    await self.client.delete_messages(chat_id, [r["message_id"] for r in batch])
                except FloodWait as err:
                    self.delete_after = time.monotonic() + max(1, err.value)
                    return
                except Exception as err:
                    # Persist failed IDs with a backoff, without blocking sends.
                    await self.collection.update_many(
                        {"_id": {"$in": [r["_id"] for r in batch]}},
                        {"$set": {"due_at": now + timedelta(minutes=5)}},
                    )
                    self.logger.warning("Cleanup will retry | chat_id=%s | %s", chat_id, type(err).__name__)
                    continue
                await self.collection.delete_many({"_id": {"$in": [r["_id"] for r in batch]}})

    async def run(self):
        try:
            await self.collection.create_index([("bot_id", 1), ("due_at", 1)])
            await self.collection.create_index("expires_at", expireAfterSeconds=0)
        except Exception as err:
            self.logger.warning("Cleanup index setup skipped: %s", type(err).__name__)
        next_sweep = 0.0
        while True:
            self.wake.clear()
            try:
                if not self.settings_loaded:
                    await self.load_settings()
                await self.flush()
                if time.monotonic() >= next_sweep:
                    await self.sweep()
                    next_sweep = time.monotonic() + 30
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.logger.warning("Cleanup worker will retry: %s", type(err).__name__)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            await asyncio.wait_for(self.flush(), timeout=5)
        except Exception:
            pass

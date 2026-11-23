import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from pyrogram.raw.types import InputPeerChat, PeerChat
from pyrogram.errors import FloodWait

spec = importlib.util.spec_from_file_location("message_cleanup", Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/core/message_cleanup.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def raw(name, **kwargs):
    return type(name, (NS,), {})(**kwargs)


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args):
        self.rows.sort(key=lambda r: r["due_at"])
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __aiter__(self):
        return self.iterate()

    async def iterate(self):
        for row in self.rows:
            yield row


class Journal:
    def __init__(self):
        self.rows = {}
        self.bulk_calls = 0

    async def bulk_write(self, operations, **kwargs):
        self.bulk_calls += 1
        for op in operations:
            self.rows.setdefault(op._filter["_id"], op._doc["$setOnInsert"].copy())

    def find(self, query):
        return Cursor([r.copy() for r in self.rows.values()
                       if r["bot_id"] == query["bot_id"] and r["due_at"] <= query["due_at"]["$lte"]])

    async def delete_many(self, query):
        for key, row in list(self.rows.items()):
            if (key in query.get("_id", {}).get("$in", [])
                    or (query.get("bot_id") == row["bot_id"] and query.get("chat_id") == row["chat_id"])):
                self.rows.pop(key)

    async def update_many(self, query, update):
        for key in query["_id"]["$in"]:
            self.rows[key].update(update["$set"])


class MessageCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.worker = cleanup.OutgoingMessageCleanup(Mock())
        self.worker.client = NS(id=42, delete_messages=AsyncMock())
        self.worker.collection = Journal()
        self.worker.enabled.add(-10)

    def capture(self, msg_id, chat=10, method="SendMessage"):
        query = raw(method, peer=InputPeerChat(chat_id=chat))
        result = raw("UpdateShortSentMessage", id=msg_id)
        self.worker.capture(query, result, 42)

    def make_due(self):
        for record in self.worker.collection.rows.values():
            record["due_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    async def test_all_send_paths_are_recorded_without_rpc_or_per_message_tasks(self):
        for index, method in enumerate(("SendMessage", "SendMedia", "SendMultiMedia", "ForwardMessages", "SendInlineBotResult")):
            self.capture(index + 1, method=method)
        self.assertEqual(len(self.worker.pending), 5)
        self.assertIsNone(self.worker.task)
        self.worker.client.delete_messages.assert_not_awaited()
        self.assertEqual(self.worker.collection.bulk_calls, 0)

    async def test_channel_posts_and_albums_are_captured_but_edits_and_other_chats_are_not(self):
        query = raw("SendMultiMedia")
        posts = [raw("UpdateNewChannelMessage", message=NS(id=i, peer_id=PeerChat(chat_id=10), out=False, post=True)) for i in (1, 2)]
        self.worker.capture(query, raw("Updates", updates=posts), 42)
        self.capture(3, method="EditMessage")
        self.capture(4, chat=20)
        self.assertEqual({r["message_id"] for r in self.worker.pending.values()}, {1, 2})

    async def test_records_survive_restart_and_delete_in_batches_of_100(self):
        for i in range(250):
            self.capture(i)
        await self.worker.flush()
        self.assertEqual(self.worker.collection.bulk_calls, 1)
        self.make_due()
        restarted = cleanup.OutgoingMessageCleanup(Mock())
        restarted.client = self.worker.client
        restarted.collection = self.worker.collection
        restarted.enabled.add(-10)
        await restarted.sweep()
        self.assertEqual([len(c.args[1]) for c in restarted.client.delete_messages.call_args_list], [100, 100, 50])
        self.assertFalse(restarted.collection.rows)

    async def test_fresh_messages_are_kept_until_five_minutes_old(self):
        self.capture(1)
        await self.worker.flush()
        await self.worker.sweep()
        self.worker.client.delete_messages.assert_not_awaited()
        self.make_due()
        await self.worker.sweep()
        self.worker.client.delete_messages.assert_awaited_once_with(-10, [1])

    async def test_disabled_setting_discards_cleanup_references_without_deleting_messages(self):
        self.capture(1)
        await self.worker.flush()
        self.capture(2)
        self.worker.set_enabled(-10, False)
        await self.worker.flush()
        await self.worker.sweep()
        self.assertFalse(self.worker.pending)
        self.assertFalse(self.worker.collection.rows)
        self.worker.client.delete_messages.assert_not_awaited()

    async def test_api_failures_keep_journal_for_retry_and_floodwait_is_respected(self):
        self.capture(1)
        await self.worker.flush()
        self.make_due()
        self.worker.client.delete_messages.side_effect = RuntimeError("network down")
        await self.worker.sweep()
        self.assertEqual(len(self.worker.collection.rows), 1)
        self.assertGreater(next(iter(self.worker.collection.rows.values()))["due_at"], datetime.now(timezone.utc))
        self.make_due()
        self.worker.client.delete_messages.side_effect = FloodWait(30)
        await self.worker.sweep()
        count = self.worker.client.delete_messages.await_count
        await self.worker.sweep()
        self.assertEqual(self.worker.client.delete_messages.await_count, count)

    async def test_database_outage_does_not_grow_memory_unbounded(self):
        self.worker.BUFFER_LIMIT = 3
        for i in range(10):
            self.capture(i)
        self.assertEqual(len(self.worker.pending), 3)
        self.worker.logger.warning.assert_called_once()

    async def test_failed_flush_preserves_pending_ids(self):
        self.capture(1)
        self.worker.collection.bulk_write = AsyncMock(side_effect=RuntimeError("database down"))
        with self.assertRaises(RuntimeError):
            await self.worker.flush()
        self.assertEqual(len(self.worker.pending), 1)

    async def test_failed_settings_load_does_not_block_bot_startup(self):
        async def unavailable_settings():
            raise RuntimeError("database unavailable")
            yield -10
        self.worker.run = AsyncMock()
        await self.worker.start(self.worker.client, self.worker.collection, unavailable_settings)
        self.assertIsNotNone(self.worker.task)
        await self.worker.stop()

    async def test_settings_retry_preserves_changes_made_since_startup(self):
        async def old_snapshot():
            yield -10
        self.worker.settings_loader = old_snapshot
        self.worker.set_enabled(-10, False)
        self.worker.set_enabled(-20, True)
        await self.worker.load_settings()
        self.assertEqual(self.worker.enabled, {-20})

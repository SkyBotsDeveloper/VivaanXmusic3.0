import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location(
    "bot_start_retry", Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/core/bot_start_retry.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BotStartRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_recovers_with_backoff_after_authorization_failure(self):
        failure = TimeoutError('Failed to invoke "auth.ImportBotAuthorization" after 10 retries')
        start = AsyncMock(side_effect=[failure, failure, "ready"])
        with patch.object(module.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            self.assertEqual(await module.start_with_telegram_retry(start, Mock()), "ready")
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [30, 60])

    async def test_unrelated_timeout_is_not_hidden(self):
        start = AsyncMock(side_effect=TimeoutError("different timeout"))
        with self.assertRaisesRegex(TimeoutError, "different timeout"):
            await module.start_with_telegram_retry(start, Mock())

    async def test_cancellation_propagates(self):
        start = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await module.start_with_telegram_retry(start, Mock())


class BotLoginDcTest(unittest.IsolatedAsyncioTestCase):
    def client(self, user_id=None, dc_id=2):
        storage = SimpleNamespace(
            user_id=AsyncMock(return_value=user_id), dc_id=AsyncMock(return_value=dc_id),
            server_address=AsyncMock(), port=AsyncMock(), auth_key=AsyncMock(),
        )
        return SimpleNamespace(
            storage=storage, ipv6=False, session=SimpleNamespace(stop=AsyncMock()),
            get_dc_option=AsyncMock(return_value=SimpleNamespace(ip_address="dc5.example", port=443)),
            get_session=AsyncMock(return_value=SimpleNamespace(auth_key=b"new-dc-key")),
        )

    async def test_fresh_login_uses_new_dc_auth_key_without_exporting_auth(self):
        client = self.client()
        old_session = client.session
        self.assertTrue(await module.select_bot_login_dc(client, 5))
        old_session.stop.assert_awaited_once()
        client.get_session.assert_awaited_once_with(
            dc_id=5, server_address="dc5.example", port=443,
            export_authorization=False, temporary=True,
        )
        client.storage.auth_key.assert_awaited_once_with(b"new-dc-key")
        self.assertEqual(client.storage.dc_id.await_args.args, (5,))

    async def test_existing_authorization_or_matching_dc_is_preserved(self):
        for client in (self.client(user_id=123), self.client(dc_id=5)):
            self.assertFalse(await module.select_bot_login_dc(client, 5))
            client.get_session.assert_not_awaited()
            client.session.stop.assert_not_awaited()

    async def test_default_automatic_login_does_not_touch_storage(self):
        client = self.client()
        self.assertFalse(await module.select_bot_login_dc(client, 0))
        client.storage.user_id.assert_not_awaited()
        client.get_dc_option.assert_not_awaited()

    async def test_failed_dc_lookup_keeps_current_connection(self):
        client = self.client()
        client.get_dc_option.side_effect = OSError("temporary lookup failure")
        with self.assertRaises(OSError):
            await module.select_bot_login_dc(client, 5)
        client.session.stop.assert_not_awaited()

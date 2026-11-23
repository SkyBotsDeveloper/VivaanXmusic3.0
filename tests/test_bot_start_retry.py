import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch


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

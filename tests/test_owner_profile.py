import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


spec = importlib.util.spec_from_file_location(
    "owner_profile", Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/core/owner_profile.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OwnerProfileTest(unittest.IsolatedAsyncioTestCase):
    async def test_username_is_resolved_from_configured_owner_id(self):
        client = SimpleNamespace(get_users=AsyncMock(return_value=SimpleNamespace(id=777, username="actual_owner")))
        self.assertEqual(await module.resolve_owner_profile_url(client, 777, Mock()),
                         "https://t.me/actual_owner?profile")
        client.get_users.assert_awaited_once_with(777)

    async def test_missing_username_or_unrelated_user_keeps_configured_id(self):
        for user in (SimpleNamespace(id=777, username=None),
                     SimpleNamespace(id=999, username="wrong_owner")):
            client = SimpleNamespace(get_users=AsyncMock(return_value=user))
            self.assertEqual(await module.resolve_owner_profile_url(client, 777, Mock()), "tg://user?id=777")

    async def test_lookup_failure_does_not_break_bot_startup(self):
        client = SimpleNamespace(get_users=AsyncMock(side_effect=TimeoutError()))
        self.assertEqual(await module.resolve_owner_profile_url(client, 777, Mock()), "tg://user?id=777")

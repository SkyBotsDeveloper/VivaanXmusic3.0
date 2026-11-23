import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

spec = importlib.util.spec_from_file_location("vc_identity", Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/core/vc_identity.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class VcIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_event_metadata_avoids_user_lookup(self):
        resolver = identity.VcIdentityResolver()
        resolver.remember({77: NS(id=77, first_name="Sky", last_name="User", username="skyuser")})
        bot = NS(get_users=AsyncMock(side_effect=RuntimeError("unknown peer")))
        self.assertEqual(await resolver.resolve(77, [bot]), ("Sky User", "skyuser"))
        bot.get_users.assert_not_awaited()

    async def test_assistant_resolves_people_unknown_to_bot(self):
        resolver = identity.VcIdentityResolver()
        bot = NS(get_users=AsyncMock(side_effect=RuntimeError("PEER_ID_INVALID")))
        assistant = NS(get_users=AsyncMock(return_value=NS(id=77, first_name="New Listener", username=None)))
        self.assertEqual(await resolver.resolve(77, [bot, assistant]), ("New Listener", None))

    async def test_inaccessible_accounts_use_numeric_identity_and_do_not_retry_storm(self):
        resolver = identity.VcIdentityResolver()
        bot = NS(get_users=AsyncMock(side_effect=TimeoutError()))
        self.assertEqual(await resolver.resolve(77, [bot]), ("77", None))
        await resolver.resolve(77, [bot])
        bot.get_users.assert_awaited_once()
        resolver.remember([NS(id=77, first_name="Recovered", username="back")])
        self.assertEqual(await resolver.resolve(77, [bot]), ("Recovered", "back"))

    async def test_minimal_updates_keep_names_and_full_updates_remove_old_username(self):
        resolver = identity.VcIdentityResolver(limit=2)
        resolver.remember([NS(id=77, first_name="A", username="old")])
        resolver.remember([NS(id=77, first_name="B", min=True)])
        self.assertEqual(resolver.cached(77), ("B", "old"))
        resolver.remember([NS(id=77, first_name="B", username=None)])
        self.assertEqual(resolver.cached(77), ("B", None))
        resolver.remember([NS(id=i, first_name=str(i)) for i in range(10)])
        self.assertEqual(len(resolver.cache), 2)

    async def test_names_are_html_escaped_and_user_id_is_always_present(self):
        text = identity.vc_join_text(-10, 77, "<Admin & Co>", "skyuser", external=True)
        self.assertIn("&lt;Admin &amp; Co&gt;", text)
        self.assertIn("@skyuser", text)
        self.assertIn("User ID: <code>77</code>", text)
        self.assertIn("Group ID: <code>-10</code>", text)
        self.assertNotIn("tg://user", text)
        self.assertNotIn("Unknown", identity.vc_join_text(-10, 77, None))

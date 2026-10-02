import ast
import importlib.util
import logging
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "VIVAANXMUSIC" / "utils" / "esse_autoplay.py"
SPEC = importlib.util.spec_from_file_location("esse_autoplay_under_test", MODULE_PATH)
esse = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(esse)
REAL_ASYNC_CLIENT = httpx.AsyncClient
SECURITY_PATH = ROOT / "VIVAANXMUSIC" / "security.py"
SECURITY_SPEC = importlib.util.spec_from_file_location(
    "security_under_test", SECURITY_PATH
)
security = importlib.util.module_from_spec(SECURITY_SPEC)
SECURITY_SPEC.loader.exec_module(security)


def response_payload(recommendations=None):
    recommendations = recommendations or [
        {"title": "All of Me", "artist": "John Legend"}
    ]
    return {
        "seed": {"title": "Perfect"},
        "recommendations": recommendations,
        "count": len(recommendations),
    }


class EsseAutoplayTest(IsolatedAsyncioTestCase):
    def client_patch(self, handler):
        transport = httpx.MockTransport(handler)
        return patch.object(
            esse.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: REAL_ASYNC_CLIENT(
                transport=transport, **kwargs
            ),
        )

    async def test_success_sends_one_authenticated_request_and_validates_candidates(self):
        calls = []

        def handler(request):
            calls.append(request)
            self.assertEqual(str(request.url), "https://esse.example/v1/recommend")
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            self.assertEqual(
                request.read(), b'{"song":"Perfect","limit":5}'
            )
            return httpx.Response(200, json=response_payload())

        with patch.multiple(
            esse,
            ESSE_API_KEY="test-secret",
            ESSE_API_URL="https://esse.example/",
            ESSE_TIMEOUT="7",
        ), self.client_patch(handler):
            result = await esse.get_recommendations("Perfect")

        self.assertEqual(result, [{"title": "All of Me", "artist": "John Legend"}])
        self.assertEqual(len(calls), 1)

    async def test_missing_key_makes_no_http_request(self):
        with patch.multiple(esse, ESSE_API_KEY=""), patch.object(
            esse.httpx, "AsyncClient"
        ) as client:
            self.assertIsNone(await esse.get_recommendations("Perfect"))
        client.assert_not_called()

    async def test_timeout_http_failures_and_invalid_json_fall_back(self):
        cases = {
            "timeout": lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout("timed out", request=request)
            ),
            "429": lambda request: httpx.Response(429, request=request),
            "503": lambda request: httpx.Response(503, request=request),
            "invalid-json": lambda request: httpx.Response(
                200, content=b"not-json", request=request
            ),
        }
        for name, handler in cases.items():
            with self.subTest(name=name):
                fallback = AsyncMock(return_value={"vidid": "legacy"})
                with patch.multiple(esse, ESSE_API_KEY="test-secret"), self.client_patch(handler):
                    with self.assertLogs(esse.logger, level=logging.INFO) as captured:
                        result = await esse.select_or_fallback(
                            "Perfect", None, AsyncMock(), fallback
                        )
                self.assertEqual(result, {"vidid": "legacy"})
                fallback.assert_awaited_once_with()
                logs = "\n".join(captured.output)
                self.assertIn("Autoplay legacy recommendation used", logs)
                self.assertNotIn("Autoplay ESSE recommendation selected", logs)

    async def test_malformed_schema_falls_back(self):
        malformed = [
            {"seed": {"title": "Perfect"}, "recommendations": [], "count": 1},
            {
                "seed": {"title": "Perfect"},
                "recommendations": [{"title": "All of Me", "artist": ""}],
                "count": 1,
            },
            {
                "seed": {"title": "Perfect"},
                "recommendations": [
                    {"title": "Song", "artist": "Artist"} for _ in range(6)
                ],
                "count": 6,
            },
        ]
        for payload in malformed:
            fallback = AsyncMock(return_value="legacy")
            handler = lambda request, body=payload: httpx.Response(
                200, json=body, request=request
            )
            with patch.multiple(esse, ESSE_API_KEY="test-secret"), self.client_patch(handler):
                result = await esse.select_or_fallback(
                    "Perfect", None, AsyncMock(), fallback
                )
            self.assertEqual(result, "legacy")
            fallback.assert_awaited_once_with()

    async def test_candidates_are_resolved_in_order_until_playable(self):
        candidates = [
            {"title": "First", "artist": "A"},
            {"title": "Second", "artist": "B"},
        ]
        resolver = AsyncMock(side_effect=[None, {"vidid": "playable"}])
        fallback = AsyncMock(return_value="legacy")
        with patch.object(esse, "get_recommendations", AsyncMock(return_value=candidates)):
            with self.assertLogs(esse.logger, level=logging.INFO) as captured:
                result = await esse.select_or_fallback("Seed", None, resolver, fallback)
        self.assertEqual(result, {"vidid": "playable"})
        self.assertEqual(resolver.await_count, 2)
        fallback.assert_not_awaited()
        self.assertIn("Autoplay ESSE recommendation selected", "\n".join(captured.output))

    async def test_all_unplayable_candidates_use_legacy_fallback(self):
        resolver = AsyncMock(return_value=None)
        fallback = AsyncMock(return_value={"vidid": "legacy"})
        with patch.object(
            esse,
            "get_recommendations",
            AsyncMock(
                return_value=[
                    {"title": "A", "artist": "One"},
                    {"title": "B", "artist": "Two"},
                ]
            ),
        ):
            result = await esse.select_or_fallback("Seed", None, resolver, fallback)
        self.assertEqual(result, {"vidid": "legacy"})
        self.assertEqual(resolver.await_count, 2)
        fallback.assert_awaited_once_with()

    async def test_missing_key_uses_legacy_and_preserves_track_structure(self):
        legacy_track = {
            "title": "Legacy Song",
            "duration_min": "3:12",
            "duration_sec": 192,
            "thumb": "https://img.example/legacy.jpg",
            "vidid": "legacy-id",
            "link": "https://www.youtube.com/watch?v=legacy-id",
        }
        fallback = AsyncMock(return_value=legacy_track)
        with patch.multiple(esse, ESSE_API_KEY=""):
            with self.assertLogs(esse.logger, level=logging.INFO) as captured:
                result = await esse.select_or_fallback(
                    "Seed", None, AsyncMock(), fallback
                )
        self.assertEqual(result, legacy_track)
        self.assertEqual(set(result), {"title", "duration_min", "duration_sec", "thumb", "vidid", "link"})
        fallback.assert_awaited_once_with()
        logs = "\n".join(captured.output)
        self.assertIn("Autoplay legacy recommendation used", logs)
        self.assertNotIn("Autoplay ESSE recommendation selected", logs)

    async def test_candidate_resolution_failure_does_not_escape_or_skip_fallback(self):
        fallback = AsyncMock(return_value="legacy")
        with patch.object(
            esse, "get_recommendations", AsyncMock(return_value=[{"title": "A", "artist": "B"}])
        ):
            result = await esse.select_or_fallback(
                "Seed", None, AsyncMock(side_effect=RuntimeError("private details")), fallback
            )
        self.assertEqual(result, "legacy")
        fallback.assert_awaited_once_with()

    async def test_secret_is_not_written_to_failure_logs(self):
        secret = "never-log-this-test-secret"
        with patch.multiple(esse, ESSE_API_KEY=secret), self.client_patch(
            lambda request: httpx.Response(401, request=request)
        ), self.assertLogs(esse.logger, level=logging.WARNING) as captured:
            await esse.get_recommendations("Perfect")
        self.assertNotIn(secret, "\n".join(captured.output))

    def test_seed_and_both_duration_limits_are_enforced(self):
        valid = ("Next Song", "next-id", 180, "https://img.example/thumb.jpg")
        self.assertTrue(
            esse.is_playable_autoplay_metadata(*valid, "seed-id", 300, 240)
        )
        self.assertFalse(
            esse.is_playable_autoplay_metadata(
                "Seed", "seed-id", 180, valid[3], "seed-id", 300, 240
            )
        )
        self.assertFalse(
            esse.is_playable_autoplay_metadata(*valid[:2], 301, valid[3], "seed-id", 300, 400)
        )
        self.assertFalse(
            esse.is_playable_autoplay_metadata(*valid[:2], 241, valid[3], "seed-id", 300, 240)
        )
        self.assertFalse(
            esse.is_playable_autoplay_metadata(*valid[:3], None, "seed-id", 300, 240)
        )

    def test_esse_key_is_registered_as_sensitive(self):
        self.assertTrue(security._looks_sensitive_env_name("ESSE_API_KEY"))
        self.assertIn("ESSE_API_KEY", security.SECRET_CONFIG_ATTRS)

    def test_youtube_integration_reuses_current_autoplay_validation_and_legacy_order(self):
        youtube_path = ROOT / "VIVAANXMUSIC" / "platforms" / "Youtube.py"
        tree = ast.parse(youtube_path.read_text(encoding="utf-8"))
        api_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "YouTubeAPI"
        )
        methods = {node.name: node for node in api_class.body if isinstance(node, ast.AsyncFunctionDef)}
        autoplay = methods["autoplay"]
        resolver = methods["_resolve_autoplay_candidates"]
        calls = [
            node.func.attr
            for node in ast.walk(resolver)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("_format_autoplay_candidate", calls)
        self.assertIn("select_or_fallback", [
            node.func.id
            for node in ast.walk(autoplay)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ])
        legacy = next(
            node
            for node in ast.walk(autoplay)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "legacy_autoplay"
        )
        legacy_calls = [
            node.func.attr
            for node in ast.walk(legacy)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertLess(legacy_calls.index("get"), legacy_calls.index("next"))
        self.assertIn("_resolve_autoplay_candidates", legacy_calls)

"""Provider contracts, failure routing and real local outputs without bot startup."""

import asyncio
import base64
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


security = load("public_test_security", "VIVAANXMUSIC/security.py")
with patch.dict(sys.modules, {"config": ModuleType("config"), "VIVAANXMUSIC.security": security}):
    ai = load("public_test_ai", "VIVAANXMUSIC/utils/free_ai.py")
    uploads = load("public_test_uploads", "VIVAANXMUSIC/utils/file_upload.py")
    social = load("public_test_social", "VIVAANXMUSIC/utils/socialdown.py")
movie = load("public_test_movie", "VIVAANXMUSIC/utils/movie_lookup.py")
anime = load("public_test_anime", "VIVAANXMUSIC/utils/anime_images.py")


def image_bytes():
    image = Image.new("RGB", (80, 60), "white")
    ImageDraw.Draw(image).rectangle((20, 10, 60, 50), fill=(210, 35, 45))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class PublicAITest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ai.PROVIDER_COOLDOWNS.clear()
        ai._public_chat_semaphore = asyncio.Semaphore(2)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fixture.png"
        self.path.write_bytes(image_bytes())

    def test_chat_contract_uses_cpu_and_only_assistant_text(self):
        result = ([{"role": "user", "content": "Question"},
                   {"role": "assistant", "content": [{"type": "text", "text": "56"}]}], "")
        client = SimpleNamespace(submit=Mock(return_value=SimpleNamespace(result=Mock(return_value=result))))
        with patch.object(ai, "_run_with_hf_client", side_effect=lambda space, runner, **kwargs: runner(client)):
            self.assertEqual(ai._run_public_chat("Question", "SmolLM2 1.7B Instruct", 10), "56")
            args, kwargs = client.submit.call_args
            self.assertEqual(args, ("Question", [], "SmolLM2 1.7B Instruct", "CPU", 256))
            self.assertEqual(kwargs["api_name"], "/respond")
            client.submit.return_value.result.return_value = ([{"role": "user", "content": "Question"}], "")
            with self.assertRaises(ai.FreeAIError):
                ai._run_public_chat("Question", "SmolLM2 1.7B Instruct", 10)

    async def test_every_chat_alias_routes_to_actual_public_model(self):
        with patch.object(ai, "_run_public_chat", return_value="56") as runner:
            for alias in ("gpt", "chatgpt", "eliteai", "bard", "gemini", "llama", "mistral", "claude", "jarvis", "assis"):
                response = await ai.generate_chat_response("Calculate seven times eight.", alias=alias)
                self.assertEqual(response.content, "56")
                self.assertEqual(response.model, "SmolLM2 1.7B Instruct")
            self.assertEqual(runner.call_count, 10)

    async def test_chat_failure_falls_back_without_requesting_credentials(self):
        with patch.object(ai, "_run_public_chat", side_effect=[ai.FreeAIError("Queue is full"), "Working answer"]):
            result = await ai.generate_chat_response("Explain rain.")
        self.assertEqual(result.model, "SmolLM2 360M Instruct")
        self.assertEqual(result.content, "Working answer")

    async def test_identity_reports_open_model_truthfully(self):
        with patch.object(ai, "_run_public_chat") as runner:
            result = await ai.generate_chat_response("What model are you?", alias="claude")
        self.assertIn("SmolLM2", result.content)
        self.assertNotIn("Opus", result.content)
        runner.assert_not_called()

    async def test_image_fallback_validates_output_and_preserves_source(self):
        with patch.object(ai, "_run_public_image_generation", side_effect=[ai.FreeAIError("Timeout"), str(self.path)]) as runner:
            data = await ai.generate_image("A boat on a lake.")
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(Image.open(io.BytesIO(data)).size, (80, 60))
        self.assertTrue(self.path.exists())
        self.assertEqual([call.kwargs["use_cpu"] for call in runner.call_args_list], [True, False])

    async def test_encoded_editor_output_and_corrupt_image(self):
        uri = "data:image/png;base64," + base64.b64encode(image_bytes()).decode()
        output = await ai._ensure_local_image(uri)
        try:
            with Image.open(output) as image:
                self.assertEqual(image.size, (80, 60))
        finally:
            Path(output).unlink()
        with self.assertRaises(ai.FreeAIError):
            await ai._ensure_local_image("data:image/png;base64," + base64.b64encode(b"<html>Error</html>").decode())

    async def test_video_output_keeps_mp4_extension_and_preserves_shared_file(self):
        source = ROOT / "VIVAANXMUSIC/assets/vivaan/cute.mp4"
        output = Path(await ai._ensure_local_video(str(source)))
        try:
            self.assertEqual(output.suffix, ".mp4")
            self.assertEqual(output.read_bytes(), source.read_bytes())
            self.assertNotEqual(output, source)
        finally:
            output.unlink()
        self.assertTrue(source.exists())

    def test_editor_contract_serializes_images_for_current_api(self):
        result = {"image": "data:image/png;base64," + base64.b64encode(image_bytes()).decode()}
        client = SimpleNamespace(submit=Mock(return_value=SimpleNamespace(result=Mock(return_value=result))))
        with patch.object(ai, "_run_with_hf_client", side_effect=lambda space, runner, **kwargs: runner(client)):
            for runner, prompt in ((ai._run_object_manipulator_edit, "add a hat"), (ai._run_style_lora_edit, "make this anime")):
                output = runner(prompt, [str(self.path)], timeout_seconds=10)
                self.assertTrue(output.startswith("data:image/png;base64,"))
                args, kwargs = client.submit.call_args
                self.assertEqual(kwargs["api_name"], "/edit_image")
                encoded = json.loads(args[0])
                self.assertEqual(base64.b64decode(encoded[0]), image_bytes())

    def test_preview2_current_dropdown_and_safety_parameters(self):
        client = SimpleNamespace(submit=Mock(return_value=SimpleNamespace(result=Mock(return_value="output.mp4"))))
        with patch.object(ai, "_run_with_hf_client", side_effect=lambda space, runner, **kwargs: runner(client)):
            ai._run_wan22_preview2_video("Gentle motion", str(self.path), 10)
        args, kwargs = client.submit.call_args
        self.assertEqual(kwargs["api_name"], "/generate_video")
        self.assertEqual(len(args), 19)
        self.assertEqual(args[14:], ("2xNomosUni_compact_otf_medium", 1.0, True, True, True))

    async def test_upscale_and_basic_edit_remain_available_without_network(self):
        enhanced = await ai.process_image_bytes(image_bytes(), mode="enhance", mime_type="image/png")
        self.assertEqual(Image.open(io.BytesIO(enhanced)).size, (160, 120))
        with patch.object(ai, "_run_qwen_image_edit_space") as remote:
            edited = await ai.edit_image_bytes("make this grayscale", images=[(image_bytes(), "image/png")])
        channels = Image.open(io.BytesIO(edited)).convert("RGB").split()
        self.assertEqual(channels[0].tobytes(), channels[1].tobytes())
        self.assertEqual(channels[1].tobytes(), channels[2].tobytes())
        remote.assert_not_called()

    async def test_removebg_rejects_opaque_result_then_uses_local_fallback(self):
        with patch.object(ai, "_run_public_removebg", return_value=str(self.path)):
            data = await ai.process_image_bytes(image_bytes(), mode="removebg", mime_type="image/png")
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.mode, "RGBA")
        self.assertLess(image.getchannel("A").getextrema()[0], 255)
        self.assertTrue(self.path.exists())

    async def test_video_backend_outage_still_produces_real_playable_backup(self):
        with patch.object(ai, "_run_video_provider_batch", new=AsyncMock(return_value=None)), patch.object(ai, "REPLICATE_TOKEN_POOL", []):
            result = await ai.generate_video("Gentle motion", image_bytes=image_bytes(), mime_type="image/png")
        try:
            info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_name,nb_frames", "-of", "json", result.file_path], text=True))
            self.assertEqual(info["streams"][0]["codec_name"], "h264")
            self.assertEqual(int(info["streams"][0]["nb_frames"]), 96)
            self.assertEqual(float(info["format"]["duration"]), 4)
            self.assertTrue(result.used_reference_image)
            self.assertIn("Local backup", result.provider)
        finally:
            Path(result.file_path).unlink()


class MovieTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_title_does_not_return_arbitrary_movie(self):
        with patch.object(movie.httpx, "AsyncClient") as client:
            self.assertEqual(await movie.get_movie_info("  "), "Movie not found.")
        client.assert_not_called()

    async def test_keyless_metadata_enrichment_and_html_escaping(self):
        requests = []
        def handler(request):
            requests.append(request)
            if "wikipedia" in request.url.host:
                return httpx.Response(200, json={"query": {"pages": [
                    {"title": "Wrong movie", "index": 1, "extract": "A film about someone else."},
                    {"title": "Example (2020 film)", "index": 2, "extract": "A film with <unsafe> & markup.",
                     "pageprops": {"wikibase_item": "Q123"}},
                ]}})
            if request.url.params["props"] == "claims|labels":
                return httpx.Response(200, json={"entities": {"Q123": {"claims": {
                    "P2047": [{"mainsnak": {"datavalue": {"value": {"amount": "+120", "unit": "http://www.wikidata.org/entity/Q7727"}}}}],
                }}}})
            raise AssertionError("Unexpected request")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(movie.httpx, "AsyncClient", return_value=client):
            result = await movie.get_movie_info("Example 2020")
        self.assertIn("Title:</b> Example", result)
        self.assertIn("120 min", result)
        self.assertIn("&lt;unsafe&gt; &amp; markup", result)
        self.assertIn("Rating:</b> N/A", result)
        self.assertTrue(all("api_key" not in str(request.url) for request in requests))

    async def test_unrelated_search_results_are_not_wrong_movie_success(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={"query": {"pages": [{"title": "Another film", "extract": "A film."}]}})))
        with patch.object(movie.httpx, "AsyncClient", return_value=client):
            self.assertEqual(await movie.get_movie_info("NonexistentXYZ"), "Movie not found.")


class AnimeTest(unittest.TestCase):
    def test_unsupported_category_does_not_call_dead_endpoint_or_mislabel_fallback(self):
        response = Mock()
        response.json.return_value = {"results": [{"url": "https://example.com/waifu.png"}]}
        with patch.object(anime, "_supported_categories", return_value={"waifu": "png"}), patch.object(anime.requests, "get", return_value=response) as get:
            result = anime.get_waifu_data("awoo")
        self.assertEqual(get.call_args.args[0], "https://nekos.best/api/v2/waifu")
        self.assertEqual(result["images"][0]["tag"], "waifu")

    def test_animation_format_is_preserved(self):
        response = Mock()
        response.json.return_value = {"results": [{"url": "https://example.com/hug.gif"}]}
        with patch.object(anime, "_supported_categories", return_value={"hug": "gif", "waifu": "png"}), patch.object(anime.requests, "get", return_value=response):
            self.assertEqual(anime.get_waifu_data("hug")["images"][0]["format"], "gif")


class UploadTest(unittest.IsolatedAsyncioTestCase):
    async def test_html_and_truncated_downloads_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.png"
            path.write_bytes(image_bytes())
            response = SimpleNamespace(status=200, headers={}, content=SimpleNamespace(readexactly=AsyncMock(return_value=b"<html>wrong file</html>")))
            context = AsyncMock()
            context.__aenter__.return_value = response
            session = SimpleNamespace(get=Mock(return_value=context))
            with patch.object(uploads, "validate_public_http_url", side_effect=lambda url, **kwargs: url):
                with self.assertRaisesRegex(RuntimeError, "does not return"):
                    await uploads._verify_upload(session, "https://example.com/file.png", str(path))
                response.headers = {"Content-Length": "1"}
                with self.assertRaisesRegex(RuntimeError, "different file size"):
                    await uploads._verify_upload(session, "https://example.com/file.png", str(path))

    async def test_failed_provider_or_bad_link_falls_back_to_verified_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.png"
            path.write_bytes(image_bytes())
            first = AsyncMock(return_value="https://example.com/bad")
            second = AsyncMock(return_value="https://example.com/good")
            with patch.object(uploads, "UPLOAD_PROVIDERS", (("Bad", first), ("Good", second))), patch.object(uploads, "_verify_upload", new=AsyncMock(side_effect=[RuntimeError("HTML"), None])):
                result = await uploads.upload_file_with_fallbacks(str(path))
            self.assertTrue(result.ok)
            self.assertEqual(result.provider, "Good")
            self.assertEqual(result.url, "https://example.com/good")


class SocialTest(unittest.IsolatedAsyncioTestCase):
    async def test_direct_extraction_preserves_carousel_and_public_download_headers(self):
        extractor = Mock()
        extractor.extract_info.return_value = {"title": "Post", "entries": [
            {"title": "One", "url": "https://example.com/one.mp4", "ext": "mp4", "protocol": "https",
             "http_headers": {"Referer": "https://www.instagram.com/", "Cookie": "must-not-forward"}},
            {"title": "Two", "url": "https://example.com/two.jpg", "ext": "jpg", "protocol": "https"},
        ]}
        context = Mock()
        context.__enter__ = Mock(return_value=extractor)
        context.__exit__ = Mock(return_value=False)
        with patch.object(social.yt_dlp, "YoutubeDL", return_value=context), patch.object(social, "validate_public_http_url", side_effect=lambda url, **kwargs: url):
            result = await social._fetch_social_via_yt_dlp("https://www.instagram.com/p/example/")
        self.assertEqual([item.kind for item in result.items], ["video", "photo"])
        self.assertEqual(result.items[0].headers, {"Referer": "https://www.instagram.com/"})

    async def test_manifest_is_not_downloaded_as_if_it_were_video(self):
        extractor = Mock()
        extractor.extract_info.return_value = {"title": "Post", "url": "https://example.com/video.m3u8", "protocol": "m3u8_native"}
        context = Mock()
        context.__enter__ = Mock(return_value=extractor)
        context.__exit__ = Mock(return_value=False)
        with patch.object(social.yt_dlp, "YoutubeDL", return_value=context):
            with self.assertRaises(social.SocialDownloadError):
                await social._fetch_social_via_yt_dlp("https://www.instagram.com/p/example/")


if __name__ == "__main__":
    unittest.main()

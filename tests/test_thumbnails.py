"""Real Pillow rendering and playback-thumbnail flow, without bot startup."""

import asyncio
import ast
import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = load("player_test_renderer", "VIVAANXMUSIC/utils/thumbnail_renderer.py")
package = ModuleType("VIVAANXMUSIC")
package.app = SimpleNamespace(name="VivaanXMusic", id=99)
config = ModuleType("config")
config.BOT_NAME = "VivaanXMusic"
config.YOUTUBE_IMG_URL = "https://example.com/fallback.jpg"
directories = ModuleType("VIVAANXMUSIC.core.dir")
directories.CACHE_DIR = "cache"
with patch.dict(sys.modules, {"VIVAANXMUSIC": package, "config": config,
                             "VIVAANXMUSIC.core.dir": directories,
                             "VIVAANXMUSIC.utils.thumbnail_renderer": renderer}):
    thumbs = load("player_test_thumbnails", "VIVAANXMUSIC/utils/thumbnails.py")


def art(size=(960, 540), color="red"):
    image = Image.new("RGB", size, color)
    ImageDraw.Draw(image).rectangle((0, 0, size[0] // 5, size[1]), fill="gold")
    return image


class RendererTest(unittest.TestCase):
    def test_artwork_and_avatar_fill_correct_player_slots(self):
        artwork, avatar = art(), Image.new("RGB", (240, 320), "blue")
        result = renderer.render_thumbnail(artwork, avatar,
            "Adele - Hello (Official Video)", "6:07", "3B views", "Adele", "VivaanXMusic")
        self.assertEqual(result.size, (1280, 720))
        self.assertEqual(result.mode, "RGB")
        for mask, color in zip(renderer._load_template()[1], [(255, 0, 0), (0, 0, 255)]):
            x1, y1, x2, y2 = mask.getbbox()
            self.assertEqual(result.getpixel(((x1 + x2) // 2, (y1 + y2) // 2)), color)

    def test_fallback_profile_is_black_with_centered_no_dp_label(self):
        avatar = renderer._fallback_profile()
        self.assertEqual(avatar.getpixel((4, 4)), (4, 6, 10))
        pixels = avatar.convert("L").get_flattened_data()
        self.assertGreater(sum(value < 30 for value in pixels), len(pixels) * 0.8)
        self.assertGreater(sum(value > 210 for value in pixels), 1000)
        bounds = ImageDraw.Draw(avatar).textbbox((0, 0), "NO DP", font=renderer._font(renderer.FONT_BOLD, 480 // 7))
        self.assertLess(bounds[2] - bounds[0], avatar.width)
        avatar.close()

    def test_album_art_fills_box_without_cutting_top_or_bottom(self):
        mask = renderer._load_template()[1][0]
        box = mask.getbbox()
        source = Image.new("RGB", (960, 540), "green")
        draw = ImageDraw.Draw(source)
        draw.rectangle((0, 0, 959, 119), fill="red")
        draw.rectangle((0, 420, 959, 539), fill="blue")
        canvas = Image.new("RGB", renderer.CANVAS_SIZE, "black")
        renderer._paste_slot(canvas, source, mask, preserve_full_image=True)
        center_x = (box[0] + box[2]) // 2
        self.assertEqual(canvas.getpixel((center_x, box[1] + 20)), (255, 0, 0))
        self.assertEqual(canvas.getpixel((center_x, box[3] - 31)), (0, 0, 255))

    def test_long_multilingual_titles_and_portrait_artwork_render(self):
        image = renderer.render_thumbnail(art((300, 900)), Image.new("RGB", (1, 1), "blue"),
            "अरिजीत सिंह - " + "A very long song name " * 15 + "[Official Audio]", "LIVE",
            "Unknown Views", "An extremely long channel " * 10, "VivaanXMusic")
        self.assertEqual(image.size, (1280, 720))
        self.assertIsNotNone(image.getbbox())
        display, badge = renderer._split_title("Adele - Hello (Official Video)", "Adele")
        self.assertEqual((display, badge), ("Hello", "Official Video"))
        draw = ImageDraw.Draw(image)
        for title in ("UnbrokenTitle" * 80, "A very long song name " * 30):
            font, lines = renderer._title_layout(draw, title, 558)
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(draw.textlength(line, font=font) <= 558 for line in lines))

    def test_neon_colors_follow_artwork(self):
        red = renderer._recolor_template(*renderer._extract_accent_colors(art(color="red")))
        green = renderer._recolor_template(*renderer._extract_accent_colors(art(color="green")))
        self.assertGreater(red.getpixel((700, 458))[0], green.getpixel((700, 458))[0])
        self.assertGreater(green.getpixel((700, 458))[1], red.getpixel((700, 458))[1])
        self.assertIsNotNone(ImageChops.difference(red.convert("RGB"), green.convert("RGB")).getbbox())
        for region in ((35, 25, 495, 440), (875, 70, 1240, 415),
                       (60, 450, 1220, 470), (785, 490, 1180, 610),
                       (105, 640, 1175, 665)):
            self.assertIsNotNone(ImageChops.difference(red.crop(region), green.crop(region)).getbbox())

    def test_partial_render_is_never_published_and_temp_is_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "card.png"
            broken = Mock()
            def fail(path, **kwargs):
                Path(path).write_bytes(b"incomplete png")
                raise OSError("Disk write failed")
            broken.save.side_effect = fail
            with patch.object(renderer, "render_thumbnail", return_value=broken):
                with self.assertRaises(OSError):
                    renderer.render_and_save_thumbnail(str(output), None, None, "Title", "3:00", "1M", "Channel", "Vivaan")
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            broken.close.assert_called_once()


class ThumbnailFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name)
        self.artwork = self.cache / "art.jpg"
        art().save(self.artwork)
        self.search = Mock()
        self.search.next = AsyncMock(return_value={"result": [{
            "title": "Adele - Hello (Official Video)", "duration": "6:07",
            "viewCount": {"short": "3B views"}, "channel": {"name": "Adele"},
        }]})
        async def no_photos(*args, **kwargs):
            if False:
                yield
        self.bot = SimpleNamespace(name="VivaanXMusic", id=99, get_chat_photos=no_photos, download_media=AsyncMock())
        thumbs._player_thumbnail_tasks.clear()
        thumbs._player_artwork_tasks.clear()
        thumbs._player_render_semaphore = asyncio.Semaphore(2)
        for target, value in (("CACHE_DIR", str(self.cache)), ("app", self.bot),
                              ("VideosSearch", Mock(return_value=self.search)),
                              ("resolve_artwork_image", AsyncMock(return_value=(str(self.artwork), "official")))):
            p = patch.object(thumbs, target, value)
            p.start()
            self.addCleanup(p.stop)

    async def test_concurrent_same_song_and_requester_use_one_complete_cached_card(self):
        with patch.object(thumbs, "render_and_save_thumbnail", wraps=renderer.render_and_save_thumbnail) as render:
            paths = await asyncio.gather(*(thumbs.get_thumb("video-id", 7) for _ in range(8)))
            self.assertEqual(len(set(paths)), 1)
            with Image.open(paths[0]) as result:
                self.assertEqual(result.size, (1280, 720))
            self.assertEqual(render.call_count, 1)
            self.search.next.assert_awaited_once()
            self.assertEqual(await thumbs.get_thumb("video-id", 7), paths[0])
            self.assertEqual(render.call_count, 1)
        self.assertTrue(self.artwork.exists())

    async def test_different_requesters_share_artwork_but_not_player_card(self):
        async def resolve(*args, **kwargs):
            await asyncio.sleep(0.03)
            return str(self.artwork), "official"
        with patch.object(thumbs, "resolve_artwork_image", new=AsyncMock(side_effect=resolve)) as fetch:
            first, second = await asyncio.gather(thumbs.get_thumb("same", 1), thumbs.get_thumb("same", 2))
        self.assertNotEqual(first, second)
        fetch.assert_awaited_once()

    async def test_missing_metadata_artwork_and_profile_still_use_new_layout(self):
        self.search.next.side_effect = OSError("Network down")
        with patch.object(thumbs, "resolve_artwork_image", new=AsyncMock(return_value=(None, "missing"))), \
             patch.object(thumbs, "_get_legacy_thumb", new=AsyncMock()) as legacy:
            result = await thumbs.get_thumb("offline", None)
        with Image.open(result) as image:
            self.assertEqual(image.size, (1280, 720))
        self.assertIn("vivaan_cinematic_v2", result)
        legacy.assert_not_awaited()

    async def test_corrupt_cached_card_is_regenerated(self):
        cached = self.cache / "video_7_vivaan_cinematic_v2.png"
        cached.write_bytes(b"not an image" * 100)
        result = await thumbs.get_thumb("video", 7)
        self.assertEqual(result, str(cached))
        with Image.open(result) as image:
            image.verify()

    async def test_profile_downloads_are_unique_and_always_cleaned(self):
        async def photos(chat_id, **kwargs):
            yield SimpleNamespace(file_id=str(chat_id))
        async def download(file_id, file_name):
            Image.new("RGB", (400, 500), "blue").save(file_name)
            return file_name
        self.bot.get_chat_photos = photos
        self.bot.download_media.side_effect = download
        await asyncio.gather(thumbs.get_thumb("a", 1), thumbs.get_thumb("b", 1))
        paths = [call.kwargs["file_name"] for call in self.bot.download_media.call_args_list]
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(not os.path.exists(path) for path in paths))

    async def test_failed_partial_profile_downloads_are_cleaned(self):
        async def photos(chat_id, **kwargs):
            yield SimpleNamespace(file_id=str(chat_id))
        async def download(file_id, file_name):
            Path(file_name).write_bytes(b"partial download")
            raise OSError("Download interrupted")
        self.bot.get_chat_photos = photos
        self.bot.download_media.side_effect = download
        result = await thumbs.get_thumb("partial-avatar", 7)
        self.assertTrue(thumbs.is_valid_image(result))
        self.assertEqual(list(self.cache.glob("player_avatar_*")), [])

    async def test_missing_profile_uses_dp_avatar(self):
        self.assertIsNone(await thumbs._player_profile(7))
        result = await thumbs.get_thumb("no-profile", 7)
        self.assertTrue(thumbs.is_valid_image(result))

    async def test_profile_timeout_preserves_new_card_with_dp_avatar(self):
        with patch.object(thumbs, "_player_profile", new=AsyncMock(side_effect=asyncio.TimeoutError)), \
             patch.object(thumbs, "_get_legacy_thumb", new=AsyncMock()) as legacy:
            result = await thumbs.get_thumb("slow-avatar", 7)
        self.assertTrue(thumbs.is_valid_image(result))
        legacy.assert_not_awaited()

    async def test_cancelled_waiter_does_not_cancel_shared_render(self):
        started, release = threading.Event(), threading.Event()
        def render(*args):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test render did not resume")
            return renderer.render_and_save_thumbnail(*args)
        with patch.object(thumbs, "render_and_save_thumbnail", side_effect=render):
            first = asyncio.create_task(thumbs.get_thumb("cancel", 7))
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(thumbs.get_thumb("cancel", 7))
            release.set()
            result = await second
        self.assertTrue(thumbs.is_valid_image(result))
        self.assertEqual(list(self.cache.glob("*.tmp")), [])

    async def test_flag_and_render_failure_restore_previous_renderer(self):
        with patch.object(thumbs, "_get_legacy_thumb", new=AsyncMock(return_value="old.png")) as legacy:
            with patch.object(thumbs, "USE_NEON_THUMBNAILS", False):
                self.assertEqual(await thumbs.get_thumb("disabled", 7), "old.png")
            with patch.object(thumbs, "render_and_save_thumbnail", side_effect=OSError("Template unavailable")):
                self.assertEqual(await thumbs.get_thumb("failed", 7), "old.png")
            self.assertEqual(legacy.await_count, 2)

    async def test_parallel_groups_keep_render_workers_bounded(self):
        import time
        guard = threading.Lock()
        active = peak = 0
        def render(*args):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.05)
                return renderer.render_and_save_thumbnail(*args)
            finally:
                with guard:
                    active -= 1
        with patch.object(thumbs, "render_and_save_thumbnail", side_effect=render):
            paths = await asyncio.gather(*(thumbs.get_thumb("shared-video", user) for user in range(6)))
        self.assertLessEqual(peak, 2)
        self.assertEqual(len(set(paths)), 6)
        self.assertTrue(all(thumbs.is_valid_image(path) for path in paths))

    def stream_card_handler(self, fetch):
        queue = {123: [{"vidid": "track"}]}
        delivered = SimpleNamespace(delete=AsyncMock())
        send = AsyncMock(return_value=delivered)
        remember = Mock()
        async def rich_call(method, *args, **kwargs):
            return await method(*args, **kwargs)
        from pyrogram.types import InlineKeyboardMarkup
        from pyrogram.errors import FloodWait
        source = ROOT / "VIVAANXMUSIC/utils/stream/cards.py"
        functions = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
                     if isinstance(node, ast.AsyncFunctionDef)]
        namespace = dict(db=queue, app=SimpleNamespace(send_photo=send), get_thumb=fetch,
                         rich_call=rich_call, remember_player_message=remember,
                         InlineKeyboardMarkup=InlineKeyboardMarkup, FloodWait=FloodWait, asyncio=asyncio)
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
        return namespace["_deliver_stream_card"], queue, send, remember

    async def test_playback_card_delivers_new_image_and_preserves_caption_actions(self):
        from pyrogram.types import InlineKeyboardButton
        handler, queue, send, remember = self.stream_card_handler(thumbs.get_thumb)
        buttons = [[InlineKeyboardButton("Pause", callback_data="ADMIN Pause|123")]]
        await handler(123, 456, "track", 7, "Existing song caption", buttons)
        send.assert_awaited_once()
        args, kwargs = send.call_args
        self.assertEqual(args, (456,))
        self.assertEqual(kwargs["caption"], "Existing song caption")
        self.assertIn("vivaan_cinematic_v2", kwargs["photo"])
        self.assertTrue(thumbs.is_valid_image(kwargs["photo"]))
        self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "ADMIN Pause|123")
        self.assertIs(queue[123][0]["mystic"], send.return_value)
        remember.assert_called_once_with(123, send.return_value)

    async def test_finished_track_does_not_publish_stale_thumbnail(self):
        async def fetch(*args):
            path = await thumbs.get_thumb(*args)
            queue[123][0]["vidid"] = "next-track"
            return path
        handler, queue, send, remember = self.stream_card_handler(fetch)
        await handler(123, 456, "track", 7, "Existing caption", [])
        send.assert_not_awaited()
        remember.assert_not_called()


if __name__ == "__main__":
    unittest.main()

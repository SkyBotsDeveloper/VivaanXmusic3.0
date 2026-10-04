"""Real local TGS/VP9 rendering plus isolated /mmf handler lifecycle checks."""

import ast
import asyncio
import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


security = load_file("mmf_security", ROOT / "VIVAANXMUSIC/security.py")
with patch.dict(sys.modules, {"VIVAANXMUSIC.security": security}):
    meme = load_file("mmf_rendering", ROOT / "VIVAANXMUSIC/utils/mmf.py")


def tgs_fixture(path, fps=60):
    data = {"tgs": 1, "v": "5.7.4", "fr": fps, "ip": 0, "op": fps, "w": 512, "h": 512,
            "nm": "Moving rectangle", "ddd": 0, "assets": [], "layers": [{
                "ty": 4, "ind": 1, "nm": "rectangle", "ip": 0, "op": fps, "st": 0, "sr": 1,
                "ks": {"o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0},
                       "a": {"a": 0, "k": [0, 0, 0]}, "s": {"a": 0, "k": [100, 100, 100]},
                       "p": {"a": 1, "k": [
                           {"t": 0, "s": [128, 256, 0], "e": [384, 256, 0],
                            "o": {"x": 0.333, "y": 0}, "i": {"x": 0.667, "y": 1}},
                           {"t": fps - 1, "s": [384, 256, 0]}]}},
                "shapes": [{"ty": "rc", "p": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [64, 64]}, "r": {"a": 0, "k": 0}},
                           {"ty": "fl", "c": {"a": 0, "k": [1, 0.1, 0.1, 1]}, "o": {"a": 0, "k": 100}, "r": 1}]}]}
    with gzip.open(path, "wt", encoding="utf-8") as output:
        json.dump(data, output)
    return path


def video_fixture(directory, size=(512, 256), fps=24):
    frames = directory / "source_frames"
    frames.mkdir()
    width, height = size
    for index in range(fps):
        with Image.new("RGBA", size, (0, 0, 0, 0)) as frame:
            draw = ImageDraw.Draw(frame)
            x = 20 + round(index * (width - 90) / (fps - 1))
            draw.rectangle((x, height // 2 - 20, x + 40, height // 2 + 20), fill=(255, 200, 0, 255))
            frame.save(frames / f"{index:04d}.png")
    output = directory / "source.webm"
    meme._run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", str(frames / "%04d.png"),
               "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-b:v", "0", "-crf", "25", "-an", str(output)])
    return output


def video_frames(path):
    data = json.loads(meme._run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)
    stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    width, height, count = stream["width"], stream["height"], int(stream["nb_read_frames"])
    indexes = (0, count // 2, count - 1)
    select = "select=" + "+".join(f"eq(n\\,{index})" for index in indexes)
    decoded = meme._run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path),
                        "-vf", select, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"]).stdout
    length = width * height * 4
    frames = [Image.frombytes("RGBA", (width, height), decoded[offset:offset + length]) for offset in range(0, len(decoded), length)]
    return data, frames


class MediaTest(unittest.TestCase):
    def test_metadata_dispatch_and_unsupported_inputs(self):
        sticker = lambda **kwargs: SimpleNamespace(sticker=SimpleNamespace(**kwargs))
        self.assertEqual(meme.media_kind(sticker(is_animated=True, file_name="wrong.webp")), "tgs")
        self.assertEqual(meme.media_kind(sticker(is_video=True, file_name="wrong.png")), "video")
        self.assertEqual(meme.media_kind(sticker(is_animated=False, is_video=False)), "static")
        self.assertEqual(meme.media_kind(SimpleNamespace(photo=True)), "static")
        self.assertEqual(meme.media_kind(SimpleNamespace(document=SimpleNamespace(mime_type="image/png"))), "static")
        for message in (None, SimpleNamespace(video=True), SimpleNamespace(document=SimpleNamespace(mime_type="video/mp4", file_name="video.mp4"))):
            self.assertIsNone(meme.media_kind(message))

    def test_static_webp_top_and_image_document_top_bottom(self):
        for suffix, text in (("webp", "HELLO"), ("png", "TOP;BOTTOM")):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                source = directory / ("source." + suffix)
                with Image.new("RGBA", (512, 256), (30, 90, 150, 255)) as image:
                    image.save(source)
                result = meme.memify_media(source, text, "static", directory)
                self.assertTrue(source.exists(), "Source must live until the request owner cleans it")
                with Image.open(result) as image:
                    self.assertEqual(image.size, (512, 256))
                    self.assertEqual(image.format, "WEBP")
                    self.assertFalse(getattr(image, "is_animated", False))
                    self.assert_text_visible(image.convert("RGBA"), text)

    def assert_text_visible(self, frame, text):
        with meme.text_overlay(frame.size, text) as overlay:
            for index, (top, bottom) in enumerate(((0, frame.height // 2), (frame.height // 2, frame.height))):
                indexes = [(x, y) for y in range(top, bottom) for x in range(frame.width)
                           if overlay.getpixel((x, y))[3] > 220 and min(overlay.getpixel((x, y))[:3]) > 240]
                expected = text.partition(";")[0 if index == 0 else 2].strip()
                if expected:
                    self.assertGreater(len(indexes), 5, "Both requested text regions must be present")
                if not indexes:
                    continue
                visible = sum(min(frame.getpixel(position)[:3]) > 215 and frame.getpixel(position)[3] > 200 for position in indexes)
                self.assertGreater(visible / len(indexes), 0.8, "Text must remain visible in every sampled frame")
                black = [(x, y) for y in range(top, bottom) for x in range(frame.width)
                         if overlay.getpixel((x, y))[3] > 220 and max(overlay.getpixel((x, y))[:3]) < 10]
                self.assertTrue(black, "Meme text must have a black outline")
                visible = sum(max(frame.getpixel(position)[:3]) < 60 and frame.getpixel(position)[3] > 200 for position in black)
                self.assertGreater(visible / len(black), 0.7)

    def test_long_words_portrait_landscape_and_small_images_fit(self):
        for size in ((512, 160), (160, 512), (64, 64), (512, 512)):
            with self.subTest(size=size), meme.text_overlay(size, "VERY LONG TOP WORD " * 3 + "W" * 45 + ";BOTTOM WORDS " * 3) as overlay:
                box = overlay.getbbox()
                self.assertIsNotNone(box)
                self.assertGreaterEqual(box[0], 1)
                self.assertGreaterEqual(box[1], 1)
                self.assertLess(box[2], size[0])
                self.assertLess(box[3], size[1])
        with self.assertRaises(meme.MemeError):
            meme.text_overlay((4, 4), "Too much text")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires FFmpeg/libvpx-vp9 and ffprobe")
class AnimationTest(unittest.TestCase):
    assert_text_visible = MediaTest.assert_text_visible

    def assert_animation(self, output, fps, size, text):
        data, frames = video_frames(output)
        self.assertEqual(len(frames), 3)
        stream = data["streams"][0]
        self.assertEqual(stream["codec_name"], "vp9")
        self.assertEqual(int(stream["nb_read_frames"]), fps)
        self.assertEqual(Fraction(stream["avg_frame_rate"]), fps)
        self.assertAlmostEqual(float(data["format"]["duration"]), 1, delta=1 / fps + 0.01)
        self.assertEqual((stream["width"], stream["height"]), size)
        self.assertEqual(len(data["streams"]), 1, "No audio")
        self.assertLessEqual(output.stat().st_size, meme.MAX_VIDEO_BYTES)
        try:
            for frame in frames:
                self.assert_text_visible(frame, text)
                self.assertLess(frame.getpixel((0, 0))[3], 5, "Transparent background must survive")
            center = (0, size[1] // 3, size[0], size[1] * 2 // 3)
            self.assertIsNotNone(ImageChops.difference(frames[0].crop(center).convert("RGB"), frames[-1].crop(center).convert("RGB")).getbbox(), "Animation must move")
        finally:
            for frame in frames:
                frame.close()

    def test_real_tgs_animation_and_top_bottom(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = tgs_fixture(directory / "source.tgs")
            output = meme.memify_media(source, "HELLO;BOTTOM", "tgs", directory)
            self.assert_animation(output, 30, (512, 512), "HELLO;BOTTOM")
            self.assertEqual(len(list((directory / "frames").glob("*.png"))), 30)

    def test_real_webm_preserves_frames_fps_duration_alpha_and_text(self):
        for size, fps in (((512, 256), 24), ((256, 512), 12)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                source = video_fixture(directory, size, fps)
                output = meme.memify_media(source, "TOP;BOTTOM", "video", directory)
                self.assert_animation(output, fps, size, "TOP;BOTTOM")

    def test_small_video_pads_without_upscaling(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = video_fixture(directory, (128, 128), 12)
            output = meme.memify_media(source, "HELLO", "video", directory)
            _, frames = video_frames(output)
            try:
                self.assertEqual(frames[0].size, (512, 128))
                self.assertLess(frames[0].getpixel((20, 64))[3], 5)
                colored = sum(r > 180 and g > 100 and b < 80 and a > 200 for r, g, b, a in frames[0].get_flattened_data())
                self.assertLess(colored, 2500, "Original rectangle must not be upscaled")
            finally:
                for frame in frames:
                    frame.close()


class HandlerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.downloads, self.sent = [], []
        self.app = SimpleNamespace(download_media=AsyncMock(side_effect=self.download),
                                   send_document=AsyncMock(side_effect=self.send), send_sticker=AsyncMock(side_effect=self.send))
        tree = ast.parse((ROOT / "VIVAANXMUSIC/plugins/tools/mmf.py").read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
        for node in nodes:
            node.decorator_list = []
        self.ns = dict(asyncio=asyncio, tempfile=tempfile, Path=Path, Message=object, app=self.app,
                       logger=Mock(), MemeError=meme.MemeError, media_kind=meme.media_kind,
                       memify_media=meme.memify_media, _MMF_JOBS=asyncio.Semaphore(2))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "actual mmf handler", "exec"), self.ns)

    def message(self, kind="static", text="HELLO"):
        reply = SimpleNamespace(photo=(kind == "static"), sticker=None)
        if kind != "static":
            reply.sticker = SimpleNamespace(is_animated=kind == "tgs", is_video=kind == "video")
        status = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
        return SimpleNamespace(text="/mmf " + text, reply_to_message=reply, chat=SimpleNamespace(id=1),
                               reply_text=AsyncMock(return_value=status)), status

    async def download(self, message, file_name):
        path = Path(file_name)
        self.downloads.append(path)
        if meme.media_kind(message) == "tgs":
            tgs_fixture(path)
        else:
            with Image.new("RGBA", (128, 128), (20, 90, 130, 255)) as image:
                image.save(path, "PNG")
        return str(path)

    async def send(self, chat_id, **kwargs):
        path = Path(next(iter(kwargs.values())))
        self.assertTrue(path.exists(), "Upload must finish before cleanup")
        self.sent.append(path)
        await asyncio.sleep(0.02)
        self.assertTrue(path.exists())

    async def test_simultaneous_requests_are_unique_and_cleaned_after_upload(self):
        first, first_status = self.message(text="FIRST;BOTTOM")
        second, second_status = self.message(text="SECOND")
        await asyncio.gather(self.ns["mmf"](None, first), self.ns["mmf"](None, second))
        self.assertEqual(len(self.sent), 2)
        self.assertNotEqual(self.sent[0].parent, self.sent[1].parent)
        for path in self.downloads + self.sent:
            self.assertFalse(path.parent.exists())
        first_status.delete.assert_awaited_once()
        second_status.delete.assert_awaited_once()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires FFmpeg")
    async def test_tgs_is_sent_as_sticker_and_all_intermediates_are_cleaned(self):
        message, status = self.message("tgs", "TOP;BOTTOM")
        await self.ns["mmf"](None, message)
        self.app.send_sticker.assert_awaited_once()
        self.app.send_document.assert_not_awaited()
        self.assertEqual(self.sent[0].suffix, ".webm")
        self.assertFalse(self.downloads[0].parent.exists())
        status.delete.assert_awaited_once()

    async def test_processing_failure_cleans_partial_files_and_hides_exception(self):
        def fail(source, text, kind, directory):
            (Path(directory) / "partial.png").write_bytes(b"partial")
            raise RuntimeError("internal decoder traceback details")
        self.ns["memify_media"] = fail
        message, status = self.message()
        await self.ns["mmf"](None, message)
        self.assertFalse(self.downloads[0].parent.exists())
        self.app.send_document.assert_not_awaited()
        status.edit_text.assert_awaited_with("Failed to decode the image.")
        self.ns["logger"].exception.assert_called_once()

    async def test_corrupt_tgs_failure_is_concise_and_cleans_download(self):
        async def corrupt(message, file_name):
            path = Path(file_name)
            self.downloads.append(path)
            with gzip.open(path, "wt") as output:
                output.write("invalid animation json")
            return str(path)
        self.app.download_media.side_effect = corrupt
        message, status = self.message("tgs")
        await self.ns["mmf"](None, message)
        self.assertFalse(self.downloads[0].parent.exists())
        self.app.send_sticker.assert_not_awaited()
        status.edit_text.assert_awaited_with("Failed to render the animated sticker.")

    async def test_cancellation_waits_for_processing_before_cleanup(self):
        import threading
        started, finish = threading.Event(), threading.Event()
        def worker(source, text, kind, directory):
            started.set()
            finish.wait(5)
            output = Path(directory) / "memify.webp"
            output.write_bytes(b"finished")
            return output
        self.ns["memify_media"] = worker
        message, _ = self.message()
        job = asyncio.create_task(self.ns["mmf"](None, message))
        self.assertTrue(await asyncio.to_thread(started.wait, 5))
        job.cancel()
        await asyncio.sleep(0.02)
        self.assertTrue(self.downloads[0].parent.exists())
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await job
        self.assertFalse(self.downloads[0].parent.exists())

    async def test_download_and_send_failures_clean_up(self):
        original = self.download
        async def fail_download(message, file_name):
            await original(message, file_name)
            raise RuntimeError("private download details")
        for stage in ("download", "send"):
            with self.subTest(stage=stage):
                self.app.download_media.side_effect = fail_download if stage == "download" else original
                self.app.send_document.side_effect = RuntimeError("private upload details")
                message, status = self.message()
                await self.ns["mmf"](None, message)
                self.assertFalse(self.downloads[-1].parent.exists())
                self.assertNotIn("private", status.edit_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()

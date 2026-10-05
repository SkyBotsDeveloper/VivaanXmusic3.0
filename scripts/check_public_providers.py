"""Live anonymous-provider checks without starting Telegram or loading credentials.

Run from the repository: python scripts/check_public_providers.py --output report.json
Uploads contain only a generated test image. AI checks can take several minutes.
"""

import argparse
import asyncio
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

import aiohttp
import httpx
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# No MongoDB/Telegram connections, environment tokens, or bot configuration.
sys.modules["config"] = ModuleType("config")
package = ModuleType("VIVAANXMUSIC")
package.__path__ = [str(ROOT / "VIVAANXMUSIC")]
sys.modules["VIVAANXMUSIC"] = package
load("VIVAANXMUSIC.security", "VIVAANXMUSIC/security.py")
ai = load("public_check_ai", "VIVAANXMUSIC/utils/free_ai.py")
uploads = load("public_check_uploads", "VIVAANXMUSIC/utils/file_upload.py")
movie = load("public_check_movie", "VIVAANXMUSIC/utils/movie_lookup.py")
anime = load("public_check_anime", "VIVAANXMUSIC/utils/anime_images.py")
social = load("public_check_social", "VIVAANXMUSIC/utils/socialdown.py")


def describe_image(data, *, transparent=False):
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if transparent:
            assert image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 255
        return {"format": image.format, "size": image.size, "mode": image.mode}


async def main(args):
    report = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks": []}

    async def check(name, work, timeout=180):
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(work(), timeout)
            row = {"name": name, "status": "PASS", "detail": result}
        except Exception as exc:
            row = {"name": name, "status": "FAIL", "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}
        row["seconds"] = round(time.monotonic() - start, 2)
        report["checks"].append(row)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{row['status']} {name} ({row['seconds']}s): {row['detail']}", flush=True)

    with tempfile.TemporaryDirectory(prefix="vivaan-public-check-") as directory:
        image = Image.new("RGB", (320, 240), "white")
        ImageDraw.Draw(image).ellipse((80, 40, 240, 210), fill="red")
        fixture = Path(directory) / "synthetic.png"
        image.save(fixture)
        data = fixture.read_bytes()

        async def chat(alias):
            response = await ai.generate_chat_response("What is seven times eight? Give only the number.", alias=alias)
            assert "56" in response.content, response.content
            return {"model": response.model, "answer": response.content}

        async def generated_image():
            result = await ai.generate_image("A red sailboat on a calm blue lake, watercolor painting")
            return describe_image(result)

        async def remove_background(space):
            path = await asyncio.to_thread(ai._run_public_removebg, space, str(fixture))
            return describe_image(Path(path).read_bytes(), transparent=True)

        async def edited_image():
            result = await ai.edit_image_bytes("paint this in watercolor style", images=[(data, "image/png")])
            return describe_image(result)

        async def processed(mode):
            result = await ai.process_image_bytes(data, mime_type="image/png", mode=mode)
            return describe_image(result, transparent=mode == "removebg")

        async def movie_info(title):
            result = await movie.get_movie_info(title)
            assert f"Title:</b> {title}" in result, result
            assert len(result) < 4096
            return result[:200]

        async def upload(provider, uploader):
            async with aiohttp.ClientSession(timeout=uploads.UPLOAD_TIMEOUT, headers=uploads.UPLOAD_HEADERS) as session:
                url = await uploader(session, str(fixture))
                await uploads._verify_upload(session, url, str(fixture))
                async with session.get(url) as response:
                    assert response.status == 200 and await response.read() == data
                return f"{provider}: upload and full byte-for-byte download match"

        async def anime_image(tag):
            result = await asyncio.to_thread(anime.get_waifu_data, tag)
            assert result and result.get("images")
            item = result["images"][0]
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(item["url"])
                response.raise_for_status()
            return {"provider": result["source"], "actual_tag": item["tag"], **describe_image(response.content)}

        async def social_media(platform, url):
            bundle = await social.get_social_bundle(platform, url)
            assert bundle.items
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                item = bundle.items[0]
                async with client.stream("GET", item.url, headers={**item.headers, "Range": "bytes=0-4095"}) as response:
                    assert response.status_code in (200, 206), response.status_code
                    assert "text/html" not in response.headers.get("content-type", "")
                    async for chunk in response.aiter_bytes():
                        assert chunk
                        break
                    else:
                        raise ValueError("Empty media download")
            return {"source": bundle.source, "media_count": len(bundle.items), "first_kind": item.kind}

        async def backup_video():
            result = await ai.generate_video("Gentle motion", image_bytes=data, mime_type="image/png")
            try:
                output = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                    "format=duration:stream=codec_name,nb_frames", "-of", "json", result.file_path], text=True))
                assert output["streams"][0]["codec_name"] == "h264"
                return {"provider": result.provider, **output}
            finally:
                Path(result.file_path).unlink(missing_ok=True)

        async def quote_image():
            payload = {"type": "quote", "format": "webp", "backgroundColor": "#1b1429", "width": 512,
                       "scale": 2, "emojiBrand": "apple", "messages": [{"chatId": 1, "text": "API test hello",
                       "avatar": False, "from": {"id": 1, "name": "API Test", "type": "private"}, "entities": []}]}
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post("https://quote.yuri.ly/generate.webp", json=payload)
                response.raise_for_status()
            return describe_image(response.content)

        async def text_video():
            result = await ai.generate_video("A red sailboat gently floating on a calm blue lake")
            try:
                output = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                    "format=duration:stream=codec_name,nb_frames", "-of", "json", result.file_path], text=True))
                assert output["streams"][0]["codec_name"] == "h264"
                return {"provider": result.provider, **output}
            finally:
                Path(result.file_path).unlink(missing_ok=True)

        for title in ("Inception", "Sholay"):
            await check(f"movie/{title}", lambda title=title: movie_info(title), 90)
        for provider, uploader in uploads.UPLOAD_PROVIDERS:
            await check(f"upload/{provider}", lambda provider=provider, uploader=uploader: upload(provider, uploader), 90)
        for tag in ("maid", "hug", "awoo"):
            await check(f"waifu/{tag}", lambda tag=tag: anime_image(tag), 60)
        for mode in ("enhance", "removebg"):
            await check(f"image/{mode}", lambda mode=mode: processed(mode))
        await check("video/reference-image", backup_video)
        await check("quote/primary", quote_image, 40)
        for platform, url in (
            ("instagram", "https://www.instagram.com/reel/Chunk8-jurw/"),
            ("facebook", "https://www.facebook.com/cnn/videos/10155529876156509/"),
            ("snapchat", "https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYdXJwanZtdnVlAZ1Z1-5NAZ1Z19YoAAAAAw"),
            ("tiktok", "https://www.tiktok.com/@scout2015/video/6718335390845095173"),
            ("x", "https://twitter.com/oshtru/status/1577855540407197696"),
        ):
            await check(f"social/{platform}", lambda platform=platform, url=url: social_media(platform, url), 120)
        if not args.skip_ai:
            for alias in ("gpt", "chatgpt", "eliteai", "bard", "gemini", "llama", "mistral", "claude", "jarvis", "assis"):
                await check(f"chat/{alias}", lambda alias=alias: chat(alias), 65)
            await check("image/generation", generated_image)
            await check("image/style-edit", edited_image, 120)
            for space in ai.HF_REMOVEBG_SPACES:
                await check(f"removebg/{space}", lambda space=space: remove_background(space), 60)
            await check("video/text", text_video, 240)
    failures = sum(row["status"] == "FAIL" for row in report["checks"])
    print(f"{len(report['checks']) - failures}/{len(report['checks'])} live checks passed. Report: {args.output}")
    return int(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="JSON report path (prefer a temporary directory)")
    parser.add_argument("--skip-ai", action="store_true", help="Skip additional remote inference checks")
    sys.exit(asyncio.run(main(parser.parse_args())))

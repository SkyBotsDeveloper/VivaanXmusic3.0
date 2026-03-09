import os
import tempfile
from urllib.parse import urljoin

import requests
from pyrogram import Client, enums, filters
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from VIVAANXMUSIC import app
from VIVAANXMUSIC.misc import SUDOERS
from VIVAANXMUSIC.security import SecurityError, validate_public_http_url


MAX_SOURCE_BYTES = 1_000_000


def download_website(url: str) -> str:
    safe_url = validate_public_http_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/58.0.3029.110 Safari/537.3"
        )
    }

    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session = requests.Session()
    session.trust_env = False
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))

    try:
        response = session.get(
            safe_url,
            headers=headers,
            timeout=20,
            stream=True,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            location = response.headers.get("Location")
            if not location:
                raise SecurityError("Redirect blocked for safety.")
            redirect_target = validate_public_http_url(urljoin(safe_url, location))
            raise SecurityError(
                f"Redirect blocked for safety. Use the final URL directly: {redirect_target}"
            )

        response.raise_for_status()
        chunks = []
        total_size = 0
        for chunk in response.iter_content(chunk_size=65536, decode_unicode=True):
            if not chunk:
                continue
            chunk_text = chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace")
            total_size += len(chunk_text.encode("utf-8"))
            if total_size > MAX_SOURCE_BYTES:
                raise SecurityError("Downloaded content exceeded the 1 MB safety limit.")
            chunks.append(chunk_text)
        return "".join(chunks)
    finally:
        session.close()


@app.on_message(filters.command("webdl") & SUDOERS)
async def web_download(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "Please enter a valid URL.\n\nExample: `/webdl https://example.com`",
            parse_mode=enums.ParseMode.MARKDOWN,
        )

    url = message.command[1]
    status_msg = await message.reply_text("Downloading website source...")

    try:
        source_code = download_website(url)
    except SecurityError as exc:
        await status_msg.edit_text(
            f"Blocked by security policy: `{exc}`",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return
    except requests.RequestException as exc:
        await status_msg.edit_text(
            f"Failed to download source code: `{exc}`",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            prefix="website_source_",
            delete=False,
        ) as handle:
            handle.write(source_code)
            temp_path = handle.name

        await message.reply_document(
            document=temp_path,
            caption=f"Source code of: `{url}`",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as exc:
        await message.reply_text(
            f"Failed to send the file: `{exc}`",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        await status_msg.delete()

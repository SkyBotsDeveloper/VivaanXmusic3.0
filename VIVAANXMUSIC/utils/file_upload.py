import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

import aiohttp

from VIVAANXMUSIC.security import validate_public_http_url


UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=300, connect=30, sock_read=180)
UPLOAD_HEADERS = {"User-Agent": "VivaanXMusicBot/1.0 Telegram media uploader"}


@dataclass
class UploadResult:
    ok: bool
    url: str = ""
    provider: str = ""
    error: str = ""


def _is_url(value: str) -> bool:
    value = (value or "").strip()
    return value.startswith(("http://", "https://")) and " " not in value


def _tmpfiles_direct_url(url: str) -> str:
    if "tmpfiles.org/" not in url or "tmpfiles.org/dl/" in url:
        return url
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)


def _tempfile_direct_url(url: str) -> str:
    if "tempfile.org/" not in url or url.rstrip("/").endswith("/download"):
        return url
    return url.rstrip("/") + "/download"


async def _post_multipart(
    session: aiohttp.ClientSession,
    url: str,
    file_path: str,
    file_field: str,
    extra_fields: dict | None = None,
):
    form = aiohttp.FormData()
    if extra_fields:
        for key, value in extra_fields.items():
            form.add_field(key, str(value))

    with open(file_path, "rb") as file_obj:
        form.add_field(
            file_field,
            file_obj,
            filename=os.path.basename(file_path),
        )
        async with session.post(url, data=form) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}: {text[:180]}")
            return text.strip()


async def _upload_catbox(session: aiohttp.ClientSession, file_path: str) -> str:
    text = await _post_multipart(
        session,
        "https://catbox.moe/user/api.php",
        file_path,
        "fileToUpload",
        {"reqtype": "fileupload"},
    )
    if not _is_url(text):
        raise RuntimeError(text[:180] or "invalid Catbox response")
    return text


async def _upload_litterbox(session: aiohttp.ClientSession, file_path: str) -> str:
    text = await _post_multipart(
        session,
        "https://litterbox.catbox.moe/resources/internals/api.php",
        file_path,
        "fileToUpload",
        {"reqtype": "fileupload", "time": "72h"},
    )
    if not _is_url(text):
        raise RuntimeError(text[:180] or "invalid Litterbox response")
    return text


async def _upload_uguu(session: aiohttp.ClientSession, file_path: str) -> str:
    text = await _post_multipart(
        session,
        "https://uguu.se/upload",
        file_path,
        "files[]",
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid Uguu JSON: {text[:180]}") from exc

    files = payload.get("files") or []
    if files and _is_url(files[0].get("url", "")):
        return files[0]["url"].strip()
    raise RuntimeError(payload.get("description") or payload.get("error") or text[:180])


async def _upload_tmpfiles(session: aiohttp.ClientSession, file_path: str) -> str:
    text = await _post_multipart(
        session,
        "https://tmpfiles.org/api/v1/upload",
        file_path,
        "file",
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid tmpfiles JSON: {text[:180]}") from exc

    data = payload.get("data") or {}
    url = data.get("url") or payload.get("url") or ""
    if _is_url(url):
        return _tmpfiles_direct_url(url.strip())
    raise RuntimeError(payload.get("message") or payload.get("error") or text[:180])


async def _upload_tempfile(session: aiohttp.ClientSession, file_path: str) -> str:
    text = await _post_multipart(
        session,
        "https://tempfile.org/api/upload/local",
        file_path,
        "files",
        {"expiryHours": "48"},
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid TempFile JSON: {text[:180]}") from exc

    files = payload.get("files") or []
    if files and _is_url(files[0].get("url", "")):
        return _tempfile_direct_url(files[0]["url"].strip())
    raise RuntimeError(payload.get("error") or payload.get("message") or text[:180])


UPLOAD_PROVIDERS: tuple[tuple[str, Callable], ...] = (
    ("Catbox", _upload_catbox),
    ("TempFile", _upload_tempfile),
)


async def _verify_upload(session, url, file_path):
    with open(file_path, "rb") as source:
        expected = source.read(4096)
    for _ in range(5):
        safe_url = validate_public_http_url(url, allow_subdomains=True)
        async with session.get(
            safe_url, headers={"Range": f"bytes=0-{len(expected) - 1}", "Accept-Encoding": "identity"},
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=25),
        ) as response:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise RuntimeError("Upload download redirect has no target.")
                url = urljoin(safe_url, location)
                continue
            if response.status not in {200, 206}:
                raise RuntimeError(f"Upload download returned HTTP {response.status}.")
            total = response.headers.get("Content-Range", "").rsplit("/", 1)[-1]
            if response.status == 200:
                total = response.headers.get("Content-Length", "")
            if total.isdigit() and int(total) != os.path.getsize(file_path):
                raise RuntimeError("Upload link has a different file size.")
            actual = await response.content.readexactly(len(expected))
            if actual != expected:
                raise RuntimeError("Upload link does not return the uploaded file.")
            return
    raise RuntimeError("Upload download has too many redirects.")


async def upload_file_with_fallbacks(file_path: str) -> UploadResult:
    if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
        return UploadResult(ok=False, error="The file is missing or empty.")
    errors = []
    async with aiohttp.ClientSession(
        timeout=UPLOAD_TIMEOUT,
        headers=UPLOAD_HEADERS,
    ) as session:
        for provider, uploader in UPLOAD_PROVIDERS:
            try:
                url = await uploader(session, file_path)
                if not _is_url(url):
                    raise RuntimeError("invalid URL response")
                await _verify_upload(session, url, file_path)
            except Exception as exc:
                errors.append(f"{provider}: {type(exc).__name__}: {exc}")
                continue

            return UploadResult(ok=True, url=url, provider=provider)

    return UploadResult(ok=False, error="\n".join(errors[-4:]))

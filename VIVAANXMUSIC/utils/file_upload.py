import json
import os
from dataclasses import dataclass
from typing import Callable

import aiohttp


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
    ("Litterbox", _upload_litterbox),
    ("Uguu", _upload_uguu),
    ("tmpfiles", _upload_tmpfiles),
    ("TempFile", _upload_tempfile),
)


async def upload_file_with_fallbacks(file_path: str) -> UploadResult:
    errors = []
    async with aiohttp.ClientSession(
        timeout=UPLOAD_TIMEOUT,
        headers=UPLOAD_HEADERS,
    ) as session:
        for provider, uploader in UPLOAD_PROVIDERS:
            try:
                url = await uploader(session, file_path)
            except Exception as exc:
                errors.append(f"{provider}: {type(exc).__name__}: {exc}")
                continue

            if _is_url(url):
                return UploadResult(ok=True, url=url, provider=provider)
            errors.append(f"{provider}: invalid URL response")

    return UploadResult(ok=False, error="\n".join(errors[-4:]))

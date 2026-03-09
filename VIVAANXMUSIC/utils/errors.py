import os
import sys
import traceback
from datetime import datetime
from functools import wraps

import aiofiles
from pyrogram.errors.exceptions.forbidden_403 import ChatWriteForbidden

from config import DEBUG_IGNORE_LOG, LOGGER_ID
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.exceptions import is_ignored_error
from VIVAANXMUSIC.utils.pastebin import VIVAANBIN
from VIVAANXMUSIC.security import redact_secrets


DEBUG_LOG_FILE = "ignored_errors.log"


async def send_large_error(text: str, caption: str, filename: str):
    text = redact_secrets(text)
    caption = redact_secrets(caption)
    try:
        paste_url = await VIVAANBIN(text)
        if paste_url:
            await app.send_message(LOGGER_ID, f"{caption}\n\nPaste: {paste_url}")
            return
    except Exception:
        pass

    path = f"{filename}.txt"
    async with aiofiles.open(path, "w", encoding="utf-8") as handle:
        await handle.write(text)
    await app.send_document(LOGGER_ID, path, caption="Error Log (Fallback)")
    os.remove(path)


def format_traceback(err, tb, label: str, extras: dict | None = None) -> str:
    exc_type = type(err).__name__
    parts = [
        f"<b>{label} Captured</b>",
        f"<b>Error Type:</b> <code>{exc_type}</code>",
    ]
    if extras:
        parts.extend(
            f"<b>{key}:</b> <code>{redact_secrets(str(value))}</code>"
            for key, value in extras.items()
        )
    parts.append(f"\n<b>Traceback:</b>\n<pre>{redact_secrets(tb)}</pre>")
    return redact_secrets("\n".join(parts))


async def handle_trace(err, tb, label, filename, extras=None):
    if is_ignored_error(err):
        await log_ignored_error(err, tb, label, extras)
        return

    caption = format_traceback(err, tb, label, extras)
    if len(caption) > 4096:
        await send_large_error(tb, caption.split("\n\n")[0], filename)
    else:
        await app.send_message(LOGGER_ID, caption)


async def log_ignored_error(err, tb, label, extras=None):
    if not DEBUG_IGNORE_LOG:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"\n--- Ignored Error | {label} @ {timestamp} ---",
        f"Type: {type(err).__name__}",
        *(f"{key}: {redact_secrets(str(value))}" for key, value in (extras or {}).items()),
        "Traceback:",
        redact_secrets(tb.strip()),
        "------------------------------------------\n",
    ]
    async with aiofiles.open(DEBUG_LOG_FILE, "a", encoding="utf-8") as log:
        await log.write("\n".join(lines))


def capture_err(func):
    @wraps(func)
    async def wrapper(client, message, *args, **kwargs):
        try:
            return await func(client, message, *args, **kwargs)
        except ChatWriteForbidden:
            await app.leave_chat(message.chat.id)
        except Exception as err:
            tb = "".join(traceback.format_exception(*sys.exc_info()))
            extras = {
                "User": message.from_user.mention if message.from_user else "N/A",
                "Command": message.text or message.caption,
                "Chat ID": message.chat.id,
            }
            filename = f"error_log_{message.chat.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            await handle_trace(err, tb, "Error", filename, extras)
            raise err

    return wrapper


def capture_callback_err(func):
    @wraps(func)
    async def wrapper(client, callback_query, *args, **kwargs):
        try:
            return await func(client, callback_query, *args, **kwargs)
        except Exception as err:
            tb = "".join(traceback.format_exception(*sys.exc_info()))
            extras = {
                "User": callback_query.from_user.mention if callback_query.from_user else "N/A",
                "Chat ID": callback_query.message.chat.id,
            }
            filename = (
                f"cb_error_log_{callback_query.message.chat.id}_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            await handle_trace(err, tb, "Callback Error", filename, extras)
            raise err

    return wrapper


def capture_internal_err(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as err:
            tb = "".join(traceback.format_exception(*sys.exc_info()))
            extras = {"Function": func.__name__}
            filename = f"internal_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            await handle_trace(err, tb, "Internal Error", filename, extras)
            raise err

    return wrapper

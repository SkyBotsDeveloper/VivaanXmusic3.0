import asyncio
import os
import tempfile

from gtts import gTTS
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.free_ai import FreeAIError, generate_chat_response


async def send_typing_action(client: Client, chat_id: int, interval: int = 3):
    try:
        while True:
            await client.send_chat_action(chat_id, ChatAction.TYPING)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


def _build_fullname(
    first_name: str | None,
    last_name: str | None,
    username: str | None,
) -> str:
    first = first_name or ""
    last = (last_name or "").strip()
    full = (f"{first} {last}".strip()) or (f"@{username}" if username else "")
    return full or "there"


def _user_mention_text(user) -> str:
    full = _build_fullname(
        getattr(user, "first_name", None),
        getattr(user, "last_name", None),
        getattr(user, "username", None),
    )
    mention_attr = getattr(user, "mention", None)
    if callable(mention_attr):
        try:
            return mention_attr(full)
        except Exception:
            pass
    return f"[{full}](tg://user?id={user.id})"


def get_requester_identity(message: Message) -> tuple[str, str]:
    if message.from_user:
        user = message.from_user
        full = _build_fullname(
            user.first_name,
            getattr(user, "last_name", None),
            getattr(user, "username", None),
        )
        return full, _user_mention_text(user)
    if message.sender_chat:
        title = message.sender_chat.title or "there"
        return title, title
    return "there", "there"


def get_prompt(message: Message) -> str | None:
    source = (message.text or message.caption or "").strip()
    parts = source.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()

    if message.reply_to_message:
        replied = (
            message.reply_to_message.text or message.reply_to_message.caption or ""
        ).strip()
        if replied:
            return replied
    return None


def build_response_text(model_name: str, content: str) -> str:
    return f"Engine: {model_name}\n\n{content}"


async def send_chunked_reply(message: Message, text: str):
    for start in range(0, len(text), 4096):
        await message.reply_text(
            text[start : start + 4096],
            disable_web_page_preview=True,
        )


async def process_query(
    client: Client,
    message: Message,
    *,
    tts: bool = False,
    alias: str | None = None,
):
    _, mention = get_requester_identity(message)

    if len(message.command) < 2 and not message.reply_to_message:
        return await message.reply_text(
            f"Hello {mention}, how can I assist you today?",
            disable_web_page_preview=True,
        )

    query = get_prompt(message)
    if not query:
        return await message.reply_text("Please provide a prompt after the command.")

    if len(query) > 4000:
        return await message.reply_text(
            "Your prompt is too long (max 4000 characters). Please shorten it."
        )

    audio_file = None
    typing_task = asyncio.create_task(send_typing_action(client, message.chat.id))
    command_name = ((message.command or [""])[0] or "").lower()
    selected_alias = alias or "chatgpt"
    if not alias and command_name in {"ai", "ask", "master"}:
        selected_alias = "eliteai"

    try:
        result = await asyncio.wait_for(
            generate_chat_response(query, alias=selected_alias),
            timeout=60,
        )

        if tts:
            content = result.content[:1000]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as handle:
                audio_file = handle.name
            tts_engine = gTTS(text=content, lang="en")
            tts_engine.save(audio_file)
            await client.send_voice(chat_id=message.chat.id, voice=audio_file)
        else:
            await send_chunked_reply(
                message,
                build_response_text(result.model, result.content),
            )
    except asyncio.TimeoutError:
        await message.reply_text("Timeout. Please try again in a moment.")
    except FreeAIError as exc:
        await message.reply_text(str(exc))
    finally:
        typing_task.cancel()
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)


@app.on_message(filters.command(["arvis"], prefixes=["j", "J"]))
async def jarvis_handler(client: Client, message: Message):
    await process_query(client, message, alias="jarvis")


@app.on_message(
    filters.command(
        ["chatgpt", "ai", "ask", "Master"],
        prefixes=["+", ".", "/", "-", "?", "$", "#", "&"],
    )
)
async def chatgpt_handler(client: Client, message: Message):
    await process_query(client, message)


@app.on_message(filters.command(["ssis"], prefixes=["a", "A"]))
async def vivaan_tts_handler(client: Client, message: Message):
    await process_query(client, message, tts=True, alias="assis")

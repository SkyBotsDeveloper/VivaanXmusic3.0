from pyrogram import filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import BANNED_USERS
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.database import (
    enable_voiceplay_exclusive,
    get_voiceplay,
    set_voiceplay,
)
from VIVAANXMUSIC.utils.decorators.admins import ActualAdminCB, AdminActual
from VIVAANXMUSIC.utils.voiceplay import voiceplay_manager


def _language_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🇮🇳 Hindi / Hinglish",
                    callback_data=f"voiceplay:set:hi:{user_id}",
                ),
                InlineKeyboardButton(
                    "🇬🇧 English",
                    callback_data=f"voiceplay:set:en:{user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⏹ Turn Off",
                    callback_data=f"voiceplay:set:off:{user_id}",
                )
            ],
        ]
    )


@app.on_message(
    filters.command(["voiceplay", "vcmusic"]) & filters.group & ~BANNED_USERS
)
@AdminActual
async def voiceplay_command(_, message: Message, strings):
    argument = message.command[1].lower() if len(message.command) > 1 else ""
    current = await get_voiceplay(message.chat.id)

    if argument in {"off", "disable", "disabled"}:
        await set_voiceplay(message.chat.id, False, current["language"])
        await voiceplay_manager.stop_session(message.chat.id)
        await voiceplay_manager.leave_if_idle(message.chat.id)
        return await message.reply_text(
            "⏹ <b>Voice Play disabled.</b> Normal music commands will keep working."
        )

    status = (
        f"ON ({'Hindi / Hinglish' if current['language'] == 'hi' else 'English'})"
        if current["enabled"]
        else "OFF"
    )
    await message.reply_text(
        "🎙️ <b>Voice Play</b>\n\n"
        f"Current status: <b>{status}</b>\n\n"
        "Choose a language. While enabled, the assistant listens only during the "
        "short request window after its prompt. Three unsuccessful attempts will "
        "make the assistant leave the VC; Voice Play will remain enabled for the group.",
        reply_markup=_language_keyboard(message.from_user.id),
    )


@app.on_callback_query(filters.regex(r"^voiceplay:set:"))
@ActualAdminCB
async def voiceplay_callback(_, callback: CallbackQuery, strings):
    try:
        _, _, choice, owner_id = callback.data.split(":", 3)
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        return await callback.answer("Invalid Voice Play action.", show_alert=True)

    if callback.from_user.id != owner_id:
        return await callback.answer(
            "Only the admin who opened this menu can use these buttons.",
            show_alert=True,
        )

    chat_id = callback.message.chat.id
    if choice == "off":
        current = await get_voiceplay(chat_id)
        await set_voiceplay(chat_id, False, current["language"])
        await voiceplay_manager.stop_session(chat_id)
        await voiceplay_manager.leave_if_idle(chat_id)
        await callback.answer("Voice Play disabled.")
        return await callback.message.edit_text(
            "⏹ <b>Voice Play disabled.</b> Normal music commands remain unchanged."
        )

    if choice not in {"hi", "en"}:
        return await callback.answer("Unknown language.", show_alert=True)

    await voiceplay_manager.stop_session(chat_id)
    autoplay_was_enabled = await enable_voiceplay_exclusive(chat_id, choice)
    language_name = "Hindi / Hinglish" if choice == "hi" else "English"
    await callback.answer(f"Voice Play enabled in {language_name}.")
    await callback.message.edit_text(
        "✅ <b>Voice Play enabled</b>\n\n"
        f"Language: <b>{language_name}</b>\n"
        + (
            "Autoplay: <b>OFF (disabled automatically)</b>\n"
            if autoplay_was_enabled
            else "Autoplay: <b>OFF</b>\n"
        )
        + "Start a song with /play. After the final queued song finishes, "
        "the assistant will ask what you want to hear next."
        + "\n\nSay phrases such as <i>play Sanam Re</i>, "
        "<i>Sanam Re song bajao</i>, or <i>Sanam Re laga do</i>.",
    )

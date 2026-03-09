from typing import Union
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from VIVAANXMUSIC.utils.button_styles import danger_button, primary_button, success_button


def queue_markup(
    _,
    DURATION,
    CPLAY,
    videoid,
    played: Union[bool, int] = None,
    dur: Union[bool, int] = None,
):
    not_dur = [
        [
            primary_button(
                text=_["QU_B_1"],
                callback_data=f"GetQueued {CPLAY}|{videoid}",
            ),
            danger_button(
                text=_["CLOSE_BUTTON"],
                callback_data="close",
            ),
        ]
    ]
    dur = [
        [
            InlineKeyboardButton(
                text=_["QU_B_2"].format(played, dur),
                callback_data="GetTimer",
            )
        ],
        [
            primary_button(
                text=_["QU_B_1"],
                callback_data=f"GetQueued {CPLAY}|{videoid}",
            ),
            danger_button(
                text=_["CLOSE_BUTTON"],
                callback_data="close",
            ),
        ],
    ]
    upl = InlineKeyboardMarkup(not_dur if DURATION == "Unknown" else dur)
    return upl


def queue_back_markup(_, CPLAY):
    upl = InlineKeyboardMarkup(
        [
            [
                primary_button(
                    text=_["BACK_BUTTON"],
                    callback_data=f"queue_back_timer {CPLAY}",
                ),
                danger_button(
                    text=_["CLOSE_BUTTON"],
                    callback_data="close",
                ),
            ]
        ]
    )
    return upl


def aq_markup(_, chat_id):
    buttons = [
        [
            success_button(text="▷", callback_data=f"ADMIN Resume|{chat_id}"),
            primary_button(text="II", callback_data=f"ADMIN Pause|{chat_id}"),
            primary_button(text="‣‣I", callback_data=f"ADMIN Skip|{chat_id}"),
            danger_button(text="▢", callback_data=f"ADMIN Stop|{chat_id}"),
        ],
        [danger_button(text=_["CLOSE_BUTTON"], callback_data="close")],
    ]
    return buttons

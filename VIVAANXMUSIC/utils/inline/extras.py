from pyrogram.types import InlineKeyboardMarkup

from config import SUPPORT_CHAT
from VIVAANXMUSIC.utils.button_styles import danger_button, success_button


def botplaylist_markup(_):
    buttons = [
        [
            success_button(text=_["S_B_4"], url=SUPPORT_CHAT),
            danger_button(text=_["CLOSE_BUTTON"], callback_data="close"),
        ],
    ]
    return buttons


def close_markup(_):
    upl = InlineKeyboardMarkup(
        [
            [
                danger_button(
                    text=_["CLOSE_BUTTON"],
                    callback_data="close",
                ),
            ]
        ]
    )
    return upl


def supp_markup(_):
    upl = InlineKeyboardMarkup(
        [
            [
                success_button(
                    text=_["S_B_4"],
                    url=SUPPORT_CHAT,
                ),
            ]
        ]
    )
    return upl

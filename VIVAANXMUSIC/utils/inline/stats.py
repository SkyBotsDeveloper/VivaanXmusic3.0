from pyrogram.types import InlineKeyboardMarkup

from VIVAANXMUSIC.button_styles import danger_button, primary_button


def stats_buttons(_, status):
    not_sudo = [
        primary_button(
            text=_["SA_B_1"],
            callback_data="TopOverall",
        )
    ]
    sudo = [
        primary_button(
            text=_["SA_B_2"],
            callback_data="bot_stats_sudo",
        ),
        primary_button(
            text=_["SA_B_3"],
            callback_data="TopOverall",
        ),
    ]
    upl = InlineKeyboardMarkup(
        [
            sudo if status else not_sudo,
            [
                danger_button(
                    text=_["CLOSE_BUTTON"],
                    callback_data="close",
                ),
            ],
        ]
    )
    return upl


def back_stats_buttons(_):
    upl = InlineKeyboardMarkup(
        [
            [
                primary_button(
                    text=_["BACK_BUTTON"],
                    callback_data="stats_back",
                ),
                danger_button(
                    text=_["CLOSE_BUTTON"],
                    callback_data="close",
                ),
            ],
        ]
    )
    return upl

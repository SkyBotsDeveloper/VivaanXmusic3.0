from pyrogram.types import InlineKeyboardMarkup

from VIVAANXMUSIC.utils.button_styles import danger_button, primary_button, success_button


def speed_markup(_, chat_id):
    upl = InlineKeyboardMarkup(
        [
            [
                primary_button(
                    text="🕒 0.5x",
                    callback_data=f"SpeedUP {chat_id}|0.5",
                ),
                primary_button(
                    text="🕓 0.75x",
                    callback_data=f"SpeedUP {chat_id}|0.75",
                ),
            ],
            [
                success_button(
                    text=_["P_B_4"],
                    callback_data=f"SpeedUP {chat_id}|1.0",
                ),
            ],
            [
                primary_button(
                    text="🕤 1.5x",
                    callback_data=f"SpeedUP {chat_id}|1.5",
                ),
                primary_button(
                    text="🕛 2.0x",
                    callback_data=f"SpeedUP {chat_id}|2.0",
                ),
            ],
            [
                danger_button(
                    text=_["CLOSE_BUTTON"],
                    callback_data="close",
                ),
            ],
        ]
    )
    return upl

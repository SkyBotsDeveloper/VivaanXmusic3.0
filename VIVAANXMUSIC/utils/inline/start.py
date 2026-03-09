import config
from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.button_styles import primary_button, success_button


def start_panel(_):
    buttons = [
        [
            primary_button(
                text=_["S_B_1"], url=f"https://t.me/{app.username}?startgroup=true"
            ),
            success_button(text=_["S_B_2"], url=config.SUPPORT_CHANNEL),
        ],
    ]
    return buttons


def private_panel(_):
    buttons = [
        [
            primary_button(
                text=_["S_B_1"],
                url=f"https://t.me/{app.username}?startgroup=true",
            )
        ],
        [
            primary_button(text=_["S_B_7"], user_id=config.OWNER_ID),
            success_button(text=_["S_B_4"], url=config.SUPPORT_CHAT),
        ],
        [
            primary_button(text=_["S_B_3"], callback_data="open_help"),
        ],
    ]
    return buttons

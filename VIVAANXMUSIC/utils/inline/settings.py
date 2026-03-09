from typing import Union

from pyrogram.types import InlineKeyboardButton

from VIVAANXMUSIC.utils.button_styles import danger_button, primary_button, success_button


def setting_markup(_):
    buttons = [
        [
            primary_button(text=_["ST_B_1"], callback_data="AU"),
            primary_button(text=_["ST_B_3"], callback_data="LG"),
        ],
        [
            primary_button(text=_["ST_B_2"], callback_data="PM"),
        ],
        [
            primary_button(text=_["ST_B_4"], callback_data="VM"),
        ],
        [
            danger_button(text=_["CLOSE_BUTTON"], callback_data="close"),
        ],
    ]
    return buttons


def vote_mode_markup(_, current, mode: Union[bool, str] = None):
    buttons = [
        [
            primary_button(text="Vᴏᴛɪɴɢ ᴍᴏᴅᴇ ➜", callback_data="VOTEANSWER"),
            success_button(
                text=_["ST_B_5"] if mode == True else _["ST_B_6"],
                callback_data="VOMODECHANGE",
            ) if mode == True else danger_button(
                text=_["ST_B_5"] if mode == True else _["ST_B_6"],
                callback_data="VOMODECHANGE",
            ),
        ],
        [
            danger_button(text="-2", callback_data="FERRARIUDTI M"),
            InlineKeyboardButton(
                text=f"ᴄᴜʀʀᴇɴᴛ : {current}",
                callback_data="ANSWERVOMODE",
            ),
            success_button(text="+2", callback_data="FERRARIUDTI A"),
        ],
        [
            primary_button(
                text=_["BACK_BUTTON"],
                callback_data="settings_helper",
            ),
            danger_button(text=_["CLOSE_BUTTON"], callback_data="close"),
        ],
    ]
    return buttons


def auth_users_markup(_, status: Union[bool, str] = None):
    buttons = [
        [
            primary_button(text=_["ST_B_7"], callback_data="AUTHANSWER"),
            success_button(
                text=_["ST_B_8"] if status == True else _["ST_B_9"],
                callback_data="AUTH",
            ) if status == True else danger_button(
                text=_["ST_B_8"] if status == True else _["ST_B_9"],
                callback_data="AUTH",
            ),
        ],
        [
            primary_button(text=_["ST_B_1"], callback_data="AUTHLIST"),
        ],
        [
            primary_button(
                text=_["BACK_BUTTON"],
                callback_data="settings_helper",
            ),
            danger_button(text=_["CLOSE_BUTTON"], callback_data="close"),
        ],
    ]
    return buttons


def playmode_users_markup(
    _,
    Direct: Union[bool, str] = None,
    Group: Union[bool, str] = None,
    Playtype: Union[bool, str] = None,
):
    buttons = [
        [
            primary_button(text=_["ST_B_10"], callback_data="SEARCHANSWER"),
            success_button(
                text=_["ST_B_11"] if Direct == True else _["ST_B_12"],
                callback_data="MODECHANGE",
            ) if Direct == True else danger_button(
                text=_["ST_B_11"] if Direct == True else _["ST_B_12"],
                callback_data="MODECHANGE",
            ),
        ],
        [
            primary_button(text=_["ST_B_13"], callback_data="AUTHANSWER"),
            success_button(
                text=_["ST_B_8"] if Group == True else _["ST_B_9"],
                callback_data="CHANNELMODECHANGE",
            ) if Group == True else danger_button(
                text=_["ST_B_8"] if Group == True else _["ST_B_9"],
                callback_data="CHANNELMODECHANGE",
            ),
        ],
        [
            primary_button(text=_["ST_B_14"], callback_data="PLAYTYPEANSWER"),
            success_button(
                text=_["ST_B_8"] if Playtype == True else _["ST_B_9"],
                callback_data="PLAYTYPECHANGE",
            ) if Playtype == True else danger_button(
                text=_["ST_B_8"] if Playtype == True else _["ST_B_9"],
                callback_data="PLAYTYPECHANGE",
            ),
        ],
        [
            primary_button(
                text=_["BACK_BUTTON"],
                callback_data="settings_helper",
            ),
            danger_button(text=_["CLOSE_BUTTON"], callback_data="close"),
        ],
    ]
    return buttons

def audio_quality_markup(
    _,
    low: Union[bool, str] = None,
    medium: Union[bool, str] = None,
    high: Union[bool, str] = None,
):
    buttons = [
        [
            success_button(
                text=_["ST_B_8"].format("✅"),
                callback_data="LQA",
            ) if low == True else InlineKeyboardButton(
                text=_["ST_B_8"].format(""),
                callback_data="LQA",
            )
        ],
        [
            success_button(
                text=_["ST_B_9"].format("✅"),
                callback_data="MQA",
            ) if medium == True else InlineKeyboardButton(
                text=_["ST_B_9"].format(""),
                callback_data="MQA",
            )
        ],
        [
            success_button(
                text=_["ST_B_10"].format("✅"),
                callback_data="HQA",
            ) if high == True else InlineKeyboardButton(
                text=_["ST_B_10"].format(""),
                callback_data="HQA",
            )
        ],
        [
            primary_button(
                text=_["BACK_BUTTON"],
                callback_data="settingsback_helper",
            ),
            danger_button(
                text=_["CLOSE_BUTTON"], callback_data="close"
            ),
        ],
    ]
    return buttons


def video_quality_markup(
    _,
    low: Union[bool, str] = None,
    medium: Union[bool, str] = None,
    high: Union[bool, str] = None,
):
    buttons = [
        [
            success_button(
                text=_["ST_B_11"].format("✅"),
                callback_data="LQV",
            ) if low == True else InlineKeyboardButton(
                text=_["ST_B_11"].format(""),
                callback_data="LQV",
            )
        ],
        [
            success_button(
                text=_["ST_B_12"].format("✅"),
                callback_data="MQV",
            ) if medium == True else InlineKeyboardButton(
                text=_["ST_B_12"].format(""),
                callback_data="MQV",
            )
        ],
        [
            success_button(
                text=_["ST_B_13"].format("✅"),
                callback_data="HQV",
            ) if high == True else InlineKeyboardButton(
                text=_["ST_B_13"].format(""),
                callback_data="HQV",
            )
        ],
        [
            primary_button(
                text=_["BACK_BUTTON"],
                callback_data="settingsback_helper",
            ),
            danger_button(
                text=_["CLOSE_BUTTON"], callback_data="close"
            ),
        ],
    ]
    return buttons

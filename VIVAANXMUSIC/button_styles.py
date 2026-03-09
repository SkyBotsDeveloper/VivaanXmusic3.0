import inspect
from typing import Any, Optional

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton


_STYLE_SUPPORTED = "style" in inspect.signature(InlineKeyboardButton.__init__).parameters


def styled_button(*, style: Optional[ButtonStyle] = None, **kwargs: Any) -> InlineKeyboardButton:
    if _STYLE_SUPPORTED and style is not None:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def primary_button(**kwargs: Any) -> InlineKeyboardButton:
    return styled_button(style=ButtonStyle.PRIMARY, **kwargs)


def success_button(**kwargs: Any) -> InlineKeyboardButton:
    return styled_button(style=ButtonStyle.SUCCESS, **kwargs)


def danger_button(**kwargs: Any) -> InlineKeyboardButton:
    return styled_button(style=ButtonStyle.DANGER, **kwargs)

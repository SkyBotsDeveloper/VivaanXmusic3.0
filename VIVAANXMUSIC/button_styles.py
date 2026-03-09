import inspect
from typing import Any

from pyrogram.types import InlineKeyboardButton

try:
    from pyrogram.enums import ButtonStyle as _ButtonStyle
except Exception:
    _ButtonStyle = None


_STYLE_SUPPORTED = "style" in inspect.signature(InlineKeyboardButton.__init__).parameters


def styled_button(*, style: Any = None, **kwargs: Any) -> InlineKeyboardButton:
    if _STYLE_SUPPORTED and style is not None:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def primary_button(**kwargs: Any) -> InlineKeyboardButton:
    return styled_button(
        style=getattr(_ButtonStyle, "PRIMARY", None),
        **kwargs,
    )


def success_button(**kwargs: Any) -> InlineKeyboardButton:
    return styled_button(
        style=getattr(_ButtonStyle, "SUCCESS", None),
        **kwargs,
    )


def danger_button(**kwargs: Any) -> InlineKeyboardButton:
    return styled_button(
        style=getattr(_ButtonStyle, "DANGER", None),
        **kwargs,
    )

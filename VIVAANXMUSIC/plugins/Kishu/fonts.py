from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from VIVAANXMUSIC import app
from VIVAANXMUSIC.utils.font_styles import Fonts

FONT_TEXT_CACHE: dict[tuple[int, int], str] = {}

PAGE_ONE = [
    [("Typewriter", "typewriter"), ("Outline", "outline"), ("Serif", "serif")],
    [("Bold Serif", "bold_cool"), ("Cool", "cool"), ("Small Caps", "small_cap")],
    [("Script", "script"), ("Script Bold", "script_bolt"), ("Tiny", "tiny")],
    [("Comic", "comic"), ("Sans", "sans"), ("Slant Sans", "slant_sans")],
    [("Slant", "slant"), ("Sim", "sim"), ("Circles", "circles")],
    [("Dark Circles", "circle_dark"), ("Gothic", "gothic"), ("Bold Gothic", "gothic_bolt")],
    [("Cloud", "cloud"), ("Happy", "happy"), ("Sad", "sad")],
]

PAGE_TWO = [
    [("Special", "special"), ("Squares", "squares"), ("Bold Squares", "squares_bold")],
    [("Andalucia", "andalucia"), ("Manga", "manga"), ("Stinky", "stinky")],
    [("Bubbles", "bubbles"), ("Underline", "underline"), ("Ladybug", "ladybug")],
    [("Rays", "rays"), ("Birds", "birds"), ("Slash", "slash")],
    [("Stop", "stop"), ("Skyline", "skyline"), ("Arrows", "arrows")],
    [("Qvnes", "qvnes"), ("Strike", "strike"), ("Frozen", "frozen")],
]

STYLE_MAP = {
    "typewriter": Fonts.typewriter,
    "outline": Fonts.outline,
    "serif": Fonts.serief,
    "bold_cool": Fonts.bold_cool,
    "cool": Fonts.cool,
    "small_cap": Fonts.smallcap,
    "script": Fonts.script,
    "script_bolt": Fonts.bold_script,
    "tiny": Fonts.tiny,
    "comic": Fonts.comic,
    "sans": Fonts.san,
    "slant_sans": Fonts.slant_san,
    "slant": Fonts.slant,
    "sim": Fonts.sim,
    "circles": Fonts.circles,
    "circle_dark": Fonts.dark_circle,
    "gothic": Fonts.gothic,
    "gothic_bolt": Fonts.bold_gothic,
    "cloud": Fonts.cloud,
    "happy": Fonts.happy,
    "sad": Fonts.sad,
    "special": Fonts.special,
    "squares": Fonts.square,
    "squares_bold": Fonts.dark_square,
    "andalucia": Fonts.andalucia,
    "manga": Fonts.manga,
    "stinky": Fonts.stinky,
    "bubbles": Fonts.bubbles,
    "underline": Fonts.underline,
    "ladybug": Fonts.ladybug,
    "rays": Fonts.rays,
    "birds": Fonts.birds,
    "slash": Fonts.slash,
    "stop": Fonts.stop,
    "skyline": Fonts.skyline,
    "arrows": Fonts.arrows,
    "qvnes": Fonts.rvnes,
    "strike": Fonts.strike,
    "frozen": Fonts.frozen,
}


def _cache_key(message) -> tuple[int, int]:
    return message.chat.id, message.id


def _build_buttons(page: int) -> InlineKeyboardMarkup:
    rows = PAGE_ONE if page == 0 else PAGE_TWO
    keyboard = [
        [
            InlineKeyboardButton(label, callback_data=f"style+{style_name}")
            for label, style_name in row
        ]
        for row in rows
    ]
    if page == 0:
        keyboard.append(
            [
                InlineKeyboardButton("Close", callback_data="close_reply"),
                InlineKeyboardButton("Next ->", callback_data="nxt"),
            ]
        )
    else:
        keyboard.append(
            [
                InlineKeyboardButton("Close", callback_data="close_reply"),
                InlineKeyboardButton("Back", callback_data="nxt+0"),
            ]
        )
    return InlineKeyboardMarkup(keyboard)


def _extract_source_text(message) -> str:
    cached = FONT_TEXT_CACHE.get(_cache_key(message))
    if cached:
        return cached
    return (message.text or "").replace("`", "").strip()


@app.on_message(filters.command(["font", "fonts"]))
async def style_buttons(_, message, cb=False):
    if cb:
        await message.message.edit_reply_markup(_build_buttons(0))
        return

    if len(message.command) < 2:
        return await message.reply(
            "❌ Please provide text to style.\n\nExample: `/font Hello World!`",
            quote=True,
        )

    text = message.text.split(" ", 1)[1].strip()
    sent = await message.reply_text(
        f"`{text}`",
        reply_markup=_build_buttons(0),
        quote=True,
    )
    FONT_TEXT_CACHE[_cache_key(sent)] = text


@app.on_callback_query(filters.regex("^nxt"))
async def nxt(_, query):
    await query.answer()
    if query.data == "nxt":
        await query.message.edit_reply_markup(_build_buttons(1))
    else:
        await query.message.edit_reply_markup(_build_buttons(0))


@app.on_callback_query(filters.regex("^style"))
async def style(_, query):
    await query.answer()
    _, style_name = query.data.split("+", 1)

    styler = STYLE_MAP.get(style_name)
    if not styler:
        return await query.answer("Unknown style type.", show_alert=True)

    text = _extract_source_text(query.message)
    if not text:
        return await query.answer(
            "Original text was not found. Send /font again.",
            show_alert=True,
        )

    FONT_TEXT_CACHE[_cache_key(query.message)] = text
    await query.message.edit_text(
        styler(text),
        reply_markup=query.message.reply_markup,
    )

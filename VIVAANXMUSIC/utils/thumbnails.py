import asyncio
import os
import re
from functools import lru_cache
import aiofiles
import aiohttp
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from unidecode import unidecode
from urllib.request import Request, urlopen
from youtubesearchpython.future import VideosSearch
from VIVAANXMUSIC import app
from config import BOT_NAME, YOUTUBE_IMG_URL
from VIVAANXMUSIC.core.dir import CACHE_DIR


# Font paths
TITLE_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font2.ttf"
META_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font.ttf"
FALLBACK_AVATAR_URL = "https://files.catbox.moe/0ld5qc.jpg"

# Constants - Enhanced Layout
CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
ART_SIZE = 296
AVATAR_SIZE = 112
ART_CARD_BOX = (882, 118, 1226, 560)
PLAYBACK_BOX = (44, 566, 1236, 676)
BRAND_BOX = (964, 38, 1236, 92)
NOW_PLAYING_BOX = (58, 58, 220, 104)


def fit_cover(image, width: int, height: int):
    """Resize and crop image to fill the target area."""
    src = image.convert("RGBA")
    ratio = max(width / src.size[0], height / src.size[1])
    resized = src.resize(
        (int(src.size[0] * ratio), int(src.size[1] * ratio)),
        Image.LANCZOS,
    )
    left = max((resized.size[0] - width) // 2, 0)
    top = max((resized.size[1] - height) // 2, 0)
    return resized.crop((left, top, left + width, top + height))


def antialiased_circle_mask(size: int, scale: int = 4):
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * scale, size * scale), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def antialiased_rounded_mask(size: int, radius: int, scale: int = 4):
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * scale, size * scale),
        radius=radius * scale,
        fill=255,
    )
    return mask.resize((size, size), Image.LANCZOS)


def masked_circle(image, size: int, border_width: int = 6, border_color=(255, 255, 255, 240)):
    fitted = fit_cover(image, size, size)
    mask = antialiased_circle_mask(size)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(fitted, (0, 0), mask)
    if border_width > 0:
        draw = ImageDraw.Draw(result)
        inset = border_width // 2
        draw.ellipse(
            (inset, inset, size - inset - 1, size - inset - 1),
            outline=border_color,
            width=border_width,
        )
    return result


def rounded_media(image, size: int, radius: int = 36, border_width: int = 5):
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner_padding = max(border_width - 1, 3)
    inner_size = max(size - (inner_padding * 2), 1)
    fitted = fit_cover(image, inner_size, inner_size)
    mask = antialiased_rounded_mask(inner_size, max(radius - inner_padding, 1))
    result.paste(fitted, (inner_padding, inner_padding), mask)
    draw = ImageDraw.Draw(result)
    inset = border_width // 2
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=max(radius - 2, 1),
        outline=(255, 255, 255, 210),
        width=border_width,
    )
    return result


def trim_text(text: str, limit: int) -> str:
    clean_text = " ".join(str(text or "").split())
    if len(clean_text) <= limit:
        return clean_text
    return clean_text[: max(limit - 3, 0)].rstrip() + "..."


def resolve_brand_name() -> str:
    raw_name = getattr(app, "name", None) or BOT_NAME or "EliteMusic"
    clean_name = trim_text(" ".join(unidecode(str(raw_name)).split()), 24)
    return clean_name or "EliteMusic"


@lru_cache(maxsize=16)
def load_font(path, size: int):
    """Load font with fallback to default."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def cache_remote_file(url: str, output_path: str) -> bool:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        if getattr(response, "status", 200) != 200:
            return False
        with open(output_path, "wb") as file:
            file.write(response.read())
    return True


def text_width(draw, text: str, font) -> float:
    try:
        return draw.textlength(text, font=font)
    except Exception:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]


def wrap_text(draw, text: str, font, max_width: int, max_lines: int = 3) -> list[str]:
    words = trim_text(text, 140).split()
    if not words:
        return ["Unknown Title"]

    lines = []
    current = ""
    index = 0

    while index < len(words):
        word = words[index]
        test_line = f"{current} {word}".strip()
        if not current or text_width(draw, test_line, font) <= max_width:
            current = test_line
            index += 1
            continue

        lines.append(current)
        current = ""
        if len(lines) == max_lines - 1:
            break

    remaining = " ".join(words[index:]).strip()
    last_line = current if current else remaining
    if remaining and current and current != remaining:
        last_line = f"{current} {remaining}".strip()
    if text_width(draw, last_line, font) > max_width:
        while last_line and text_width(draw, f"{last_line}...", font) > max_width:
            last_line = last_line[:-1].rstrip()
        last_line = f"{last_line}..." if last_line else "..."

    if last_line:
        lines.append(last_line)
    return lines[:max_lines]


def draw_waveform(
    draw,
    x_start,
    y,
    width,
    height,
    accent_color,
    base_color,
    progress_ratio=0.37,
    segments=72,
):
    """Draw a cleaner rhythmic waveform with active/inactive regions."""
    segment_width = width / max(segments, 1)
    active_x = x_start + (width * progress_ratio)
    accent_rgba = (*accent_color[:3], 205) if len(accent_color) == 4 else (*accent_color, 205)
    base_rgba = (*base_color[:3], 92) if len(base_color) == 4 else (*base_color, 92)

    for i in range(segments):
        center_x = x_start + ((i + 0.5) * segment_width)
        motion = (
            abs(np.sin((i * 0.31) + 0.4)) * 0.52
            + abs(np.sin((i * 0.12) + 1.7)) * 0.28
            + abs(np.sin((i * 0.74) + 0.2)) * 0.16
        )
        bar_height = max(4, int((height * 0.28) + (height * min(motion, 0.92))))
        line_width = 2 if i % 7 else 3
        color = accent_rgba if center_x <= active_x else base_rgba

        draw.line(
            [
                (center_x, y - bar_height),
                (center_x, y + bar_height),
            ],
            fill=color,
            width=line_width,
        )


def draw_text_with_outline(draw, position, text, font, fill_color, outline_color, outline_width=2):
    """Draw text with outline effect for better visibility."""
    x, y = position
    for adj_x in range(-outline_width, outline_width + 1):
        for adj_y in range(-outline_width, outline_width + 1):
            if adj_x != 0 or adj_y != 0:
                draw.text((x + adj_x, y + adj_y), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)


def add_glow(base, box, color, blur_radius=70):
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(box, fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(blur_radius))
    return Image.alpha_composite(base, glow)


def draw_glass_panel(
    base,
    box,
    radius=34,
    fill=(18, 28, 40, 122),
    border=(255, 255, 255, 68),
    blur_radius=18,
    show_top_line=True,
    show_bottom_line=True,
):
    x1, y1, x2, y2 = [int(value) for value in box]
    width = x2 - x1
    height = y2 - y1

    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (x1 + 10, y1 + 14, x2 + 10, y2 + 14),
        radius=radius,
        fill=(0, 0, 0, 72),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    base = Image.alpha_composite(base, shadow)

    crop = base.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(blur_radius))
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=255)
    base.paste(crop, (x1, y1), mask)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle((0, 0, width, height), radius=radius, fill=fill)
    overlay_draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=radius,
        outline=border,
        width=2,
    )
    if show_top_line:
        overlay_draw.line(
            [(26, 24), (width - 28, 24)],
            fill=(255, 255, 255, 50),
            width=2,
        )
    if show_bottom_line:
        overlay_draw.line(
            [(24, height - 26), (width - 24, height - 46)],
            fill=(255, 255, 255, 20),
            width=1,
        )
    base.alpha_composite(overlay, (x1, y1))
    return base


def draw_chip(draw, box, label, value, label_font, value_font, accent_color):
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 14), label.upper(), fill=(196, 211, 223), font=label_font)
    draw.text((x1 + 18, y1 + 42), value, fill=(255, 255, 255), font=value_font)
    draw.rounded_rectangle(
        (x1, y1, x1 + 8, y2),
        radius=4,
        fill=accent_color,
    )


def accent_palette(image):
    sample = np.array(image.convert("RGB").resize((40, 40))).reshape(-1, 3)
    usable = sample[sample.mean(axis=1) > 40]
    if usable.size == 0:
        usable = sample
    base = usable.mean(axis=0)
    accent = tuple(int(max(70, min(255, channel * 1.15))) for channel in base)
    soft = tuple(int((channel * 0.55) + 90) for channel in accent)
    return accent, soft


async def get_thumb(videoid, user_id=None):
    """Generate an enhanced glassmorphic playback thumbnail."""
    cache_user_id = user_id if user_id is not None else "blank"
    cache_path = os.path.join(CACHE_DIR, f"{videoid}_{cache_user_id}_elite_glass_v19.png")
    if os.path.isfile(cache_path):
        return cache_path

    url = f"https://www.youtube.com/watch?v={videoid}"
    temp_thumb_path = os.path.join(CACHE_DIR, f"thumb_{videoid}_glass.png")
    fallback_avatar_path = os.path.join(CACHE_DIR, "elite_avatar_fallback.jpg")
    sp = None
    try:
        results = VideosSearch(url, limit=1)
        results_data = (await results.next()).get("result", [])
        if not results_data:
            return YOUTUBE_IMG_URL

        result = results_data[0]
        title = trim_text(
            re.sub(r"\s+", " ", re.sub(r"[^\w\s&\-']", " ", result.get("title", ""))).strip().title()
            or "Unsupported Title",
            140,
        )
        duration = str(result.get("duration") or "Unknown")
        thumbnail = result.get("thumbnails", [{}])[0].get("url", "").split("?")[0]
        views = trim_text(str((result.get("viewCount") or {}).get("short") or "Unknown Views"), 18)
        channel = trim_text(str((result.get("channel") or {}).get("name") or "Unknown Channel"), 34)

        if not thumbnail:
            return YOUTUBE_IMG_URL

        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail) as resp:
                if resp.status != 200:
                    return YOUTUBE_IMG_URL
                f = await aiofiles.open(temp_thumb_path, mode="wb")
                await f.write(await resp.read())
                await f.close()

        if user_id is not None:
            try:
                async for photo in app.get_chat_photos(user_id, 1):
                    sp = await app.download_media(photo.file_id, file_name=f"{user_id}.jpg")
                    break
            except Exception:
                sp = None

        if sp:
            user_dp = Image.open(sp).convert("RGBA")
        else:
            if not os.path.isfile(fallback_avatar_path):
                try:
                    await asyncio.to_thread(
                        cache_remote_file,
                        FALLBACK_AVATAR_URL,
                        fallback_avatar_path,
                    )
                except Exception:
                    pass

            try:
                user_dp = Image.open(fallback_avatar_path).convert("RGBA")
            except Exception:
                user_dp = Image.new("RGBA", (200, 200), (100, 100, 100, 255))

        youtube_thumb = Image.open(temp_thumb_path).convert("RGBA")
        accent_color, accent_soft = accent_palette(youtube_thumb)
        accent_glow = (*accent_color, 78)
        accent_wash = (*accent_soft, 54)

        background = fit_cover(youtube_thumb, CANVAS_WIDTH, CANVAS_HEIGHT)
        background = background.filter(ImageFilter.GaussianBlur(22))
        background = ImageEnhance.Contrast(background).enhance(1.04)
        background = ImageEnhance.Color(background).enhance(0.76)
        background = ImageEnhance.Brightness(background).enhance(0.43)

        overlay = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for y in range(CANVAS_HEIGHT):
            alpha = int(84 + (72 * y / CANVAS_HEIGHT))
            overlay_draw.line([(0, y), (CANVAS_WIDTH, y)], fill=(7, 11, 18, alpha), width=1)
        for x in range(CANVAS_WIDTH):
            alpha = int(132 * (1 - (x / CANVAS_WIDTH)))
            overlay_draw.line([(x, 0), (x, CANVAS_HEIGHT)], fill=(10, 18, 28, alpha), width=1)
        background = Image.alpha_composite(background, overlay)
        background = add_glow(background, (-120, 450, 340, 900), accent_wash, blur_radius=120)
        background = add_glow(background, (900, -80, 1310, 280), accent_glow, blur_radius=100)

        background = draw_glass_panel(
            background,
            ART_CARD_BOX,
            radius=40,
            fill=(17, 26, 37, 92),
            border=(255, 255, 255, 62),
            blur_radius=18,
            show_top_line=False,
            show_bottom_line=False,
        )
        background = draw_glass_panel(
            background,
            PLAYBACK_BOX,
            radius=28,
            fill=(15, 23, 34, 92),
            border=(255, 255, 255, 56),
            blur_radius=15,
            show_top_line=False,
            show_bottom_line=False,
        )
        background = draw_glass_panel(
            background,
            BRAND_BOX,
            radius=24,
            fill=(22, 31, 43, 94),
            border=(255, 255, 255, 54),
            blur_radius=12,
            show_top_line=False,
            show_bottom_line=False,
        )
        background = draw_glass_panel(
            background,
            NOW_PLAYING_BOX,
            radius=22,
            fill=(22, 31, 43, 96),
            border=(255, 255, 255, 54),
            blur_radius=12,
            show_top_line=False,
            show_bottom_line=False,
        )

        art = rounded_media(youtube_thumb, ART_SIZE, radius=40, border_width=5)
        art_x = ART_CARD_BOX[0] + ((ART_CARD_BOX[2] - ART_CARD_BOX[0] - ART_SIZE) // 2)
        art_y = 166
        background = add_glow(
            background,
            (art_x - 30, art_y - 24, art_x + ART_SIZE + 34, art_y + ART_SIZE + 42),
            (*accent_color, 72),
            blur_radius=74,
        )
        background.paste(art, (art_x, art_y), art)

        avatar = masked_circle(user_dp, AVATAR_SIZE, border_width=6, border_color=(255, 255, 255, 230))
        avatar_x = art_x + ART_SIZE - AVATAR_SIZE // 2 + 2
        avatar_y = art_y + ART_SIZE - AVATAR_SIZE // 2 + 6
        avatar_x = min(avatar_x, CANVAS_WIDTH - AVATAR_SIZE - 28)
        avatar_y = min(avatar_y, CANVAS_HEIGHT - AVATAR_SIZE - 28)
        background = add_glow(
            background,
            (avatar_x - 18, avatar_y - 16, avatar_x + AVATAR_SIZE + 20, avatar_y + AVATAR_SIZE + 22),
            (*accent_soft, 64),
            blur_radius=58,
        )
        background.paste(avatar, (avatar_x, avatar_y), avatar)

        draw = ImageDraw.Draw(background)

        eyebrow_font = load_font(META_FONT_PATH, 15)
        title_font = load_font(TITLE_FONT_PATH, 50)
        sub_font = load_font(META_FONT_PATH, 24)
        meta_font = load_font(META_FONT_PATH, 20)
        progress_label_font = load_font(META_FONT_PATH, 16)
        progress_time_font = load_font(META_FONT_PATH, 18)
        brand_font = load_font(TITLE_FONT_PATH, 22)

        now_playing_text = "NOW PLAYING"
        now_playing_center_x = (NOW_PLAYING_BOX[0] + NOW_PLAYING_BOX[2]) / 2
        now_playing_center_y = ((NOW_PLAYING_BOX[1] + NOW_PLAYING_BOX[3]) / 2) + 1
        draw.text(
            (now_playing_center_x, now_playing_center_y),
            now_playing_text,
            fill=(238, 244, 250),
            font=eyebrow_font,
            anchor="mm",
        )

        title_lines = wrap_text(draw, title, title_font, 690, max_lines=2)
        title_y = 148
        line_height = 60
        for index, line in enumerate(title_lines):
            draw_text_with_outline(
                draw,
                (60, title_y + (index * line_height)),
                line,
                title_font,
                fill_color=(255, 255, 255),
                outline_color=(6, 10, 14),
                outline_width=1,
            )

        subtitle_y = title_y + (len(title_lines) * line_height) + 10
        draw.text(
            (60, subtitle_y),
            trim_text(channel, 34),
            fill=(215, 225, 235),
            font=sub_font,
        )

        meta_text = f"{trim_text(duration, 10)}  •  {views}  •  YouTube"
        draw.text(
            (60, subtitle_y + 42),
            meta_text,
            fill=(182, 196, 210),
            font=meta_font,
        )
        draw.rounded_rectangle(
            (60, subtitle_y + 82, 260, subtitle_y + 88),
            radius=3,
            fill=(*accent_color, 190),
        )

        progress_left = PLAYBACK_BOX[0] + 34
        bar_y = PLAYBACK_BOX[1] + 57
        bar_x_start = progress_left
        bar_x_end = PLAYBACK_BOX[2] - 34
        bar_width = bar_x_end - bar_x_start
        progress_ratio = 0.37
        prog_x = bar_x_start + int(bar_width * progress_ratio)

        draw.line(
            [(bar_x_start, bar_y), (bar_x_end, bar_y)],
            fill=(255, 255, 255, 34),
            width=2,
        )
        draw.line(
            [(bar_x_start, bar_y), (prog_x, bar_y)],
            fill=(*accent_color, 165),
            width=3,
        )
        draw_waveform(
            draw,
            bar_x_start,
            bar_y,
            bar_width,
            14,
            accent_color,
            (255, 255, 255, 255),
            progress_ratio=progress_ratio,
            segments=72,
        )

        draw.ellipse(
            [(prog_x - 13, bar_y - 13), (prog_x + 13, bar_y + 13)],
            fill=(*accent_color, 52),
        )
        draw.ellipse(
            [(prog_x - 8, bar_y - 8), (prog_x + 8, bar_y + 8)],
            fill=(255, 255, 255),
            outline=accent_color,
            width=3,
        )

        time_y = PLAYBACK_BOX[1] + 77
        draw.text(
            (bar_x_start, time_y),
            "00:00",
            fill=(255, 255, 255),
            font=progress_time_font,
        )
        duration_text_width = text_width(draw, duration, progress_time_font)
        draw.text(
            (bar_x_end - duration_text_width, time_y),
            duration,
            fill=(255, 255, 255),
            font=progress_time_font,
        )

        brand_name = resolve_brand_name()
        brand_center_x = (BRAND_BOX[0] + BRAND_BOX[2]) / 2
        brand_center_y = ((BRAND_BOX[1] + BRAND_BOX[3]) / 2) + 1
        draw.text(
            (brand_center_x, brand_center_y),
            brand_name,
            fill=(255, 255, 255),
            font=brand_font,
            anchor="mm",
        )

        draw.text(
            (ART_CARD_BOX[0] + 28, ART_CARD_BOX[3] - 74),
            trim_text(channel, 22),
            fill=(232, 239, 247),
            font=sub_font,
        )
        draw.text(
            (ART_CARD_BOX[0] + 28, ART_CARD_BOX[3] - 42),
            f"{views}  •  YouTube",
            fill=(186, 200, 214),
            font=progress_label_font,
        )

        try:
            os.remove(temp_thumb_path)
        except Exception:
            pass
        try:
            if sp and os.path.exists(sp):
                os.remove(sp)
        except Exception:
            pass

        background.save(cache_path)
        return cache_path

    except Exception:
        try:
            if os.path.exists(temp_thumb_path):
                os.remove(temp_thumb_path)
        except Exception:
            pass
        return YOUTUBE_IMG_URL

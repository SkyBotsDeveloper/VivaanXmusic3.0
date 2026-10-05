"""Vivaan playback cards with Ruhu's artwork-derived lighting palette."""

import colorsys
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import numpy as np

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from unidecode import unidecode

CANVAS_SIZE = (1280, 720)
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "thumb" / "player"
FONT_BOLD = str(ASSET_DIR / "font.ttf")
FONT_LIGHT = str(ASSET_DIR / "font2.ttf")
TEMPLATE_PATH = ASSET_DIR / "cinematic-template.png"
RESAMPLE = Image.Resampling.LANCZOS


def render_and_save_thumbnail(output_path, youtube, profile, title, duration, views, channel, app_name):
    """Publish a complete image atomically, keeping concurrent cache readers safe."""
    thumbnail = render_thumbnail(youtube, profile, title, duration, views, channel, app_name)
    temporary_path = f"{output_path}.{uuid4().hex}.tmp"
    try:
        thumbnail.save(temporary_path, format="PNG", compress_level=5)
        os.replace(temporary_path, output_path)
    finally:
        thumbnail.close()
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
    return output_path


def _cover(image, size, centering=(0.5, 0.5)):
    return ImageOps.fit(
        image.convert("RGB"),
        size,
        method=RESAMPLE,
        centering=centering,
    )


def _mix(first, second, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(
        int(round(a + ((b - a) * amount))) for a, b in zip(first, second)
    )


def _with_alpha(color, alpha):
    return (*color[:3], max(0, min(255, int(alpha))))


def _vibrant(color):
    red, green, blue = (channel / 255 for channel in color)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    saturation = max(0.62, min(0.95, saturation * 1.18))
    value = max(0.82, min(1.0, value * 1.16))
    return tuple(
        int(round(channel * 255))
        for channel in colorsys.hsv_to_rgb(hue, saturation, value)
    )


def _rotate_hue(color, amount):
    red, green, blue = (channel / 255 for channel in color)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    hue = (hue + amount) % 1.0
    saturation = max(0.62, saturation)
    value = max(0.85, value)
    return tuple(
        int(round(channel * 255))
        for channel in colorsys.hsv_to_rgb(hue, saturation, value)
    )


def _extract_accent_colors(image):
    """Find two bright accent colours while preserving the source hue."""
    sample = _cover(image, (128, 72))
    quantized = sample.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    swatches = []

    for count, palette_index in quantized.getcolors(maxcolors=256) or []:
        offset = palette_index * 3
        color = tuple(palette[offset : offset + 3])
        if len(color) != 3:
            continue

        red, green, blue = (channel / 255 for channel in color)
        hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        if saturation < 0.18 or value < 0.15:
            continue

        # Skin/orange tones are useful, but should not overpower a strong
        # environmental colour such as green, blue, or purple.
        skin_penalty = 0.68 if 0.025 <= hue <= 0.12 and saturation < 0.78 else 1.0
        score = (
            count
            * (0.35 + (saturation * 1.55))
            * (0.45 + value)
            * skin_penalty
        )
        swatches.append((score, color, hue))

    if not swatches:
        return (55, 175, 255), (210, 85, 255)

    swatches.sort(reverse=True, key=lambda item: item[0])
    primary_score, primary_raw, primary_hue = swatches[0]
    primary = _vibrant(primary_raw)

    secondary_raw = None
    secondary_rank = -1.0
    for score, color, hue in swatches[1:]:
        hue_distance = min(abs(hue - primary_hue), 1.0 - abs(hue - primary_hue))
        rgb_distance = math.sqrt(
            sum((first - second) ** 2 for first, second in zip(primary_raw, color))
        ) / 441.67
        rank = score * (0.45 + hue_distance + rgb_distance)
        if rank > secondary_rank:
            secondary_rank = rank
            secondary_raw = color

    secondary = _vibrant(secondary_raw) if secondary_raw else _rotate_hue(primary, 0.11)
    distance = math.sqrt(
        sum((first - second) ** 2 for first, second in zip(primary, secondary))
    )
    if distance < 70:
        secondary = _rotate_hue(primary, 0.11)

    return primary, secondary


@lru_cache(maxsize=64)
def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _split_title(raw_title, channel):
    title = unidecode(str(raw_title or "Unsupported Title"))
    qualifiers = [
        re.sub(r"\s+", " ", match).strip()
        for match in re.findall(r"[\(\[]([^)\]]+)[)\]]", title)
    ]
    title = re.sub(r"\s*[\(\[][^)\]]+[)\]]\s*", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -|")

    parts = re.split(r"\s+-\s+", title, maxsplit=1)
    if len(parts) == 2:
        artist, song = parts
        normalized_channel = re.sub(r"\W+", "", unidecode(str(channel))).casefold()
        normalized_artist = re.sub(r"\W+", "", artist).casefold()
        if (
            normalized_artist
            and (
                normalized_artist in normalized_channel
                or normalized_channel in normalized_artist
                or len(artist) <= 35
            )
        ):
            title = song.strip()

    unique_qualifiers = []
    for qualifier in qualifiers:
        if qualifier and qualifier.casefold() not in {
            value.casefold() for value in unique_qualifiers
        }:
            unique_qualifiers.append(qualifier)

    badge = " • ".join(unique_qualifiers[:2]) or "YouTube Music"
    return title or "Unsupported Title", badge


def _ellipsize(draw, text, font, width):
    text = " ".join(str(text or "").split())
    if draw.textlength(text, font=font) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if draw.textlength(text[:middle].rstrip() + "...", font=font) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "..."


def _title_layout(draw, text, width):
    words = str(text or "Unknown Title").split()
    for size in (54, 48, 42, 38):
        font = _font(FONT_BOLD, size)
        lines, current = [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
        if len(lines) <= 2 and all(draw.textlength(line, font=font) <= width for line in lines):
            return font, lines
    fitted = [_ellipsize(draw, lines[0], font, width)]
    if len(lines) > 1:
        fitted.append(_ellipsize(draw, " ".join(lines[1:]), font, width))
    return font, fitted


@lru_cache(maxsize=1)
def _load_template():
    """Separate the generated neutral light plate from its two chroma apertures."""
    with Image.open(TEMPLATE_PATH) as source:
        plate = source.convert("RGB").resize(CANVAS_SIZE, RESAMPLE)
    pixels = np.asarray(plate, dtype=np.float32)
    red, green, blue = (pixels[:, :, channel] for channel in range(3))
    dominance = green - np.maximum(red, blue)
    # Smooth chroma keying retains the generated aperture's antialiased rim.
    chroma = np.clip(1.1 * (dominance - 8) / np.maximum(green - 8, 1), 0, 1)
    chroma[(green < 80) | (dominance < 25)] = 0
    left = chroma.copy()
    left[:, CANVAS_SIZE[0] // 2:] = 0
    right = chroma.copy()
    right[:, :CANVAS_SIZE[0] // 2] = 0
    masks = tuple(Image.fromarray(np.rint(values * 255).astype(np.uint8))
                  for values in (left, right))
    if any(mask.getbbox() is None for mask in masks):
        raise ValueError("Cinematic template is missing an artwork/profile aperture")
    # The neutral template alone is tinted; original artwork/portraits never are.
    neutral = np.asarray(plate.convert("L"), dtype=np.float32) / 255
    neutral *= 1 - chroma
    neutral.setflags(write=False)
    return neutral, masks


def _recolor_template(primary, secondary):
    neutral, _ = _load_template()
    position = np.linspace(0, 1, CANVAS_SIZE[0], dtype=np.float32)[None, :, None]
    palette = (np.asarray(primary, dtype=np.float32)[None, None, :] * (1 - position)
               + np.asarray(secondary, dtype=np.float32)[None, None, :] * position)
    light = neutral[:, :, None]
    # Colored bloom with a near-white emissive core preserves realistic lighting.
    white = np.clip((light - 0.55) / 0.45, 0, 1) * 0.84
    pixels = light * (palette * (1 - white) + 255 * white)
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))


def _paste_slot(canvas, source, mask, preserve_full_image=False):
    box = mask.getbbox()
    size = (box[2] - box[0], box[3] - box[1])
    if preserve_full_image:
        slot = _cover(source, size).filter(ImageFilter.GaussianBlur(14))
        slot = ImageEnhance.Brightness(slot).enhance(0.55)
        artwork = ImageOps.contain(source.convert("RGB"), size, method=RESAMPLE)
        slot.paste(artwork, ((size[0] - artwork.width) // 2,
                            (size[1] - artwork.height) // 2))
    else:
        slot = _cover(source, size)
    canvas.paste(slot, box[:2], mask.crop(box))


def render_thumbnail(youtube, profile, title, duration, views, channel, app_name):
    """Fill the generated design locally; lighting follows this song's artwork."""
    primary, secondary = _extract_accent_colors(youtube)
    light_plate = _recolor_template(primary, secondary)
    background = _cover(youtube, CANVAS_SIZE).filter(ImageFilter.GaussianBlur(28))
    background = ImageEnhance.Brightness(background).enhance(0.16)
    canvas = ImageChops.screen(light_plate, background)
    _, (album_mask, avatar_mask) = _load_template()
    _paste_slot(canvas, youtube, album_mask, preserve_full_image=True)
    _paste_slot(canvas, profile, avatar_mask)

    details = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(details)
    brand_font = _font(FONT_LIGHT, 25)
    brand = unidecode(str(app_name or "Vivaan Music"))
    draw.text((1220, 22), _ellipsize(draw, brand, brand_font, 650),
              anchor="ra", font=brand_font, fill=(240, 248, 255))
    draw.text((82, 428), "NOW PLAYING", font=_font(FONT_LIGHT, 19),
              fill=_mix(primary, (255, 255, 239), 0.8))
    metadata = f"{unidecode(str(channel or 'Unknown Channel'))}  |  {views or 'Unknown Views'}"
    meta_font = _font(FONT_LIGHT, 21)
    draw.text((218, 476), _ellipsize(draw, metadata, meta_font, 570),
              font=meta_font, fill=(223, 235, 247))
    display_title, badge = _split_title(title, channel)
    font, lines = _title_layout(draw, display_title, 558)
    if len(lines) == 2:
        font = _font(FONT_BOLD, min(font.size, 38))
    for index, line in enumerate(lines):
        draw.text((216, 505 + index * 44), line, font=font, fill=(253, 254, 255))
    badge_font = _font(FONT_LIGHT, 17)
    badge = _ellipsize(draw, badge, badge_font, 520)
    badge_y = 597 if len(lines) == 2 else 576
    badge_width = int(draw.textlength(badge, font=badge_font)) + 28
    draw.rounded_rectangle((218, badge_y, 218 + badge_width, badge_y + 28),
                           radius=14, fill=_with_alpha(primary, 135),
                           outline=_with_alpha(_mix(primary, (255, 255, 241), 0.65), 210), width=1)
    draw.text((232, badge_y + 3), badge, font=badge_font, fill=(252, 254, 255))
    time_font = _font(FONT_LIGHT, 18)
    draw.text((105, 618), "00:00", font=time_font, fill=(222, 235, 247))
    draw.text((1175, 618), str(duration or "Unknown")[:12], anchor="ra", font=time_font,
              fill=(222, 235, 247))
    return Image.alpha_composite(canvas.convert("RGBA"), details).convert("RGB")

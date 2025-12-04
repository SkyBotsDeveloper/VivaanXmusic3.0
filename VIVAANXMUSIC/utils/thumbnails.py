import os
import aiofiles
import aiohttp
import asyncio
from functools import partial
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from youtubesearchpython.__future__ import VideosSearch
from collections import Counter
from config import YOUTUBE_IMG_URL
from VIVAANXMUSIC.core.dir import CACHE_DIR


# Font paths - adjusted for your repo structure
TITLE_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font2.ttf"
META_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font.ttf"


def load_font(path, size: int):
    """Load font with fallback to default if path doesn't exist."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def get_dominant_color_and_brightness(img: Image.Image):
    """Extract dominant color and determine brightness tone."""
    small = img.resize((50, 50))
    pixels = [p for p in small.getdata() if (len(p) == 3) or (len(p) == 4 and p[3] > 128)]
    if not pixels:
        return (255, 0, 0), "dark"
    r, g, b = Counter(pixels).most_common(1)[0][0][:3]
    brightness = (0.299 * r + 0.587 * g + 0.114 * b)
    tone = "dark" if brightness < 128 else "light"
    avg = (r + g + b) // 3
    return (int((r + avg) / 2), int((g + avg) / 2), int((b + avg) / 2)), tone


def wrap_text_multilingual(text, font, max_width, max_lines=2, draw=None):
    """Wrap text intelligently, supporting both space-separated and CJK languages."""
    if draw is None:
        temp = Image.new("RGBA", (10, 10))
        draw = ImageDraw.Draw(temp)
    
    use_word_split = " " in text.strip()
    lines = []
    
    if use_word_split:
        words = text.split()
        current = ""
        for w in words:
            candidate = (current + " " + w).strip() if current else w
            width = draw.textlength(candidate, font=font)
            if width <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = w
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
    else:
        current = ""
        for ch in text:
            candidate = current + ch
            width = draw.textlength(candidate, font=font)
            if width <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = ch
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
    
    # Add ellipsis if text was truncated
    joined = "".join(lines)
    if len(joined) < len(text) and lines:
        last = lines[-1]
        ellipsis = ".."
        while draw.textlength(last + ellipsis, font=font) > max_width and len(last) > 0:
            last = last[:-1]
        lines[-1] = last + ellipsis if len(last) > 0 else ellipsis
    
    return lines[:max_lines]


def draw_text_with_shadow(draw, pos, text, font, fill):
    """Draw text with a subtle shadow effect."""
    x, y = pos
    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 200))
    draw.text((x, y), text, font=font, fill=fill)


async def blur_image(img, radius):
    """Apply Gaussian blur asynchronously."""
    return await asyncio.to_thread(img.filter, ImageFilter.GaussianBlur(radius))


def truncate_title(text, max_words=25, max_chars=120, hard_char_limit=25):
    """Truncate title to reasonable length."""
    words = text.split()
    if len(words) > max_words or len(text) > max_chars:
        text = " ".join(words[:max_words])[:max_chars].rstrip()
    if len(text) > hard_char_limit:
        text = text[:hard_char_limit].rstrip() + "."
    return text


def choose_title_font(text, max_width, max_lines=2):
    """Dynamically choose font size that fits the text."""
    for size in (48, 44, 40, 36, 32, 30, 28, 26, 24):
        f = load_font(TITLE_FONT_PATH, size)
        temp = Image.new("RGBA", (10, 10))
        d = ImageDraw.Draw(temp)
        lines = wrap_text_multilingual(text, f, max_width, max_lines=max_lines, draw=d)
        if len(lines) <= max_lines:
            fits = all(d.textlength(line, font=f) <= max_width for line in lines)
            if fits:
                return f
    return load_font(TITLE_FONT_PATH, 24)


async def _download_image(session, url, path):
    """Download image with error handling."""
    try:
        async with session.get(url, timeout=20) as resp:
            if resp.status == 200:
                async with aiofiles.open(path, "wb") as f:
                    await f.write(await resp.read())
                return True
    except Exception:
        return False
    return False


async def get_thumb(videoid: str) -> str:
    """
    Generate a cinematic thumbnail for a YouTube video.
    
    Args:
        videoid: YouTube video ID
    
    Returns:
        Path to generated thumbnail image
    """
    cache_path = os.path.join(CACHE_DIR, f"{videoid}_cinematic_final.png")
    if os.path.exists(cache_path):
        return cache_path
    
    try:
        # Fetch video metadata from YouTube
        search = VideosSearch(f"https://www.youtube.com/watch?v={videoid}", limit=1)
        result = await search.next()
        data = result["result"][0]
        title = truncate_title(data.get("title", "Unknown Title"))
        thumbnail = data.get("thumbnails", [{}])[0].get("url") or YOUTUBE_IMG_URL
        channel = data.get("channel", {}).get("name", "Unknown Channel")
        views = data.get("viewCount", {}).get("short", "Unknown Views")
        duration = data.get("duration", "Live")
    except Exception:
        title = "Unknown Title"
        thumbnail = YOUTUBE_IMG_URL
        channel = "Unknown Channel"
        views = "Unknown Views"
        duration = "Live"
    
    is_live = str(duration).lower() in {"live", "live now", ""}
    
    # Download thumbnail image
    thumb_path = os.path.join(CACHE_DIR, f"thumb_{videoid}.png")
    async with aiohttp.ClientSession() as session:
        ok = await _download_image(session, thumbnail, thumb_path)
        if not ok and thumbnail != YOUTUBE_IMG_URL:
            ok = await _download_image(session, YOUTUBE_IMG_URL, thumb_path)
        if not ok:
            blue = Image.new("RGBA", (1280, 720), (30, 30, 60, 255))
            async with aiofiles.open(thumb_path, "wb") as f:
                await asyncio.to_thread(blue.save, thumb_path, "PNG")
    
    # Load and process base image
    try:
        base = Image.open(thumb_path).convert("RGBA").resize((1280, 720))
    except Exception:
        base = Image.new("RGBA", (1280, 720), (30, 30, 60, 255))
    
    # Extract dominant color and determine text color
    dom_color, tone = get_dominant_color_and_brightness(base)
    text_color = "white" if tone == "dark" else "#222222"
    meta_color = "#DDDDDD" if tone == "dark" else "#333333"
    
    # Create background with blur and glass effect
    bg = await blur_image(base, 32)
    glass = Image.new("RGBA", bg.size, (255, 255, 255, 70))
    bg = Image.alpha_composite(bg, glass)
    
    # Add vibrant gradient overlay
    vib = Image.new("RGBA", bg.size)
    vd = ImageDraw.Draw(vib)
    w, h = bg.size
    for y in range(h):
        r = int(dom_color[0] + (255 - dom_color[0]) * (y / h))
        g = int(dom_color[1] + (255 - dom_color[1]) * (y / h))
        b = int(dom_color[2] + (255 - dom_color[2]) * (y / h))
        vd.line([(0, y), (w, y)], fill=(r, g, b, 90), width=1)
    bg = Image.alpha_composite(bg, vib)
    
    # Add final glass polish
    top_glass = Image.new("RGBA", bg.size, (255, 255, 255, 40))
    bg = Image.alpha_composite(bg, top_glass)
    
    # Prepare drawing context
    draw = ImageDraw.Draw(bg)
    
    # Text positioning
    text_x = 90 + 500 + 60
    text_max_w = 640
    title_font = choose_title_font(title, text_max_w, max_lines=2)
    meta_font = load_font(META_FONT_PATH, 24)
    time_font = load_font(META_FONT_PATH, 22)
    
    # Draw thumbnail with rounded corners and shadow
    thumb_w, thumb_h = 500, 280
    thumb_x, thumb_y = 90, (720 - thumb_h) // 2
    thumb = base.resize((thumb_w, thumb_h))
    
    # Create shadow
    shadow_pad = 24
    shadow = Image.new("RGBA", (thumb_w + shadow_pad, thumb_h + shadow_pad), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        (shadow_pad // 2, shadow_pad // 2, thumb_w + shadow_pad // 2, thumb_h + shadow_pad // 2),
        radius=34,
        fill=(0, 0, 0, 170)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    bg.paste(shadow, (thumb_x - shadow_pad // 2, thumb_y - shadow_pad // 2), shadow)
    
    # Apply rounded corners to thumbnail
    mask = Image.new("L", (thumb_w, thumb_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, thumb_w, thumb_h), radius=30, fill=255)
    bg.paste(thumb, (thumb_x, thumb_y), mask)
    
    # Draw title
    title_y = thumb_y + 5
    wrapped_title = wrap_text_multilingual(title, title_font, text_max_w, max_lines=2, draw=draw)
    title_heights = []
    for line in wrapped_title:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        hline = bbox[3] - bbox[1]
        draw_text_with_shadow(draw, (text_x, title_y + sum(title_heights)), line, title_font, text_color)
        title_heights.append(hline + 6)
    title_block_height = sum(title_heights)
    
    # Draw metadata (channel + views)
    meta_y = title_y + title_block_height + 5
    meta_text = f"{channel} • {views}"
    draw_text_with_shadow(draw, (text_x, meta_y), meta_text, meta_font, meta_color)
    
    # Draw progress bar with glow effect
    bar_start = text_x
    bar_y = meta_y + 80
    total_len = 550
    prog_fraction = 0.35
    prog_len = int(total_len * prog_fraction)
    
    # Glow effect
    glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.line([(bar_start, bar_y), (bar_start + prog_len, bar_y)], fill=dom_color, width=32)
    glow = glow.filter(ImageFilter.GaussianBlur(20))
    bg = Image.alpha_composite(bg, glow)
    
    # Progress bar
    draw = ImageDraw.Draw(bg)
    draw.line([(bar_start, bar_y), (bar_start + prog_len, bar_y)], fill=dom_color, width=9)
    draw.line([(bar_start + prog_len, bar_y), (bar_start + total_len, bar_y)], fill="#444444", width=7)
    draw.ellipse(
        [(bar_start + prog_len - 10, bar_y - 10), (bar_start + prog_len + 10, bar_y + 10)],
        fill=dom_color
    )
    
    # Draw time indicators
    current_time_text = f"00:{int(prog_fraction * 100):02d}"
    draw_text_with_shadow(draw, (bar_start, bar_y + 18), current_time_text, time_font, meta_color)
    
    end_text = "LIVE" if is_live else duration
    end_fill = "red" if is_live else meta_color
    end_width = draw.textbbox((0, 0), end_text, font=time_font)[2]
    draw_text_with_shadow(draw, (bar_start + total_len - end_width, bar_y + 18), end_text, time_font, end_fill)
    
    # Save thumbnail
    bg.save(cache_path, "PNG")
    
    # Cleanup temporary thumbnail
    try:
        os.remove(thumb_path)
    except OSError:
        pass
    
    return cache_path

import os
import re
import aiofiles
import aiohttp
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from unidecode import unidecode
from youtubesearchpython.__future__ import VideosSearch
from collections import Counter
from VIVAANXMUSIC import app
from config import YOUTUBE_IMG_URL
from VIVAANXMUSIC.core.dir import CACHE_DIR


# Font paths
TITLE_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font2.ttf"
META_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font.ttf"

# Constants
CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
CIRCLE_BIG = 280  # Thumbnail circle
CIRCLE_SMALL = 170  # User DP circle


def changeImageSize(maxWidth, maxHeight, image):
    """Resize image while maintaining aspect ratio."""
    widthRatio = maxWidth / image.size[0]
    heightRatio = maxHeight / image.size[1]
    newWidth = int(widthRatio * image.size[0])
    newHeight = int(heightRatio * image.size[1])
    newImage = image.resize((newWidth, newHeight))
    return newImage


def circle(img):
    """Convert image to circular shape with white border."""
    h, w = img.size
    a = Image.new('L', [h, w], 0)
    b = ImageDraw.Draw(a)
    b.pieslice([(0, 0), (h, w)], 0, 360, fill=255, outline="white")
    c = np.array(img)
    d = np.array(a)
    e = np.dstack((c, d))
    return Image.fromarray(e)


def clear(text):
    """Truncate title to fit within 60 characters."""
    list_words = text.split(" ")
    title = ""
    for i in list_words:
        if len(title) + len(i) < 60:
            title += " " + i
    return title.strip()


def load_font(path, size: int):
    """Load font with fallback to default."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def draw_waveform(draw, x_start, y, width, height, color, segments=80):
    """Draw waveform visualization for progress bar."""
    segment_width = width // segments
    np.random.seed(42)
    
    for i in range(segments):
        wave_height = int(height * 0.4 * (0.5 + 0.5 * np.sin(i * 0.2)))
        bar_x = x_start + i * segment_width
        
        draw.line(
            [(bar_x + segment_width // 2, y - wave_height),
             (bar_x + segment_width // 2, y + wave_height)],
            fill=color,
            width=1
        )


def draw_text_with_outline(draw, position, text, font, fill_color, outline_color, outline_width=2):
    """Draw text with outline effect for better visibility."""
    x, y = position
    
    # Draw outline by drawing text multiple times around the position
    for adj_x in range(-outline_width, outline_width + 1):
        for adj_y in range(-outline_width, outline_width + 1):
            if adj_x != 0 or adj_y != 0:
                draw.text((x + adj_x, y + adj_y), text, font=font, fill=outline_color)
    
    # Draw main text on top
    draw.text((x, y), text, font=font, fill=fill_color)


async def get_thumb(videoid, user_id=None):
    """
    Generate professional music player style thumbnail with:
    - YouTube thumbnail as background (blurred)
    - BIGGER YouTube thumbnail circle (280px) on RIGHT, vertically centered
    - SMALLER User DP circle (170px) overlapping at BOTTOM-RIGHT
    - Song info on LEFT SIDE with bright white text
    - Styled "NOW PLAYING" text at top
    - Waveform progress bar at bottom
    
    Args:
        videoid: YouTube video ID
        user_id: Telegram user ID for profile picture (optional, defaults to bot ID)
    
    Returns:
        Path to generated thumbnail
    """
    if user_id is None:
        user_id = app.id
    
    cache_path = os.path.join(CACHE_DIR, f"{videoid}_{user_id}_elite.png")
    if os.path.isfile(cache_path):
        return cache_path

    url = f"https://www.youtube.com/watch?v={videoid}"
    try:
        # Fetch YouTube video metadata
        results = VideosSearch(url, limit=1)
        for result in (await results.next())["result"]:
            try:
                title = result["title"]
                title = re.sub(r"\W+", " ", title)
                title = title.title()
            except:
                title = "Unsupported Title"
            try:
                duration = result["duration"]
            except:
                duration = "Unknown Mins"
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            try:
                views = result["viewCount"]["short"]
            except:
                views = "Unknown Views"
            try:
                channel = result["channel"]["name"]
            except:
                channel = "Unknown Channel"

        # Download YouTube thumbnail
        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail) as resp:
                if resp.status == 200:
                    f = await aiofiles.open(f"{CACHE_DIR}/thumb{videoid}.png", mode="wb")
                    await f.write(await resp.read())
                    await f.close()

        # Get user profile picture
        try:
            async for photo in app.get_chat_photos(user_id, 1):
                sp = await app.download_media(photo.file_id, file_name=f'{user_id}.jpg')
        except:
            try:
                async for photo in app.get_chat_photos(app.id, 1):
                    sp = await app.download_media(photo.file_id, file_name=f'{app.id}.jpg')
            except:
                sp = None

        # Load images
        if sp:
            user_dp = Image.open(sp)
        else:
            user_dp = Image.new("RGBA", (200, 200), (100, 100, 100, 255))

        youtube_thumb = Image.open(f"{CACHE_DIR}/thumb{videoid}.png")

        # ============================================
        # CREATE BACKGROUND (blurred YouTube thumbnail)
        # ============================================
        image1 = changeImageSize(CANVAS_WIDTH, CANVAS_HEIGHT, youtube_thumb)
        image2 = image1.convert("RGBA")
        background = image2.filter(filter=ImageFilter.BoxBlur(15))
        enhancer = ImageEnhance.Brightness(background)
        background = enhancer.enhance(0.55)

        # Add dark overlay for better text contrast
        overlay = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 80))
        background = Image.alpha_composite(background, overlay)

        # ============================================
        # ADD CIRCULAR IMAGES (RIGHT SIDE - PROFESSIONAL LAYOUT)
        # ============================================
        # YouTube thumbnail circle (280x280) - Positioned on right, vertically centered
        # Right margin: 40px from edge
        # X position: 1280 - 40 - 280 = 960
        # Y position: (720 - 280) / 2 = 220
        thumb_circle_x = CANVAS_WIDTH - 40 - CIRCLE_BIG
        thumb_circle_y = (CANVAS_HEIGHT - CIRCLE_BIG) // 2
        
        y = changeImageSize(CIRCLE_BIG, CIRCLE_BIG, circle(youtube_thumb))
        background.paste(y, (thumb_circle_x, thumb_circle_y), mask=y)

        # User DP circle (170x170) - Overlapping at BOTTOM-RIGHT of thumbnail circle
        # Position: slightly to right and down from thumbnail circle
        # This creates the overlapping effect
        user_circle_x = thumb_circle_x + CIRCLE_BIG - (CIRCLE_SMALL // 2) - 20
        user_circle_y = thumb_circle_y + CIRCLE_BIG - (CIRCLE_SMALL // 2) - 20
        
        a = changeImageSize(CIRCLE_SMALL, CIRCLE_SMALL, circle(user_dp))
        background.paste(a, (user_circle_x, user_circle_y), mask=a)

        # ============================================
        # DRAW TEXT AND UI ELEMENTS
        # ============================================
        draw = ImageDraw.Draw(background)

        # Load fonts
        now_playing_font = load_font(TITLE_FONT_PATH, 56)
        title_font = load_font(TITLE_FONT_PATH, 34)
        meta_font = load_font(META_FONT_PATH, 20)
        time_font = load_font(META_FONT_PATH, 16)

        # --- NOW PLAYING text (top left - styled with effect) ---
        draw_text_with_outline(
            draw,
            (40, 20),
            "NOW PLAYING",
            now_playing_font,
            fill_color=(255, 255, 255),
            outline_color=(0, 0, 0),
            outline_width=1
        )

        # --- Song Title (left side) ---
        draw.text(
            (40, 100),
            clear(title),
            fill=(255, 255, 255),
            font=title_font,
        )

        # --- Metadata (Views, Duration, Channel) - BRIGHT WHITE ---
        meta_y = 165
        meta_line_height = 30
        
        draw.text(
            (40, meta_y),
            f"Views : {views[:23]}",
            fill=(255, 255, 255),
            font=meta_font,
        )
        draw.text(
            (40, meta_y + meta_line_height),
            f"Duration : {duration[:23]}",
            fill=(255, 255, 255),
            font=meta_font,
        )
        draw.text(
            (40, meta_y + (meta_line_height * 2)),
            f"Channel : {channel[:30]}",
            fill=(255, 255, 255),
            font=meta_font,
        )

        # ============================================
        # PROGRESS BAR WITH WAVEFORM (AT BOTTOM)
        # ============================================
        bar_y = 540
        bar_x_start = 40
        bar_x_end = thumb_circle_x - 30  # Stop before circles
        bar_width = bar_x_end - bar_x_start
        bar_height = 30

        # Draw waveform visualization
        draw_waveform(draw, bar_x_start, bar_y, bar_width, bar_height, (100, 150, 200), segments=80)

        # Progress line (white line showing current progress at ~35%)
        prog_x = bar_x_start + int(bar_width * 0.35)
        draw.line(
            [(bar_x_start, bar_y), (prog_x, bar_y)],
            fill="white",
            width=3,
        )
        # Progress indicator circle
        draw.ellipse(
            [(prog_x - 7, bar_y - 7), (prog_x + 7, bar_y + 7)],
            fill="white",
        )

        # ============================================
        # TIME INDICATORS (BELOW PROGRESS BAR)
        # ============================================
        time_y = bar_y + 40
        
        # Current time (left)
        draw.text(
            (40, time_y),
            "00:00",
            fill=(255, 255, 255),
            font=time_font,
        )
        
        # Total duration (right)
        draw.text(
            (bar_x_end - 80, time_y),
            f"{duration[:23]}",
            fill=(255, 255, 255),
            font=time_font,
        )

        # ============================================
        # BOT NAME AT TOP RIGHT
        # ============================================
        try:
            brand_name = unidecode(app.name)
        except:
            brand_name = "Elite Musics"

        brand_font = load_font(TITLE_FONT_PATH, 20)
        draw.text((CANVAS_WIDTH - 200, 20), brand_name, fill="white", font=brand_font)

        # ============================================
        # CLEANUP AND SAVE
        # ============================================
        try:
            os.remove(f"{CACHE_DIR}/thumb{videoid}.png")
        except:
            pass

        # Save final thumbnail
        background.save(cache_path)
        return cache_path

    except Exception as e:
        return YOUTUBE_IMG_URL

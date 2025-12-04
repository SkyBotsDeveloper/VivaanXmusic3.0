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

# Constants - Professional Layout
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
    """Draw waveform visualization for progress bar - with varied heights like music player."""
    segment_width = width // segments
    np.random.seed(42)
    
    for i in range(segments):
        # Create more dynamic wave pattern
        wave_height = int(height * 0.5 * (0.3 + 0.7 * np.sin(i * 0.15 + np.random.random())))
        bar_x = x_start + i * segment_width
        bar_width = max(1, segment_width - 1)
        
        # Draw filled rectangle for each segment (more professional look)
        draw.rectangle(
            [(bar_x + 1, y - wave_height),
             (bar_x + bar_width, y + wave_height)],
            fill=color,
            outline=None
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


def draw_progress_bar_professional(draw, x_start, y, width, height, current_progress=0.35):
    """Draw professional progress bar with background, filled, and indicator."""
    # Background bar
    draw.rectangle(
        [(x_start, y - 2), (x_start + width, y + 2)],
        fill=(80, 80, 80),
        outline=None
    )
    
    # Filled progress
    prog_x = x_start + int(width * current_progress)
    draw.rectangle(
        [(x_start, y - 2), (prog_x, y + 2)],
        fill=(200, 200, 200),
        outline=None
    )
    
    # Progress circle indicator
    draw.ellipse(
        [(prog_x - 6, y - 6), (prog_x + 6, y + 6)],
        fill=(255, 255, 255),
        outline=(200, 200, 200)
    )


async def get_thumb(videoid, user_id=None):
    """
    Generate professional music player style thumbnail with:
    - YouTube thumbnail as background (blurred)
    - BIGGER YouTube thumbnail circle (280px) on RIGHT, vertically centered
    - SMALLER User DP circle (170px) overlapping at BOTTOM-RIGHT (FULLY VISIBLE)
    - Song info on LEFT SIDE with bright white text (MUCH BIGGER)
    - Styled "NOW PLAYING" text at top (BIGGER)
    - Professional music player UI at bottom with waveform, progress bar, time, volume
    
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
        # ADD CIRCULAR IMAGES (RIGHT SIDE - PERFECT POSITIONING)
        # ============================================
        # YouTube thumbnail circle (280x280) - Positioned on right, vertically centered
        thumb_circle_x = CANVAS_WIDTH - 35 - CIRCLE_BIG
        thumb_circle_y = 180
        
        y = changeImageSize(CIRCLE_BIG, CIRCLE_BIG, circle(youtube_thumb))
        background.paste(y, (thumb_circle_x, thumb_circle_y), mask=y)

        # User DP circle (170x170) - Overlapping at BOTTOM-RIGHT of thumbnail circle
        user_circle_x = thumb_circle_x + CIRCLE_BIG - (CIRCLE_SMALL // 2) - 15
        user_circle_y = thumb_circle_y + CIRCLE_BIG - (CIRCLE_SMALL // 2) - 10
        
        # Ensure user DP doesn't get cut off at canvas edges
        if user_circle_x + CIRCLE_SMALL > CANVAS_WIDTH:
            user_circle_x = CANVAS_WIDTH - CIRCLE_SMALL - 10
        if user_circle_y + CIRCLE_SMALL > CANVAS_HEIGHT:
            user_circle_y = CANVAS_HEIGHT - CIRCLE_SMALL - 10
        
        a = changeImageSize(CIRCLE_SMALL, CIRCLE_SMALL, circle(user_dp))
        background.paste(a, (user_circle_x, user_circle_y), mask=a)

        # ============================================
        # DRAW TEXT AND UI ELEMENTS
        # ============================================
        draw = ImageDraw.Draw(background)

        # Load fonts - ALL BIGGER
        now_playing_font = load_font(TITLE_FONT_PATH, 62)
        title_font = load_font(TITLE_FONT_PATH, 36)
        meta_font = load_font(META_FONT_PATH, 25)
        time_font = load_font(META_FONT_PATH, 16)
        small_time_font = load_font(META_FONT_PATH, 14)

        # --- NOW PLAYING text (top left - styled with effect, BIGGER & SHIFTED DOWN) ---
        draw_text_with_outline(
            draw,
            (40, 25),
            "NOW PLAYING",
            now_playing_font,
            fill_color=(255, 255, 255),
            outline_color=(0, 0, 0),
            outline_width=1
        )

        # --- Song Title (left side) - BIGGER & SHIFTED DOWN ---
        draw.text(
            (40, 105),
            clear(title),
            fill=(255, 255, 255),
            font=title_font,
        )

        # --- Metadata (Views, Duration, Channel) - BRIGHT WHITE, MUCH BIGGER & SHIFTED DOWN ---
        meta_y = 170
        meta_line_height = 35
        
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
        # PROFESSIONAL PLAYER UI AT BOTTOM
        # ============================================
        # Semi-transparent dark background for player controls area
        player_bg = Image.new("RGBA", (CANVAS_WIDTH, 100), (40, 40, 40, 180))
        background.paste(player_bg, (0, 620), player_bg)

        # --- WAVEFORM VISUALIZATION (TOP OF PLAYER AREA) ---
        wave_y = 550
        wave_x_start = 40
        wave_x_end = thumb_circle_x - 30
        wave_width = wave_x_end - wave_x_start
        wave_height = 40

        draw_waveform(draw, wave_x_start, wave_y, wave_width, wave_height, (100, 150, 200), segments=100)

        # --- TIME INDICATOR ABOVE WAVEFORM ---
        time_above_y = 520
        # Current time on left
        draw.text(
            (40, time_above_y),
            "00:55",
            fill=(255, 255, 255),
            font=small_time_font,
        )
        # Total duration on right
        draw.text(
            (wave_x_end - 60, time_above_y),
            f"{duration[:23]}",
            fill=(255, 255, 255),
            font=small_time_font,
        )

        # --- PROGRESS BAR ---
        bar_y = 605
        draw_progress_bar_professional(draw, wave_x_start, bar_y, wave_width, 4, current_progress=0.35)

        # --- VOLUME INDICATOR (AT BOTTOM) ---
        volume_y = 655
        volume_label_x = 40
        volume_bar_x = 120
        volume_bar_width = 80
        
        # Volume label
        draw.text(
            (volume_label_x, volume_y),
            "Volume:",
            fill=(220, 220, 220),
            font=small_time_font,
        )
        
        # Volume bar (5 filled, 3 empty = 62.5%)
        for i in range(8):
            bar_x = volume_bar_x + (i * 12)
            if i < 5:
                color = (100, 150, 200)  # Filled
            else:
                color = (60, 60, 60)  # Empty
            
            draw.rectangle(
                [(bar_x, volume_y + 2), (bar_x + 8, volume_y + 12)],
                fill=color,
                outline=(100, 100, 100)
            )

        # ============================================
        # BOT NAME AT TOP RIGHT
        # ============================================
        try:
            brand_name = unidecode(app.name)
        except:
            brand_name = "Elite Musics"

        brand_font = load_font(TITLE_FONT_PATH, 22)
        draw.text((CANVAS_WIDTH - 220, 25), brand_name, fill="white", font=brand_font)

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

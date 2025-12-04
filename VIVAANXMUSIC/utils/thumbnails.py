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
    np.random.seed(42)  # For consistent visualization
    
    for i in range(segments):
        # Create wave pattern
        wave_height = int(height * 0.4 * (0.5 + 0.5 * np.sin(i * 0.2)))
        bar_x = x_start + i * segment_width
        
        # Draw vertical bar
        draw.line(
            [(bar_x + segment_width // 2, y - wave_height),
             (bar_x + segment_width // 2, y + wave_height)],
            fill=color,
            width=1
        )


async def get_thumb(videoid, user_id=None):
    """
    Generate music player style thumbnail with:
    - YouTube thumbnail as background (blurred)
    - BIGGER YouTube thumbnail circle on left side (280px)
    - SMALLER User DP circle overlapping at corner (170px)
    - Song info on left side with bright white text
    - NOW PLAYING text at top
    - Waveform progress bar
    
    Args:
        videoid: YouTube video ID
        user_id: Telegram user ID for profile picture (optional, defaults to bot ID)
    
    Returns:
        Path to generated thumbnail
    """
    # Default to bot's ID if user_id not provided
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
            # Fallback to bot's profile picture
            try:
                async for photo in app.get_chat_photos(app.id, 1):
                    sp = await app.download_media(photo.file_id, file_name=f'{app.id}.jpg')
            except:
                sp = None

        # Load images
        if sp:
            user_dp = Image.open(sp)
        else:
            # Create placeholder if no profile picture available
            user_dp = Image.new("RGBA", (200, 200), (100, 100, 100, 255))

        youtube_thumb = Image.open(f"{CACHE_DIR}/thumb{videoid}.png")

        # ============================================
        # CREATE BACKGROUND (blurred YouTube thumbnail)
        # ============================================
        image1 = changeImageSize(1280, 720, youtube_thumb)
        image2 = image1.convert("RGBA")
        background = image2.filter(filter=ImageFilter.BoxBlur(15))
        enhancer = ImageEnhance.Brightness(background)
        background = enhancer.enhance(0.55)  # Darken slightly for text readability

        # Add dark overlay for better text contrast
        overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 80))
        background = Image.alpha_composite(background, overlay)

        # ============================================
        # ADD CIRCULAR IMAGES
        # ============================================
        # YouTube thumbnail (left side circle) - BIGGER 280x280
        y = changeImageSize(280, 280, circle(youtube_thumb))
        background.paste(y, (50, 200), mask=y)

        # User DP (right side circle overlapping) - SMALLER 170x170
        # Position so it overlaps at the corner of thumbnail circle
        # Thumbnail circle center is at (50+140, 200+140) = (190, 340)
        # User circle should overlap at bottom-right, so center at ~(280, 350)
        a = changeImageSize(170, 170, circle(user_dp))
        background.paste(a, (230, 300), mask=a)

        # ============================================
        # DRAW TEXT AND UI ELEMENTS
        # ============================================
        draw = ImageDraw.Draw(background)

        # Load fonts
        now_playing_font = load_font(TITLE_FONT_PATH, 44)
        title_font = load_font(TITLE_FONT_PATH, 28)
        meta_font = load_font(META_FONT_PATH, 20)
        time_font = load_font(META_FONT_PATH, 18)

        # --- NOW PLAYING text (top left with keyboard style) ---
        draw.text((40, 20), "NOW PLAYING", fill="white", font=now_playing_font)

        # --- Song Title (left side) ---
        draw.text(
            (40, 140),
            clear(title),
            fill="white",
            font=title_font,
        )

        # --- Metadata (Views, Duration, Channel) - BRIGHT WHITE ---
        meta_y = 200
        draw.text(
            (40, meta_y),
            f"Views : {views[:23]}",
            fill=(255, 255, 255),  # Pure white instead of (200, 200, 200)
            font=meta_font,
        )
        draw.text(
            (40, meta_y + 35),
            f"Duration : {duration[:23]}",
            fill=(255, 255, 255),  # Pure white instead of (200, 200, 200)
            font=meta_font,
        )
        draw.text(
            (40, meta_y + 70),
            f"Channel : {channel[:30]}",
            fill=(255, 255, 255),  # Pure white instead of (200, 200, 200)
            font=meta_font,
        )

        # ============================================
        # PROGRESS BAR WITH WAVEFORM
        # ============================================
        bar_y = 500
        bar_x_start = 40
        bar_width = 1200
        bar_height = 30

        # Draw waveform visualization
        draw_waveform(draw, bar_x_start, bar_y, bar_width, bar_height, (100, 150, 200), segments=80)

        # Progress line (white line showing current progress)
        prog_x = bar_x_start + int(bar_width * 0.35)
        draw.line(
            [(bar_x_start, bar_y), (prog_x, bar_y)],
            fill="white",
            width=3,
        )
        draw.ellipse(
            [(prog_x - 7, bar_y - 7), (prog_x + 7, bar_y + 7)],
            fill="white",
        )

        # ============================================
        # TIME INDICATORS
        # ============================================
        draw.text(
            (40, bar_y + 35),
            "00:00",
            fill=(255, 255, 255),  # Pure white
            font=time_font,
        )
        draw.text(
            (bar_x_start + bar_width - 80, bar_y + 35),
            f"{duration[:23]}",
            fill=(255, 255, 255),  # Pure white
            font=time_font,
        )

        # ============================================
        # BOT NAME AT TOP RIGHT
        # ============================================
        try:
            brand_name = unidecode(app.name)
        except:
            brand_name = "Elite Musics"

        brand_font = load_font(TITLE_FONT_PATH, 22)
        draw.text((1000, 20), brand_name, fill="white", font=brand_font)

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

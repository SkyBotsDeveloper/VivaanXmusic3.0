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


def get_dominant_color(img: Image.Image):
    """Extract dominant color from image for accent."""
    small = img.resize((50, 50))
    pixels = [p for p in small.getdata() if (len(p) == 3) or (len(p) == 4 and p[3] > 128)]
    if not pixels:
        return (255, 100, 0)
    r, g, b = Counter(pixels).most_common(1)[0][0][:3]
    return (r, g, b)


def load_font(path, size: int):
    """Load font with fallback to default."""
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


async def get_thumb(videoid, user_id):
    """
    Generate Elite Musics thumbnail with YouTube video + User DP.
    
    Args:
        videoid: YouTube video ID
        user_id: Telegram user ID for profile picture
    
    Returns:
        Path to generated thumbnail
    """
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
            async for photo in app.get_chat_photos(app.id, 1):
                sp = await app.download_media(photo.file_id, file_name=f'{app.id}.jpg')

        # Load images
        user_dp = Image.open(sp)
        youtube_thumb = Image.open(f"{CACHE_DIR}/thumb{videoid}.png")

        # Prepare base image with YouTube thumbnail
        image1 = changeImageSize(1280, 720, youtube_thumb)
        image2 = image1.convert("RGBA")
        background = image2.filter(filter=ImageFilter.BoxBlur(10))
        enhancer = ImageEnhance.Brightness(background)
        background = enhancer.enhance(0.5)

        # Extract dominant color for accents
        dom_color = get_dominant_color(image1)

        # Add circular thumbnails
        # YouTube thumbnail (left side)
        y = changeImageSize(200, 200, circle(youtube_thumb))
        background.paste(y, (45, 225), mask=y)

        # User DP (right side)
        a = changeImageSize(200, 200, circle(user_dp))
        background.paste(a, (1045, 225), mask=a)

        # Draw text and UI elements
        draw = ImageDraw.Draw(background)
        
        # Load fonts using constants
        title_font = load_font(TITLE_FONT_PATH, 30)
        meta_font = load_font(META_FONT_PATH, 30)
        brand_font = load_font(TITLE_FONT_PATH, 28)
        status_font = load_font(META_FONT_PATH, 14)

        # Brand name at top right
        draw.text((1110, 8), "Elite Musics", fill="white", font=brand_font)

        # Channel and views
        draw.text(
            (55, 560),
            f"{channel} | {views[:23]}",
            (255, 255, 255),
            font=title_font,
        )

        # Song title
        draw.text(
            (57, 600),
            clear(title),
            (255, 255, 255),
            font=meta_font,
        )

        # Progress bar (white line)
        draw.line(
            [(55, 660), (1220, 660)],
            fill="white",
            width=5,
            joint="curve",
        )

        # Progress indicator (circle on progress bar)
        draw.ellipse(
            [(918, 648), (942, 672)],
            outline="white",
            fill="white",
            width=15,
        )

        # Time indicators
        draw.text(
            (36, 685),
            "00:00",
            (255, 255, 255),
            font=title_font,
        )

        draw.text(
            (1185, 685),
            f"{duration[:23]}",
            (255, 255, 255),
            font=title_font,
        )

        # Cleanup temporary thumbnail
        try:
            os.remove(f"{CACHE_DIR}/thumb{videoid}.png")
        except:
            pass

        # Save final thumbnail
        background.save(cache_path)
        return cache_path

    except Exception as e:
        return YOUTUBE_IMG_URL

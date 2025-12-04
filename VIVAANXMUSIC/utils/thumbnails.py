import os
import re
import aiofiles
import aiohttp
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from unidecode import unidecode
from youtubesearchpython.__future__ import VideosSearch
from VIVAANXMUSIC import app
from config import YOUTUBE_IMG_URL
from VIVAANXMUSIC.core.dir import CACHE_DIR


# Font paths
TITLE_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font2.ttf"
META_FONT_PATH = "VIVAANXMUSIC/assets/thumb/font.ttf"

# Constants - Professional Layout
CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
CIRCLE_BIG = 280
CIRCLE_SMALL = 170


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
    except:
        return ImageFont.load_default()


def draw_waveform(draw, x_start, y, width, height, color, segments=80):
    """Draw waveform visualization for progress bar."""
    segment_width = width // segments
    np.random.seed(42)
    
    for i in range(segments):
        wave_height = int(height * 0.5 * (0.3 + 0.7 * np.sin(i * 0.15 + np.random.random())))
        bar_x = x_start + i * segment_width
        bar_width = max(1, segment_width - 1)
        
        draw.rectangle(
            [(bar_x + 1, y - wave_height), (bar_x + bar_width, y + wave_height)],
            fill=color,
            outline=None
        )


def draw_text_with_outline(draw, position, text, font, fill_color, outline_color, outline_width=2):
    """Draw text with outline effect."""
    x, y = position
    
    for adj_x in range(-outline_width, outline_width + 1):
        for adj_y in range(-outline_width, outline_width + 1):
            if adj_x != 0 or adj_y != 0:
                draw.text((x + adj_x, y + adj_y), text, font=font, fill=outline_color)
    
    draw.text((x, y), text, font=font, fill=fill_color)


def draw_progress_bar_professional(draw, x_start, y, width, height, current_progress=0.35):
    """Draw professional progress bar."""
    draw.rectangle([(x_start, y - 2), (x_start + width, y + 2)], fill=(80, 80, 80), outline=None)
    
    prog_x = x_start + int(width * current_progress)
    draw.rectangle([(x_start, y - 2), (prog_x, y + 2)], fill=(200, 200, 200), outline=None)
    
    draw.ellipse([(prog_x - 6, y - 6), (prog_x + 6, y + 6)], fill=(255, 255, 255), outline=(200, 200, 200))


def draw_play_button(draw, x, y, size, color):
    """Draw play button (triangle)."""
    points = [(x - size//2, y - size//2), (x - size//2, y + size//2), (x + size//2, y)]
    draw.polygon(points, fill=color)


def draw_shuffle_button(draw, x, y, size, color):
    """Draw shuffle button (×)."""
    offset = size // 3
    draw.line([(x - offset, y - offset), (x + offset, y + offset)], fill=color, width=3)
    draw.line([(x - offset, y + offset), (x + offset, y - offset)], fill=color, width=3)


def draw_previous_button(draw, x, y, size, color):
    """Draw previous button (⏮)."""
    draw.rectangle([(x - size//2, y - size//2), (x - size//2 + 3, y + size//2)], fill=color)
    draw.polygon([(x - size//2 + 5, y - size//2), (x + size//2, y), (x - size//2 + 5, y + size//2)], fill=color)


def draw_next_button(draw, x, y, size, color):
    """Draw next button (⏭)."""
    draw.polygon([(x - size//2, y - size//2), (x - size//2, y + size//2), (x + size//2 - 5, y)], fill=color)
    draw.rectangle([(x + size//2 - 3, y - size//2), (x + size//2, y + size//2)], fill=color)


def draw_repeat_button(draw, x, y, size, color):
    """Draw repeat button (↻)."""
    arc_radius = size // 2
    draw.arc([(x - arc_radius, y - arc_radius), (x + arc_radius, y + arc_radius)], 45, 315, fill=color, width=3)
    draw.polygon([(x + arc_radius - 2, y - arc_radius + 3), (x + arc_radius + 2, y - arc_radius - 2), (x + arc_radius + 2, y - arc_radius + 5)], fill=color)


async def get_thumb(videoid, user_id=None):
    """Generate professional music player thumbnail."""
    try:
        if user_id is None:
            user_id = app.id
        
        cache_path = os.path.join(CACHE_DIR, f"{videoid}_{user_id}_elite.png")
        if os.path.isfile(cache_path):
            return cache_path

        url = f"https://www.youtube.com/watch?v={videoid}"
        
        # Fetch YouTube video metadata
        results = VideosSearch(url, limit=1)
        result_data = await results.next()
        
        if not result_data or not result_data.get("result"):
            return YOUTUBE_IMG_URL
        
        result = result_data["result"][0]
        
        try:
            title = result.get("title", "Unsupported Title")
            title = re.sub(r"\W+", " ", title)
            title = title.title()
        except:
            title = "Unsupported Title"
        
        try:
            duration = result.get("duration", "Unknown Mins")
        except:
            duration = "Unknown Mins"
        
        try:
            thumbnail = result.get("thumbnails", [{}])[0].get("url", YOUTUBE_IMG_URL).split("?")[0]
        except:
            return YOUTUBE_IMG_URL
        
        try:
            views = result.get("viewCount", {}).get("short", "Unknown Views")
        except:
            views = "Unknown Views"
        
        try:
            channel = result.get("channel", {}).get("name", "Unknown Channel")
        except:
            channel = "Unknown Channel"

        # Download YouTube thumbnail
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(thumbnail, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        thumb_data = await resp.read()
                        thumb_path = f"{CACHE_DIR}/thumb{videoid}.png"
                        async with aiofiles.open(thumb_path, mode="wb") as f:
                            await f.write(thumb_data)
                    else:
                        return YOUTUBE_IMG_URL
        except Exception as e:
            return YOUTUBE_IMG_URL

        # Get user profile picture
        try:
            sp = None
            async for photo in app.get_chat_photos(user_id, 1):
                sp = await app.download_media(photo.file_id, file_name=f'{user_id}.jpg')
                break
        except:
            sp = None
        
        if sp is None:
            try:
                async for photo in app.get_chat_photos(app.id, 1):
                    sp = await app.download_media(photo.file_id, file_name=f'{app.id}.jpg')
                    break
            except:
                sp = None

        # Load images
        try:
            if sp and os.path.isfile(sp):
                user_dp = Image.open(sp)
            else:
                user_dp = Image.new("RGBA", (200, 200), (100, 100, 100, 255))
        except:
            user_dp = Image.new("RGBA", (200, 200), (100, 100, 100, 255))

        try:
            thumb_path = f"{CACHE_DIR}/thumb{videoid}.png"
            if not os.path.isfile(thumb_path):
                return YOUTUBE_IMG_URL
            youtube_thumb = Image.open(thumb_path)
        except:
            return YOUTUBE_IMG_URL

        # CREATE BACKGROUND
        image1 = changeImageSize(CANVAS_WIDTH, CANVAS_HEIGHT, youtube_thumb)
        image2 = image1.convert("RGBA")
        background = image2.filter(filter=ImageFilter.BoxBlur(15))
        enhancer = ImageEnhance.Brightness(background)
        background = enhancer.enhance(0.55)

        overlay = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 80))
        background = Image.alpha_composite(background, overlay)

        # ADD CIRCULAR IMAGES
        thumb_circle_x = CANVAS_WIDTH - 35 - CIRCLE_BIG
        thumb_circle_y = 180
        
        y = changeImageSize(CIRCLE_BIG, CIRCLE_BIG, circle(youtube_thumb))
        background.paste(y, (thumb_circle_x, thumb_circle_y), mask=y)

        user_circle_x = thumb_circle_x + CIRCLE_BIG - (CIRCLE_SMALL // 2) - 15
        user_circle_y = thumb_circle_y + CIRCLE_BIG - (CIRCLE_SMALL // 2) - 10
        
        if user_circle_x + CIRCLE_SMALL > CANVAS_WIDTH:
            user_circle_x = CANVAS_WIDTH - CIRCLE_SMALL - 10
        if user_circle_y + CIRCLE_SMALL > CANVAS_HEIGHT:
            user_circle_y = CANVAS_HEIGHT - CIRCLE_SMALL - 10
        
        a = changeImageSize(CIRCLE_SMALL, CIRCLE_SMALL, circle(user_dp))
        background.paste(a, (user_circle_x, user_circle_y), mask=a)

        # DRAW TEXT AND UI
        draw = ImageDraw.Draw(background)

        now_playing_font = load_font(TITLE_FONT_PATH, 62)
        title_font = load_font(TITLE_FONT_PATH, 36)
        meta_font = load_font(META_FONT_PATH, 25)
        small_time_font = load_font(META_FONT_PATH, 14)

        # NOW PLAYING
        draw_text_with_outline(draw, (40, 25), "NOW PLAYING", now_playing_font, (255, 255, 255), (0, 0, 0), 1)

        # Song Title
        draw.text((40, 105), clear(title), fill=(255, 255, 255), font=title_font)

        # Metadata
        meta_y = 170
        meta_line_height = 35
        draw.text((40, meta_y), f"Views : {views[:23]}", fill=(255, 255, 255), font=meta_font)
        draw.text((40, meta_y + meta_line_height), f"Duration : {duration[:23]}", fill=(255, 255, 255), font=meta_font)
        draw.text((40, meta_y + (meta_line_height * 2)), f"Channel : {channel[:30]}", fill=(255, 255, 255), font=meta_font)

        # PLAYER UI
        player_bg = Image.new("RGBA", (CANVAS_WIDTH, 100), (40, 40, 40, 180))
        background.paste(player_bg, (0, 620), player_bg)

        # Waveform
        wave_y = 550
        wave_x_start = 40
        wave_x_end = thumb_circle_x - 30
        wave_width = wave_x_end - wave_x_start
        wave_height = 40

        draw_waveform(draw, wave_x_start, wave_y, wave_width, wave_height, (100, 150, 200), segments=100)

        # Time
        time_above_y = 520
        draw.text((40, time_above_y), "00:55", fill=(255, 255, 255), font=small_time_font)
        draw.text((wave_x_end - 60, time_above_y), f"{duration[:23]}", fill=(255, 255, 255), font=small_time_font)

        # Progress bar
        bar_y = 605
        draw_progress_bar_professional(draw, wave_x_start, bar_y, wave_width, 4, current_progress=0.35)

        # Control buttons
        button_y = 665
        button_color = (220, 220, 220)
        button_size = 20
        control_area_width = wave_width
        button_spacing = control_area_width // 6
        
        shuffle_x = wave_x_start + button_spacing
        draw_shuffle_button(draw, shuffle_x, button_y, button_size, button_color)
        
        prev_x = wave_x_start + (button_spacing * 2)
        draw_previous_button(draw, prev_x, button_y, button_size, button_color)
        
        play_x = wave_x_start + (button_spacing * 3)
        play_button_size = button_size + 8
        draw_play_button(draw, play_x, button_y, play_button_size, (100, 150, 200))
        
        next_x = wave_x_start + (button_spacing * 4)
        draw_next_button(draw, next_x, button_y, button_size, button_color)
        
        repeat_x = wave_x_start + (button_spacing * 5)
        draw_repeat_button(draw, repeat_x, button_y, button_size, button_color)

        # Bot name
        try:
            brand_name = unidecode(app.name)
        except:
            brand_name = "Elite Musics"

        brand_font = load_font(TITLE_FONT_PATH, 22)
        draw.text((CANVAS_WIDTH - 220, 25), brand_name, fill="white", font=brand_font)

        # Save
        background.save(cache_path)
        
        # Cleanup
        try:
            os.remove(f"{CACHE_DIR}/thumb{videoid}.png")
        except:
            pass

        return cache_path

    except Exception as e:
        print(f"Error generating thumbnail: {str(e)}")
        return YOUTUBE_IMG_URL

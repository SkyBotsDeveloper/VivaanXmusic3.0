"""Local, animation-preserving rendering for /mmf only."""

import gzip
import json
import math
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from VIVAANXMUSIC.security import build_subprocess_env


MAX_VIDEO_BYTES = 256 * 1024
MAX_DURATION = 3.0
FONT = Path(__file__).resolve().parents[1] / "assets" / "default.ttf"


class MemeError(ValueError):
    """A concise explanation suitable for the command's status message."""


def media_kind(message):
    if message is None:
        return None
    sticker = getattr(message, "sticker", None)
    if sticker:
        if getattr(sticker, "is_animated", False):
            return "tgs"
        if getattr(sticker, "is_video", False):
            return "video"
        mime = getattr(sticker, "mime_type", "") or ""
        suffix = Path(getattr(sticker, "file_name", "") or "").suffix.lower()
        if mime == "application/x-tgsticker" or suffix == ".tgs":
            return "tgs"
        if mime == "video/webm" or suffix == ".webm":
            return "video"
        return "static"
    if getattr(message, "photo", None):
        return "static"
    document = getattr(message, "document", None)
    if document:
        mime = getattr(document, "mime_type", "") or ""
        suffix = Path(getattr(document, "file_name", "") or "").suffix.lower()
        images = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
        if mime.startswith("image/") or (mime in ("", "application/octet-stream") and suffix in images):
            return "static"
    return None


def _font(size):
    if os.name == "nt":
        try:
            return ImageFont.truetype("arial.ttf", size)
        except OSError:
            pass
    return ImageFont.truetype(str(FONT), size)


def _wrap(text, draw, font, width, stroke):
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            box = draw.textbbox((0, 0), candidate, font=font, stroke_width=stroke)
            if box[2] - box[0] <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            for char in word:
                box = draw.textbbox((0, 0), line + char, font=font, stroke_width=stroke)
                if box[2] - box[0] > width and line:
                    lines.append(line)
                    line = char
                else:
                    line += char
        if line:
            lines.append(line)
    return lines


def text_overlay(size, text):
    """Fit centered white/stroked top and bottom text inside actual frame bounds."""
    width, height = size
    upper, _, lower = text.partition(";")
    upper, lower = upper.strip(), lower.strip()
    if not upper and not lower:
        raise MemeError("Give me text after /mmf to memify.")
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin = max(1, round(min(size) * 0.025))
    usable_width = width - 2 * margin
    available_height = height - 2 * margin
    if upper and lower:
        available_height = (height - 3 * margin) // 2
    initial = max(1, min(round(width * 70 / 640), round(height * 0.18)))

    def layout(font_size):
        font = _font(font_size)
        stroke = max(1, round(font_size / 22))
        gap = max(1, round(font_size * 0.1))
        groups = []
        for value in (upper, lower):
            lines = _wrap(value, draw, font, usable_width, stroke)
            boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
            total = sum(box[3] - box[1] for box in boxes) + gap * max(0, len(lines) - 1)
            if total > available_height or any(box[2] - box[0] > usable_width for box in boxes):
                return None
            groups.append((lines, boxes, total))
        return font, stroke, gap, groups

    chosen = None
    low, high = 1, initial
    while low <= high:
        middle = (low + high) // 2
        fitted = layout(middle)
        if fitted is None:
            high = middle - 1
        else:
            chosen = fitted
            low = middle + 1
    if chosen is None:
        overlay.close()
        raise MemeError("Text is too long to fit this image. Please use shorter text.")
    font, stroke, gap, groups = chosen
    for index, (lines, boxes, total) in enumerate(groups):
        y = margin if index == 0 else height - margin - total
        for line, box in zip(lines, boxes):
            x = (width - (box[2] - box[0])) / 2 - box[0]
            draw.text((x, y - box[1]), line, font=font, fill="white", stroke_width=stroke, stroke_fill="black")
            y += box[3] - box[1] + gap
    return overlay


def _run(command):
    try:
        return subprocess.run(command, capture_output=True, check=True, timeout=120,
                              env=build_subprocess_env())
    except FileNotFoundError as exc:
        raise MemeError("FFmpeg and ffprobe are required to process animated stickers.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"Media subprocess failed: {detail}") from exc


def probe_video(path):
    result = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    data = json.loads(result.stdout)
    stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    duration = float(stream.get("duration") or data["format"].get("duration") or 0)
    rate = Fraction(stream.get("avg_frame_rate") or "0/1")
    if rate <= 0:
        rate = Fraction(stream["r_frame_rate"])
    if stream["codec_name"] != "vp9" or rate <= 0 or not math.isfinite(duration) or duration <= 0:
        raise MemeError("Failed to decode the video sticker.")
    if duration > MAX_DURATION + 0.05:
        raise MemeError("Video stickers must be at most 3 seconds long.")
    return (int(stream["width"]), int(stream["height"])), min(rate, Fraction(30)), min(duration, MAX_DURATION)


def _sticker_geometry(size):
    width, height = size
    if width <= 0 or height <= 0:
        raise MemeError("Invalid sticker dimensions.")
    ratio = min(1, 512 / max(size))
    resized = max(1, round(width * ratio)), max(1, round(height * ratio))
    # Telegram requires one side to be 512. Pad small inputs rather than upscale.
    canvas = (512, resized[1]) if width >= height else (resized[0], 512)
    offset = (canvas[0] - resized[0]) // 2, (canvas[1] - resized[1]) // 2
    return resized, canvas, offset


def _render_tgs(source, work_dir):
    from rlottie_python import LottieAnimation

    with gzip.open(source, "rt", encoding="utf-8") as stream:
        animation_data = stream.read()
    data = json.loads(animation_data)
    source_rate = Fraction(str(data["fr"]))
    if source_rate <= 0:
        raise MemeError("Failed to decode the animated sticker.")
    duration = float(Fraction(str(data["op"])) - Fraction(str(data.get("ip", 0)))) / float(source_rate)
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
        raise MemeError("Animated stickers must be at most 3 seconds long.")
    rate = min(source_rate, Fraction(30))
    resized, canvas, offset = _sticker_geometry((int(data["w"]), int(data["h"])))
    frames = work_dir / "frames"
    frames.mkdir()
    with LottieAnimation.from_data(animation_data) as animation:
        total = animation.lottie_animation_get_totalframe()
        if total < 1:
            raise MemeError("Failed to decode the animated sticker.")
        for index in range(math.ceil(duration * float(rate))):
            frame_num = min(total - 1, int(index * source_rate / rate))
            with animation.render_pillow_frame(frame_num=frame_num, width=resized[0], height=resized[1]) as frame:
                frame.save(frames / f"frame_{index:04d}.png")
    return frames / "frame_%04d.png", resized, canvas, offset, rate, duration


def _encode_video(source_args, overlay, output, resized, canvas, offset, rate, duration):
    rw, rh = resized
    cw, ch = canvas
    x, y = offset
    filters = (f"[0:v]fps={rate},scale={rw}:{rh}:flags=lanczos,format=rgba,"
               f"pad={cw}:{ch}:{x}:{y}:color=black@0[base];"
               f"[base][1:v]overlay={x}:{y}:shortest=1:format=auto,format=yuva420p[v]")
    for quality in (32, 42, 52, 63):
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
              "-filter_complex_threads", "1", *source_args,
              "-loop", "1", "-framerate", str(rate), "-i", str(overlay),
              "-filter_complex", filters, "-map", "[v]", "-an",
              "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
              "-b:v", "0", "-crf", str(quality), "-deadline", "good", "-cpu-used", "4",
              "-threads", "2", "-t", str(duration), "-fps_mode", "passthrough", str(output)])
        if output.stat().st_size <= MAX_VIDEO_BYTES:
            return output
    raise MemeError("Processed sticker exceeds Telegram's 256 KB limit. Please use less text.")


def memify_media(source, text, kind, work_dir):
    """The caller owns the unique directory and keeps it alive through upload."""
    source, work_dir = Path(source), Path(work_dir)
    if kind == "static":
        output = work_dir / "memify.webp"
        with Image.open(source) as original:
            frame = ImageOps.exif_transpose(original).convert("RGBA")
        with frame, text_overlay(frame.size, text) as overlay:
            with Image.alpha_composite(frame, overlay) as meme:
                meme.save(output, "WEBP", quality=95)
        return output
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MemeError("FFmpeg and ffprobe are required to process animated stickers.")
    if kind == "tgs":
        source, resized, canvas, offset, rate, duration = _render_tgs(source, work_dir)
        source_args = ["-framerate", str(rate), "-i", str(source)]
    elif kind == "video":
        size, rate, duration = probe_video(source)
        resized, canvas, offset = _sticker_geometry(size)
        # libvpx retains WebM alpha; FFmpeg's native VP9 decoder doesn't.
        source_args = ["-c:v", "libvpx-vp9", "-i", str(source)]
    else:
        raise MemeError("Unsupported media. Reply to an image or sticker.")
    overlay_path = work_dir / "text.png"
    with text_overlay(resized, text) as overlay:
        overlay.save(overlay_path)
    return _encode_video(source_args, overlay_path, work_dir / "memify.webm",
                         resized, canvas, offset, rate, duration)

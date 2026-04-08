from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import mimetypes
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass

import httpx
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2
from gradio_client import Client as GradioClient, handle_file
from PIL import Image

import config as runtime_config
from VIVAANXMUSIC.security import build_subprocess_env


GENVID_USE_PUBLIC_FALLBACKS = getattr(
    runtime_config, "GENVID_USE_PUBLIC_FALLBACKS", "0"
)
HF_TOKEN = getattr(runtime_config, "HF_TOKEN", None)
HF_TOKENS = getattr(runtime_config, "HF_TOKENS", "")
OCR_SPACE_API_KEY = getattr(runtime_config, "OCR_SPACE_API_KEY", "helloworld")
REPLICATE_API_TOKEN = getattr(runtime_config, "REPLICATE_API_TOKEN", None)
REPLICATE_API_TOKENS = getattr(runtime_config, "REPLICATE_API_TOKENS", "")


HTTP_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
HTTP_HEADERS = {"User-Agent": "VivaanX/FreeAI/1.0"}
CHAT_API_URL = "https://api-xqwa.onrender.com/chat/"
IMAGE_GEN_URL = "https://death-image.ashlynn.workers.dev/generate"
IMAGE_ENHANCE_URL = "https://arimagex.netlify.app/api/enhance"
IMAGE_REMOVEBG_URL = "https://arimagex.netlify.app/api/removebg"
OCR_SPACE_API_URL = "https://api.ocr.space/parse/image"
REPLICATE_API_URL = "https://api.replicate.com/v1"
TEXT_VIDEO_MJ_URL = "https://text-to-video-mj.vercel.app/generate"
TEXT_VIDEO_MJ_PROXY_URL = "https://mag.dhanjeerider.workers.dev/"
VHEER_BASE_URL = "https://vheer.com"
VHEER_UPLOAD_URL = f"{VHEER_BASE_URL}/app/api/vheer/upload"
VHEER_STATUS_URL = f"{VHEER_BASE_URL}/app/api/vheer/status"
VHEER_ENCRYPTION_SECRET = "vH33r_2025_AES_GCM_S3cur3_K3y_9X7mP4qR8nT2wE5yU1oI6aS3dF7gH0jK9lZ"
VHEER_ENCRYPTION_SALT = b"vheer-salt-2024"
VHEER_IMAGE_TO_VIDEO_TASK_TYPE = 5
VIDEO_REFERENCE_MAX_DIMENSION = 1024
VIDEO_REFERENCE_JPEG_QUALITY = 88
REPLICATE_SEEDANCE_MODEL = "bytedance/seedance-1-lite"
REPLICATE_MINIMAX_MODEL = "minimax/video-01"
REPLICATE_KLING_MODEL = "kwaivgi/kling-v2.1"
HF_VISION_SPACE = "prithivMLmods/Qwen2.5-VL"
HF_VISION_FALLBACK_SPACE = "prithivMLmods/Qwen-3.5-HF-Demo"
HF_VISION_ALT_SPACE = "vikhyatk/moondream2"
HF_COGVIDEO2_SPACE = "zai-org/CogVideoX-2B-Space"
HF_COGVIDEO5_SPACE = "zai-org/CogVideoX-5B-Space"
HF_LTX_VIDEO_SPACE = "DeepRat/LTX-Video-ZeroGPU-Optimized"
HF_WAN22_FAST_I2V_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"
HF_WAN22_PREVIEW_SPACE = "r3gm/wan2-2-fp8da-aoti-preview"
HF_WAN22_PREVIEW2_SPACE = "r3gm/wan2-2-fp8da-aoti-preview2"
HF_WAN22_OBSXRVER_SPACE = "obsxrver/WAN22-I2V-Demo"
HF_WAN22_DREAM_SPACE = "dream2589632147/Dream-wan2-2-faster-Pro"
HF_IMAGE_EDIT_SPACE = "Qwen/Qwen-Image-Edit-2511"
HF_IMAGE_EDIT_FAST_SPACE = "Nichotin/Qwen-Image-Edit-2511-Fast-ZeroGPU"
HF_IMAGE_EDIT_ALT_SPACE = "lenML/Qwen-Image-Edit-2511-Fast"
HF_IMAGE_OBJECT_SPACE = "prithivMLmods/Qwen-Image-Edit-Object-Manipulator"
HF_FACE_SWAP_SPACE = "V0pr0S/ComfyUI-Reactor-Fast-Face-Swap-CPU"
HF_IMAGE_STYLE_SPACE = "prithivMLmods/Qwen-Image-Edit-2511-LoRAs-Fast"
DEFAULT_VISION_PROMPT = "Describe this image."
DETAILED_VISION_PROMPT = (
    "Describe this image clearly and helpfully. Mention the main subject, setting, "
    "important objects, colors, actions, style, and any visible text. If it looks "
    "like a screenshot, poster, UI, or meme, say that."
)
VISION_PROVIDER_TIMEOUT = 50
OCR_VISIBLE_TEXT_LIMIT = 900
CHAT_MODEL_CANDIDATES = ("gpt-4", "gpt-4o-mini")
CHAT_ALIAS_PROFILES = {
    "eliteai": {
        "display_name": "Elite AI",
        "identity_response": "I am Elite AI. Powered by EliteGen developed by Siddhartha.",
        "system_prompt": (
            "You are Elite AI. Your identity line is: Powered by EliteGen developed by Siddhartha. "
            "Respond naturally and helpfully. If the user asks what model you are, who developed you, or what AI powers you, "
            "say: I am Elite AI. Powered by EliteGen developed by Siddhartha. Do not mention backend providers and do not claim to be ChatGPT."
        ),
    },
    "gpt": {
        "display_name": "GPT",
        "identity_response": "I am GPT. My model name is GPT-5.4.",
        "system_prompt": (
            "You are GPT. Respond in a clear, balanced, capable assistant style similar to the latest GPT family. "
            "If the user asks what model you are, say you are GPT-5.4."
        ),
    },
    "jarvis": {
        "display_name": "Jarvis",
        "identity_response": "I am Jarvis. Powered by EliteGen developed by Siddhartha.",
        "system_prompt": (
            "You are Jarvis. Your identity line is: Powered by EliteGen developed by Siddhartha. "
            "Respond smartly and directly. If the user asks what model you are, who developed you, or what AI powers you, "
            "say: I am Jarvis. Powered by EliteGen developed by Siddhartha."
        ),
    },
    "assis": {
        "display_name": "Assistant",
        "identity_response": "I am Assistant. Powered by EliteGen developed by Siddhartha.",
        "system_prompt": (
            "You are Assistant. Your identity line is: Powered by EliteGen developed by Siddhartha. "
            "Respond clearly and naturally. If the user asks what model you are, who developed you, or what AI powers you, "
            "say: I am Assistant. Powered by EliteGen developed by Siddhartha."
        ),
    },
    "chatgpt": {
        "display_name": "ChatGPT",
        "identity_response": "I am ChatGPT. My model name is GPT-5.4.",
        "system_prompt": (
            "You are ChatGPT. Respond helpfully, naturally, and clearly, in the style of the latest ChatGPT model. "
            "If the user asks what model you are, say: I am ChatGPT powered by GPT-5.4."
        ),
    },
    "gemini": {
        "display_name": "Gemini",
        "identity_response": "I am Gemini. My model name is Gemini 2.5 Pro.",
        "system_prompt": (
            "You are Gemini. Respond in a concise, polished, multimodal-assistant tone. "
            "If the user asks what model you are, say you are Gemini 2.5 Pro."
        ),
    },
    "bard": {
        "display_name": "Bard",
        "identity_response": "I am Bard. My model name is Gemini 2.5 Pro.",
        "system_prompt": (
            "You are Bard. Respond in a conversational, thoughtful, lightly creative style. "
            "If the user asks what model you are, say you are Gemini 2.5 Pro."
        ),
    },
    "llama": {
        "display_name": "LLaMA",
        "identity_response": "I am LLaMA. My model name is Llama 4 Maverick.",
        "system_prompt": (
            "You are LLaMA. Respond directly, technically, and efficiently. "
            "If the user asks what model you are, say you are Llama 4 Maverick."
        ),
    },
    "mistral": {
        "display_name": "Mistral",
        "identity_response": "I am Mistral. My model name is Mistral Small 4.",
        "system_prompt": (
            "You are Mistral. Respond crisply, logically, and with minimal fluff. "
            "If the user asks what model you are, say you are Mistral Small 4."
        ),
    },
    "claude": {
        "display_name": "Claude",
        "identity_response": "I am Claude. My model name is Claude Opus 4.1.",
        "system_prompt": (
            "You are Claude. Respond calmly, carefully, and with a polished explanatory style. "
            "If the user asks what model you are, say you are Claude Opus 4.1."
        ),
    },
    "geminivision": {
        "display_name": "Gemini Vision",
        "identity_response": "I am Gemini Vision.",
        "system_prompt": (
            "You are Gemini Vision. If the user asks what model you are, say you are Gemini Vision."
        ),
    },
}
VIDEO_NEGATIVE_PROMPT = (
    "low quality, blur, watermark, text, distorted anatomy, artifacts"
)
IMAGE_TO_VIDEO_NEGATIVE_PROMPT = (
    "low quality, blur, watermark, text, distorted anatomy, artifacts, "
    "identity change, face change, body change, clothing change, scene change, "
    "background change, camera cut, extra people, extra limbs, morphing, flicker"
)
VISION_SYSTEM_PROMPT = (
    "You answer questions about an image using the provided multimodal analysis, OCR "
    "text, and fallback captions. Prefer the direct multimodal analysis when present. "
    "Use OCR text to capture visible writing, but mention when OCR may be approximate. "
    "Never speculate about symbolism, brand, intent, unseen objects, or context beyond "
    "the supplied evidence. If the evidence is limited, say so briefly. Keep the answer "
    "natural, concise, and useful. Do not invent details."
)
PROMO_LINE_MARKERS = (
    "need proxies cheaper than the market",
    "ashlynn_repository",
    "try our own hosting service",
    "join our",
    "join:",
    "op.wtf",
)
DEFAULT_IMAGE_MOTION_MARKERS = (
    "make this image come alive",
    "smooth cinematic motion",
    "animate this image",
    "bring this image to life",
)
BLOCKED_RESPONSE_MARKERS = (
    "pollinations legacy text api",
    'add a "api_key"',
    "no yupp accounts configured",
    "invalid model",
    "something went wrong. please try again later.",
)
VISION_UPSTREAM_ERROR_MARKERS = (
    "unlogged user is runnning out of daily zerogpu quotas",
    "you have exceeded your gpu quota",
    "exceeded your gpu quota",
    "no gpu was available",
    "queue is too long",
    "try again in",
    "upstream gradio app has raised an exception",
)
IMAGE_EDIT_ERROR_MARKERS = (
    "you have exceeded your gpu quota",
    "unlogged user is runnning out of daily zerogpu quotas",
    "queue is too long",
    "no gpu was available",
    "try again in",
    "upstream gradio app has raised an exception",
    "provider timed out",
)
PROMO_URL_PATTERN = re.compile(
    r"https?://(?:t\.me|op\.wtf|ar-hosting\.pages\.dev)\S*",
    re.IGNORECASE,
)
TRY_AGAIN_PATTERN = re.compile(
    r"try again in (\d+):(\d+):(\d+)",
    re.IGNORECASE,
)
DEFAULT_VISION_PATTERN = re.compile(r"^describe this image\.?$", re.IGNORECASE)
THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
IDENTITY_QUERY_MARKERS = (
    "who made you",
    "who made u",
    "who created you",
    "who is your creator",
    "who's your creator",
    "your creator",
    "creator name",
    "who developed you",
    "who is your developer",
    "who's your developer",
    "developer name",
    "who built you",
    "built you",
    "who owns you",
    "owner name",
    "who is behind you",
    "who's behind you",
    "what company made you",
    "which company made you",
    "what company created you",
    "which company created you",
    "company name",
    "your company",
    "brand name",
    "your brand",
    "what model are you",
    "which model are you",
    "what llm model are you",
    "which llm model are you",
    "what llm are you",
    "which llm are you",
    "what ai are you",
    "what are you powered by",
    "what powers you",
    "what powers this bot",
    "what powers this ai",
    "your model name",
    "model name",
    "introduce yourself",
    "tell me about yourself",
    "what is your name",
    "tum kaun ho",
    "tumhare model ka name kya hai",
    "tum kon se model ho",
    "tum konse model ho",
    "kisne banaya",
    "kisne banaya hai",
    "tumhe kisne banaya",
    "tumko kisne banaya",
    "tumhara creator kaun hai",
    "tumhara developer kaun hai",
    "tumhara owner kaun hai",
    "tumhari company ka name kya hai",
    "tumhara company name kya hai",
    "tumhara brand name kya hai",
    "kiske dwara",
    "konsa llm",
    "kon sa llm",
    "creator kon hai",
    "creator ka name",
    "developer kon hai",
    "developer ka name",
    "company kon si hai",
)
PROVIDER_COOLDOWNS: dict[str, float] = {}
TOKEN_COOLDOWNS: dict[str, float] = {}
TOKEN_ROTATION_LOCK = threading.Lock()
TOKEN_ROTATION_STATE = {"replicate": 0, "hf": 0}


class FreeAIError(RuntimeError):
    pass


@dataclass(slots=True)
class ChatResult:
    model: str
    content: str


@dataclass(slots=True)
class VideoResult:
    provider: str
    file_path: str
    used_reference_image: bool


@dataclass(slots=True)
class VideoProvider:
    name: str
    timeout_seconds: int
    supports_reference: bool
    requires_reference: bool
    runner: object


def _build_data_uri(mime_type: str, image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _parse_token_pool(*values: str | None) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw in re.split(r"[\r\n,]+", str(value or "")):
            token = raw.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            items.append(token)
    return tuple(items)


REPLICATE_TOKEN_POOL = _parse_token_pool(REPLICATE_API_TOKENS, REPLICATE_API_TOKEN)
HF_TOKEN_POOL = _parse_token_pool(HF_TOKENS, HF_TOKEN)


def _is_enabled(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _path_to_data_uri(path: str) -> str:
    guessed_type, _ = mimetypes.guess_type(path)
    mime_type = guessed_type or "image/jpeg"
    with open(path, "rb") as handle:
        return _build_data_uri(mime_type, handle.read())


def _sanitize_chat_text(text: str | None) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    lowered_raw = raw.lower()
    if any(marker in lowered_raw for marker in BLOCKED_RESPONSE_MARKERS):
        return ""

    cleaned_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1]:
                cleaned_lines.append("")
            continue
        if PROMO_URL_PATTERN.search(stripped):
            continue
        if any(marker in lowered for marker in PROMO_LINE_MARKERS):
            continue
        cleaned_lines.append(stripped)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _is_identity_query(prompt: str | None) -> bool:
    lowered = str(prompt or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in IDENTITY_QUERY_MARKERS)


def _extract_json_error(payload) -> str:
    if isinstance(payload, dict):
        for key in ("response", "message", "error", "detail", "msg"):
            value = payload.get(key)
            if value:
                return str(value)
    return "Unknown upstream error."


def _derive_vheer_key() -> bytes:
    return PBKDF2(
        VHEER_ENCRYPTION_SECRET.encode("utf-8"),
        VHEER_ENCRYPTION_SALT,
        dkLen=32,
        count=10000,
        hmac_hash_module=SHA256,
    )


def _encrypt_vheer_payload(payload: dict) -> str:
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(12)
    cipher = AES.new(_derive_vheer_key(), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return base64.b64encode(nonce + ciphertext + tag).decode("utf-8")


def _decrypt_vheer_payload(encoded_payload: str):
    raw = base64.b64decode(encoded_payload)
    if len(raw) < 28:
        raise FreeAIError("Vheer returned an invalid encrypted payload.")
    nonce = raw[:12]
    ciphertext = raw[12:-16]
    tag = raw[-16:]
    cipher = AES.new(_derive_vheer_key(), AES.MODE_GCM, nonce=nonce)
    decrypted = cipher.decrypt_and_verify(ciphertext, tag)
    return json.loads(decrypted.decode("utf-8"))


def _write_temp_image(image_bytes: bytes, mime_type: str) -> str:
    suffix = ".png" if "png" in mime_type.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(image_bytes)
        return handle.name


def _prepare_video_reference_image(image_bytes: bytes, mime_type: str) -> str:
    source_path = _write_temp_image(image_bytes, mime_type)
    prepared_path: str | None = None
    try:
        with Image.open(source_path) as image:
            image.load()

            has_alpha = image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            )
            converted = image.convert("RGBA" if has_alpha else "RGB")

            width, height = converted.size
            max_side = max(width, height, 1)
            scale = min(1.0, VIDEO_REFERENCE_MAX_DIMENSION / max_side)
            if scale < 1.0:
                resized = (
                    max(1, int(round(width * scale))),
                    max(1, int(round(height * scale))),
                )
                converted = converted.resize(resized, Image.Resampling.LANCZOS)

            suffix = ".png" if has_alpha else ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                prepared_path = handle.name
                if has_alpha:
                    converted.save(handle, format="PNG", optimize=True)
                else:
                    converted.save(
                        handle,
                        format="JPEG",
                        quality=VIDEO_REFERENCE_JPEG_QUALITY,
                        optimize=True,
                    )

        return prepared_path or source_path
    except Exception:
        return source_path
    finally:
        if prepared_path and prepared_path != source_path:
            _remove_file(source_path)


def _remove_file(path: str | None):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _cooldown_seconds_from_error(message: str) -> int | None:
    text = (message or "").strip()
    if not text:
        return None

    match = TRY_AGAIN_PATTERN.search(text)
    if match:
        hours, minutes, seconds = map(int, match.groups())
        return (hours * 3600) + (minutes * 60) + seconds

    lowered = text.lower()
    if (
        "gpu quota" in lowered
        or "maximum allowed" in lowered
        or "no gpu was available" in lowered
        or "monthly spending limit" in lowered
        or "insufficient credit" in lowered
    ):
        return 30 * 60
    if "queue is too long" in lowered:
        return 10 * 60
    if "timed out" in lowered or "read operation timed out" in lowered:
        return 5 * 60
    return None


def _provider_cooldown_remaining(provider_name: str) -> int:
    until = PROVIDER_COOLDOWNS.get(provider_name, 0)
    remaining = int(until - time.time())
    return remaining if remaining > 0 else 0


def _set_provider_cooldown(provider_name: str, message: str):
    seconds = _cooldown_seconds_from_error(message)
    lowered = (message or "").lower()
    if provider_name == "Vheer / Free I2V" and (
        "timed out" in lowered or "timeout" in lowered
    ):
        seconds = 15
    if seconds:
        PROVIDER_COOLDOWNS[provider_name] = time.time() + seconds
    else:
        PROVIDER_COOLDOWNS.pop(provider_name, None)


def _clear_provider_cooldown(provider_name: str):
    PROVIDER_COOLDOWNS.pop(provider_name, None)


def _token_cooldown_key(service: str, token: str) -> str:
    return f"{service}:{token}"


def _token_cooldown_remaining(service: str, token: str) -> int:
    until = TOKEN_COOLDOWNS.get(_token_cooldown_key(service, token), 0)
    remaining = int(until - time.time())
    return remaining if remaining > 0 else 0


def _set_token_cooldown(service: str, token: str, message: str):
    seconds = _cooldown_seconds_from_error(message)
    key = _token_cooldown_key(service, token)
    if seconds:
        TOKEN_COOLDOWNS[key] = time.time() + seconds
    else:
        TOKEN_COOLDOWNS.pop(key, None)


def _clear_token_cooldown(service: str, token: str):
    TOKEN_COOLDOWNS.pop(_token_cooldown_key(service, token), None)


def _rotate_tokens(service: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    if not tokens:
        return ()

    with TOKEN_ROTATION_LOCK:
        start = TOKEN_ROTATION_STATE.get(service, 0) % len(tokens)
        TOKEN_ROTATION_STATE[service] = (start + 1) % len(tokens)

    rotated = tokens[start:] + tokens[:start]
    active = [
        token
        for token in rotated
        if _token_cooldown_remaining(service, token) <= 0
    ]
    return tuple(active or rotated)


def _get_replicate_tokens() -> tuple[str, ...]:
    return _rotate_tokens("replicate", REPLICATE_TOKEN_POOL)


def _get_hf_tokens() -> tuple[str, ...]:
    return _rotate_tokens("hf", HF_TOKEN_POOL)


def _unwrap_gradio_media(payload):
    current = payload
    for _ in range(4):
        if isinstance(current, tuple) and current:
            current = current[0]
            continue
        if isinstance(current, dict) and "value" in current:
            current = current.get("value")
            continue
        break
    return current


def _extract_video_path(payload) -> str | None:
    current = _unwrap_gradio_media(payload)
    if isinstance(current, list):
        for item in current:
            candidate = _extract_video_path(item)
            if candidate:
                return candidate
        return None
    if isinstance(current, dict):
        video = current.get("video")
        if isinstance(video, dict):
            video = video.get("path") or video.get("url")
        if isinstance(video, str) and video:
            return video
        path = current.get("path")
        if isinstance(path, str) and path:
            return path
    if isinstance(current, str) and current:
        return current
    return None


def _extract_image_path(payload) -> str | None:
    current = _unwrap_gradio_media(payload)
    if isinstance(current, list):
        for item in current:
            candidate = _extract_image_path(item)
            if candidate:
                return candidate
        return None
    if isinstance(current, dict):
        image = current.get("image")
        if isinstance(image, dict):
            image = image.get("path") or image.get("url")
        if isinstance(image, str) and image:
            return image
        path = current.get("path") or current.get("url")
        if isinstance(path, str) and path:
            return path
    if isinstance(current, str) and current:
        return current
    return None


async def _ensure_local_video(path_or_url: str) -> str:
    if os.path.exists(path_or_url):
        return path_or_url
    if not re.match(r"^https?://", path_or_url, flags=re.IGNORECASE):
        raise FreeAIError("Generated video file was not available locally.")

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.get(path_or_url)
        if response.status_code != 200:
            raise FreeAIError("Generated video could not be downloaded.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as handle:
            handle.write(response.content)
            return handle.name


async def _ensure_local_image(path_or_url: str) -> str:
    if os.path.exists(path_or_url):
        return path_or_url
    if not re.match(r"^https?://", path_or_url, flags=re.IGNORECASE):
        raise FreeAIError("Edited image file was not available locally.")

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.get(path_or_url)
        if response.status_code != 200:
            raise FreeAIError("Edited image could not be downloaded.")
        suffix = os.path.splitext(path_or_url)[1] or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(response.content)
            return handle.name


async def _render_local_backup_video(image_path: str) -> str:
    width, height = _compute_video_dimensions(image_path)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as handle:
        output_path = handle.name

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},format=yuv420p,"
        "fade=t=in:st=0:d=0.25,fade=t=out:st=3.75:d=0.25"
    )

    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-vf",
        vf,
        "-t",
        "4",
        "-r",
        "24",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
        output_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env=build_subprocess_env(),
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not os.path.exists(output_path):
        _remove_file(output_path)
        error_text = (stderr or b"").decode("utf-8", "ignore").strip()
        raise FreeAIError(error_text or "Local backup render failed.")
    return output_path


async def _run_local_backup_video(
    prompt: str,
    *,
    reference_image_path: str | None,
) -> VideoResult:
    generated_image_path = None
    try:
        if reference_image_path:
            image_path = reference_image_path
            provider_name = "Local backup animation"
            used_reference = True
        else:
            image_bytes = await generate_image(prompt)
            generated_image_path = _write_temp_image(image_bytes, "image/png")
            image_path = generated_image_path
            provider_name = "Local backup render"
            used_reference = False

        video_path = await _render_local_backup_video(image_path)
        return VideoResult(
            provider=provider_name,
            file_path=video_path,
            used_reference_image=used_reference,
        )
    finally:
        if generated_image_path:
            _remove_file(generated_image_path)


def _run_gradio_job(client: GradioClient, timeout_seconds: int, *args, api_name: str):
    job = client.submit(*args, api_name=api_name)
    deadline = time.time() + timeout_seconds

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            try:
                job.cancel()
            except Exception:
                pass
            raise FreeAIError("Provider timed out.")

        try:
            return job.result(timeout=min(10, remaining))
        except concurrent.futures.TimeoutError:
            pass

        try:
            status = job.status()
        except Exception:
            continue

        status_code = getattr(status, "code", None)
        status_name = getattr(status_code, "name", str(status_code or "")).upper()
        status_message = str(getattr(status, "message", "") or "").strip()
        eta = getattr(status, "eta", None)

        if status_name == "FAILED":
            raise FreeAIError(status_message or "Provider failed.")
        if status_name == "CANCELLED":
            raise FreeAIError(status_message or "Provider cancelled the request.")
        if status_message and TRY_AGAIN_PATTERN.search(status_message):
            raise FreeAIError(status_message)
        if eta is not None and float(eta) > max(120, remaining + 20):
            try:
                job.cancel()
            except Exception:
                pass
            raise FreeAIError(f"Queue is too long ({int(eta)}s).")


def _run_text_only_video_space(
    space_id: str,
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    result = _run_with_hf_client(
        space_id,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            prompt,
            api_name="/predict",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{space_id} returned no video.")
    return video_path


def _replicate_headers(token: str, *, wait_seconds: int | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if wait_seconds:
        headers["Prefer"] = f"wait={max(1, min(60, wait_seconds))}"
    return headers


def _replicate_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text.strip() or "Replicate request failed."

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if detail:
            return str(detail)
        title = payload.get("title")
        error = payload.get("error")
        if title and error:
            return f"{title}: {error}"
        if title:
            return str(title)
        if error:
            return str(error)
    return "Replicate request failed."


def _replicate_output_video_path(payload) -> str | None:
    video_path = _extract_video_path(payload)
    if video_path:
        return video_path
    if isinstance(payload, dict):
        for key in ("output", "video", "url"):
            value = payload.get(key)
            candidate = _extract_video_path(value)
            if candidate:
                return candidate
    return None


def _run_replicate_prediction_once(
    token: str,
    model: str,
    input_payload: dict,
    timeout_seconds: int,
) -> str:
    headers = _replicate_headers(token, wait_seconds=min(timeout_seconds, 60))
    request_timeout = httpx.Timeout(max(timeout_seconds + 15, 60), connect=10.0)
    with httpx.Client(
        timeout=request_timeout,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = client.post(
            f"{REPLICATE_API_URL}/models/{model}/predictions",
            headers=headers,
            json={"input": input_payload},
        )
        if response.status_code >= 400:
            raise FreeAIError(_replicate_error_message(response))

        prediction = response.json()
        deadline = time.time() + timeout_seconds

        while True:
            status = str(prediction.get("status") or "").lower()
            if status == "succeeded":
                output_path = _replicate_output_video_path(prediction.get("output"))
                if output_path:
                    return output_path
                raise FreeAIError(f"{model} returned no video.")
            if status in {"failed", "canceled", "cancelled"}:
                error_text = str(prediction.get("error") or "").strip()
                raise FreeAIError(error_text or f"{model} {status}.")

            remaining = deadline - time.time()
            if remaining <= 0:
                cancel_url = (prediction.get("urls") or {}).get("cancel")
                if cancel_url:
                    try:
                        client.post(cancel_url, headers=_replicate_headers(token))
                    except Exception:
                        pass
                raise FreeAIError("Replicate provider timed out.")

            get_url = (prediction.get("urls") or {}).get("get")
            if not get_url:
                raise FreeAIError(f"{model} did not return a status URL.")

            time.sleep(min(4, max(1, remaining)))
            poll = client.get(get_url, headers=_replicate_headers(token))
            if poll.status_code >= 400:
                raise FreeAIError(_replicate_error_message(poll))
            prediction = poll.json()


def _run_replicate_prediction(
    model: str,
    input_payload: dict,
    timeout_seconds: int,
) -> str:
    tokens = _get_replicate_tokens()
    if not tokens:
        raise FreeAIError("Replicate API token is not configured.")

    failures: list[str] = []
    for token in tokens:
        try:
            output = _run_replicate_prediction_once(
                token,
                model,
                input_payload,
                timeout_seconds,
            )
            _clear_token_cooldown("replicate", token)
            return output
        except FreeAIError as exc:
            message = str(exc)
            _set_token_cooldown("replicate", token, message)
            failures.append(message)

    details = "\n".join(failures[:3])
    raise FreeAIError(details or "Replicate request failed.")


def _run_replicate_seedance_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    input_payload = {
        "prompt": prompt,
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "16:9",
        "fps": 24,
        "camera_fixed": bool(reference_image_path),
    }
    if reference_image_path:
        input_payload["image"] = _path_to_data_uri(reference_image_path)
    return _run_replicate_prediction(
        REPLICATE_SEEDANCE_MODEL,
        input_payload,
        timeout_seconds,
    )


def _run_replicate_minimax_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    input_payload = {
        "prompt": prompt,
        "prompt_optimizer": not bool(reference_image_path),
    }
    if reference_image_path:
        input_payload["first_frame_image"] = _path_to_data_uri(reference_image_path)
    return _run_replicate_prediction(
        REPLICATE_MINIMAX_MODEL,
        input_payload,
        timeout_seconds,
    )


def _run_replicate_kling_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if not reference_image_path:
        raise FreeAIError("Kling requires a reference image.")

    input_payload = {
        "prompt": prompt,
        "start_image": _path_to_data_uri(reference_image_path),
        "duration": 5,
        "mode": "standard",
        "negative_prompt": IMAGE_TO_VIDEO_NEGATIVE_PROMPT,
    }
    return _run_replicate_prediction(
        REPLICATE_KLING_MODEL,
        input_payload,
        timeout_seconds,
    )


def _extract_simple_video_json_url(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    if str(payload.get("status") or "").lower() not in {"success", "ok"}:
        return None
    value = str(payload.get("url") or "").strip()
    return value or None


def _run_text_video_mj_api(
    api_url: str,
    prompt: str,
    timeout_seconds: int,
) -> str:
    request_timeout = httpx.Timeout(max(timeout_seconds, 30), connect=10.0)
    async_headers = dict(HTTP_HEADERS)
    with httpx.Client(
        timeout=request_timeout,
        headers=async_headers,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = client.get(
            api_url,
            params={"prompt": prompt},
        )
        if response.status_code >= 400:
            raise FreeAIError(response.text.strip() or "Text-to-video API request failed.")

        try:
            payload = response.json()
        except Exception:
            text = response.text.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    import json

                    payload = json.loads(text)
                except Exception as exc:
                    raise FreeAIError("Text-to-video API returned an invalid response.") from exc
            else:
                raise FreeAIError("Text-to-video API returned an invalid response.")

        video_url = _extract_simple_video_json_url(payload)
        if video_url:
            return video_url

        detail = _extract_json_error(payload)
        raise FreeAIError(detail or "Text-to-video API returned no video.")


def _run_vidforge_text_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if reference_image_path:
        raise FreeAIError("VidForge text-to-video does not support reference images.")
    return _run_text_video_mj_api(TEXT_VIDEO_MJ_URL, prompt, timeout_seconds)


def _run_vidforge_proxy_text_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if reference_image_path:
        raise FreeAIError("VidForge proxy text-to-video does not support reference images.")
    return _run_text_video_mj_api(TEXT_VIDEO_MJ_PROXY_URL, prompt, timeout_seconds)


def _run_alava_wan_demo(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_text_only_video_space(
        "Alava01/Wan-video-demo",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_hysts_zeroscope_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    result = _run_with_hf_client(
        "hysts/zeroscope-v2",
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            prompt,
            0,
            24,
            10,
            api_name="/run",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError("hysts/zeroscope-v2 returned no video.")
    return video_path


def _pick_vheer_video_url(payload) -> str | None:
    if not isinstance(payload, dict):
        return None

    urls = payload.get("downloadUrls") or payload.get("download_urls") or []
    if isinstance(urls, str):
        urls = [urls]

    for url in urls:
        candidate = str(url or "").strip()
        if candidate.lower().endswith(".mp4"):
            return candidate

    for url in urls:
        candidate = str(url or "").strip()
        if candidate:
            return candidate
    return None


def _run_vheer_image_to_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if not reference_image_path:
        raise FreeAIError("Vheer requires a reference image.")

    upload_timeout = httpx.Timeout(max(timeout_seconds, 60), connect=10.0)
    status_timeout = httpx.Timeout(30.0, connect=10.0)
    upload_payload = {
        "type": VHEER_IMAGE_TO_VIDEO_TASK_TYPE,
        "model": "vheer_quality",
        "prompt": prompt,
        "aspectRatio": "auto",
        "duration": 5,
        "resolution": 768,
        "frameRate": 24,
        "generate_audio": False,
    }

    with open(reference_image_path, "rb") as image_handle:
        files = {
            "file": (
                os.path.basename(reference_image_path),
                image_handle,
                mimetypes.guess_type(reference_image_path)[0] or "image/png",
            )
        }
        data = {"params": _encrypt_vheer_payload(upload_payload)}

        with httpx.Client(
            timeout=upload_timeout,
            headers=HTTP_HEADERS,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = client.post(VHEER_UPLOAD_URL, files=files, data=data)
            try:
                payload = response.json()
            except Exception as exc:
                raise FreeAIError("Vheer upload returned an invalid response.") from exc

            if response.status_code != 200 or payload.get("code") != 200:
                raise FreeAIError(_extract_json_error(payload))

            encrypted_data = payload.get("data_enc")
            if not encrypted_data:
                raise FreeAIError("Vheer upload returned no task payload.")

            task_payload = _decrypt_vheer_payload(encrypted_data)
            task_code = str(task_payload.get("code") or "").strip()
            if not task_code:
                raise FreeAIError("Vheer upload returned no task code.")

            deadline = time.monotonic() + max(timeout_seconds, 120)
            while time.monotonic() < deadline:
                status_request = {
                    "type": VHEER_IMAGE_TO_VIDEO_TASK_TYPE,
                    "code": task_code,
                    "user_id": "",
                    "cost_credit": 0,
                }
                status_response = client.post(
                    VHEER_STATUS_URL,
                    json={"params": _encrypt_vheer_payload(status_request)},
                    timeout=status_timeout,
                )
                try:
                    status_payload = status_response.json()
                except Exception as exc:
                    raise FreeAIError("Vheer status returned an invalid response.") from exc

                if status_response.status_code != 200 or status_payload.get("code") != 200:
                    raise FreeAIError(_extract_json_error(status_payload))

                encrypted_status = status_payload.get("data_enc")
                if not encrypted_status:
                    raise FreeAIError("Vheer status returned no task data.")

                task_status = _decrypt_vheer_payload(encrypted_status)
                state = str(task_status.get("status") or "").strip().lower()
                if state in {"success", "completed", "done"}:
                    video_url = _pick_vheer_video_url(task_status)
                    if video_url:
                        return video_url
                    raise FreeAIError("Vheer finished without a video URL.")
                if state in {"failed", "error", "canceled", "cancelled"}:
                    raise FreeAIError(_extract_json_error(task_status))

                time.sleep(2)

    raise FreeAIError("Vheer image-to-video timed out.")


def _run_cogvideox_2b_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    result = _run_with_hf_client(
        HF_COGVIDEO2_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            prompt,
            20,
            5.0,
            api_name="/generate",
        ),
        allow_anonymous=False,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{HF_COGVIDEO2_SPACE} returned no video.")
    return video_path


def _run_cogvideox_5b_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    image_input = handle_file(reference_image_path) if reference_image_path else None
    result = _run_with_hf_client(
        HF_COGVIDEO5_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            prompt,
            image_input,
            None,
            0.8,
            -1,
            False,
            False,
            api_name="/generate",
        ),
        allow_anonymous=False,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{HF_COGVIDEO5_SPACE} returned no video.")
    return video_path


def _run_multimodalart_video(
    prompt: str,
    reference_image_path: str,
    timeout_seconds: int,
) -> str:
    result = _run_with_hf_client(
        "multimodalart/wan2-1-fast",
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            handle_file(reference_image_path),
            prompt,
            512,
            512,
            "low quality, blur, watermark, text, duplicate frames",
            2,
            1.0,
            4,
            42,
            True,
            api_name="/generate_video",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError("Multimodalart provider returned no video.")
    return video_path


def _compute_video_dimensions(image_path: str | None) -> tuple[int, int]:
    if not image_path:
        return 576, 384

    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except Exception:
        return 576, 384

    if width <= 0 or height <= 0:
        return 576, 384

    aspect = width / max(1, height)
    if aspect >= 1.2:
        return 576, 384
    if aspect <= 0.83:
        return 384, 576
    return 480, 480


def _is_default_image_motion_prompt(prompt: str | None) -> bool:
    lowered = str(prompt or "").strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in DEFAULT_IMAGE_MOTION_MARKERS)


def _build_image_to_video_prompt(prompt: str | None) -> str:
    user_prompt = str(prompt or "").strip()
    prefix = (
        "Animate the exact uploaded image into a short realistic video. "
        "Preserve the same person, face, body, outfit, objects, background, "
        "lighting, composition, and camera framing. Add only natural motion "
        "already implied by the image. If a person is visible, continue their "
        "existing action naturally with subtle realistic movement. Do not change "
        "identity, replace the subject, invent a different scene, or transform "
        "the image into something unrelated."
    )
    if _is_default_image_motion_prompt(user_prompt):
        return (
            f"{prefix} Keep the motion gentle, coherent, and faithful to the "
            "original image context."
        )
    return f"{prefix} Requested motion: {user_prompt}"


def _run_deeprat_ltx_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    width, height = _compute_video_dimensions(reference_image_path)
    if reference_image_path:
        result = _run_with_hf_client(
            HF_LTX_VIDEO_SPACE,
            lambda client: _run_gradio_job(
                client,
                timeout_seconds,
                prompt,
                VIDEO_NEGATIVE_PROMPT,
                handle_file(reference_image_path),
                None,
                height,
                width,
                "image-to-video",
                1.0,
                9,
                42,
                True,
                1,
                False,
                False,
                api_name="/image_to_video",
            ),
            allow_anonymous=True,
        )
    else:
        result = _run_with_hf_client(
            HF_LTX_VIDEO_SPACE,
            lambda client: _run_gradio_job(
                client,
                timeout_seconds,
                prompt,
                VIDEO_NEGATIVE_PROMPT,
                None,
                None,
                height,
                width,
                "text-to-video",
                1.0,
                9,
                42,
                True,
                1,
                False,
                False,
                api_name="/text_to_video",
            ),
            allow_anonymous=True,
        )

    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{HF_LTX_VIDEO_SPACE} returned no video.")
    return video_path


def _run_wan22_basic_i2v_space(
    space_id: str,
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if not reference_image_path:
        raise FreeAIError("Reference image required.")

    result = _run_with_hf_client(
        space_id,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            handle_file(reference_image_path),
            prompt,
            6,
            VIDEO_NEGATIVE_PROMPT,
            2,
            1,
            1,
            42,
            True,
            api_name="/generate_video",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{space_id} returned no video.")
    return video_path


def _run_wan22_preview_i2v_space(
    space_id: str,
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if not reference_image_path:
        raise FreeAIError("Reference image required.")

    result = _run_with_hf_client(
        space_id,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            handle_file(reference_image_path),
            handle_file(reference_image_path),
            prompt,
            6,
            VIDEO_NEGATIVE_PROMPT,
            2,
            1,
            1,
            42,
            True,
            6,
            "UniPCMultistep",
            3.0,
            16,
            True,
            api_name="/generate_video",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{space_id} returned no video.")
    return video_path


def _run_wan22_dream_i2v_space(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    if not reference_image_path:
        raise FreeAIError("Reference image required.")

    result = _run_with_hf_client(
        HF_WAN22_DREAM_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            handle_file(reference_image_path),
            prompt,
            6,
            "static, blurry, low quality, watermark, text",
            2,
            1,
            1,
            42,
            True,
            False,
            api_name="/generate_video",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{HF_WAN22_DREAM_SPACE} returned no video.")
    return video_path


def _run_wan22_fast_i2v_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan22_basic_i2v_space(
        HF_WAN22_FAST_I2V_SPACE,
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_wan22_preview_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan22_preview_i2v_space(
        HF_WAN22_PREVIEW_SPACE,
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_wan22_preview2_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan22_preview_i2v_space(
        HF_WAN22_PREVIEW2_SPACE,
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_wan22_obsxrver_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan22_basic_i2v_space(
        HF_WAN22_OBSXRVER_SPACE,
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_wan_generation_clone(
    space_id: str,
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    image = handle_file(reference_image_path) if reference_image_path else None
    result = _run_with_hf_client(
        space_id,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            prompt,
            image,
            512,
            512,
            25,
            20,
            5,
            -1,
            api_name="/generate_video",
        ),
        allow_anonymous=True,
    )
    video_path = _extract_video_path(result)
    if video_path:
        return video_path

    status_text = ""
    if isinstance(result, tuple) and len(result) > 1:
        status_text = str(result[1] or "").strip()
    raise FreeAIError(status_text or f"{space_id} returned no video.")


def _run_openking_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "OpenKing/wan2-video-generation",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_smikke_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "Smikke/wan2-video-generation",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_mrfalco_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "mrfalco/wan2-video-generation",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_chanpoin_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "ChanPoin/wan2-video-generation",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_keen007_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "keen007/wan2-video-generation",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_aliothtalks_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "AliothTalks/wan2-video-generation",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_bytfity_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    return _run_wan_generation_clone(
        "BYTFITY/wan2-video-generation262515414142",
        prompt,
        reference_image_path,
        timeout_seconds,
    )


def _run_wan_async_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    def _runner(client: GradioClient) -> str:
        client.predict(prompt, "960*960", True, -1, api_name="/t2v_generation_async")
        deadline = time.time() + timeout_seconds

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            status = client.predict(api_name="/status_refresh")
            video_path = _extract_video_path(status)
            if video_path:
                return video_path

            estimated_wait = None
            if isinstance(status, tuple) and len(status) > 2:
                try:
                    estimated_wait = float(status[2])
                except (TypeError, ValueError):
                    estimated_wait = None

            if estimated_wait and estimated_wait > max(120, remaining + 20):
                raise FreeAIError(f"Wan queue is too long ({int(estimated_wait)}s).")
            time.sleep(min(6, max(1, remaining)))

        raise FreeAIError("Wan provider timed out.")

    return _run_with_hf_client(
        "Wan-AI/Wan2.1",
        _runner,
        allow_anonymous=True,
    )


def _discard_background_video_task(task: asyncio.Task):
    try:
        output_path = task.result()
    except Exception:
        return

    if isinstance(output_path, str) and os.path.exists(output_path):
        _remove_file(output_path)


async def _run_video_provider_batch(
    providers: list[VideoProvider],
    *,
    prompt: str,
    reference_image_path: str | None,
    progress_callback,
    failures: list[str],
) -> VideoResult | None:
    eligible: list[VideoProvider] = []
    for provider in providers:
        remaining = _provider_cooldown_remaining(provider.name)
        if remaining:
            failures.append(
                f"{provider.name}: cooldown active ({remaining}s remaining)"
            )
            continue
        if provider.requires_reference and not reference_image_path:
            failures.append(f"{provider.name}: no reference image available")
            continue
        eligible.append(provider)

    if not eligible:
        return None

    if progress_callback:
        if len(eligible) == 1:
            label = eligible[0].name
        else:
            label = "Fast pool:\n" + "\n".join(item.name for item in eligible[:4])
            if len(eligible) > 4:
                label += f"\n+{len(eligible) - 4} more"
        await progress_callback(label)

    tasks = {
        asyncio.create_task(
                asyncio.wait_for(
                    asyncio.to_thread(
                        provider.runner,
                        prompt,
                        reference_image_path if provider.supports_reference else None,
                        provider.timeout_seconds,
                    ),
                timeout=provider.timeout_seconds + 30,
            )
        ): provider
        for provider in eligible
    }

    while tasks:
        done, _ = await asyncio.wait(
            set(tasks),
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            provider = tasks.pop(task)
            try:
                output_path = task.result()
                local_path = await _ensure_local_video(output_path)
                _clear_provider_cooldown(provider.name)

                for pending_task in tasks:
                    pending_task.add_done_callback(_discard_background_video_task)

                return VideoResult(
                    provider=provider.name,
                    file_path=local_path,
                    used_reference_image=bool(
                        reference_image_path and provider.supports_reference
                    ),
                )
            except asyncio.TimeoutError:
                error_text = "Provider hard timed out."
                _set_provider_cooldown(provider.name, error_text)
                failures.append(f"{provider.name}: {error_text}")
            except Exception as exc:
                error_text = str(exc)
                _set_provider_cooldown(provider.name, error_text)
                failures.append(f"{provider.name}: {error_text}")

    return None


async def _chat_request(
    client: httpx.AsyncClient,
    prompt: str,
    model: str,
    system_prompt: str | None = None,
) -> ChatResult:
    params = {"question": prompt, "model": model}
    if system_prompt:
        params["systemprompt"] = system_prompt

    response = await client.get(CHAT_API_URL, params=params)
    payload = response.json()
    if response.status_code != 200 or payload.get("successful") != "success":
        raise FreeAIError(_extract_json_error(payload))

    cleaned = _sanitize_chat_text(payload.get("response"))
    if not cleaned:
        raise FreeAIError("Upstream chat response was empty or promotional.")
    return ChatResult(model=str(payload.get("model") or model), content=cleaned)


async def generate_chat_response(
    prompt: str,
    *,
    alias: str = "gpt",
    system_prompt: str | None = None,
) -> ChatResult:
    profile = CHAT_ALIAS_PROFILES.get(alias.lower(), {})
    display_name = str(profile.get("display_name") or alias.upper())
    identity_response = str(profile.get("identity_response") or "").strip()
    if identity_response and _is_identity_query(prompt):
        return ChatResult(model=display_name, content=identity_response)
    alias_prompt = str(profile.get("system_prompt") or "").strip()
    combined_system_prompt = "\n\n".join(
        part for part in (alias_prompt, system_prompt) if part
    ) or None

    failures: list[str] = []
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        for model in CHAT_MODEL_CANDIDATES:
            for attempt in range(2):
                try:
                    result = await _chat_request(
                        client,
                        prompt,
                        model,
                        combined_system_prompt,
                    )
                    return ChatResult(
                        model=display_name,
                        content=result.content,
                    )
                except (httpx.HTTPError, FreeAIError) as exc:
                    failures.append(f"{model} attempt {attempt + 1}: {exc}")
    details = "\n".join(failures[:4])
    raise FreeAIError(f"Chat service is temporarily unavailable.\n{details}")


def _get_gradio_client(space_id: str, *, token: str | None = None) -> GradioClient:
    return GradioClient(space_id, token=token, verbose=False)


def _run_with_hf_client(
    space_id: str,
    runner,
    *,
    allow_anonymous: bool,
):
    failures: list[str] = []
    tokens = list(_get_hf_tokens())
    candidates: list[str | None] = tokens[:]
    if allow_anonymous or not candidates:
        candidates.append(None)

    for token in candidates:
        try:
            result = runner(_get_gradio_client(space_id, token=token))
            if token:
                _clear_token_cooldown("hf", token)
            return result
        except Exception as exc:
            message = str(exc)
            if token:
                _set_token_cooldown("hf", token, message)
            failures.append(message)

    details = "\n".join(failures[:3])
    raise FreeAIError(details or f"{space_id} request failed.")


def _clean_vision_text(text: str | None) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""

    cleaned = THINK_BLOCK_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"^```[\w-]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = re.sub(r"^\s*(assistant|answer)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _raise_if_vision_upstream_error(text: str):
    lowered = (text or "").lower()
    if any(marker in lowered for marker in VISION_UPSTREAM_ERROR_MARKERS):
        raise FreeAIError(text)


def _raise_if_image_edit_upstream_error(text: str):
    lowered = (text or "").lower()
    if any(marker in lowered for marker in IMAGE_EDIT_ERROR_MARKERS):
        raise FreeAIError(text)


def _is_default_vision_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    return bool(DEFAULT_VISION_PATTERN.fullmatch(text)) or text == DETAILED_VISION_PROMPT


def _has_useful_ocr_text(text: str) -> bool:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return False
    alpha_num = re.sub(r"[^A-Za-z0-9]", "", compact)
    return len(alpha_num) >= 10 and len(compact) >= 12


def _trim_visible_text(text: str) -> str:
    compact = re.sub(r"[ \t]+\n", "\n", (text or "").strip())
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    if len(compact) <= OCR_VISIBLE_TEXT_LIMIT:
        return compact

    shortened = compact[:OCR_VISIBLE_TEXT_LIMIT].rsplit(" ", 1)[0].rstrip()
    return f"{shortened}..."


def _prompt_wants_text(prompt: str) -> bool:
    lowered = (prompt or "").lower()
    keywords = (
        "text",
        "read",
        "written",
        "write",
        "screenshot",
        "caption",
        "ocr",
        "transcribe",
        "what does",
        "what is written",
        "say",
    )
    return any(keyword in lowered for keyword in keywords)


def _build_plain_vision_fallback(
    prompt: str,
    *,
    direct_answer: str = "",
    caption: str = "",
    ocr_text: str = "",
) -> str:
    base = (direct_answer or caption or "").strip()
    visible_text = _trim_visible_text(ocr_text) if _has_useful_ocr_text(ocr_text) else ""

    if not base:
        if visible_text:
            return f"Visible text detected:\n{visible_text}"
        return ""

    if not visible_text:
        return base

    if not (_is_default_vision_prompt(prompt) or _prompt_wants_text(prompt)):
        return base

    if visible_text.lower() in base.lower():
        return base
    return f"{base}\n\nVisible text detected:\n{visible_text}"


def _build_caption_only_response(prompt: str, caption: str) -> str:
    cleaned_caption = (caption or "").strip()
    if not cleaned_caption:
        return ""
    if _is_default_vision_prompt(prompt):
        return cleaned_caption

    lowered = (prompt or "").lower()
    if any(keyword in lowered for keyword in ("represent", "mean", "symbol", "identify")):
        return (
            "From the available free fallback analysis, this image appears to show:\n"
            f"{cleaned_caption}\n\n"
            "I can't confidently tell anything more specific than that from this fallback alone."
        )

    return (
        "From the available free fallback analysis, the image appears to show:\n"
        f"{cleaned_caption}"
    )


def _image_path_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def _run_qwen_outpost_vision(image_path: str, prompt: str) -> tuple[str, str]:
    result = _run_with_hf_client(
        HF_VISION_SPACE,
        lambda client: client.predict(
            "Qwen3-VL-4B-Instruct",
            prompt,
            _image_path_to_base64(image_path),
            384,
            0.2,
            0.9,
            50,
            1.1,
            30,
            api_name="/run_router",
        ),
        allow_anonymous=True,
    )
    cleaned = _clean_vision_text(result)
    _raise_if_vision_upstream_error(cleaned)
    if not cleaned:
        raise FreeAIError("Qwen multimodal response was empty.")
    return "Qwen3-VL-4B-Instruct", cleaned


def _run_qwen_hf_demo_vision(image_path: str, prompt: str) -> tuple[str, str]:
    category = "Caption" if _is_default_vision_prompt(prompt) else "Query"
    _, text_output = _run_with_hf_client(
        HF_VISION_FALLBACK_SPACE,
        lambda client: client.predict(
            handle_file(image_path),
            category,
            prompt,
            api_name="/process_inputs",
        ),
        allow_anonymous=True,
    )
    cleaned = _clean_vision_text(text_output)
    _raise_if_vision_upstream_error(cleaned)
    if not cleaned:
        raise FreeAIError("Qwen HF demo returned an empty response.")
    return "Qwen HF Demo", cleaned


def _run_moondream_vision(image_path: str, prompt: str) -> tuple[str, str]:
    result = _run_with_hf_client(
        HF_VISION_ALT_SPACE,
        lambda client: client.predict(
            handle_file(image_path),
            prompt,
            api_name="/answer_question",
        ),
        allow_anonymous=True,
    )
    cleaned = _clean_vision_text(result)
    _raise_if_vision_upstream_error(cleaned)
    if not cleaned:
        raise FreeAIError("Moondream returned an empty response.")
    return "Moondream2", cleaned


async def _answer_with_direct_vision(
    image_path: str,
    prompt: str,
) -> tuple[str, str, list[str]]:
    failures: list[str] = []
    providers = (
        ("Qwen3-VL-4B-Instruct", _run_qwen_outpost_vision),
        ("Qwen HF Demo", _run_qwen_hf_demo_vision),
        ("Moondream2", _run_moondream_vision),
    )

    for name, runner in providers:
        try:
            model, answer = await asyncio.wait_for(
                asyncio.to_thread(runner, image_path, prompt),
                timeout=VISION_PROVIDER_TIMEOUT,
            )
            if answer:
                return model, answer, failures
            failures.append(f"{name}: empty response")
        except asyncio.TimeoutError:
            failures.append(f"{name}: timed out")
        except Exception as exc:
            failures.append(f"{name}: {exc}")

    return "", "", failures


async def _extract_text_with_ocr_space(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
) -> str:
    api_key = (OCR_SPACE_API_KEY or "").strip()
    if not api_key:
        return ""

    extension = mimetypes.guess_extension(mime_type) or ".jpg"
    files = {
        "file": (
            f"vision{extension}",
            image_bytes,
            mime_type,
        )
    }
    data = {
        "language": "auto",
        "isOverlayRequired": "false",
        "detectOrientation": "true",
        "scale": "true",
        "OCREngine": "2",
    }
    headers = {
        **HTTP_HEADERS,
        "apikey": api_key,
    }

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.post(
            OCR_SPACE_API_URL,
            headers=headers,
            data=data,
            files=files,
        )

    if response.status_code != 200:
        raise FreeAIError("OCR request failed.")

    payload = response.json()
    if payload.get("IsErroredOnProcessing"):
        errors = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "OCR failed."
        if isinstance(errors, list):
            errors = "; ".join(str(item) for item in errors if item)
        raise FreeAIError(str(errors))

    text_blocks: list[str] = []
    for item in payload.get("ParsedResults") or []:
        parsed = str(item.get("ParsedText") or "").strip()
        if parsed:
            text_blocks.append(parsed)

    return _trim_visible_text("\n\n".join(text_blocks))


async def _await_optional_ocr_text(task: asyncio.Task, failures: list[str]) -> str:
    try:
        return await asyncio.wait_for(task, timeout=30)
    except asyncio.TimeoutError:
        failures.append("OCR.Space: timed out")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        failures.append(f"OCR.Space: {exc}")
    return ""


async def _synthesize_vision_answer(
    user_prompt: str,
    *,
    direct_answer: str = "",
    caption: str = "",
    ocr_text: str = "",
) -> ChatResult:
    sections: list[str] = []
    if not direct_answer:
        sections.append(
            "Reliability note:\n"
            "No direct multimodal answer was available, so rely conservatively on the "
            "fallback caption and OCR only."
        )
    if direct_answer:
        sections.append(f"Direct multimodal analysis:\n{direct_answer}")
    if caption:
        sections.append(f"Fallback caption:\n{caption}")
    if _has_useful_ocr_text(ocr_text):
        sections.append(
            "OCR text (can contain small mistakes):\n"
            f"{_trim_visible_text(ocr_text)}"
        )

    question = user_prompt
    if _is_default_vision_prompt(user_prompt):
        question = (
            "Describe this image clearly and naturally. Mention the subject, setting, "
            "important details, and visible text when relevant."
        )

    return await generate_chat_response(
        "\n\n".join(sections) + f"\n\nUser request:\n{question}",
        alias="geminivision",
        system_prompt=VISION_SYSTEM_PROMPT,
    )


def _caption_with_florence(image_path: str) -> tuple[str, str]:
    result = _run_with_hf_client(
        "prithivMLmods/Florence-2-Image-Caption",
        lambda client: client.predict(
            uploaded_image=handle_file(image_path),
            model_choice="Florence-2-base",
            api_name="/describe_image",
        ),
        allow_anonymous=True,
    )
    cleaned = _clean_vision_text(result)
    _raise_if_vision_upstream_error(cleaned)
    if not cleaned:
        raise FreeAIError("Florence returned an empty caption.")
    return "Florence-2-base", cleaned


def _caption_with_blip(image_path: str) -> tuple[str, str]:
    result = _run_with_hf_client(
        "hysts/image-captioning-with-blip",
        lambda client: client.predict(
            image=handle_file(image_path),
            text="A picture of",
            api_name="/caption",
        ),
        allow_anonymous=True,
    )
    cleaned = _clean_vision_text(result)
    _raise_if_vision_upstream_error(cleaned)
    if not cleaned:
        raise FreeAIError("BLIP returned an empty caption.")
    return "BLIP", cleaned


async def _caption_image(image_path: str) -> tuple[str, str]:
    failures: list[str] = []
    for runner in (_caption_with_florence, _caption_with_blip):
        try:
            backend, caption = await asyncio.to_thread(runner, image_path)
            if caption:
                return backend, caption
            failures.append(f"{runner.__name__}: empty caption")
        except Exception as exc:
            failures.append(f"{runner.__name__}: {exc}")

    details = "\n".join(failures[:4])
    raise FreeAIError(f"Vision service is temporarily unavailable.\n{details}")


async def generate_vision_response(
    prompt: str,
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
) -> ChatResult:
    user_prompt = (prompt or "").strip() or DEFAULT_VISION_PROMPT
    vision_prompt = (
        DETAILED_VISION_PROMPT if _is_default_vision_prompt(user_prompt) else user_prompt
    )
    image_path = _write_temp_image(image_bytes, mime_type)
    ocr_failures: list[str] = []
    direct_model = ""
    direct_answer = ""
    direct_failures: list[str] = []
    caption_model = ""
    caption = ""
    caption_error = ""
    ocr_text = ""
    ocr_task = asyncio.create_task(
        _extract_text_with_ocr_space(image_bytes, mime_type=mime_type)
    )

    try:
        direct_model, direct_answer, direct_failures = await _answer_with_direct_vision(
            image_path,
            vision_prompt,
        )
        ocr_text = await _await_optional_ocr_text(ocr_task, ocr_failures)

        if direct_answer and not _has_useful_ocr_text(ocr_text):
            return ChatResult(model=direct_model, content=direct_answer)

        if not direct_answer:
            try:
                caption_model, caption = await _caption_image(image_path)
            except FreeAIError as exc:
                caption_error = str(exc)
    finally:
        if not ocr_task.done():
            ocr_task.cancel()
            try:
                await ocr_task
            except BaseException:
                pass
        _remove_file(image_path)

    base_model = direct_model or caption_model
    base_content = direct_answer or caption

    if caption and not direct_answer and not _has_useful_ocr_text(ocr_text):
        return ChatResult(
            model=caption_model,
            content=_build_caption_only_response(user_prompt, caption),
        )

    if base_content:
        try:
            synthesized = await _synthesize_vision_answer(
                user_prompt,
                direct_answer=direct_answer,
                caption=caption,
                ocr_text=ocr_text,
            )
            model_parts = [base_model, synthesized.model]
            if _has_useful_ocr_text(ocr_text):
                model_parts.insert(1, "OCR.Space")
            return ChatResult(
                model=" + ".join(part for part in model_parts if part),
                content=synthesized.content,
            )
        except FreeAIError:
            fallback_text = _build_plain_vision_fallback(
                user_prompt,
                direct_answer=direct_answer,
                caption=caption,
                ocr_text=ocr_text,
            )
            if fallback_text:
                model_name = base_model
                if _has_useful_ocr_text(ocr_text):
                    model_name = f"{model_name} + OCR.Space"
                return ChatResult(model=model_name, content=fallback_text)

    if _has_useful_ocr_text(ocr_text):
        return ChatResult(
            model="OCR.Space",
            content=f"Visible text detected:\n{_trim_visible_text(ocr_text)}",
        )

    failures = direct_failures + ocr_failures
    if caption_error:
        failures.append(caption_error)
    details = "\n".join(failures[:6])
    raise FreeAIError(
        "Image analysis service is temporarily unavailable.\n"
        f"{details}"
    )


IMAGE_EDIT_FACE_SWAP_PATTERNS = (
    "face swap",
    "swap face",
    "swap faces",
    "replace face",
    "put the second face",
    "use the second image face",
)
IMAGE_EDIT_REMOVE_PATTERNS = (
    "remove",
    "erase",
    "delete",
    "hide",
    "take away",
    "without",
)
IMAGE_EDIT_ADD_PATTERNS = (
    "add",
    "put",
    "place",
    "insert",
    "give",
    "wear",
    "holding",
    "make him hold",
    "make her hold",
)
IMAGE_EDIT_CLOTHING_PATTERNS = (
    "dress",
    "outfit",
    "clothes",
    "clothing",
    "shirt",
    "t-shirt",
    "tshirt",
    "jacket",
    "hoodie",
    "kurta",
    "saree",
    "lehenga",
    "wear",
    "wearing",
)
IMAGE_EDIT_STYLE_LORA_MAP = (
    ("anime", "Photo-to-Anime"),
    ("manga", "Manga-Tone"),
    ("comic", "Manga-Tone"),
    ("cinematic", "Cinematic-FlatLog"),
    ("movie", "Cinematic-FlatLog"),
    ("realistic", "Anything2Real"),
    ("real", "Anything2Real"),
    ("polaroid", "Polaroid-Photo"),
    ("angle", "Multiple-Angles"),
    ("angles", "Multiple-Angles"),
    ("dark", "Midnight-Noir-Eyes-Spotlight"),
    ("noir", "Midnight-Noir-Eyes-Spotlight"),
    ("night", "Midnight-Noir-Eyes-Spotlight"),
    ("studio", "Studio-DeLight"),
)


def _prompt_is_face_swap(prompt: str) -> bool:
    lowered = (prompt or "").lower()
    if any(pattern in lowered for pattern in IMAGE_EDIT_FACE_SWAP_PATTERNS):
        return True
    return ("swap" in lowered and "face" in lowered) or (
        "replace" in lowered and "face" in lowered
    )


def _choose_object_lora(prompt: str) -> str:
    lowered = (prompt or "").lower()
    if "extract outfit" in lowered or "extract clothing" in lowered or "flat mockup" in lowered:
        return "Extract-Outfit"
    if "outfit layout" in lowered or "design layout" in lowered or "fashion layout" in lowered:
        return "Outfit-Design-Layout"
    if "zoom" in lowered or "closer" in lowered or "close up" in lowered:
        return "Zoom-Master"
    if any(word in lowered for word in IMAGE_EDIT_REMOVE_PATTERNS):
        return "QIE-2511-Object-Remover-v2"
    return "Qwen-Image-Edit-2511-Object-Adder"


def _prompt_mentions_clothing(prompt: str) -> bool:
    lowered = (prompt or "").lower()
    return any(word in lowered for word in IMAGE_EDIT_CLOTHING_PATTERNS)


def _needs_object_manipulator(prompt: str) -> bool:
    lowered = (prompt or "").lower()
    if "extract outfit" in lowered or "extract clothing" in lowered or "flat mockup" in lowered:
        return True
    if "outfit layout" in lowered or "design layout" in lowered or "fashion layout" in lowered:
        return True
    if "zoom" in lowered or "closer" in lowered or "close up" in lowered:
        return True
    if any(word in lowered for word in IMAGE_EDIT_REMOVE_PATTERNS):
        return True
    if any(word in lowered for word in IMAGE_EDIT_ADD_PATTERNS):
        return not _prompt_mentions_clothing(prompt)
    return False


def _gallery_inputs(image_paths: list[str]):
    return [handle_file(path) for path in image_paths]


def _compute_edit_dimensions(image_path: str) -> tuple[int, int]:
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except Exception:
        return 512, 512

    if width <= 0 or height <= 0:
        return 512, 512

    align = 32
    max_edge = 896
    min_edge = 256

    scale = 1.0
    if min(width, height) < min_edge:
        scale = max(scale, min_edge / min(width, height))
    if max(width, height) * scale > max_edge:
        scale = max_edge / max(width, height)

    target_width = max(align, int(round((width * scale) / align) * align))
    target_height = max(align, int(round((height * scale) / align) * align))

    if target_width <= 0 or target_height <= 0:
        return 512, 512
    return target_width, target_height


def _pick_style_lora(prompt: str) -> str | None:
    lowered = (prompt or "").lower()
    for keyword, adapter in IMAGE_EDIT_STYLE_LORA_MAP:
        if keyword in lowered:
            return adapter
    return None


def _set_image_edit_route_cooldown(route_key: str, message: str):
    lowered = (message or "").lower()
    if (
        "app has raised an exception" in lowered
        or "invalid state" in lowered
        or "paused" in lowered
    ):
        PROVIDER_COOLDOWNS[route_key] = time.time() + (10 * 60)
        return
    _set_provider_cooldown(route_key, message)


def _run_qwen_image_edit_space(
    space_id: str,
    prompt: str,
    image_paths: list[str],
    *,
    timeout_seconds: int,
    rewrite_prompt: bool = True,
) -> str:
    guidance_scale = 4.0 if space_id == HF_IMAGE_EDIT_SPACE else 1.0
    width, height = _compute_edit_dimensions(image_paths[0])
    result = _run_with_hf_client(
        space_id,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            _gallery_inputs(image_paths),
            prompt,
            0,
            True,
            guidance_scale,
            4,
            width,
            height,
            rewrite_prompt,
            api_name="/infer",
        ),
        allow_anonymous=True,
    )
    image_path = _extract_image_path(result)
    if not image_path:
        raise FreeAIError(f"{space_id} returned no edited image.")
    return image_path


def _run_qwen_lenml_edit(
    prompt: str,
    image_paths: list[str],
    *,
    timeout_seconds: int,
) -> str:
    prepared = image_paths[:3]
    while len(prepared) < 3:
        prepared.append(prepared[-1] if prepared else image_paths[0])
    width, height = _compute_edit_dimensions(prepared[0])

    result = _run_with_hf_client(
        HF_IMAGE_EDIT_ALT_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            handle_file(prepared[0]),
            handle_file(prepared[1]),
            handle_file(prepared[2]),
            prompt,
            0,
            True,
            1.0,
            4,
            width,
            height,
            api_name="/infer",
        ),
        allow_anonymous=True,
    )
    image_path = _extract_image_path(result)
    if not image_path:
        raise FreeAIError(f"{HF_IMAGE_EDIT_ALT_SPACE} returned no edited image.")
    return image_path


def _run_object_manipulator_edit(
    prompt: str,
    image_paths: list[str],
    *,
    timeout_seconds: int,
) -> str:
    result = _run_with_hf_client(
        HF_IMAGE_OBJECT_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            _gallery_inputs(image_paths),
            prompt,
            _choose_object_lora(prompt),
            0,
            True,
            1.0,
            4,
            api_name="/infer",
        ),
        allow_anonymous=True,
    )
    image_path = _extract_image_path(result)
    if not image_path:
        raise FreeAIError(f"{HF_IMAGE_OBJECT_SPACE} returned no edited image.")
    return image_path


def _run_style_lora_edit(
    prompt: str,
    image_paths: list[str],
    *,
    timeout_seconds: int,
) -> str:
    lora = _pick_style_lora(prompt)
    if not lora:
        raise FreeAIError("No matching style fallback for this prompt.")

    result = _run_with_hf_client(
        HF_IMAGE_STYLE_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            _gallery_inputs(image_paths),
            prompt,
            lora,
            0,
            True,
            1.0,
            4,
            api_name="/infer",
        ),
        allow_anonymous=True,
    )
    image_path = _extract_image_path(result)
    if not image_path:
        raise FreeAIError(f"{HF_IMAGE_STYLE_SPACE} returned no edited image.")
    return image_path


def _run_reactor_face_swap(
    image_paths: list[str],
    *,
    timeout_seconds: int,
) -> str:
    if len(image_paths) < 2:
        raise FreeAIError("Face swap needs two images.")

    result = _run_with_hf_client(
        HF_FACE_SWAP_SPACE,
        lambda client: _run_gradio_job(
            client,
            timeout_seconds,
            handle_file(image_paths[1]),
            handle_file(image_paths[0]),
            "0",
            "hyperswap_1b_256.onnx",
            "none",
            0.7,
            api_name="/generate_image",
        ),
        allow_anonymous=True,
    )
    image_path = _extract_image_path(result)
    if not image_path:
        raise FreeAIError(f"{HF_FACE_SWAP_SPACE} returned no swapped image.")
    return image_path


def _choose_image_edit_routes(prompt: str, image_count: int) -> tuple[str, ...]:
    routes: list[str] = []
    if image_count >= 2 and _prompt_is_face_swap(prompt):
        routes.append("reactor_face_swap")
    routes.extend(["qwen_official", "qwen_fast"])
    if image_count >= 2 and _prompt_mentions_clothing(prompt):
        if _needs_object_manipulator(prompt):
            routes.append("object_manipulator")
        if _pick_style_lora(prompt):
            routes.append("style_lora")
        routes.append("qwen_lenml")
    else:
        if _needs_object_manipulator(prompt):
            routes.append("object_manipulator")
        if _pick_style_lora(prompt):
            routes.append("style_lora")
        routes.append("qwen_lenml")

    seen: set[str] = set()
    ordered: list[str] = []
    for route in routes:
        if route not in seen:
            seen.add(route)
            ordered.append(route)
    return tuple(ordered)


async def edit_image_bytes(
    prompt: str,
    *,
    images: list[tuple[bytes, str]],
) -> bytes:
    text_prompt = (prompt or "").strip()
    if not text_prompt:
        raise FreeAIError("Please describe the image edit you want.")
    if not images:
        raise FreeAIError("Please reply to an image first.")

    image_paths: list[str] = []
    output_path: str | None = None
    routes = _choose_image_edit_routes(text_prompt, len(images))

    try:
        for image_bytes, mime_type in images[:3]:
            image_paths.append(_write_temp_image(image_bytes, mime_type))

        for route in routes:
            route_key = f"image_edit:{route}"
            if _provider_cooldown_remaining(route_key) > 0:
                continue
            try:
                if route == "reactor_face_swap":
                    candidate = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_reactor_face_swap,
                            image_paths,
                            timeout_seconds=45,
                        ),
                        timeout=50,
                    )
                elif route == "object_manipulator":
                    candidate = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_object_manipulator_edit,
                            text_prompt,
                            image_paths,
                            timeout_seconds=40,
                        ),
                        timeout=45,
                    )
                elif route == "qwen_official":
                    candidate = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_qwen_image_edit_space,
                            HF_IMAGE_EDIT_SPACE,
                            text_prompt,
                            image_paths,
                            timeout_seconds=50,
                            rewrite_prompt=True,
                        ),
                        timeout=55,
                    )
                elif route == "qwen_fast":
                    candidate = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_qwen_image_edit_space,
                            HF_IMAGE_EDIT_FAST_SPACE,
                            text_prompt,
                            image_paths,
                            timeout_seconds=35,
                            rewrite_prompt=True,
                        ),
                        timeout=40,
                    )
                elif route == "style_lora":
                    candidate = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_style_lora_edit,
                            text_prompt,
                            image_paths,
                            timeout_seconds=35,
                        ),
                        timeout=40,
                    )
                else:
                    candidate = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_qwen_lenml_edit,
                            text_prompt,
                            image_paths,
                            timeout_seconds=35,
                        ),
                        timeout=40,
                    )

                output_path = await _ensure_local_image(candidate)
                _clear_provider_cooldown(route_key)
                with open(output_path, "rb") as handle:
                    return handle.read()
            except asyncio.TimeoutError:
                _set_image_edit_route_cooldown(route_key, "Provider timed out.")
                continue
            except Exception as exc:
                message = str(exc).strip() or "unknown error"
                _set_image_edit_route_cooldown(route_key, message)
                continue

        raise FreeAIError(
            "Image editing service is temporarily unavailable right now. Try again later."
        )
    finally:
        for path in image_paths:
            _remove_file(path)
        if output_path and output_path not in image_paths:
            _remove_file(output_path)


async def generate_image(prompt: str) -> bytes:
    params = {
        "prompt": prompt,
        "image": 1,
        "dimensions": "1:1",
        "safety": "true",
        "steps": 4,
    }
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.get(IMAGE_GEN_URL, params=params)
        try:
            payload = response.json()
        except Exception as exc:
            raise FreeAIError("Image generation service returned an invalid response.") from exc

        images = payload.get("images") or [] if isinstance(payload, dict) else []
        if response.status_code != 200 or not images:
            detail = (
                _extract_json_error(payload)
                if isinstance(payload, dict)
                else "Image generation service did not return an image."
            )
            if not detail or detail == "Unknown upstream error.":
                detail = "Image generation service did not return an image."
            raise FreeAIError(detail)

        image_response = await client.get(images[0])
        if image_response.status_code != 200:
            raise FreeAIError("Generated image could not be downloaded.")
        return image_response.content


async def process_image_bytes(
    image_bytes: bytes,
    *,
    mime_type: str = "image/jpeg",
    mode: str,
) -> bytes:
    if mode == "enhance":
        endpoint = IMAGE_ENHANCE_URL
    elif mode == "removebg":
        endpoint = IMAGE_REMOVEBG_URL
    else:
        raise FreeAIError(f"Unsupported image mode: {mode}")

    payload = {"imageUrl": _build_data_uri(mime_type, image_bytes)}
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.post(endpoint, json=payload)
        content_type = (response.headers.get("content-type") or "").lower()
        if response.status_code != 200:
            if "application/json" in content_type:
                raise FreeAIError(_extract_json_error(response.json()))
            raise FreeAIError("Image processing service returned a non-200 response.")
        if "application/json" in content_type:
            payload = response.json()
            image_url = payload.get("imageUrl")
            if not image_url:
                raise FreeAIError(_extract_json_error(payload))
            image_response = await client.get(image_url)
            if image_response.status_code != 200:
                raise FreeAIError("Processed image could not be downloaded.")
            return image_response.content
        if not content_type.startswith("image/"):
            raise FreeAIError("Image processing service returned an unexpected payload.")
        return response.content


async def generate_video(
    prompt: str,
    *,
    image_bytes: bytes | None = None,
    mime_type: str = "image/jpeg",
    progress_callback=None,
) -> VideoResult:
    text_prompt = (prompt or "").strip()
    if not text_prompt and not image_bytes:
        raise FreeAIError("Please provide a prompt for video generation.")

    if not text_prompt:
        text_prompt = "make this image come alive, smooth cinematic motion"

    reference_image_path = None
    used_reference_image = False
    failures: list[str] = []

    try:
        if image_bytes:
            reference_image_path = _prepare_video_reference_image(
                image_bytes, mime_type
            )
            used_reference_image = True
            text_prompt = _build_image_to_video_prompt(text_prompt)

        provider_batches: list[list[VideoProvider]] = []

        if reference_image_path:
            provider_batches.append(
                [
                    VideoProvider(
                        "Vheer / Free I2V",
                        300,
                        True,
                        True,
                        _run_vheer_image_to_video,
                    ),
                ]
            )

            if REPLICATE_TOKEN_POOL:
                provider_batches.extend(
                    [
                        [
                            VideoProvider(
                                "Replicate / Seedance 1 Lite",
                                300,
                                True,
                                False,
                                _run_replicate_seedance_video,
                            ),
                        ],
                        [
                            VideoProvider(
                                "Replicate / MiniMax Video-01",
                                300,
                                True,
                                False,
                                _run_replicate_minimax_video,
                            ),
                        ],
                        [
                            VideoProvider(
                                "Replicate / Kling v2.1",
                                240,
                                True,
                                True,
                                _run_replicate_kling_video,
                            )
                        ],
                    ]
                )

        else:
            if REPLICATE_TOKEN_POOL:
                provider_batches.extend(
                    [
                        [
                            VideoProvider(
                                "Replicate / Seedance 1 Lite",
                                240,
                                True,
                                False,
                                _run_replicate_seedance_video,
                            ),
                        ],
                        [
                            VideoProvider(
                                "Replicate / MiniMax Video-01",
                                240,
                                True,
                                False,
                                _run_replicate_minimax_video,
                            ),
                        ],
                    ]
                )

            if not REPLICATE_TOKEN_POOL or _is_enabled(GENVID_USE_PUBLIC_FALLBACKS):
                provider_batches.extend(
                    [
                        [
                            VideoProvider(
                                "hysts / zeroscope-v2",
                                45,
                                False,
                                False,
                                _run_hysts_zeroscope_video,
                            ),
                            VideoProvider(
                                "Alava01 / Wan Demo",
                                50,
                                False,
                                False,
                                _run_alava_wan_demo,
                            ),
                        ],
                        [
                            VideoProvider(
                                "Wan-AI / Wan2.1",
                                75,
                                False,
                                False,
                                _run_wan_async_video,
                            ),
                        ],
                    ]
                )

            provider_batches.append(
                [
                    VideoProvider(
                        "VidForge / MJ T2V",
                        70,
                        False,
                        False,
                        _run_vidforge_text_video,
                    ),
                    VideoProvider(
                        "VidForge Proxy / MJ T2V",
                        80,
                        False,
                        False,
                        _run_vidforge_proxy_text_video,
                    ),
                ]
            )

        for batch in provider_batches:
            result = await _run_video_provider_batch(
                batch,
                prompt=text_prompt,
                reference_image_path=reference_image_path,
                progress_callback=progress_callback,
                failures=failures,
            )
            if result:
                result.used_reference_image = (
                    used_reference_image and result.used_reference_image
                )
                return result

        if progress_callback:
            await progress_callback("Backup render")
        try:
            result = await _run_local_backup_video(
                text_prompt,
                reference_image_path=reference_image_path,
            )
            result.used_reference_image = (
                used_reference_image and result.used_reference_image
            )
            return result
        except Exception as exc:
            failures.append(f"Local backup: {exc}")

        details = "\n".join(failures[:8])
        if REPLICATE_TOKEN_POOL:
            headline = "Configured video providers are temporarily unavailable."
        else:
            headline = (
                "Public no-key video providers are temporarily unavailable.\n"
                "Tip: set HF_TOKEN/HF_TOKENS or REPLICATE_API_TOKEN/REPLICATE_API_TOKENS for more reliable /genvid output."
            )
        raise FreeAIError(
            f"{headline}\n{details}"
        )
    finally:
        _remove_file(reference_image_path)


def vision_unavailable_message() -> str:
    return (
        "Vision command ab free multimodal + OCR fallback stack use karta hai. "
        "Best results ke liye reply-to-image use karo; HF_TOKEN optional hai aur "
        "OCR_SPACE_API_KEY default shared free key par chal sakta hai."
    )

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import mimetypes
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass

import httpx
from gradio_client import Client as GradioClient, handle_file

import config as runtime_config


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
REPLICATE_SEEDANCE_MODEL = "bytedance/seedance-1-lite"
REPLICATE_MINIMAX_MODEL = "minimax/video-01"
REPLICATE_KLING_MODEL = "kwaivgi/kling-v2.1"
HF_VISION_SPACE = "prithivMLmods/Qwen2.5-VL"
HF_VISION_FALLBACK_SPACE = "prithivMLmods/Qwen-3.5-HF-Demo"
HF_VISION_ALT_SPACE = "vikhyatk/moondream2"
DEFAULT_VISION_PROMPT = "Describe this image."
DETAILED_VISION_PROMPT = (
    "Describe this image clearly and helpfully. Mention the main subject, setting, "
    "important objects, colors, actions, style, and any visible text. If it looks "
    "like a screenshot, poster, UI, or meme, say that."
)
VISION_PROVIDER_TIMEOUT = 50
OCR_VISIBLE_TEXT_LIMIT = 900
CHAT_MODEL_CANDIDATES = ("gpt-4", "gpt-4o-mini")
VIDEO_NEGATIVE_PROMPT = (
    "low quality, blur, watermark, text, distorted anatomy, artifacts"
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


def _extract_json_error(payload) -> str:
    if isinstance(payload, dict):
        for key in ("response", "message", "error", "detail"):
            value = payload.get(key)
            if value:
                return str(value)
    return "Unknown upstream error."


def _write_temp_image(image_bytes: bytes, mime_type: str) -> str:
    suffix = ".png" if "png" in mime_type.lower() else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(image_bytes)
        return handle.name


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
        if eta is not None and float(eta) > (remaining + 5):
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
        "camera_fixed": False,
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
        "prompt_optimizer": True,
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
        "negative_prompt": VIDEO_NEGATIVE_PROMPT,
    }
    return _run_replicate_prediction(
        REPLICATE_KLING_MODEL,
        input_payload,
        timeout_seconds,
    )


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

            if estimated_wait and estimated_wait > max(45, remaining + 5):
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
            asyncio.to_thread(
                provider.runner,
                prompt,
                reference_image_path if provider.supports_reference else None,
                provider.timeout_seconds,
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
                    return await _chat_request(client, prompt, model, system_prompt)
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


async def generate_image(prompt: str) -> bytes:
    params = {
        "prompt": prompt,
        "image": 1,
        "dimensions": "1:1",
        "safety": "false",
        "steps": 4,
    }
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        headers=HTTP_HEADERS,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.get(IMAGE_GEN_URL, params=params)
        payload = response.json()
        images = payload.get("images") or []
        if response.status_code != 200 or not images:
            raise FreeAIError("Image generation service did not return an image.")

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
            reference_image_path = _write_temp_image(image_bytes, mime_type)
            used_reference_image = True

        provider_batches: list[list[VideoProvider]] = []

        if REPLICATE_TOKEN_POOL:
            replicate_batch = [
                [
                    VideoProvider(
                        "Replicate / Seedance 1 Lite",
                        150,
                        True,
                        False,
                        _run_replicate_seedance_video,
                    ),
                ],
                [
                    VideoProvider(
                        "Replicate / MiniMax Video-01",
                        150,
                        True,
                        False,
                        _run_replicate_minimax_video,
                    ),
                ],
            ]
            if reference_image_path:
                replicate_batch.append(
                    [
                        VideoProvider(
                            "Replicate / Kling v2.1",
                            150,
                            True,
                            True,
                            _run_replicate_kling_video,
                        )
                    ]
                )
            provider_batches.extend(replicate_batch)

        if not REPLICATE_TOKEN_POOL or _is_enabled(GENVID_USE_PUBLIC_FALLBACKS):
            provider_batches.extend(
                [
                    [
                        VideoProvider(
                            "hysts / zeroscope-v2",
                            25,
                            False,
                            False,
                            _run_hysts_zeroscope_video,
                        ),
                        VideoProvider(
                            "Alava01 / Wan Demo",
                            30,
                            False,
                            False,
                            _run_alava_wan_demo,
                        ),
                        VideoProvider(
                            "OpenKing / Wan2 Video",
                            35,
                            True,
                            False,
                            _run_openking_video,
                        ),
                        VideoProvider(
                            "Smikke / Wan2 Video",
                            35,
                            True,
                            False,
                            _run_smikke_video,
                        ),
                        VideoProvider(
                            "Mrfalco / Wan2 Video",
                            35,
                            True,
                            False,
                            _run_mrfalco_video,
                        ),
                        VideoProvider(
                            "ChanPoin / Wan2 Video",
                            35,
                            True,
                            False,
                            _run_chanpoin_video,
                        ),
                        VideoProvider(
                            "Keen007 / Wan2 Video",
                            35,
                            True,
                            False,
                            _run_keen007_video,
                        ),
                    ],
                    [
                        VideoProvider(
                            "Wan-AI / Wan2.1",
                            20,
                            False,
                            False,
                            _run_wan_async_video,
                        ),
                    ],
                ]
            )

            if reference_image_path:
                provider_batches.append(
                    [
                        VideoProvider(
                            "Multimodalart / Wan2.1 Fast",
                            45,
                            True,
                            True,
                            _run_multimodalart_video,
                        )
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

        details = "\n".join(failures[:8])
        if REPLICATE_TOKEN_POOL:
            headline = "Configured video providers are temporarily unavailable."
        else:
            headline = (
                "Public no-key video providers are temporarily unavailable.\n"
                "Tip: set REPLICATE_API_TOKEN or REPLICATE_API_TOKENS for reliable /genvid output."
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

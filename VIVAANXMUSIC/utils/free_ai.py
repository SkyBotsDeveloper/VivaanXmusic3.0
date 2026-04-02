from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import os
import re
import tempfile
import time
from dataclasses import dataclass

import httpx
from gradio_client import Client as GradioClient, handle_file


HTTP_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
HTTP_HEADERS = {"User-Agent": "VivaanX/FreeAI/1.0"}
CHAT_API_URL = "https://api-xqwa.onrender.com/chat/"
IMAGE_GEN_URL = "https://death-image.ashlynn.workers.dev/generate"
IMAGE_ENHANCE_URL = "https://arimagex.netlify.app/api/enhance"
IMAGE_REMOVEBG_URL = "https://arimagex.netlify.app/api/removebg"
CHAT_MODEL_CANDIDATES = ("gpt-4", "gpt-4o-mini")
VISION_SYSTEM_PROMPT = (
    "You answer questions about an image using only the provided visual description. "
    "If the description is not enough to answer confidently, say so briefly. "
    "Do not invent details."
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
PROMO_URL_PATTERN = re.compile(
    r"https?://(?:t\.me|op\.wtf|ar-hosting\.pages\.dev)\S*",
    re.IGNORECASE,
)
TRY_AGAIN_PATTERN = re.compile(
    r"try again in (\d+):(\d+):(\d+)",
    re.IGNORECASE,
)
PROVIDER_COOLDOWNS: dict[str, float] = {}


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
    client = GradioClient(space_id, verbose=False)
    result = _run_gradio_job(
        client,
        timeout_seconds,
        prompt,
        api_name="/predict",
    )
    video_path = _extract_video_path(result)
    if not video_path:
        raise FreeAIError(f"{space_id} returned no video.")
    return video_path


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
    client = GradioClient("hysts/zeroscope-v2", verbose=False)
    result = _run_gradio_job(
        client,
        timeout_seconds,
        prompt,
        0,
        24,
        10,
        api_name="/run",
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
    client = GradioClient("multimodalart/wan2-1-fast", verbose=False)
    result = _run_gradio_job(
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
    client = GradioClient(space_id, verbose=False)
    image = handle_file(reference_image_path) if reference_image_path else None
    result = _run_gradio_job(
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
    client = GradioClient("Wan-AI/Wan2.1", verbose=False)
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


def _caption_with_florence(image_path: str) -> tuple[str, str]:
    client = GradioClient("prithivMLmods/Florence-2-Image-Caption")
    result = client.predict(
        uploaded_image=handle_file(image_path),
        model_choice="Florence-2-base",
        api_name="/describe_image",
    )
    return "Florence-2-base", str(result or "").strip()


def _caption_with_blip(image_path: str) -> tuple[str, str]:
    client = GradioClient("hysts/image-captioning-with-blip")
    result = client.predict(
        image=handle_file(image_path),
        text="A picture of",
        api_name="/caption",
    )
    return "BLIP", str(result or "").strip()


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
    image_path = _write_temp_image(image_bytes, mime_type)
    try:
        vision_model, caption = await _caption_image(image_path)
    finally:
        try:
            import os

            os.remove(image_path)
        except Exception:
            pass

    user_prompt = (prompt or "").strip() or "Describe this image."
    if user_prompt.lower() in {"describe this image", "describe this image."}:
        return ChatResult(model=vision_model, content=caption)

    answer = await generate_chat_response(
        (
            f"Visual description:\n{caption}\n\n"
            f"User question:\n{user_prompt}"
        ),
        alias="geminivision",
        system_prompt=VISION_SYSTEM_PROMPT,
    )
    return ChatResult(
        model=f"{vision_model} + {answer.model}",
        content=answer.content,
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

        provider_batches = [
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
        raise FreeAIError(
            "Public no-key video providers are temporarily unavailable.\n"
            f"{details}"
        )
    finally:
        _remove_file(reference_image_path)


def vision_unavailable_message() -> str:
    return (
        "Vision command abhi free provider stack me available nahi hai. "
        "Chat, image generation, enhance, aur remove-bg commands wire ho rahe hain, "
        "lekin direct image analysis ke liye koi stable no-key endpoint docs me nahi mila."
    )

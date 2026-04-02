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
    try:
        return job.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        try:
            job.cancel()
        except Exception:
            pass
        raise FreeAIError("Provider timed out.") from exc


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


def _run_openking_video(
    prompt: str,
    reference_image_path: str | None,
    timeout_seconds: int,
) -> str:
    client = GradioClient("OpenKing/wan2-video-generation", verbose=False)
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
    raise FreeAIError(status_text or "OpenKing provider returned no video.")


def _run_wan_async_video(prompt: str) -> str:
    client = GradioClient("Wan-AI/Wan2.1", verbose=False)
    client.predict(prompt, "960*960", True, -1, api_name="/t2v_generation_async")

    for _ in range(12):
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

        if estimated_wait and estimated_wait > 240:
            raise FreeAIError(f"Wan queue is too long ({int(estimated_wait)}s).")
        time.sleep(8)

    raise FreeAIError("Wan provider timed out.")


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
        else:
            try:
                reference_image_path = _write_temp_image(
                    await generate_image(text_prompt),
                    "image/png",
                )
                used_reference_image = True
            except Exception as exc:
                failures.append(f"Reference image: {exc}")

        providers = [
            ("Multimodalart / Wan2.1 Fast", 180, True, _run_multimodalart_video),
            ("OpenKing / Wan2 Video", 210, False, _run_openking_video),
            ("Wan-AI / Wan2.1", 120, False, _run_wan_async_video),
        ]

        for provider_name, timeout_seconds, needs_reference, runner in providers:
            if needs_reference and not reference_image_path:
                failures.append(f"{provider_name}: no reference image available")
                continue

            if progress_callback:
                await progress_callback(provider_name)

            try:
                if runner is _run_wan_async_video:
                    output_path = await asyncio.to_thread(runner, text_prompt)
                else:
                    output_path = await asyncio.to_thread(
                        runner,
                        text_prompt,
                        reference_image_path,
                        timeout_seconds,
                    )
                local_path = await _ensure_local_video(output_path)
                return VideoResult(
                    provider=provider_name,
                    file_path=local_path,
                    used_reference_image=used_reference_image,
                )
            except Exception as exc:
                failures.append(f"{provider_name}: {exc}")

        details = "\n".join(failures[:5])
        raise FreeAIError(
            "Video generation service is temporarily unavailable.\n"
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

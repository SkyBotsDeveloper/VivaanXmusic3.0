from __future__ import annotations

import base64
import re
from dataclasses import dataclass

import httpx


HTTP_TIMEOUT = httpx.Timeout(45.0, connect=10.0)
HTTP_HEADERS = {"User-Agent": "VivaanX/FreeAI/1.0"}
CHAT_API_URL = "https://api-xqwa.onrender.com/chat/"
IMAGE_GEN_URL = "https://death-image.ashlynn.workers.dev/generate"
IMAGE_ENHANCE_URL = "https://arimagex.netlify.app/api/enhance"
IMAGE_REMOVEBG_URL = "https://arimagex.netlify.app/api/removebg"
CHAT_MODEL_CANDIDATES = ("gpt-4", "gpt-4o-mini")
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


def vision_unavailable_message() -> str:
    return (
        "Vision command abhi free provider stack me available nahi hai. "
        "Chat, image generation, enhance, aur remove-bg commands wire ho rahe hain, "
        "lekin direct image analysis ke liye koi stable no-key endpoint docs me nahi mila."
    )

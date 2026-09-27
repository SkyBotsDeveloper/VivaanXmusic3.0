import asyncio
import io
import time
import wave
from collections.abc import Iterable

import httpx


GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def parse_api_keys(*values: str | None) -> tuple[str, ...]:
    """Parse, trim, and deduplicate individual or comma-separated API keys."""
    result = []
    seen = set()
    for value in values:
        for key in str(value or "").split(","):
            key = key.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(key)
    return tuple(result)


def pcm_to_wav(
    raw_audio: bytes,
    *,
    sample_rate: int,
    sample_width: int,
    channels: int = 1,
) -> bytes:
    """Wrap raw PCM in a WAV container suitable for transcription APIs."""
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(raw_audio)
    return output.getvalue()


def transcript_from_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    text = str(payload.get("text") or "").strip()
    return text or None


async def transcribe_groq(
    raw_audio: bytes,
    *,
    api_key: str,
    model: str,
    sample_rate: int,
    sample_width: int,
    timeout_seconds: float,
) -> str | None:
    """Transcribe a short multilingual PCM clip with Groq Whisper."""
    if not api_key:
        return None

    wav_audio = pcm_to_wav(
        raw_audio,
        sample_rate=sample_rate,
        sample_width=sample_width,
    )
    timeout = httpx.Timeout(timeout_seconds, connect=min(8.0, timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            GROQ_TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": model,
                "response_format": "json",
                "temperature": "0",
            },
            files={"file": ("voice-request.wav", wav_audio, "audio/wav")},
        )
        response.raise_for_status()
        return transcript_from_payload(response.json())


class GroqKeyPool:
    """Round-robin Groq keys with bounded failover and per-key cooldowns."""

    def __init__(
        self,
        api_keys: Iterable[str],
        *,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self.api_keys = parse_api_keys(*api_keys)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._cursor = 0
        self._cooldowns: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.api_keys)

    async def _available_keys(self) -> list[str]:
        if not self.api_keys:
            return []
        async with self._lock:
            now = time.monotonic()
            start = self._cursor % len(self.api_keys)
            self._cursor = (start + 1) % len(self.api_keys)
            ordered = self.api_keys[start:] + self.api_keys[:start]
            return [key for key in ordered if self._cooldowns.get(key, 0.0) <= now]

    async def _cooldown(self, api_key: str, seconds: float) -> None:
        async with self._lock:
            self._cooldowns[api_key] = max(
                self._cooldowns.get(api_key, 0.0),
                time.monotonic() + max(1.0, seconds),
            )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        try:
            return min(300.0, max(5.0, float(response.headers.get("Retry-After", 30))))
        except (TypeError, ValueError):
            return 30.0

    async def transcribe(
        self,
        raw_audio: bytes,
        *,
        sample_rate: int,
        sample_width: int,
    ) -> str | None:
        for api_key in await self._available_keys():
            try:
                transcript = await transcribe_groq(
                    raw_audio,
                    api_key=api_key,
                    model=self.model,
                    sample_rate=sample_rate,
                    sample_width=sample_width,
                    timeout_seconds=self.timeout_seconds,
                )
                if transcript:
                    return transcript
            except httpx.HTTPStatusError as err:
                status = err.response.status_code
                if status == 429:
                    await self._cooldown(api_key, self._retry_after(err.response))
                    continue
                if status in {401, 403}:
                    await self._cooldown(api_key, 3600)
                    continue
                if status in {408, 425} or status >= 500:
                    await self._cooldown(api_key, 15)
                    continue
                raise
            except (httpx.TimeoutException, httpx.TransportError):
                await self._cooldown(api_key, 10)
                continue
        return None

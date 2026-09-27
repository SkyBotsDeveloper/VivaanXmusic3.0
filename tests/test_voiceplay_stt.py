import importlib.util
import io
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "VIVAANXMUSIC" / "utils" / "voiceplay_stt.py"
)
SPEC = importlib.util.spec_from_file_location("voiceplay_stt", MODULE_PATH)
voiceplay_stt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voiceplay_stt)


class VoicePlaySttTest(unittest.TestCase):
    def test_parse_api_keys_supports_primary_backup_and_pool(self):
        self.assertEqual(
            voiceplay_stt.parse_api_keys(
                "key-1",
                " key-2 ",
                "key-2,key-3",
            ),
            ("key-1", "key-2", "key-3"),
        )

    def test_pcm_to_wav_preserves_audio_format(self):
        pcm = (b"\x01\x00\x02\x00") * 100
        encoded = voiceplay_stt.pcm_to_wav(
            pcm,
            sample_rate=16_000,
            sample_width=2,
        )
        with wave.open(io.BytesIO(encoded), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16_000)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm)

    def test_transcript_from_payload(self):
        self.assertEqual(
            voiceplay_stt.transcript_from_payload({"text": "  Baila Lento  "}),
            "Baila Lento",
        )

    def test_transcript_from_invalid_payload(self):
        self.assertIsNone(voiceplay_stt.transcript_from_payload({"text": "  "}))
        self.assertIsNone(voiceplay_stt.transcript_from_payload([]))


class VoicePlaySttHttpTest(unittest.IsolatedAsyncioTestCase):
    async def test_groq_request_uses_multilingual_transcription_endpoint(self):
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"text": "Baila Lento"}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def post(self, url, **kwargs):
                calls.append((url, kwargs))
                return FakeResponse()

        with patch.object(
            voiceplay_stt.httpx,
            "AsyncClient",
            return_value=FakeClient(),
        ):
            transcript = await voiceplay_stt.transcribe_groq(
                b"\x01\x00" * 100,
                api_key="secret",
                model="whisper-large-v3-turbo",
                sample_rate=16_000,
                sample_width=2,
                timeout_seconds=15,
            )

        self.assertEqual(transcript, "Baila Lento")
        self.assertEqual(calls[0][0], voiceplay_stt.GROQ_TRANSCRIPTION_URL)
        self.assertEqual(
            calls[0][1]["data"]["model"],
            "whisper-large-v3-turbo",
        )
        self.assertIn("file", calls[0][1]["files"])
        self.assertEqual(
            calls[0][1]["headers"]["Authorization"],
            "Bearer secret",
        )

    async def test_key_pool_fails_over_after_rate_limit(self):
        request = httpx.Request("POST", voiceplay_stt.GROQ_TRANSCRIPTION_URL)
        response = httpx.Response(429, request=request, headers={"Retry-After": "60"})
        rate_limit = httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=response,
        )
        transcribe = AsyncMock(side_effect=[rate_limit, "Baila Lento"])
        pool = voiceplay_stt.GroqKeyPool(
            ["key-1", "key-2"],
            model="whisper-large-v3-turbo",
            timeout_seconds=15,
        )

        with patch.object(voiceplay_stt, "transcribe_groq", transcribe):
            result = await pool.transcribe(
                b"\x01\x00" * 100,
                sample_rate=16_000,
                sample_width=2,
            )

        self.assertEqual(result, "Baila Lento")
        self.assertEqual(transcribe.await_count, 2)
        self.assertEqual(transcribe.await_args_list[0].kwargs["api_key"], "key-1")
        self.assertEqual(transcribe.await_args_list[1].kwargs["api_key"], "key-2")


if __name__ == "__main__":
    unittest.main()

import asyncio
import audioop
import html
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import uuid4

import edge_tts
import speech_recognition as sr
from pytgcalls.types import RecordStream
from pytgcalls.types.raw import AudioParameters

import config
from strings import get_string
from VIVAANXMUSIC import LOGGER, YouTube, app
from VIVAANXMUSIC.utils.database import (
    get_lang,
    get_voiceplay,
    group_assistant,
    is_active_chat,
    set_voiceplay,
)
from VIVAANXMUSIC.utils.formatters import time_to_seconds
from VIVAANXMUSIC.utils.voiceplay_text import song_query_candidates


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
LISTEN_SECONDS = max(4, _env_int("VOICEPLAY_LISTEN_SECONDS", 8))
SILENCE_SECONDS = max(0.6, _env_float("VOICEPLAY_SILENCE_SECONDS", 1.2))
MIN_VOICE_SECONDS = max(0.2, _env_float("VOICEPLAY_MIN_VOICE_SECONDS", 0.45))
VAD_THRESHOLD = max(50, _env_int("VOICEPLAY_VAD_THRESHOLD", 280))
MAX_ATTEMPTS = 3
MAX_BUFFER_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * (LISTEN_SECONDS + 2)
MAX_TRANSCRIPTIONS = max(1, _env_int("VOICEPLAY_MAX_TRANSCRIPTIONS", 4))
STT_TIMEOUT = max(8, _env_int("VOICEPLAY_STT_TIMEOUT", 15))

VOICE_NAMES = {
    "hi": os.getenv("VOICEPLAY_HINDI_VOICE", "hi-IN-SwaraNeural"),
    "en": os.getenv("VOICEPLAY_ENGLISH_VOICE", "en-IN-NeerjaNeural"),
}

PROMPTS = {
    "hi": {
        "ask": "Aap agla kaunsa gaana sunna chahte hain? Boliye.",
        "retry": "Sorry, mujhe clearly sunai nahi diya. Please dobara boliye.",
        "leave": "Sorry, main teen baar mein request samajh nahi paayi. Main voice chat se ja rahi hoon.",
    },
    "en": {
        "ask": "What would you like to listen to next? Please say the song name.",
        "retry": "Sorry, I did not hear that clearly. Please try again.",
        "leave": "Sorry, I could not understand the request after three tries. I am leaving the voice chat.",
    },
}


@dataclass
class ListeningSession:
    chat_id: int
    original_chat_id: int
    language: str
    token: str = field(default_factory=lambda: uuid4().hex)
    attempt: int = 1
    accepting: bool = False
    buffers: dict[int, bytearray] = field(default_factory=dict)
    voiced_seconds: dict[int, float] = field(default_factory=dict)
    source_users: dict[int, int] = field(default_factory=dict)
    voiced_sources: set[int] = field(default_factory=set)
    collision: bool = False
    listen_started: float = 0.0
    last_voice_at: float = 0.0
    watchdog: Optional[asyncio.Task] = None

    def reset_audio(self) -> None:
        self.accepting = False
        self.buffers.clear()
        self.voiced_seconds.clear()
        self.voiced_sources.clear()
        self.collision = False
        self.listen_started = 0.0
        self.last_voice_at = 0.0


class VoicePlayManager:
    def __init__(self) -> None:
        self._sessions: dict[int, ListeningSession] = {}
        self._start_tasks: dict[int, asyncio.Task] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._tts_locks: dict[str, asyncio.Lock] = {}
        self._tts_cache: dict[str, tuple[str, float]] = {}
        self._transcription_slots = asyncio.Semaphore(MAX_TRANSCRIPTIONS)
        self._tmp_dir = Path(tempfile.gettempdir()) / "vivaan_voiceplay"
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    def _lock(self, chat_id: int) -> asyncio.Lock:
        lock = self._locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chat_id] = lock
        return lock

    def schedule_track_started(self, chat_id: int, original_chat_id: int) -> None:
        existing = self._start_tasks.get(chat_id)
        if existing and not existing.done():
            return

        async def runner() -> None:
            try:
                await self.start_listening(chat_id, original_chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                LOGGER(__name__).warning(
                    "Voice Play round failed to start | chat_id=%s | reason=%s",
                    chat_id,
                    err,
                )
            finally:
                current = asyncio.current_task()
                if self._start_tasks.get(chat_id) is current:
                    self._start_tasks.pop(chat_id, None)

        self._start_tasks[chat_id] = asyncio.create_task(runner())

    async def start_listening(self, chat_id: int, original_chat_id: int) -> bool:
        async with self._lock(chat_id):
            setting = await get_voiceplay(chat_id)
            if not setting["enabled"] or not await is_active_chat(chat_id):
                return False
            if chat_id in self._sessions:
                return False

            language = setting["language"] if setting["language"] in PROMPTS else "en"
            assistant = await self._assistant(chat_id)
            source_users = {}
            try:
                participants = await assistant.get_participants(chat_id)
                source_users = {
                    int(participant.source): int(participant.user_id)
                    for participant in participants or []
                    if getattr(participant, "source", None)
                    and getattr(participant, "user_id", None)
                }
            except Exception:
                pass

            session = ListeningSession(
                chat_id=chat_id,
                original_chat_id=original_chat_id,
                language=language,
                source_users=source_users,
            )
            self._sessions[chat_id] = session

        try:
            await self._prepare_attempt(session, "ask")
            return True
        except Exception as err:
            await self._capture_unavailable(session, err)
            return False

    async def stop_session(self, chat_id: int) -> None:
        start_task = self._start_tasks.pop(chat_id, None)
        current = asyncio.current_task()
        if start_task and start_task is not current and not start_task.done():
            start_task.cancel()

        session = self._sessions.pop(chat_id, None)
        if session and session.watchdog and session.watchdog is not current:
            session.watchdog.cancel()
        if start_task or session:
            await self._stop_capture(chat_id)

    async def _stop_capture(self, chat_id: int) -> None:
        try:
            from VIVAANXMUSIC.core.call import JARVIS

            JARVIS.suppress_stream_end(chat_id)
            assistant = await self._assistant(chat_id)
            await assistant.record(chat_id, None)
        except Exception:
            pass

    async def _capture_unavailable(
        self,
        session: ListeningSession,
        error: Exception,
    ) -> None:
        self._sessions.pop(session.chat_id, None)
        await self._stop_capture(session.chat_id)
        await set_voiceplay(session.chat_id, False, session.language)
        LOGGER(__name__).error(
            "Voice Play capture unavailable | chat_id=%s | reason=%s",
            session.chat_id,
            error,
        )
        try:
            await app.send_message(
                session.original_chat_id,
                "❌ Voice Play could not access the live VC audio and was disabled. "
                "Normal music playback is still active.",
            )
        except Exception:
            pass

    async def handle_stream_frames(self, update) -> None:
        session = self._sessions.get(int(update.chat_id))
        if not session or not session.accepting:
            return

        now = time.monotonic()
        for item in update.frames or []:
            data = item.frame
            source = int(item.ssrc)
            if not data:
                continue

            try:
                level = audioop.rms(data, SAMPLE_WIDTH)
            except Exception:
                continue
            voiced = level >= VAD_THRESHOLD

            if voiced:
                session.voiced_sources.add(source)
                if len(session.voiced_sources) > 1:
                    session.collision = True
                session.last_voice_at = now
                session.voiced_seconds[source] = session.voiced_seconds.get(
                    source, 0.0
                ) + (len(data) / (SAMPLE_RATE * SAMPLE_WIDTH))

            if voiced or source in session.buffers:
                buffer = session.buffers.setdefault(source, bytearray())
                remaining = MAX_BUFFER_BYTES - len(buffer)
                if remaining > 0:
                    buffer.extend(data[:remaining])

    async def _assistant(self, chat_id: int):
        from VIVAANXMUSIC.core.call import JARVIS

        return await group_assistant(JARVIS, chat_id)

    async def _prepare_attempt(self, session: ListeningSession, prompt: str) -> None:
        if self._sessions.get(session.chat_id) is not session:
            return
        session.reset_audio()

        assistant = await self._assistant(session.chat_id)
        await assistant.record(
            session.chat_id,
            RecordStream(
                True,
                AudioParameters(bitrate=SAMPLE_RATE, channels=1),
            ),
        )

        await self._speak(session, prompt, restore=prompt != "leave")
        if self._sessions.get(session.chat_id) is not session or prompt == "leave":
            return

        session.reset_audio()
        session.accepting = True
        session.listen_started = time.monotonic()
        session.watchdog = asyncio.create_task(self._watch(session))

    async def _watch(self, session: ListeningSession) -> None:
        try:
            while self._sessions.get(session.chat_id) is session and session.accepting:
                await asyncio.sleep(0.2)
                now = time.monotonic()
                elapsed = now - session.listen_started

                enough_voice = any(
                    seconds >= MIN_VOICE_SECONDS
                    for seconds in session.voiced_seconds.values()
                )
                silence_done = (
                    enough_voice
                    and session.last_voice_at > 0
                    and now - session.last_voice_at >= SILENCE_SECONDS
                )
                if (
                    session.collision
                    and session.last_voice_at > 0
                    and (now - session.last_voice_at >= 0.5)
                ):
                    await self._finish_attempt(session)
                    return
                if silence_done or elapsed >= LISTEN_SECONDS:
                    await self._finish_attempt(session)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as err:
            LOGGER(__name__).warning(
                "Voice Play listener failed | chat_id=%s | reason=%s",
                session.chat_id,
                err,
            )
            await self._failed_attempt(session)

    async def _finish_attempt(self, session: ListeningSession) -> None:
        if self._sessions.get(session.chat_id) is not session:
            return
        session.accepting = False
        await self._stop_capture(session.chat_id)

        valid_sources = [
            source
            for source, seconds in session.voiced_seconds.items()
            if seconds >= MIN_VOICE_SECONDS
        ]
        if session.collision or len(valid_sources) != 1:
            await self._failed_attempt(session)
            return

        source = valid_sources[0]
        audio_bytes = bytes(session.buffers.get(source) or b"")
        transcript = await self._transcribe(audio_bytes, session.language)
        if not transcript:
            await self._failed_attempt(session)
            return

        candidates = song_query_candidates(transcript)
        if not candidates:
            await self._failed_attempt(session)
            return

        user_id = session.source_users.get(source, 0)
        success = await self._queue_song(session, candidates, transcript, user_id)
        if success:
            self._sessions.pop(session.chat_id, None)
            return
        await self._failed_attempt(session)

    async def _transcribe(self, raw_audio: bytes, language: str) -> Optional[str]:
        if len(raw_audio) < SAMPLE_RATE * SAMPLE_WIDTH // 5:
            return None

        locale = "hi-IN" if language == "hi" else "en-IN"
        recognizer = sr.Recognizer()
        recognizer.operation_timeout = STT_TIMEOUT
        audio = sr.AudioData(raw_audio, SAMPLE_RATE, SAMPLE_WIDTH)

        def recognize():
            return recognizer.recognize_google(audio, language=locale, show_all=True)

        acquired = False
        try:
            await asyncio.wait_for(
                self._transcription_slots.acquire(),
                timeout=STT_TIMEOUT,
            )
            acquired = True
            result = await asyncio.wait_for(
                asyncio.to_thread(recognize),
                timeout=STT_TIMEOUT,
            )
        except Exception as err:
            LOGGER(__name__).info("Voice Play transcription failed: %s", err)
            return None
        finally:
            if acquired:
                self._transcription_slots.release()

        if isinstance(result, str):
            return result.strip() or None
        alternatives = (
            (result or {}).get("alternative", []) if isinstance(result, dict) else []
        )
        if not alternatives:
            return None
        best = alternatives[0]
        confidence = best.get("confidence")
        if confidence is not None and float(confidence) < 0.35:
            return None
        return str(best.get("transcript") or "").strip() or None

    async def _queue_song(
        self,
        session: ListeningSession,
        candidates: list[str],
        transcript: str,
        user_id: int,
    ) -> bool:
        details = None
        selected_query = None
        for query in candidates:
            try:
                result, _ = await YouTube.track(query)
                if result and result.get("vidid"):
                    details = result
                    selected_query = query
                    break
            except Exception:
                continue
        if not details:
            return False

        duration = details.get("duration_min")
        if not duration:
            return False
        duration_seconds = time_to_seconds(duration)
        if duration_seconds and duration_seconds > config.DURATION_LIMIT:
            await app.send_message(
                session.original_chat_id,
                "Voice request found "
                f"<b>{html.escape(str(details.get('title', selected_query)))}</b>, "
                "but it exceeds the duration limit.",
            )
            self._sessions.pop(session.chat_id, None)
            return True

        user_name = "Voice Request"
        if user_id:
            try:
                user = await app.get_users(user_id)
                user_name = user.first_name or user_name
            except Exception:
                pass

        status = await app.send_message(
            session.original_chat_id,
            f"🎙️ Heard: <b>{html.escape(transcript)}</b>\n"
            f"🔎 Playing: <b>{html.escape(str(details['title']))}</b>",
        )
        try:
            from VIVAANXMUSIC.utils.stream.stream import stream

            strings = get_string(await get_lang(session.chat_id))
            await stream(
                strings,
                status,
                user_id,
                details,
                session.chat_id,
                user_name,
                session.original_chat_id,
                video=False,
                streamtype="youtube",
                forceplay=False,
            )
        except Exception as err:
            LOGGER(__name__).warning(
                "Voice Play queue failed | chat_id=%s | query=%s | reason=%s",
                session.chat_id,
                selected_query,
                err,
            )
            try:
                await status.edit_text(f"❌ Could not queue that song: {err}")
            except Exception:
                pass
            # The speech was understood; an operational playback failure must
            # not consume a listening attempt or force the assistant to leave.
            self._sessions.pop(session.chat_id, None)
            return True
        try:
            await status.delete()
        except Exception:
            pass
        return True

    async def _failed_attempt(self, session: ListeningSession) -> None:
        if self._sessions.get(session.chat_id) is not session:
            return

        if session.attempt >= MAX_ATTEMPTS:
            self._sessions.pop(session.chat_id, None)
            await set_voiceplay(session.chat_id, False, session.language)
            await self._prepare_terminal_prompt(session)
            try:
                await app.send_message(
                    session.original_chat_id,
                    "Voice Play was disabled after 3 unsuccessful attempts. The assistant left the voice chat.",
                )
            except Exception:
                pass
            from VIVAANXMUSIC.core.call import JARVIS

            await JARVIS.stop_stream(session.chat_id)
            return

        session.attempt += 1
        try:
            await self._prepare_attempt(session, "retry")
        except Exception as err:
            await self._capture_unavailable(session, err)

    async def _prepare_terminal_prompt(self, session: ListeningSession) -> None:
        await self._stop_capture(session.chat_id)
        await self._speak(session, "leave", restore=False)

    async def _speak(
        self, session: ListeningSession, prompt: str, restore: bool
    ) -> bool:
        text = PROMPTS[session.language][prompt]
        try:
            path, duration = await self._prompt_audio(session.language, prompt)
            from VIVAANXMUSIC.core.call import JARVIS

            spoken = await JARVIS.play_voice_prompt(
                session.chat_id,
                path,
                duration,
                restore=restore,
            )
            if spoken:
                return True
        except Exception as err:
            LOGGER(__name__).warning(
                "Voice Play prompt failed | chat_id=%s | reason=%s",
                session.chat_id,
                err,
            )
        try:
            await app.send_message(session.original_chat_id, f"🎙️ {text}")
        except Exception:
            pass
        return False

    async def _prompt_audio(self, language: str, prompt: str) -> tuple[str, float]:
        key = f"{language}:{prompt}"
        cached = self._tts_cache.get(key)
        if cached and os.path.exists(cached[0]):
            return cached

        lock = self._tts_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._tts_cache.get(key)
            if cached and os.path.exists(cached[0]):
                return cached

            path = self._tmp_dir / f"{language}_{prompt}.mp3"
            communicator = edge_tts.Communicate(
                PROMPTS[language][prompt],
                VOICE_NAMES[language],
            )
            await asyncio.wait_for(communicator.save(str(path)), timeout=30)
            duration = await self._media_duration(str(path))
            result = (str(path), max(1.0, duration))
            self._tts_cache[key] = result
            return result

    @staticmethod
    async def _media_duration(path: str) -> float:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        try:
            return float(stdout.decode().strip())
        except (TypeError, ValueError):
            return 2.5


voiceplay_manager = VoicePlayManager()

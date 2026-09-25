import asyncio

from pyrogram import Client

import config

from ..logging import LOGGER

assistants = []
assistantids = []

ASSISTANT_START_TIMEOUT = 60
ASSISTANT_STEP_TIMEOUT = 15

GROUPS_TO_JOIN = [
    "aboutvivaan",
    "VivaanSupport",
    "VivaanUpdates",
    "AboutSidXD",
    "VivaanNetwork",
]


async def _run_with_timeout(awaitable, timeout: int, label: str):
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{label} timed out after {timeout}s") from None


def _has_session(value) -> bool:
    session = str(value or "").strip()
    return bool(session and session.lower() not in {"none", "null"})


# Initialize userbots
class Userbot:
    def __init__(self):
        self.one = Client(
            "VivaanAssis1",
            config.API_ID,
            config.API_HASH,
            session_string=str(config.STRING1),
            no_updates=True,
        )
        self.two = Client(
            "VivaanAssis2",
            config.API_ID,
            config.API_HASH,
            session_string=str(config.STRING2),
            no_updates=True,
        )
        self.three = Client(
            "VivaanAssis3",
            config.API_ID,
            config.API_HASH,
            session_string=str(config.STRING3),
            no_updates=True,
        )
        self.four = Client(
            "VivaanAssis4",
            config.API_ID,
            config.API_HASH,
            session_string=str(config.STRING4),
            no_updates=True,
        )
        self.five = Client(
            "VivaanAssis5",
            config.API_ID,
            config.API_HASH,
            session_string=str(config.STRING5),
            no_updates=True,
        )

    async def start_assistant(self, client: Client, index: int):
        string_attr = [
            config.STRING1,
            config.STRING2,
            config.STRING3,
            config.STRING4,
            config.STRING5,
        ][index - 1]
        if not _has_session(string_attr):
            return False

        try:
            LOGGER(__name__).info(f"Starting Assistant {index}...")
            await _run_with_timeout(
                client.start(),
                ASSISTANT_START_TIMEOUT,
                f"Assistant {index} client.start()",
            )

            me = await _run_with_timeout(
                client.get_me(),
                ASSISTANT_STEP_TIMEOUT,
                f"Assistant {index} get_me()",
            )
            client.id, client.name, client.username = me.id, me.first_name, me.username

            if index not in assistants:
                assistants.append(index)
            if me.id not in assistantids:
                assistantids.append(me.id)

            LOGGER(__name__).info(f"Assistant {index} authenticated as {client.name}")

            for group in GROUPS_TO_JOIN:
                try:
                    await _run_with_timeout(
                        client.join_chat(group),
                        ASSISTANT_STEP_TIMEOUT,
                        f"Assistant {index} join_chat({group})",
                    )
                except Exception as e:
                    LOGGER(__name__).warning(
                        f"Assistant {index} could not join @{group}: {e}"
                    )

            try:
                await _run_with_timeout(
                    client.send_message(
                        config.LOGGER_ID, f"Vivaan's Assistant {index} Started"
                    ),
                    ASSISTANT_STEP_TIMEOUT,
                    f"Assistant {index} log message",
                )
            except Exception as e:
                LOGGER(__name__).warning(
                    f"Assistant {index} can't send log group startup message: {e}"
                )

            LOGGER(__name__).info(f"Assistant {index} Started as {client.name}")
            return True

        except Exception as e:
            LOGGER(__name__).error(f"Failed to start Assistant {index}: {e}")
            try:
                await _run_with_timeout(
                    client.stop(),
                    ASSISTANT_STEP_TIMEOUT,
                    f"Assistant {index} stop after failed start",
                )
            except Exception:
                pass
            return False

    async def start(self):
        LOGGER(__name__).info("Starting Vivaan's Assistants...")
        await self.start_assistant(self.one, 1)
        await self.start_assistant(self.two, 2)
        await self.start_assistant(self.three, 3)
        await self.start_assistant(self.four, 4)
        await self.start_assistant(self.five, 5)
        if not assistants:
            LOGGER(__name__).error(
                "No assistants started. Check STRING_SESSION values and assistant logs."
            )
            exit()
        LOGGER(__name__).info(f"Assistants ready: {', '.join(map(str, assistants))}")

    async def stop(self):
        LOGGER(__name__).info("Stopping Assistants...")
        try:
            if config.STRING1:
                await self.one.stop()
            if config.STRING2:
                await self.two.stop()
            if config.STRING3:
                await self.three.stop()
            if config.STRING4:
                await self.four.stop()
            if config.STRING5:
                await self.five.stop()
        except Exception as e:
            LOGGER(__name__).error(f"Error while stopping assistants: {e}")

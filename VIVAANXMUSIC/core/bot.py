import sys
from pyrogram import Client, errors
from pyrogram.enums import ChatMemberStatus

import config
from ..logging import LOGGER
from .bot_start_retry import select_bot_login_dc, start_with_telegram_retry
from .owner_profile import resolve_owner_profile_url
from .anonymous_admin import AnonymousAdminVerification
from .message_cleanup import OutgoingMessageCleanup


class JARVIS(Client):
    def __init__(self):
        self.anonymous_admins = AnonymousAdminVerification(LOGGER(__name__))
        self.message_cleanup = OutgoingMessageCleanup(LOGGER(__name__))
        super().__init__(
            name="VivaanXMusic",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            in_memory=True,
            workers=48,
            max_concurrent_transmissions=7,
        )
        LOGGER(__name__).info("Bot client initialized.")

    async def invoke(self, query, *args, **kwargs):
        result = await super().invoke(query, *args, **kwargs)
        try:
            self.message_cleanup.capture(query, result, getattr(self, "id", None))
        except Exception:
            LOGGER(__name__).exception("Could not record an outgoing message for cleanup")
        return result

    def add_handler(self, handler, group=0):
        return super().add_handler(self.anonymous_admins.wrap(handler), group)

    async def sign_in_bot(self, bot_token):
        if await select_bot_login_dc(self, config.BOT_LOGIN_DC):
            LOGGER(__name__).info("Using Telegram DC %s for fresh bot authorization.", config.BOT_LOGIN_DC)
        return await super().sign_in_bot(bot_token)

    async def start(self):
        await start_with_telegram_retry(super().start, LOGGER(__name__))
        me = await self.get_me()
        self.username, self.id = me.username, me.id
        self.name = f"{me.first_name} {me.last_name or ''}".strip()
        self.mention = me.mention

        try:
            await self.send_message(
                config.LOGGER_ID,
                (
                    f"<u><b>» {self.mention} ʙᴏᴛ sᴛᴀʀᴛᴇᴅ :</b></u>\n\n"
                    f"ɪᴅ : <code>{self.id}</code>\n"
                    f"ɴᴀᴍᴇ : {self.name}\n"
                    f"ᴜsᴇʀɴᴀᴍᴇ : @{self.username}"
                ),
            )
        except (errors.ChannelInvalid, errors.PeerIdInvalid):
            LOGGER(__name__).error("❌ Bot cannot access the log group/channel – add & promote it first!")
            sys.exit()
        except Exception as exc:
            LOGGER(__name__).error(f"❌ Bot has failed to access the log group.\nReason: {type(exc).__name__}")
            sys.exit()

        try:
            member = await self.get_chat_member(config.LOGGER_ID, self.id)
            if member.status != ChatMemberStatus.ADMINISTRATOR:
                LOGGER(__name__).error("❌ Promote the bot as admin in the log group/channel.")
                sys.exit()
        except Exception as e:
            LOGGER(__name__).error(f"❌ Could not check admin status: {e}")
            sys.exit()

        self.owner_profile_url = await resolve_owner_profile_url(self, config.OWNER_ID, LOGGER(__name__))
        LOGGER(__name__).info(f"✅ Music Bot started as {self.name} (@{self.username})")

from pyrogram import filters

from config import BANNED_USERS
from VIVAANXMUSIC import app


@app.on_callback_query(filters.regex(r"^anon_verify ") & ~BANNED_USERS)
async def verify_anonymous_admin(client, query):
    await app.anonymous_admins.verify(client, query)

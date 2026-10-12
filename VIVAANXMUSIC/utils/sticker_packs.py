"""Resolve sticker-pack ownership using the current Telegram session."""

import logging

from pyrogram import raw
from pyrogram.errors import PeerIdInvalid, UsernameInvalid, UsernameNotOccupied
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .rich_buttons import rich_call


class StickerOwnerUnavailable(Exception):
    """Telegram rejected all supported references to the command sender."""


async def get_sticker_bot_username(client) -> str:
    me = await client.get_me()
    if not me.username:
        raise ValueError("the running bot has no username")
    return me.username.lower()


async def create_sticker_set_for_user(client, message, **kwargs):
    if not message.from_user:
        raise ValueError("run this command from your own Telegram account")

    user_id = message.from_user.id
    fallback = raw.types.InputUser(user_id=user_id, access_hash=0)
    owner = fallback
    try:
        peer = await client.resolve_peer(user_id)
    except PeerIdInvalid:
        # A group-only sender may not have a full cached user yet.
        pass
    else:
        if isinstance(peer, raw.types.InputPeerUser) and peer.user_id == user_id:
            owner = raw.types.InputUser(user_id=user_id, access_hash=peer.access_hash or 0)

    tried = set()
    last_error = None

    async def try_owner(reference):
        nonlocal last_error
        key = reference.write()
        if key in tried:
            return False, None
        tried.add(key)
        try:
            return True, await client.invoke(
                raw.functions.stickers.CreateStickerSet(user_id=reference, **kwargs)
            )
        except PeerIdInvalid as error:
            last_error = error
            return False, None

    success, result = await try_owner(owner)
    if success:
        return result

    # Refresh a public user reference only after Telegram rejects the cache.
    if message.from_user.username:
        try:
            resolved = await client.invoke(raw.functions.contacts.ResolveUsername(
                username=message.from_user.username
            ))
        except (PeerIdInvalid, UsernameInvalid, UsernameNotOccupied):
            pass
        else:
            if isinstance(resolved.peer, raw.types.PeerUser) and resolved.peer.user_id == user_id:
                user = next((user for user in resolved.users if isinstance(user, raw.types.User)
                             and user.id == user_id and not user.min
                             and user.access_hash is not None), None)
                if user is not None:
                    success, result = await try_owner(raw.types.InputUser(
                        user_id=user_id, access_hash=user.access_hash
                    ))
                    if success:
                        return result

    # Bots support an ID/zero-hash reference; no fromMessage constructors.
    success, result = await try_owner(fallback)
    if success:
        return result

    logging.getLogger(__name__).warning(
        "Sticker owner access denied: user_id=%s chat_id=%s pack=%s attempts=%s error=%s",
        user_id, message.chat.id, kwargs.get("short_name"), len(tried), last_error,
    )
    if message.chat.id < 0:
        raise StickerOwnerUnavailable() from last_error
    raise last_error


async def prompt_sticker_owner_start(response, bot_username):
    await rich_call(
        response.edit,
        "Telegram couldn't access your account as this pack's owner.\n"
        "Open this bot in private, press Start, then retry this command here.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Start bot in private", url=f"https://t.me/{bot_username}")]
        ]),
    )

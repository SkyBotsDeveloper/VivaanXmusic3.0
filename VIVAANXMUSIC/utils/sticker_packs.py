"""Resolve sticker-pack ownership using the current Telegram session."""

from pyrogram import raw
from pyrogram.errors import PeerIdInvalid


async def get_sticker_bot_username(client) -> str:
    me = await client.get_me()
    if not me.username:
        raise ValueError("the running bot has no username")
    return me.username.lower()


async def create_sticker_set_for_user(client, message, **kwargs):
    if not message.from_user:
        raise ValueError("run this command from your own Telegram account")

    user_id = message.from_user.id
    if message.chat.id < 0:
        # A group sender can have only a 'min' user/hash in the peer cache.
        reference = raw.types.InputUserFromMessage(
            peer=await client.resolve_peer(message.chat.id),
            msg_id=message.id,
            user_id=user_id,
        )
    else:
        # Bots can resolve a known user by ID without a cached access hash.
        reference = raw.types.InputUser(user_id=user_id, access_hash=0)

    users = await client.invoke(raw.functions.users.GetUsers(id=[reference]))
    user = next((user for user in users if isinstance(user, raw.types.User)
                 and user.id == user_id), None)
    if user is None:
        raise PeerIdInvalid()

    owner = reference
    if not user.min and user.access_hash is not None:
        owner = raw.types.InputUser(user_id=user_id, access_hash=user.access_hash)

    try:
        return await client.invoke(raw.functions.stickers.CreateStickerSet(user_id=owner, **kwargs))
    except PeerIdInvalid:
        # Retry once with the original message/bot reference, preserving owner.
        if owner.write() == reference.write():
            raise
        return await client.invoke(raw.functions.stickers.CreateStickerSet(user_id=reference, **kwargs))

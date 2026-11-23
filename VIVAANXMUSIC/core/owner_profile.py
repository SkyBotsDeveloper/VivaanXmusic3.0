import asyncio


async def resolve_owner_profile_url(client, owner_id, logger):
    fallback = f"tg://user?id={owner_id}"
    try:
        owner = await asyncio.wait_for(client.get_users(owner_id), timeout=5)
    except Exception as exc:
        logger.warning("Owner username lookup unavailable (%s); using the configured user ID.",
                       type(exc).__name__)
        return fallback
    if owner.id == owner_id and owner.username:
        # Telegram's profile flag opens the profile rather than the chat view.
        logger.info("Dev button resolved to the configured owner's username profile.")
        return f"https://t.me/{owner.username}?profile"
    return fallback

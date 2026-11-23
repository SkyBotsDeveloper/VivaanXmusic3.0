import asyncio


async def select_bot_login_dc(client, dc_id):
    """Route a fresh bot login like Kurigram's built-in UserMigrate handler."""
    if not dc_id or await client.storage.user_id() is not None:
        return False
    if await client.storage.dc_id() == dc_id:
        return False

    dc = await client.get_dc_option(dc_id, ipv6=client.ipv6)
    await client.session.stop()
    # A different DC needs a fresh auth key. Do not reuse the old DC's key or
    # export authorization: this session has not logged in yet.
    client.session = await client.get_session(
        dc_id=dc_id,
        server_address=dc.ip_address,
        port=dc.port,
        export_authorization=False,
        temporary=True,
    )
    await client.storage.dc_id(dc_id)
    await client.storage.server_address(dc.ip_address)
    await client.storage.port(dc.port)
    await client.storage.auth_key(client.session.auth_key)
    return True


async def start_with_telegram_retry(start, logger):
    """Retry a failed bot authorization without delaying successful starts."""
    delay = 30
    while True:
        try:
            return await start()
        except TimeoutError as exc:
            if 'Failed to invoke "auth.ImportBotAuthorization"' not in str(exc):
                raise
            logger.warning("Telegram bot authorization failed; retrying in %s seconds.", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

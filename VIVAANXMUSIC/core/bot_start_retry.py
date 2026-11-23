import asyncio


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

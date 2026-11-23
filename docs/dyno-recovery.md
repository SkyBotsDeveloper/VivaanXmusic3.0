# Worker recovery

The `start` entry point runs a small supervisor outside the bot's asyncio loop.
It is enabled only when `DYNO_GUARD_ENABLED=1`, `DYNO_GUARD_APP` matches
`HEROKU_APP_NAME`, and the current `DYNO` is a worker.

For `skybeatznew`, set:

```text
DYNO_GUARD_ENABLED=1
DYNO_GUARD_APP=skybeatznew
DYNO_MEMORY_QUOTA_MB=1024
```

The quota is for the current Standard-2X worker. Update it if the dyno size changes.
The existing `HEROKU_API_KEY` must have access to this app.

- Daily restart: 03:00 Asia/Kolkata (21:30 UTC the previous day), within the
  10-second polling interval. Booting after 03:00 schedules the following day.
- Memory: monitor the entire container, including FFmpeg children and swap;
  subtract reclaimable inactive file cache. Restart at 90% of the quota sustained
  for 30 seconds, after a 2-minute startup grace period. Local recovery has a
  5-minute cooldown to avoid fast restart loops.
- A restart uses the Heroku API endpoint for this worker alone. If the API is
  unavailable, recycle the bot and its process group locally. If Heroku accepts
  the request but does not stop the dyno within 45 seconds, use the same fallback.
- Exited workers relaunch with bounded 10–300 second crash backoff. SIGTERM from
  Heroku stops the supervisor and the bot process group without relaunching them.
- Telegram authorization already retries independently; no manual restart is
  needed when a temporary Telegram error clears.

Restarts interrupt active playback and clear in-memory queues. This limits the
impact of accumulated memory pressure; it cannot guarantee that a sudden memory
spike will never cause R14/R15 or fix a persistent memory leak. The supervisor
works while its own process and dyno are alive; Heroku handles dyno-level failures.

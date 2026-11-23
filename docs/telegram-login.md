# Bot login routing

`BOT_LOGIN_DC=0` keeps the library's automatic routing (the default).
Values `1` through `5` opt into a specific initial Telegram data center for a
fresh bot authorization. Existing authorized sessions are left alone.

For `skybeatznew`, the default DC 2 route returned `RPC_CALL_FAIL`, while DC 5
authenticated the same bot token and API credentials successfully in isolated
Kurigram and Telethon probes. Its Heroku configuration therefore uses
`BOT_LOGIN_DC=5`.

The client resolves the data-center address from Telegram's configuration and
creates a fresh DC-specific auth key using Kurigram's existing migration flow.
It does not reuse the DC 2 key on DC 5 or attempt to export a login that has not
succeeded. Telegram's normal subsequent migration handling remains active.

No token rotation, assistant session change, or playback change is required.
Set the variable back to `0` to restore the automatic initial route.

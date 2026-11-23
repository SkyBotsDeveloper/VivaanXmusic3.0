# Group playback controls

- `/music on` (default): everyone can request audio/video. Explicitly enabling
  it also resets the existing play-type setting to Everyone.
- `/music off`: stops current playback/queue and blocks play commands, channel
  play, force play, spoken requests and old selection buttons. A group admin gets
  **Play for now** to approve their own request once without enabling music for
  everyone. Buttons expire after two minutes and recheck current admin status.
- `/vcnotify on`: the assistant joins an existing VC silently, including after
  a bot restart. It does not start a new VC. A banned assistant generates one
  unban notice per new VC. Notifications default to off.
- `/setlogger -100xxxx`: run in the source group to route only that group's VC
  notifications to another group/channel. The bot must be an admin there (with
  posting rights for channels). `/setlogger` shows the current destination;
  `/setlogger off` restores notifications in the source group. This does not
  enable notifications by itself: use `/vcnotify on` as well. Failed logger
  delivery never falls back to cluttering the source group.
- VC names come first from Telegram update metadata, with assistant/bot lookup
  as fallback. Names are escaped, usernames shown when available, and numeric
  user IDs always included. Deleted/inaccessible accounts use their ID rather
  than an invented "Unknown" name. Identity caching is bounded and expires.
- `/autodelete on`: all subsequent bot messages in that chat (including media,
  albums and Rich menus) become eligible for cleanup after five minutes, with
  a shared sweep every 30 seconds. Song-end cleanup also remains active. Message
  IDs are written to MongoDB in batches, so saved work survives worker restarts.
  There is no history scan or per-message timer. External VC logs are retained
  unless auto-delete is enabled in the actual logging chat too.
  `/autodelete off` cancels pending cleanup for that chat; other people's messages are never
  tracked. A hard crash can lose IDs awaiting the next 15-second batch flush.
- Anonymous group commands show **Verify admin and run**. Clicking rechecks the
  current group-admin status, the original command filters and its individual
  privileges. Approvals are bound to one group/command, expire after two minutes
  and can be consumed only once. Other channel senders cannot impersonate an
  anonymous group admin; regular members cannot verify a command. Verification
  is not a permanent permission grant and never changes Telegram admin rights.
- Five continuous minutes without a human listener stop playback, clear the
  queue, leave the VC and notify the source group. Muted humans count; the bot
  and assistants do not. This takes priority over notification presence. The
  assistant stays out of that same VC until a new play request, a new VC, or an
  explicit `/vcnotify on`. Autoplay remains configured for the next session.

Listener snapshots use Telegram directly rather than the transport's cached
participant list. Checks run every 30 seconds; leave occurs at the first check
after five minutes of confirmed inactivity. Failed checks reset the timer so
temporary API failures cannot kick out active listeners. Notification presence
uses a native listen-only call without additional FFmpeg processes.

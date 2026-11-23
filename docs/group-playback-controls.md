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

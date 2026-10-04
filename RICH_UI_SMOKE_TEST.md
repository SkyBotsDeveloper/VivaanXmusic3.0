# Rich UI deployment smoke checklist

Run after deploying the commit and installing `requirements.txt` (Kurigram 2.2.26).
Use a Telegram client with Rich Message support. Repeat the layout check on
desktop and mobile. Automated tests do not establish live client appearance.

For every screen below, check: native Rich buttons, unchanged labels/colors,
unchanged row grouping, working actions, preserved media/text, and edits to the
same message instead of a new copy where the existing flow edits a message.

1. **Welcome and Help:** send `/start` in private chat. Check the 1-2-1 layout;
   open the add-to-group link, developer link and support link. Press Help &
   Commands, open a category, press Back, Next, Previous and Menu/Home. The
   welcome video and the same Rich 1-2-1 buttons must return. Open the first
   Help category's promotion/punishment submenu and Back. Also send `/help`
   directly and follow its Menu/Home button; test `/start help`.
2. **Player:** in a test group with an active voice chat, send `/play <song>`.
   Check the thumbnail/caption and the five controls on one row. Press Pause,
   Resume, Replay and Skip with at least two queued tracks. Watch at least two
   timer updates, then press Stop and Close. Playback and authorization must
   behave as before. Test a video track and a Telegram audio upload too.
3. **Queue:** queue two songs; send `/queue` or `/player`, press Queued Tracks,
   then Back to the timer/player view. Check media, caption and timer updates.
   Test a live stream where duration is unknown as well.
4. **Settings:** send `/settings` in a group. Open Playmode, change Search mode,
   permissions and play type, then Back. Open Auth Users, toggle the existing
   option, view Auth List, then Back. Open Vote mode, toggle it and adjust its
   count, then Back. Test with an admin and a non-admin; permission checks must
   remain unchanged. In private chat, use Language's Back to welcome.
5. **Languages:** send `/lang`; select each of Arabic, English, Hindi, Russian
   and Turkish. Check the restored language keyboard and its Back button.
   Repeat `/start` -> Help -> category -> Back -> Home for each language.
6. **Song/download:** send `/song <song>` and confirm the existing direct audio
   download. This checkout retains legacy selection callbacks but does not
   currently create a selection card from `/song` or `/start`. If a selection
   card from an earlier deployment is still available, press Audio, Back, Video,
   Back, choose a format and confirm the download; also test Close. Those
   callbacks must rebuild Rich media/buttons. Their full selection/Back chain
   is additionally covered by the offline handler tests; no new entry point was added.
7. **Stats:** send `/stats`, open Overall stats and Back. As an existing sudo
   user, open Bot stats and Back. Video cards and buttons must remain Rich.
8. **Other tools:** send `/font Hello`; press Next, a style and Back. Check that
   the original source text and three-button rows survive. Test `/figlet Hello`,
   `/lyrics <song>` result/page/back navigation, `/speed` controls during playback,
   and one tool/error screen with Close. Existing commands/actions must match
   their prior behavior.
9. **Inline search:** type `@<bot_username> <song>` and choose a search result.
   Check its Rich photo/text and the existing YouTube URL button. Try the empty
   inline query's command articles; they should still insert their commands.
10. **Restart:** leave Help, Settings, Fonts, a song-selection card and a player
    visible, restart the bot, then press an existing navigation button. Confirm
    received Rich blocks preserve the body/media without a local menu cache.
    Restart/player availability still follows the bot's existing playback state.

Record client versions and the exact command/button sequence for any rendering
or RPC issue. Do not infer visual success solely from the offline test suite.

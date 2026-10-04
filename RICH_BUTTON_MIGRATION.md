# Complete Rich button migration audit

Baseline: `880def7` on `main`. The working tree was clean when this task began.
This supersedes the previous guarded migration and its intentionally inline paths.

## Runtime result

| Interface | Native Rich delivery |
| --- | --- |
| Player cards, controls and timer updates | YES |
| Help pages, categories and pagination | YES |
| Help Back/Home navigation | YES |
| Welcome restoration from Help and Settings | Always Rich |
| Settings, auth, playmode and vote menus | YES |
| Language selection and restored menu | YES |
| Queue and Back to player | YES |
| Song/download selections and Back | YES |
| Stats and Back | YES |
| Admin, VC and confirmation controls | YES |
| Media cards and other tool keyboards | YES |
| Inline search result button | YES |

**Remaining old InlineKeyboardMarkup runtime delivery locations: none.**
No normal-chat flow is exempted for media, markup-only edits or navigation.
`InlineKeyboardMarkup` and `InlineKeyboardButton` remain as local keyboard
*descriptors*, preserving the existing builders and their conditional visibility.
The descriptors are converted before delivery; the native send/edit requests
contain Rich blocks and no normal reply markup.

## Architecture and compatibility

Kurigram is upgraded from **2.2.24 to stable 2.2.26**, verified against PyPI's
release metadata and official wheel. No other dependency is added or upgraded.
The tested environment also imports the pinned PyTgCalls 2.3.3 successfully.

`utils/rich_buttons.py` now constructs `InputRichMessage(blocks=...)`, one
`InputRichBlockButtons` per original row, and native `RichMessageButton` actions.
Existing styles are copied directly: blue `primary`, green `success`, red `danger`,
and default where the original descriptor has no color. The 1-2-1 welcome,
three-column Help/Fonts rows, and five-column player controls stay intact.
`align=None` omits the left/center/right alignment flags so rows use full-width
columns. Telegram clients control final pixel dimensions and shape; no label
padding or unsupported width/height fields are used.

Native photo/video/animation/document/audio/voice-note blocks accept original
URLs, uploads and file IDs. Parsed text/entities become native text blocks;
media captions are rendered as text alongside the media. Native media upload
and MTProto serialization are handled by Kurigram, with no custom HTTP layer.

Markup-only changes rebuild the received body/media with replacement button
rows and edit the **same message ID** using `edit_message_text(rich_message=...)`.
Text/caption edits preserve the current media. Media edits replace the media
and caption. Updates with no new keyboard remove the buttons as before.
Incoming Rich blocks are rehydrated to input blocks, so callbacks do not require
a process-local cache. Sparse send responses are fetched once to pin uploaded
media to Telegram file IDs before temporary thumbnails can be deleted. A
per-message snapshot handles sparse edit/text responses; there is no UI database.

Help and private Settings Back/Home call `restore_welcome` with the existing
welcome video selection, caption and `private_panel` buttons. The old reachable
/start inline fallback is removed. Fonts reads Rich text/button descriptors;
song video downloads read thumbnail dimensions from the Rich photo block.
Those are presentation compatibility changes, not callback or state changes.
The current `/song` command directly downloads audio and has no keyboard;
its legacy format-selection/Back callbacks are retained and migrated without
adding a new command entry point. Their tests start from an existing card.

2.2.26 removed deprecated Message shortcut arguments. The shared helper adapts
existing `quote`, `reply_to_message_id` and `disable_web_page_preview` calls,
including plain-text paths affected by the upgrade. Reply IDs, topics and preview
settings are preserved. No handlers, permission checks, DB operations or
playback operations were renamed or reordered. AST comparison after removing
the new renderer wrappers proves the other changed call sites retain their
original arguments, handlers and conditions.

There is **no silent inline fallback**. Unsupported actions or send options raise
an explicit error. Telegram Rich rows have a hard limit of 1-8 buttons; current
builders fit that limit. Payments, games and password-protected callbacks are not
native Rich button actions and are rejected, but no current repository keyboard
uses them. Stable Kurigram's Rich send omits scheduling/repeat/TTL/business send
options; none of the current keyboard delivery sites requests these options.
These are helper guards, not remaining runtime inline exceptions.

## Inline query audit

`plugins/bot/inline.py` still returns the original photo result metadata, but
its outgoing content is `InputRichMessageContent` with native Rich HTML media
and button rows. The serialized result contains `InputBotInlineMessageRichMessage`
and no normal reply markup. Telegram officially supports Rich input message
content in inline results. The command-only articles in `utils/inlinequery.py`
have no buttons and remain unchanged. No inline-query keyboard exception remains.

## Validation

- Full repository unittest discovery: **68 tests passed** on Kurigram 2.2.26.
- Full Python compilation: **201 files passed**, including both Rich test files.
- Native Rich type/helper imports and PyTgCalls compatibility imports passed.
- Native MTProto send/edit, media upload and received-block parsing exercised
  offline; callbacks and URLs checked against original keyboard descriptors.
- All five locales: Arabic, English, Hindi, Russian and Turkish, including every
  locale text's entity round-trip and native text serialization.
- Original 1-, 2-, 3-, 5- and 8-button rows and multi-row layouts preserved;
  full-width flags and primary/success/danger style serialization checked.
- Photo, video, animation, document, audio and voice-note construction/re-edit;
  local thumbnail cleanup and received file-ID reuse checked.
- Actual handler bodies tested through Start/Help/category/Back/next/previous/Home,
  Settings/playmode change/Back/auth toggle, Language/select/Back, Song/formats/Back,
  Player/card/pause/resume/timer/Queue/Back, Stats/details/Back and Fonts/page/style/Back.
  Services and RPC responses are offline doubles; handler/render code is real.
- Repo-wide AST audit finds zero direct old keyboard send/update calls. Named
  safe callback delegates all call the shared renderer. Positional Fonts keyboard
  updates are included. Existing builders are unchanged.
- `git diff --check` and explicit changed-file review performed before commit.

These checks establish API serialization and navigation behavior, not Telegram
client appearance or live playback. Run [the deployment smoke checklist](RICH_UI_SMOKE_TEST.md)
on Telegram after deployment; no live smoke test is claimed here.

## Native keyboard delivery/update inventory

Line numbers below refer to this implementation. They include text/media sends,
caption/media edits, markup-only rebuilds and positional keyboard updates. Existing
safe callback helpers delegate to these native routes; `/start` helper and welcome
restoration also build their native views through the shared renderer.

| File | Native delivery/update lines |
| --- | --- |
| `VIVAANXMUSIC/core/call.py` | 1519, 1540, 1558 |
| `VIVAANXMUSIC/platforms/Telegram.py` | 121 |
| `VIVAANXMUSIC/plugins/Kishu/figlet.py` | 31, 43 |
| `VIVAANXMUSIC/plugins/Kishu/fonts.py` | 115, 126, 139, 141, 161 |
| `VIVAANXMUSIC/plugins/Kishu/ip.py` | 238 |
| `VIVAANXMUSIC/plugins/Kishu/password.py` | 38 |
| `VIVAANXMUSIC/plugins/Kishu/wishcute.py` | 48, 64 |
| `VIVAANXMUSIC/plugins/Manager/del_msg.py` | 80 |
| `VIVAANXMUSIC/plugins/Manager/grouphandler.py` | 41, 63 |
| `VIVAANXMUSIC/plugins/Manager/info.py` | 79 |
| `VIVAANXMUSIC/plugins/Manager/language.py` | 51, 54, 66, 69, 90, 93 |
| `VIVAANXMUSIC/plugins/Manager/welcome.py` | 129 |
| `VIVAANXMUSIC/plugins/Manager/zombie.py` | 105 |
| `VIVAANXMUSIC/plugins/admins/auth.py` | 90 |
| `VIVAANXMUSIC/plugins/admins/autodelete.py` | 24, 32, 40, 45 |
| `VIVAANXMUSIC/plugins/admins/autoplay.py` | 39, 54, 61, 66 |
| `VIVAANXMUSIC/plugins/admins/callback.py` | 56, 63, 66, 127, 180, 188, 308, 400, 424, 434, 549 |
| `VIVAANXMUSIC/plugins/admins/loop.py` | 28, 36, 42 |
| `VIVAANXMUSIC/plugins/admins/pause.py` | 20 |
| `VIVAANXMUSIC/plugins/admins/resume.py` | 20 |
| `VIVAANXMUSIC/plugins/admins/seek.py` | 37, 44, 68, 73 |
| `VIVAANXMUSIC/plugins/admins/shuffle.py` | 25, 29, 32 |
| `VIVAANXMUSIC/plugins/admins/skip.py` | 49, 76, 88, 200, 224, 238 |
| `VIVAANXMUSIC/plugins/admins/speed.py` | 34, 107, 110 |
| `VIVAANXMUSIC/plugins/admins/stop.py` | 22 |
| `VIVAANXMUSIC/plugins/admins/totalmembers.py` | 33, 47 |
| `VIVAANXMUSIC/plugins/admins/vcnotify.py` | 25, 38, 48, 53 |
| `VIVAANXMUSIC/plugins/admins/voiceplay.py` | 65 |
| `VIVAANXMUSIC/plugins/bot/help.py` | 41, 45, 56, 74, 85, 98, 111, 129, 139, 149 |
| `VIVAANXMUSIC/plugins/bot/settings.py` | 43, 58, 82, 149, 180, 240, 285, 301, 324 |
| `VIVAANXMUSIC/plugins/bot/start.py` | 45, 46, 47, 226 |
| `VIVAANXMUSIC/plugins/misc/tts.py` | 148, 216, 231, 250, 261, 276 |
| `VIVAANXMUSIC/plugins/misc/urlshortner.py` | 63, 86 |
| `VIVAANXMUSIC/plugins/play/play.py` | 452, 500, 560, 592, 611, 699, 889 |
| `VIVAANXMUSIC/plugins/play/playmode.py` | 33 |
| `VIVAANXMUSIC/plugins/sudo/sudoers.py` | 57, 92, 100 |
| `VIVAANXMUSIC/plugins/tools/active.py` | 65 |
| `VIVAANXMUSIC/plugins/tools/bugs.py` | 58, 71 |
| `VIVAANXMUSIC/plugins/tools/chatlog.py` | 45 |
| `VIVAANXMUSIC/plugins/tools/kang.py` | 223 |
| `VIVAANXMUSIC/plugins/tools/lyrics.py` | 321, 419 |
| `VIVAANXMUSIC/plugins/tools/masti.py` | 57 |
| `VIVAANXMUSIC/plugins/tools/ping.py` | 26 |
| `VIVAANXMUSIC/plugins/tools/queue.py` | 101, 118, 177, 182, 185, 243, 260 |
| `VIVAANXMUSIC/plugins/tools/song.py` | 488, 549 |
| `VIVAANXMUSIC/plugins/tools/stats.py` | 29, 40, 71, 73, 228, 230 |
| `VIVAANXMUSIC/plugins/tools/sticker.py` | 107 |
| `VIVAANXMUSIC/plugins/tools/telegraph.py` | 37 |
| `VIVAANXMUSIC/utils/decorators/admins.py` | 53, 105, 149 |
| `VIVAANXMUSIC/utils/decorators/play.py` | 49, 80, 135 |
| `VIVAANXMUSIC/utils/stream/cards.py` | 34, 42 |
| `VIVAANXMUSIC/utils/stream/stream.py` | 213, 241, 324, 347, 381, 406, 437, 505, 531 |

## Changed-file manifest

Every file below belongs to the Rich migration, native-version shortcut
compatibility, its tests, or its audit/smoke documentation.

- `RICH_BUTTON_MIGRATION.md`
- `RICH_UI_SMOKE_TEST.md`
- `VIVAANXMUSIC/core/call.py`
- `VIVAANXMUSIC/platforms/Telegram.py`
- `VIVAANXMUSIC/plugins/Kishu/dicegame.py`
- `VIVAANXMUSIC/plugins/Kishu/figlet.py`
- `VIVAANXMUSIC/plugins/Kishu/fonts.py`
- `VIVAANXMUSIC/plugins/Kishu/groupdata.py`
- `VIVAANXMUSIC/plugins/Kishu/ip.py`
- `VIVAANXMUSIC/plugins/Kishu/password.py`
- `VIVAANXMUSIC/plugins/Kishu/wishcute.py`
- `VIVAANXMUSIC/plugins/Manager/del_msg.py`
- `VIVAANXMUSIC/plugins/Manager/id.py`
- `VIVAANXMUSIC/plugins/Manager/language.py`
- `VIVAANXMUSIC/plugins/Manager/welcome.py`
- `VIVAANXMUSIC/plugins/Manager/zombie.py`
- `VIVAANXMUSIC/plugins/admins/callback.py`
- `VIVAANXMUSIC/plugins/admins/skip.py`
- `VIVAANXMUSIC/plugins/admins/speed.py`
- `VIVAANXMUSIC/plugins/admins/totalmembers.py`
- `VIVAANXMUSIC/plugins/admins/voiceplay.py`
- `VIVAANXMUSIC/plugins/bot/help.py`
- `VIVAANXMUSIC/plugins/bot/inline.py`
- `VIVAANXMUSIC/plugins/bot/settings.py`
- `VIVAANXMUSIC/plugins/bot/start.py`
- `VIVAANXMUSIC/plugins/misc/instadl.py`
- `VIVAANXMUSIC/plugins/misc/movie.py`
- `VIVAANXMUSIC/plugins/misc/news.py`
- `VIVAANXMUSIC/plugins/play/play.py`
- `VIVAANXMUSIC/plugins/play/playmode.py`
- `VIVAANXMUSIC/plugins/sudo/restart.py`
- `VIVAANXMUSIC/plugins/sudo/sudoers.py`
- `VIVAANXMUSIC/plugins/tools/active.py`
- `VIVAANXMUSIC/plugins/tools/ai.py`
- `VIVAANXMUSIC/plugins/tools/chatlog.py`
- `VIVAANXMUSIC/plugins/tools/gpt.py`
- `VIVAANXMUSIC/plugins/tools/kang.py`
- `VIVAANXMUSIC/plugins/tools/lyrics.py`
- `VIVAANXMUSIC/plugins/tools/masti.py`
- `VIVAANXMUSIC/plugins/tools/ping.py`
- `VIVAANXMUSIC/plugins/tools/queue.py`
- `VIVAANXMUSIC/plugins/tools/song.py`
- `VIVAANXMUSIC/plugins/tools/stats.py`
- `VIVAANXMUSIC/plugins/tools/sticker.py`
- `VIVAANXMUSIC/plugins/tools/telegraph.py`
- `VIVAANXMUSIC/plugins/tools/videoedit.py`
- `VIVAANXMUSIC/utils/decorators/admins.py`
- `VIVAANXMUSIC/utils/decorators/language.py`
- `VIVAANXMUSIC/utils/decorators/play.py`
- `VIVAANXMUSIC/utils/rich_buttons.py`
- `VIVAANXMUSIC/utils/stream/cards.py`
- `VIVAANXMUSIC/utils/stream/stream.py`
- `requirements.txt`
- `tests/test_rich_buttons.py`
- `tests/test_rich_navigation.py`

## Sources inspected

- [Telegram Rich formatting and native button/media blocks](https://core.telegram.org/bots/api#rich-message-formatting-options)
- [Telegram Rich button row limits/alignment](https://core.telegram.org/bots/api#inputrichblockbuttons)
- [Official TDLib button row alignment schema](https://github.com/tdlib/td/blob/master/td/generate/scheme/td_api.tl)
- [Stable Kurigram 2.2.26 release](https://pypi.org/project/Kurigram/2.2.26/)
- Installed official 2.2.26 wheel: native Rich input/output types, action/style
  serialization, upload helpers, send/edit/inline methods and Message shortcuts.

# Rich button migration audit

Baseline: `6906eb00e90872b31edc493942233dafe020922d` on `main`. The working tree was clean before editing.

## Delivery coverage

Count delivery/update call sites, not unique runtime messages or button instances:

- **172 existing inline delivery/update sites**: 169 calls with `reply_markup=` plus three positional font markup updates.
- **85 sites routed through native Rich delivery when compatible**: 78 direct calls and seven callers of the existing safe callback helpers.
- **87 intentionally retained inline sites**: 84 incompatible media/inline-query/markup-only workflow sites and three inactive `/start` restoration branches.
- The four already-Rich `/start` delivery paths now reuse the shared converter; these are outside the 172 inline-site count.
- **94 original `InlineKeyboardMarkup` constructor locations** remain as layout/action descriptors for the shared converter or the documented inline workflows. Their continued presence is intentional, not a missed migration.

## Shared implementation

`VIVAANXMUSIC/utils/rich_buttons.py` provides `keyboard_html`, `text_html` and `rich_call`.

Kurigram is unchanged at **2.2.24**. That version exposes `InputRichMessage(html=...)`, `send_rich_message`, and native `edit_message_text(rich_message=...)`, but not the newer `InputRichBlockButtons`/`RichMessageButton` classes. No new dependencies, forks, HTTP Bot API calls, global client patches or UI state caches were added.

Each original row becomes one `<tg-button-row>` with the same ordered buttons. Alignment is omitted for full-width equal columns, including single-button rows and the 1-2-1 `/start` keyboard. Rows are never regrouped. Existing primary/success/danger styles are copied; default stays default. Labels, callback data (including compatible UTF-8 bytes), URLs, profile/add-group links and conditions come from the unchanged builders.

Rich HTML supports URL, callback, WebApp, same-bot login, copy-text and switch-inline actions. Payment/game/password-protected actions, alternate login bots, binary callback data, custom icon metadata or a row outside 1-8 buttons keep the entire keyboard inline. The current repository builders do not use the newer chosen-chat or disabled fields, but their supported Rich HTML actions are handled if present.

Text is first parsed using the original Kurigram parse mode/entities, then emitted as escaped Rich HTML. Mentions, emoji UTF-16 offsets, nested emphasis, spoilers, inline code, preformatted blocks, blockquotes and line breaks are preserved. Entity objects are not mutated. `/start` retains its original restoration flag and media URLs.

`rich_call` preserves reply/thread/topic/business/notification/protection parameters. It sends via native Kurigram or edits the same message ID. Media/caption edits, inline-message-ID callbacks, unsupported formatting/options and incompatible keyboards call the original method before any RPC. RPC failures propagate through existing handlers without a second send.

## Intentionally inline interactions

- Standard uploads, file IDs, caption fields, animation/document delivery and media edits remain unchanged. Converting them would change the returned Message media/caption interface; 2.2.24 lacks Rich media bindings for those payloads.
- Markup-only edits cannot replace embedded Rich button blocks. Fonts also reads message.reply_markup. Keeping each of these workflows inline avoids new UI state/caches or changes to callback logic.
- Help, stats, ping, queue, song/download and player cards preserve their standard media and caption-edit lifecycle.
- Settings, language, playmode, fonts and member export preserve their markup-only lifecycle.
- Inline-query photo results keep their existing result type and keyboard.
- `/start`'s three legacy send branches remain available behind `START_RICH_BUTTONS = False`; the flag stays enabled for Rich output.

Runtime limits also retain inline delivery for scheduled/repeated text sends or other options absent from `send_rich_message`, explicit enabled/custom link-preview options, URL-bearing bodies with automatic previews enabled, and media targets. Rich content cannot retain a classic automatic webpage card, so those bodies use the original method; button URLs still convert unchanged. Telegram clients control button height, padding, corners, colors and final RTL rendering; no unsupported sizing or whitespace tricks were introduced.

## Validation

- Syntax compilation of all 200 repository Python sources and validation of every new helper import/symbol in 35 production files.
- AST comparison against the baseline: unwrapping `rich_call` and removing its imports restores the original AST in all 34 wrapped files. Callback handlers, arguments, literals, URLs, data, permission checks and conditional row construction are identical. `/start` is checked separately for unchanged command/callback bodies.
- Offline tests cover layout sizes 1/2/3/8 and 1-2-1, escaping, semantic styles, callback bytes, URLs, profile/add-group links, WebApp/login/copy/switch actions and unsupported-action fallbacks.
- Builder/visibility checks and text round trips cover every supported language: `ar`, `en`, `hi`, `ru`, `tr`, including English fallback labels. Existing locale files remain unchanged.
- Native Kurigram/MTProto send/edit serialization with a recording client verifies message IDs, reply/topic/business metadata, actions, flags, fallback behavior and no duplicate RPC on failure.
- `python -X utf8 -m unittest discover -s tests -v`: **53 tests passed** (39 existing plus 14 migration tests).
- No live Telegram clicks or pixel/rendering verification were performed; Telegram server/client acceptance remains a deployment smoke test.

## Complete delivery-site classification

Line numbers below refer to the baseline commit above. `Rich` includes guarded delivery and safe-helper callers; `Inline` includes documented compatibility and restoration paths. This accounts for every existing delivery/update site.

| File | Rich sites (baseline lines) | Inline sites (baseline lines) | Reason for inline sites |
| --- | --- | --- | --- |
| `VIVAANXMUSIC/core/call.py` | - | 1518, 1539, 1557 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/platforms/Telegram.py` | 120 | - | - |
| `VIVAANXMUSIC/plugins/Kishu/figlet.py` | 30, 42 | - | - |
| `VIVAANXMUSIC/plugins/Kishu/fonts.py` | - | 114, 125, 138, 140, 160 | Fonts reads message.reply_markup and paginates with markup-only edits. |
| `VIVAANXMUSIC/plugins/Kishu/ip.py` | 237 | - | - |
| `VIVAANXMUSIC/plugins/Kishu/password.py` | 37 | - | - |
| `VIVAANXMUSIC/plugins/Kishu/wishcute.py` | - | 47, 63 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/Manager/del_msg.py` | 79 | - | - |
| `VIVAANXMUSIC/plugins/Manager/grouphandler.py` | 40, 62 | - | - |
| `VIVAANXMUSIC/plugins/Manager/info.py` | 78 | - | - |
| `VIVAANXMUSIC/plugins/Manager/language.py` | - | 50, 53, 65, 68, 89, 92 | Language/settings share markup-only update callbacks. |
| `VIVAANXMUSIC/plugins/Manager/welcome.py` | - | 128 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/Manager/zombie.py` | 104 | - | - |
| `VIVAANXMUSIC/plugins/admins/auth.py` | 89 | - | - |
| `VIVAANXMUSIC/plugins/admins/autodelete.py` | 23, 31, 39, 44 | - | - |
| `VIVAANXMUSIC/plugins/admins/autoplay.py` | 38, 53, 60, 65 | - | - |
| `VIVAANXMUSIC/plugins/admins/callback.py` | 55, 62, 65, 179, 187, 193, 261, 270, 307, 334, 390, 407, 457 | 126, 399, 423, 433, 548 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/admins/loop.py` | 27, 35, 41 | - | - |
| `VIVAANXMUSIC/plugins/admins/pause.py` | 19 | - | - |
| `VIVAANXMUSIC/plugins/admins/resume.py` | 19 | - | - |
| `VIVAANXMUSIC/plugins/admins/seek.py` | 36, 43, 67, 72 | - | - |
| `VIVAANXMUSIC/plugins/admins/shuffle.py` | 24, 28, 31 | - | - |
| `VIVAANXMUSIC/plugins/admins/skip.py` | 48, 75, 87 | 199, 223, 237 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/admins/speed.py` | 33, 106, 109 | - | - |
| `VIVAANXMUSIC/plugins/admins/stop.py` | 21 | - | - |
| `VIVAANXMUSIC/plugins/admins/totalmembers.py` | - | 32, 46 | Export removes only the keyboard before collecting members. |
| `VIVAANXMUSIC/plugins/admins/vcnotify.py` | 24, 37, 47, 52 | - | - |
| `VIVAANXMUSIC/plugins/admins/voiceplay.py` | 64 | - | - |
| `VIVAANXMUSIC/plugins/bot/help.py` | - | 39, 43, 54, 72, 83, 96, 109, 127, 137, 147, 158 | Help pages/back navigation retain standard media/caption behavior. |
| `VIVAANXMUSIC/plugins/bot/inline.py` | - | 57 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/bot/settings.py` | - | 40, 55, 73, 79, 146, 177, 237, 282, 298, 321 | Settings changes buttons without replacing message content. |
| `VIVAANXMUSIC/plugins/bot/start.py` | - | 55, 58, 61, 306 | Existing /start fallback retained; active /start already uses Rich HTML. Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/misc/tts.py` | 147, 215, 230, 249, 260, 275 | - | - |
| `VIVAANXMUSIC/plugins/misc/urlshortner.py` | 62, 85 | - | - |
| `VIVAANXMUSIC/plugins/play/play.py` | 451, 499, 698 | 559, 591, 610, 888 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/play/playmode.py` | - | 32 | Playmode shares settings markup-only update callbacks. |
| `VIVAANXMUSIC/plugins/sudo/sudoers.py` | - | 56, 91, 99 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/tools/active.py` | 64 | - | - |
| `VIVAANXMUSIC/plugins/tools/bugs.py` | 57, 70 | - | - |
| `VIVAANXMUSIC/plugins/tools/chatlog.py` | - | 44, 107 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/tools/kang.py` | 222 | - | - |
| `VIVAANXMUSIC/plugins/tools/lyrics.py` | 320, 418 | - | - |
| `VIVAANXMUSIC/plugins/tools/masti.py` | - | 56 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/plugins/tools/ping.py` | - | 25 | Ping edits a standard video caption through edit_text. |
| `VIVAANXMUSIC/plugins/tools/queue.py` | - | 100, 117, 176, 181, 184, 242, 259 | Queue cards preserve media and update timer markup only. |
| `VIVAANXMUSIC/plugins/tools/song.py` | - | 487, 548 | Download choices use markup-only updates and standard media. |
| `VIVAANXMUSIC/plugins/tools/stats.py` | - | 28, 39, 70, 72, 227, 229 | Stats switches standard videos/media and captions. |
| `VIVAANXMUSIC/plugins/tools/sticker.py` | 106 | - | - |
| `VIVAANXMUSIC/plugins/tools/telegraph.py` | 36 | - | - |
| `VIVAANXMUSIC/utils/decorators/admins.py` | 52, 104, 148 | - | - |
| `VIVAANXMUSIC/utils/decorators/play.py` | 48, 134 | 79 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/utils/stream/cards.py` | - | 33, 41 | Standard media/inline-query/markup-only interaction retained. |
| `VIVAANXMUSIC/utils/stream/stream.py` | 240, 323, 380, 436, 504 | 212, 346, 405, 530 | Standard media/inline-query/markup-only interaction retained. |

## Changed files

Production UI changes (35 existing files), one new helper, one test module and this audit:

- `RICH_BUTTON_MIGRATION.md`
- `VIVAANXMUSIC/platforms/Telegram.py`
- `VIVAANXMUSIC/plugins/Kishu/figlet.py`
- `VIVAANXMUSIC/plugins/Kishu/ip.py`
- `VIVAANXMUSIC/plugins/Kishu/password.py`
- `VIVAANXMUSIC/plugins/Manager/del_msg.py`
- `VIVAANXMUSIC/plugins/Manager/grouphandler.py`
- `VIVAANXMUSIC/plugins/Manager/info.py`
- `VIVAANXMUSIC/plugins/Manager/zombie.py`
- `VIVAANXMUSIC/plugins/admins/auth.py`
- `VIVAANXMUSIC/plugins/admins/autodelete.py`
- `VIVAANXMUSIC/plugins/admins/autoplay.py`
- `VIVAANXMUSIC/plugins/admins/callback.py`
- `VIVAANXMUSIC/plugins/admins/loop.py`
- `VIVAANXMUSIC/plugins/admins/pause.py`
- `VIVAANXMUSIC/plugins/admins/resume.py`
- `VIVAANXMUSIC/plugins/admins/seek.py`
- `VIVAANXMUSIC/plugins/admins/shuffle.py`
- `VIVAANXMUSIC/plugins/admins/skip.py`
- `VIVAANXMUSIC/plugins/admins/speed.py`
- `VIVAANXMUSIC/plugins/admins/stop.py`
- `VIVAANXMUSIC/plugins/admins/vcnotify.py`
- `VIVAANXMUSIC/plugins/admins/voiceplay.py`
- `VIVAANXMUSIC/plugins/bot/start.py`
- `VIVAANXMUSIC/plugins/misc/tts.py`
- `VIVAANXMUSIC/plugins/misc/urlshortner.py`
- `VIVAANXMUSIC/plugins/play/play.py`
- `VIVAANXMUSIC/plugins/tools/active.py`
- `VIVAANXMUSIC/plugins/tools/bugs.py`
- `VIVAANXMUSIC/plugins/tools/kang.py`
- `VIVAANXMUSIC/plugins/tools/lyrics.py`
- `VIVAANXMUSIC/plugins/tools/sticker.py`
- `VIVAANXMUSIC/plugins/tools/telegraph.py`
- `VIVAANXMUSIC/utils/decorators/admins.py`
- `VIVAANXMUSIC/utils/decorators/play.py`
- `VIVAANXMUSIC/utils/rich_buttons.py`
- `VIVAANXMUSIC/utils/stream/stream.py`
- `tests/test_rich_buttons.py`

## Official API references

- [Telegram Rich HTML and button actions](https://core.telegram.org/bots/api#rich-message-formatting-options)
- [Telegram Rich button row limit and alignment](https://core.telegram.org/bots/api#inputrichblockbuttons)
- [TDLib full-width button row alignment semantics](https://github.com/tdlib/td/blob/master/td/generate/scheme/td_api.tl)
- [Pinned Kurigram Rich HTML input](https://github.com/KurimuzonAkuma/kurigram/blob/v2.2.24/pyrogram/types/input_content/input_rich_message.py)

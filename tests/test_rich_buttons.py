"""Offline native serialization/layout checks; no bot credentials or startup."""

import ast
import asyncio
import copy
import importlib.util
import unittest
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import yaml
from pyrogram import Client, raw, types
from pyrogram.enums import ButtonStyle, ChatType, MessageEntityType, MessageMediaType, ParseMode
from pyrogram.parser import Parser
from pyrogram.types import CallbackQuery, Chat, InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage, LoginUrl, Message, MessageEntity, ReplyParameters, User, WebAppInfo


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rich_buttons", ROOT / "VIVAANXMUSIC/utils/rich_buttons.py")
rich = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rich)
STYLE_SPEC = importlib.util.spec_from_file_location("button_styles", ROOT / "VIVAANXMUSIC/button_styles.py")
styles = importlib.util.module_from_spec(STYLE_SPEC)
STYLE_SPEC.loader.exec_module(styles)


class RichHTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.rows, self.content, self.button = [], [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tg-button-row":
            self.rows.append([])
            if "align" in attrs:
                raise AssertionError("Converted rows must use full-width columns")
        elif tag == "tg-button":
            self.button = {"attrs": attrs, "label": ""}
            self.rows[-1].append(self.button)
        elif tag == "br":
            self.content.append("\n")

    def handle_endtag(self, tag):
        if tag == "tg-button":
            self.button = None

    def handle_data(self, data):
        if self.button is not None:
            self.button["label"] += data
        else:
            self.content.append(data)


def keyboard(rows):
    return rows if isinstance(rows, InlineKeyboardMarkup) else InlineKeyboardMarkup(rows)


def builder_namespace(filename, names=None):
    """Load UI definitions alone; avoid __init__'s DB/playback/service startup."""
    path = ROOT / "VIVAANXMUSIC" / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and (names is None or node.name in names):
            nodes.append(node)
        elif names is None and isinstance(node, (ast.Assign, ast.AnnAssign)):
            nodes.append(node)
    namespace = dict(vars(styles))
    namespace.update(InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
                     app=SimpleNamespace(username="existing_bot"),
                     config=SimpleNamespace(OWNER_ID=12345, SUPPORT_CHAT="https://t.me/support", SUPPORT_CHANNEL="https://t.me/channel"),
                     SUPPORT_CHAT="https://t.me/support", Union=__import__("typing").Union,
                     time=__import__("time"), Message=Message,
                     LyricsSearchSession=SimpleNamespace, LyricsCandidate=SimpleNamespace)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class LayoutTest(unittest.TestCase):
    def assert_preserved(self, markup):
        markup = keyboard(markup)
        before = [[copy.copy(button.__dict__) for button in row] for row in markup.inline_keyboard]
        html = rich.keyboard_html(markup)
        parsed = RichHTML(html)
        self.assertEqual([len(row) for row in parsed.rows], [len(row) for row in markup.inline_keyboard])
        for old_row, new_row in zip(markup.inline_keyboard, parsed.rows):
            for old, new in zip(old_row, new_row):
                self.assertEqual(old.text, new["label"])
                expected_style = old.style.name.lower()
                self.assertEqual(new["attrs"].get("style", "default"), expected_style)
                if old.callback_data is not None:
                    data = old.callback_data.decode() if isinstance(old.callback_data, bytes) else old.callback_data
                    self.assertEqual(new["attrs"]["data"], data)
                elif old.url is not None or old.user_id is not None:
                    self.assertEqual(new["attrs"]["url"], old.url or f"tg://user?id={old.user_id}")
        self.assertEqual(before, [[button.__dict__ for button in row] for row in markup.inline_keyboard])
        async def serialize():
            return await InputRichMessage(blocks=rich.keyboard_blocks(markup)).write(client=RecordingClient())
        native = asyncio.run(serialize())
        self.assertIsInstance(native, raw.types.InputRichMessage)
        self.assertGreater(len(native.write()), 0)
        for old_row, new_row in zip(markup.inline_keyboard, native.blocks):
            self.assertFalse(new_row.align_left or new_row.align_center or new_row.align_right)
            self.assertEqual(len(old_row), len(new_row.buttons))
            for old, new in zip(old_row, new_row.buttons):
                self.assertEqual(old.text, new.text.text)
                self.assertEqual(tuple(bool(getattr(new.style, flag, False)) for flag in ("bg_primary", "bg_success", "bg_danger")),
                                 (old.style == ButtonStyle.PRIMARY, old.style == ButtonStyle.SUCCESS, old.style == ButtonStyle.DANGER))
                if old.callback_data is not None:
                    self.assertEqual(old.callback_data.encode() if isinstance(old.callback_data, str) else old.callback_data, new.type.data)
                elif old.url is not None:
                    self.assertEqual(old.url, new.type.url)
        return parsed

    def test_layouts_actions_and_escaping(self):
        for sizes in ([1], [2], [3], [8], [1, 2, 1], [2, 2], [3, 2, 1]):
            rows = [[InlineKeyboardButton(f"A & <B> {i}:{j} ❄️", callback_data=f"data {i}|{j}&<>\"", style=list(ButtonStyle)[(i+j) % 4]) for j in range(size)] for i, size in enumerate(sizes)]
            self.assert_preserved(InlineKeyboardMarkup(rows))
        self.assert_preserved(InlineKeyboardMarkup([[InlineKeyboardButton("profile", user_id=123), InlineKeyboardButton("group", url="https://t.me/bot?startgroup=true&admin=manage_chat")], [InlineKeyboardButton("bytes", callback_data=b"unchanged")]]))

    def test_additional_supported_actions(self):
        buttons = [InlineKeyboardButton("app", web_app=WebAppInfo(url="https://example.com/app?a=1&b=2")),
                   InlineKeyboardButton("login", login_url=LoginUrl(url="https://example.com/login", forward_text='A & "B"', request_write_access=True)),
                   InlineKeyboardButton("copy", copy_text='text <>&"'),
                   InlineKeyboardButton("inline", switch_inline_query=""),
                   InlineKeyboardButton("current", switch_inline_query_current_chat="same & query")]
        html = RichHTML(rich.keyboard_html(InlineKeyboardMarkup([buttons])))
        self.assertEqual([b["attrs"]["type"] for b in html.rows[0]], ["web_app", "login_url", "copy_text", "switch_inline_query", "switch_inline_query_current_chat"])
        self.assertEqual(html.rows[0][0]["attrs"]["url"], buttons[0].web_app.url)
        self.assertEqual(html.rows[0][1]["attrs"]["forward-text"], buttons[1].login_url.forward_text)
        self.assertIn("request-write-access", html.rows[0][1]["attrs"])
        self.assertEqual(html.rows[0][2]["attrs"]["text"], buttons[2].copy_text)
        self.assertEqual(html.rows[0][3]["attrs"]["query"], "")
        self.assertEqual(html.rows[0][4]["attrs"]["query"], buttons[4].switch_inline_query_current_chat)

    def test_unsupported_never_reflows_or_changes_actions(self):
        for rows in ([], [[]], [[InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(9)]],
                     [[InlineKeyboardButton("binary", callback_data=b"\xff")]],
                     [[InlineKeyboardButton("payment", pay=True)]],
                     [[InlineKeyboardButton("password", callback_data="x", requires_password=True)]],
                     [[InlineKeyboardButton("login", login_url=LoginUrl(url="https://example.com", bot_username="another_bot"))]]):
            with self.assertRaises(rich.UnsupportedRichKeyboard):
                rich.keyboard_html(InlineKeyboardMarkup(rows))

    def test_all_locales_and_ui_builder_conditions(self):
        english = yaml.safe_load((ROOT / "strings/langs/en.yml").read_text(encoding="utf-8"))
        start = builder_namespace("utils/inline/start.py")
        extras = builder_namespace("utils/inline/extras.py")
        speed = builder_namespace("utils/inline/speed.py")
        queue = builder_namespace("utils/inline/queue.py")
        play = builder_namespace("utils/inline/play.py")
        play["time_to_seconds"] = lambda value: sum(int(part) * 60 ** i for i, part in enumerate(reversed(value.split(":"))))
        help_ui = builder_namespace("utils/inline/help.py")
        settings = builder_namespace("utils/inline/settings.py")
        stats = builder_namespace("utils/inline/stats.py")
        for path in sorted((ROOT / "strings/langs").glob("*.yml")):
            strings = english | yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(language=path.stem):
                menus = [start["private_panel"](strings), start["start_panel"](strings),
                         extras["close_markup"](strings), extras["supp_markup"](strings), extras["botplaylist_markup"](strings),
                         speed["speed_markup"](strings, -100123), queue["aq_markup"](strings, -100123),
                         help_ui["first_page"](strings), help_ui["second_page"](strings), settings["setting_markup"](strings),
                         play["livestream_markup"](strings, "video", 123, "a", "g", "d"),
                         play["track_markup"](strings, "video", 123, "g", "d"),
                         play["stream_markup"](strings, -100123),
                         play["slider_markup"](strings, "video", 123, "same query", "s", "g", "d"),
                         play["playlist_markup"](strings, "video", 123, "p", "g", "d")]
                play["LAST_UPDATE_TIME"].clear()
                menus.append(play["stream_markup_timer"](strings, -100123, "0:20", "3:00"))
                for flag in (True, False, None):
                    menus.extend([settings["auth_users_markup"](strings, flag), settings["vote_mode_markup"](strings, 3, flag),
                                  settings["playmode_users_markup"](strings, flag, flag, flag), stats["stats_buttons"](strings, flag)])
                for duration in ("Unknown", "3:00"):
                    menus.append(queue["queue_markup"](strings, duration, "g", "video", "0:20", "3:00"))
                for menu in menus:
                    self.assert_preserved(menu)
                self.assertEqual([len(r) for r in keyboard(start["private_panel"](strings)).inline_keyboard], [1, 2, 1])

    def test_conditional_lyrics_and_voiceplay_keyboards(self):
        lyrics = builder_namespace("plugins/tools/lyrics.py", {"_truncate_label", "_result_label", "_build_results_markup", "_build_lyrics_markup"})
        session = SimpleNamespace(candidates=[SimpleNamespace(title="Existing title", artist="Artist") for _ in range(4)])
        self.assert_preserved(lyrics["_build_results_markup"]("token", session))
        for total in (1, 2, 3):
            for page in range(total):
                markup = lyrics["_build_lyrics_markup"]("token", 2, page, total)
                parsed = self.assert_preserved(markup)
                expected_nav = int(page > 0) + int(page < total-1) if total > 1 else 0
                self.assertEqual([len(r) for r in parsed.rows], ([expected_nav] if expected_nav else []) + [2])
        voice = builder_namespace("plugins/admins/voiceplay.py", {"_language_keyboard"})
        self.assert_preserved(voice["_language_keyboard"](123))


class TextTest(unittest.IsolatedAsyncioTestCase):
    async def test_formatting_mentions_blocks_and_literals(self):
        texts = ['🧊 <b>bold <i>italic</i></b> & unformatted < tail',
                 '[name](tg://user?id=12345)\n`code <&>`\n**bold**',
                 '<tg-spoiler>hidden</tg-spoiler>\n<pre>  fixed\n width &amp; &lt;</pre>\ntail',
                 '<blockquote expandable>line\n<b>bold</b></blockquote>',
                 '<pre><code class="language-python">print(&quot;x&quot;)</code></pre>']
        for text in texts:
            expected = await Parser(None).parse(text)
            html = await rich.text_html(text)
            self.assertEqual("".join(RichHTML(html).content), expected["message"])
        self.assertIn('<tg-spoiler>', await rich.text_html(texts[2]))
        self.assertIn('href="tg://user?id=12345"', await rich.text_html(texts[1]))

    async def test_explicit_entities_emoji_offsets_do_not_mutate(self):
        entity = MessageEntity(type=MessageEntityType.BOLD, offset=3, length=4)
        text = "🧊 bold & tail"
        self.assertEqual(await rich.text_html(text, entities=[entity]), '<p>🧊 <b>bold</b> &amp; tail</p>')
        self.assertEqual((entity.offset, entity.length), (3, 4))
        literal = '<b>literal</b> **literal** & <'
        self.assertEqual("".join(RichHTML(await rich.text_html(literal, ParseMode.DISABLED)).content), literal)

    async def test_every_locale_text_roundtrips(self):
        for path in sorted((ROOT / "strings/langs").glob("*.yml")):
            strings = yaml.safe_load(path.read_text(encoding="utf-8"))
            for key, text in strings.items():
                if isinstance(text, str):
                    with self.subTest(language=path.stem, key=key):
                        parsed = await Parser(None).parse(text)
                        self.assertEqual("".join(RichHTML(await rich.text_html(text)).content), parsed["message"])

    async def test_native_text_serialization_for_every_locale(self):
        client = RecordingClient()
        for path in sorted((ROOT / "strings/langs").glob("*.yml")):
            for key, text in yaml.safe_load(path.read_text(encoding="utf-8")).items():
                if isinstance(text, str):
                    with self.subTest(language=path.stem, key=key):
                        blocks = await rich.text_blocks(text)
                        native = await InputRichMessage(blocks=blocks).write(client=client)
                        self.assertGreater(len(native.write()), 0)


class RuntimeAuditTest(unittest.TestCase):
    def test_no_direct_old_keyboard_delivery_or_updates(self):
        remaining = []
        for path in (ROOT / "VIVAANXMUSIC").rglob("*.py"):
            if path.name == "rich_buttons.py":
                continue
            for node in ast.walk(ast.parse(path.read_bytes())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if any(key.arg == "reply_markup" for key in node.keywords) or node.func.attr.endswith("reply_markup"):
                        remaining.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(remaining, [], "Keyboard delivery must use the shared native Rich renderer")


class RecordingClient(Client):
    """Exercise real Kurigram serialization and parsing with offline RPC responses."""

    def __init__(self):
        super().__init__("offline-rich-check", api_id=1, api_hash="offline", in_memory=True)
        self.calls, self.views = [], []
        self.photos, self.documents, self.messages = {}, {}, {}
        self.fail = False

    async def resolve_peer(self, chat_id):
        if chat_id is None:
            return raw.types.InputPeerEmpty()
        if isinstance(chat_id, str) or chat_id > 0:
            return raw.types.InputPeerUser(user_id=12345, access_hash=1)
        return raw.types.InputPeerChat(chat_id=abs(chat_id))

    async def get_messages(self, chat_id, message_ids):
        return self.messages[message_ids]

    async def save_file(self, path, **kwargs):
        return raw.types.InputFile(id=99, parts=1, name=str(path), md5_checksum="")

    async def invoke(self, query, **kwargs):
        self.calls.append((query, kwargs))
        bytes(query.write())
        if self.fail:
            raise RuntimeError("existing RPC failure")
        if isinstance(query, raw.functions.messages.UploadMedia):
            file_id = 500 + len(self.calls)
            if isinstance(query.media, (raw.types.InputMediaPhotoExternal, raw.types.InputMediaUploadedPhoto)):
                photo = raw.types.Photo(id=file_id, access_hash=1, file_reference=b"ref", date=1, dc_id=2,
                                       sizes=[raw.types.PhotoSize(type="x", w=640, h=480, size=123)])
                self.photos[file_id] = photo
                return SimpleNamespace(photo=photo)
            attributes = getattr(query.media, "attributes", None)
            if not attributes:
                url = query.media.url
                if url.endswith(".mp3"):
                    attributes = [raw.types.DocumentAttributeAudio(duration=3, title="same", performer="same")]
                elif url.endswith(".ogg"):
                    attributes = [raw.types.DocumentAttributeAudio(duration=3, voice=True)]
                elif url.endswith(".pdf"):
                    attributes = [raw.types.DocumentAttributeFilename(file_name="same.pdf")]
                else:
                    attributes = [raw.types.DocumentAttributeVideo(duration=3, w=640, h=480)]
                    if url.endswith(".gif"):
                        attributes.append(raw.types.DocumentAttributeAnimated())
            document = raw.types.Document(id=file_id, access_hash=1, file_reference=b"ref", date=1, dc_id=2,
                                          mime_type="application/octet-stream", size=123, attributes=attributes)
            self.documents[file_id] = document
            return SimpleNamespace(document=document)
        native = getattr(query, "rich_message", None)
        if isinstance(native, raw.types.InputRichMessage):
            blocks = [await types.RichBlock._parse(self, block, self.photos, self.documents) for block in native.blocks]
            message_id = getattr(query, "id", 200 + len(self.views))
            message = Message(id=message_id, chat=Chat(id=-123, type=ChatType.SUPERGROUP, title="same chat"),
                              client=self, rich_message=types.RichMessage(blocks=blocks))
            self.messages[message_id] = message
            self.views.append(message)
        if isinstance(query, raw.functions.messages.EditMessage):
            return raw.types.Updates(updates=[], users=[], chats=[], date=1, seq=1)
        return raw.types.UpdateShortSentMessage(id=200 + len(self.views) - 1, pts=1, pts_count=1, date=1, out=True)


class DeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = RecordingClient()
        self.markup = InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close", style=ButtonStyle.DANGER)]])
        self.message = Message(id=42, chat=Chat(id=-123, type=ChatType.SUPERGROUP), client=self.client,
                               text="original", message_thread_id=10)

    def assert_native(self, message_id=None):
        request = self.client.calls[-1][0]
        self.assertIsInstance(request.rich_message, raw.types.InputRichMessage)
        self.assertIsNone(request.reply_markup)
        if message_id is not None:
            self.assertEqual(request.id, message_id)
        return request

    async def test_reply_preserves_reply_topic_and_flags(self):
        await rich.rich_call(self.message.reply_text, "**same text**", reply_markup=self.markup, disable_notification=True, protect_content=True)
        request = self.assert_native()
        self.assertEqual(request.reply_to.reply_to_msg_id, 42)
        self.assertEqual(request.reply_to.top_msg_id, 10)
        self.assertTrue(request.silent)
        self.assertTrue(request.noforwards)
        self.assertEqual(rich.rich_text(self.client.views[-1]), "same text")

    async def test_client_positional_send_and_explicit_reply(self):
        await rich.rich_call(self.client.send_message, -123, "same", reply_markup=self.markup,
                             reply_parameters=ReplyParameters(message_id=99), disable_web_page_preview=True)
        self.assertEqual(self.assert_native().reply_to.reply_to_msg_id, 99)

    async def test_edit_callback_keeps_message_id_and_action(self):
        callback = CallbackQuery(client=self.client, id="query", from_user=User(id=7), chat_instance="same", message=self.message)
        await rich.rich_call(callback.edit_message_text, "updated", reply_markup=self.markup)
        request = self.assert_native(42)
        self.assertEqual(request.rich_message.blocks[-1].buttons[0].type.data, b"close")

    async def test_media_send_caption_and_markup_updates_after_restart(self):
        sent = await rich.rich_call(self.message.reply_photo, "https://example.com/same.jpg", caption="**same caption**", reply_markup=self.markup)
        self.assertIsNotNone(sent.rich_message)
        self.assertIsInstance(self.assert_native().rich_message.blocks[0], raw.types.PageBlockPhoto)
        # Only received blocks survive a process restart; no local snapshot is used.
        cold = self.client.messages[sent.id]
        self.assertFalse(hasattr(cold, "_rich_ui_blocks"))
        file_id = rich.rich_media(cold, "photo").file_id
        rows = InlineKeyboardMarkup([[InlineKeyboardButton("A", callback_data="a"), InlineKeyboardButton("B", callback_data="b"), InlineKeyboardButton("C", callback_data="c")]])
        await rich.rich_call(cold.edit_reply_markup, rows)
        updated = self.client.views[-1]
        self.assertEqual(rich.rich_media(updated, "photo").file_id, file_id)
        self.assertEqual(rich.rich_text(updated), "same caption")
        self.assertEqual(len(self.assert_native(sent.id).rich_message.blocks[-1].buttons), 3)
        await rich.rich_call(cold.edit_caption, "next caption", reply_markup=self.markup)
        self.assertEqual(rich.rich_media(self.client.views[-1], "photo").file_id, file_id)
        self.assertEqual(rich.rich_text(self.client.views[-1]), "next caption")

    async def test_all_native_media_kinds(self):
        for kind, suffix in (("photo", "jpg"), ("video", "mp4"), ("animation", "gif"), ("document", "pdf"), ("audio", "mp3"), ("voice", "ogg")):
            with self.subTest(kind=kind):
                sent = await rich.rich_call(getattr(self.message, "reply_" + kind), "https://example.com/same." + suffix,
                                            caption="same caption", reply_markup=self.markup)
                self.assert_native()
                media = rich.rich_media(sent, "voice_note" if kind == "voice" else kind)
                self.assertIsNotNone(media)
                await rich.rich_call(sent.edit_reply_markup, self.markup)
                self.assert_native(sent.id)
                self.assertEqual(rich.rich_text(self.client.views[-1]), "same caption")

    async def test_text_edit_retains_media_and_clears_buttons(self):
        sent = await rich.rich_call(self.message.reply_video, "https://example.com/same.mp4", caption="original", reply_markup=self.markup)
        video = rich.rich_media(sent, "video").file_id
        await rich.rich_call(sent.edit_text, "updated caption")
        self.assert_native(sent.id)
        self.assertEqual(rich.rich_media(self.client.views[-1], "video").file_id, video)
        self.assertEqual(rich.rich_text(self.client.views[-1]), "updated caption")
        self.assertFalse(any(isinstance(b, types.RichBlockButtons) for b in self.client.views[-1].rich_message.blocks))

    async def test_no_unsupported_or_preview_fallback(self):
        with self.assertRaises(rich.UnsupportedRichKeyboard):
            await rich.rich_call(self.client.send_message, -123, "same", reply_markup=self.markup, repeat_period=60)
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("bytes", callback_data=b"\xff")]])
        await rich.rich_call(self.client.send_message, -123, "https://example.com/page", reply_markup=buttons)
        self.assertEqual(self.assert_native().rich_message.blocks[-1].buttons[0].type.data, b"\xff")
        with self.assertRaises(rich.UnsupportedRichKeyboard):
            await rich.rich_call(self.client.send_message, -123, "same", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("pay", pay=True)]]))

    async def test_legacy_shortcut_reply_compatibility(self):
        private = Message(id=55, client=self.client, chat=Chat(id=7, type=ChatType.PRIVATE))
        await rich.rich_call(private.reply_text, "same", quote=True)
        self.assertIsNone(self.client.calls[-1][0].reply_to)
        await rich.rich_call(private.reply_text, "same", quote=True, reply_to_message_id=55, reply_markup=self.markup)
        self.assertEqual(self.assert_native().reply_to.reply_to_msg_id, 55)

    async def test_unknown_argument_and_rpc_error_do_not_fallback(self):
        with self.assertRaises(TypeError):
            await rich.rich_call(self.message.reply_text, "same", reply_markup=self.markup, unknown_flag=True)
        self.client.fail = True
        with self.assertRaises(RuntimeError):
            await rich.rich_call(self.client.send_message, -123, "same", reply_markup=self.markup)
        self.assertEqual(len(self.client.calls), 1)

    async def test_native_inline_result_content(self):
        result = await rich.rich_inline_photo(client=self.client, photo_url="https://example.com/same.jpg", caption="same", reply_markup=self.markup, title="same title")
        native = await result.write(self.client)
        self.assertIsInstance(native.send_message, raw.types.InputBotInlineMessageRichMessage)
        self.assertIsNone(native.send_message.reply_markup)
        self.assertIn('data="close"', native.send_message.rich_message.html)

    async def test_local_upload_survives_thumbnail_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            thumbnail = Path(directory) / "player.jpg"
            thumbnail.write_bytes(b"offline upload fixture")
            sent = await rich.rich_call(self.message.reply_photo, str(thumbnail), caption="same", reply_markup=self.markup)
        uploaded = rich.rich_media(sent, "photo").file_id
        count = sum(isinstance(request, raw.functions.messages.UploadMedia) for request, _ in self.client.calls)
        await rich.rich_call(sent.edit_reply_markup, self.markup)
        self.assertEqual(rich.rich_media(self.client.views[-1], "photo").file_id, uploaded)
        self.assertEqual(sum(isinstance(request, raw.functions.messages.UploadMedia) for request, _ in self.client.calls), count)

    async def test_native_actions_include_login_chosen_chats_copy_and_webapp(self):
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("app", web_app=WebAppInfo(url="https://example.com/app")),
            InlineKeyboardButton("login", login_url=LoginUrl(url="https://example.com/login", bot_username="another_bot", forward_text="same", request_write_access=True)),
            InlineKeyboardButton("copy", copy_text="unchanged text"),
            InlineKeyboardButton("inline", switch_inline_query=""),
            InlineKeyboardButton("current", switch_inline_query_current_chat="same"),
            InlineKeyboardButton("chosen", switch_inline_query_chosen_chat=types.SwitchInlineQueryChosenChat(query="same", allow_user_chats=True, allow_group_chats=True)),
        ]])
        native = await InputRichMessage(blocks=rich.keyboard_blocks(buttons)).write(client=self.client)
        self.assertGreater(len(native.write()), 0)
        actions = [button.type for button in native.blocks[0].buttons]
        self.assertEqual(actions[0].url, "https://example.com/app")
        self.assertEqual(actions[1].url, "https://example.com/login")
        self.assertTrue(actions[1].request_write_access)
        self.assertEqual(actions[1].fwd_text, "same")
        self.assertEqual(actions[2].copy_text, "unchanged text")
        self.assertEqual(actions[3].query, "")
        self.assertEqual(actions[4].query, "same")
        self.assertEqual(actions[5].query, "same")

    async def test_plain_reply_and_edit_preview_compatibility(self):
        await rich.rich_call(self.message.reply_text, "same", disable_web_page_preview=True)
        request = self.client.calls[-1][0]
        self.assertIsNone(request.rich_message)
        self.assertTrue(request.no_webpage)
        self.assertEqual(request.reply_to.reply_to_msg_id, self.message.id)
        await rich.rich_call(self.message.edit_text, "same", disable_web_page_preview=True)
        request = self.client.calls[-1][0]
        self.assertTrue(request.no_webpage)
        self.assertIsNone(request.rich_message)


if __name__ == "__main__":
    unittest.main()

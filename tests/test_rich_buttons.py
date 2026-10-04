"""Offline native serialization/layout checks; no bot credentials or startup."""

import ast
import copy
import importlib.util
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import yaml
from pyrogram import Client, raw
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
        self.assertIsInstance(InputRichMessage(html=html).write(), raw.types.InputRichMessageHTML)
        self.assertGreater(len(InputRichMessage(html=html).write().write()), 0)
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
                         play["track_markup"](strings, "video", 123, "g", "d")]
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


class RecordingClient(Client):
    def __init__(self):
        super().__init__("offline-rich-check", api_id=1, api_hash="offline", in_memory=True)
        self.calls = []
        self.fail = False

    async def resolve_peer(self, chat_id):
        if chat_id is None:
            return raw.types.InputPeerEmpty()
        return raw.types.InputPeerChat(chat_id=abs(int(chat_id)))

    async def invoke(self, query, **kwargs):
        self.calls.append((query, kwargs))
        bytes(query.write())  # Execute the installed Kurigram/MTProto serialization.
        if self.fail:
            raise RuntimeError("existing RPC failure")
        if isinstance(query, raw.functions.messages.EditMessage):
            return raw.types.Updates(updates=[], users=[], chats=[], date=1, seq=1)
        return raw.types.UpdateShortSentMessage(id=200, pts=1, pts_count=1, date=1, out=True)


class DeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = RecordingClient()
        self.markup = InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close", style=ButtonStyle.DANGER)]])
        self.message = Message(id=42, chat=Chat(id=-123, type=ChatType.SUPERGROUP), client=self.client,
                               text="original", message_thread_id=10, direct_messages_topic_id=11,
                               business_connection_id="same-business")

    async def test_reply_preserves_reply_topic_business_and_flags(self):
        await rich.rich_call(self.message.reply_text, "**same text**", reply_markup=self.markup, disable_notification=True, protect_content=True)
        request, options = self.client.calls[-1]
        self.assertIsInstance(request.rich_message, raw.types.InputRichMessageHTML)
        self.assertIsNone(request.reply_markup)
        self.assertEqual(request.reply_to.reply_to_msg_id, 42)
        self.assertEqual(request.reply_to.top_msg_id, 10)
        self.assertEqual(options["business_connection_id"], "same-business")
        self.assertTrue(request.silent)
        self.assertTrue(request.noforwards)
        self.assertEqual("".join(RichHTML(request.rich_message.html).content), "same text")

    async def test_client_positional_send_and_explicit_reply(self):
        await rich.rich_call(self.client.send_message, -123, "same", reply_markup=self.markup,
                             reply_parameters=ReplyParameters(message_id=99), disable_web_page_preview=True)
        self.assertEqual(self.client.calls[-1][0].reply_to.reply_to_msg_id, 99)
        self.assertIsNotNone(self.client.calls[-1][0].rich_message)

    async def test_edit_callback_keeps_message_id_and_action(self):
        callback = CallbackQuery(client=self.client, id="query", from_user=User(id=7), chat_instance="same", message=self.message)
        await rich.rich_call(callback.edit_message_text, "updated", reply_markup=self.markup)
        request = self.client.calls[-1][0]
        self.assertEqual(request.id, 42)
        self.assertIsNotNone(request.rich_message)
        self.assertEqual(RichHTML(request.rich_message.html).rows[0][0]["attrs"]["data"], "close")

    async def test_media_edit_keeps_original_caption_and_keyboard_method(self):
        self.message.media = MessageMediaType.VIDEO
        self.message.caption = "original caption"
        await rich.rich_call(self.message.edit_text, "updated caption", reply_markup=self.markup)
        request = self.client.calls[-1][0]
        self.assertIsNone(request.rich_message)
        self.assertIsNotNone(request.reply_markup)
        self.assertEqual(request.message, "updated caption")

    async def test_unsupported_options_and_keyboard_use_original_send(self):
        await rich.rich_call(self.client.send_message, -123, "same", reply_markup=self.markup, repeat_period=60)
        self.assertIsNone(self.client.calls[-1][0].rich_message)
        self.assertEqual(self.client.calls[-1][0].schedule_repeat_period, 60)
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("bytes", callback_data=b"\xff")]])
        await rich.rich_call(self.client.send_message, -123, "same", reply_markup=buttons)
        self.assertIsNone(self.client.calls[-1][0].rich_message)
        self.assertEqual(self.client.calls[-1][0].reply_markup.rows[0].buttons[0].data, b"\xff")
        await rich.rich_call(self.client.send_message, -123, "https://example.com/page", reply_markup=self.markup)
        self.assertIsNone(self.client.calls[-1][0].rich_message)
        await rich.rich_call(self.client.send_message, -123, "https://example.com/page", reply_markup=self.markup, disable_web_page_preview=True)
        self.assertIsNotNone(self.client.calls[-1][0].rich_message)

    async def test_rpc_error_does_not_resend_or_fallback(self):
        self.client.fail = True
        with self.assertRaises(RuntimeError):
            await rich.rich_call(self.client.send_message, -123, "same", reply_markup=self.markup)
        self.assertEqual(len(self.client.calls), 1)


if __name__ == "__main__":
    unittest.main()

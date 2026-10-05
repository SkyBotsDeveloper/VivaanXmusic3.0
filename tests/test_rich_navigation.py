"""Run real UI handler bodies with native Kurigram and offline service doubles."""

import ast
import asyncio
import __future__
import random
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import yaml
from pyrogram import Client, types, raw
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message, User

from test_rich_buttons import ROOT, RecordingClient, RichHTML, builder_namespace, keyboard, rich


def handlers(filename, **extra):
    """Strip startup/decorators only; execute the actual command/callback bodies."""
    path = ROOT / "VIVAANXMUSIC" / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for node in nodes:
        node.decorator_list = []
    ns = dict(Client=Client, types=types, Message=Message, CallbackQuery=CallbackQuery,
              InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup,
              InputMediaPhoto=InputMediaPhoto, ChatType=ChatType, FloodWait=FloodWait,
              MessageNotModified=MessageNotModified, asyncio=asyncio, random=random, re=re,
              rich_call=rich.rich_call, restore_welcome=rich.restore_welcome,
              Union=__import__("typing").Union)
    ns.update(extra)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec", flags=__future__.annotations.compiler_flag), ns)
    return ns


class NavigationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = RecordingClient()
        self.client.mention = "<b>Existing Bot</b>"
        self.client.username = "existing_bot"
        self.client.name = "Existing Bot"
        self.command = Message(id=42, client=self.client, from_user=User(id=7, first_name="Same User", client=self.client),
                               chat=types.Chat(id=-123, title="Same chat", type=ChatType.SUPERGROUP), text="/start")
        self.command.delete = AsyncMock()
        english = yaml.safe_load((ROOT / "strings/langs/en.yml").read_text(encoding="utf-8"))
        self.locales = {p.stem: english | yaml.safe_load(p.read_text(encoding="utf-8")) for p in (ROOT / "strings/langs").glob("*.yml")}

    def callback(self, data):
        # Read only server-parsed Rich blocks, as a fresh callback after restart.
        message = self.client.views[-1]
        query = CallbackQuery(client=self.client, id="query", from_user=self.command.from_user,
                              chat_instance="same", message=message, data=data)
        query.matches = [re.match("(.+)", data)]
        query.answer = AsyncMock()
        return query

    def check_view(self, markup=None, message_id=None):
        view = self.client.views[-1]
        self.assertIsNotNone(view.rich_message)
        self.assertIsNone(view.reply_markup)
        if message_id is not None:
            self.assertEqual(view.id, message_id)
        if markup is not None:
            expected = keyboard(markup).inline_keyboard
            actual = rich.rich_markup(view).inline_keyboard
            self.assertEqual([len(row) for row in actual], [len(row) for row in expected])
            for old_row, new_row in zip(expected, actual):
                for old, new in zip(old_row, new_row):
                    old_data = old.callback_data.encode() if isinstance(old.callback_data, str) else old.callback_data
                    new_data = new.callback_data.encode() if isinstance(new.callback_data, str) else new.callback_data
                    old_url = f"tg://user?id={old.user_id}" if old.user_id is not None else old.url
                    self.assertEqual((old.text, old_data, old_url, old.style), (new.text, new_data, new.url, new.style))
        for request, _ in self.client.calls:
            if isinstance(request, (raw.functions.messages.SendMessage, raw.functions.messages.EditMessage)):
                self.assertIsInstance(request.rich_message, raw.types.InputRichMessage)
                self.assertIsNone(request.reply_markup)
                for block in request.rich_message.blocks:
                    if isinstance(block, raw.types.PageBlockButtonRow):
                        self.assertFalse(block.align_left or block.align_center or block.align_right)
        return view

    async def test_start_help_category_back_home_all_five_languages(self):
        start_ui = builder_namespace("utils/inline/start.py")
        help_ui = builder_namespace("utils/inline/help.py")
        start = handlers("plugins/bot/start.py", app=self.client)
        help_handlers = handlers("plugins/bot/help.py", app=self.client, **{k: v for k, v in help_ui.items() if callable(v)},
                                 private_panel=start_ui["private_panel"], get_lang=AsyncMock(return_value="en"),
                                 get_string=lambda code: self.locales[code], helpers=SimpleNamespace(HELP_2="**Existing category text**"),
                                 SUPPORT_CHAT="https://t.me/support", START_VIDS=["https://example.com/welcome.mp4"])
        for locale, strings in self.locales.items():
            with self.subTest(language=locale):
                help_handlers["get_lang"].return_value = locale
                caption = strings["start_2"].format(self.command.from_user.mention, self.client.mention)
                buttons = start_ui["private_panel"](strings)
                await start["_send_start_message"](self.command, "https://example.com/welcome.mp4", caption, buttons)
                message_id = self.check_view(buttons).id
                await help_handlers["helper_private"](self.client, self.callback("open_help"), strings)
                self.check_view(help_ui["first_page"](strings), message_id)
                await help_handlers["helper_cb"](self.client, self.callback("help_callback hb2_p1"), strings)
                self.check_view(help_ui["help_back_markup"](strings, 1), message_id)
                await help_handlers["help_back_cb"](self.client, self.callback("help_back_1"), strings)
                self.check_view(help_ui["first_page"](strings), message_id)
                await help_handlers["help_next_cb"](self.client, self.callback("help_next_2"), strings)
                self.check_view(help_ui["second_page"](strings), message_id)
                await help_handlers["help_prev_cb"](self.client, self.callback("help_prev_1"), strings)
                self.check_view(help_ui["first_page"](strings), message_id)
                await help_handlers["back_to_main_cb"](self.client, self.callback("back_to_main"), strings)
                restored = self.check_view(buttons, message_id)
                self.assertIsNotNone(rich.rich_media(restored, "video"))
                self.assertEqual(rich.rich_text(restored), "".join(RichHTML(await rich.text_html(caption)).content))

    async def test_settings_option_auth_admin_back_and_language(self):
        ui = builder_namespace("utils/inline/settings.py")
        start_ui = builder_namespace("utils/inline/start.py")
        settings = handlers("plugins/bot/settings.py", app=self.client, **{k: v for k, v in ui.items() if callable(v)},
                            private_panel=start_ui["private_panel"], OWNER_ID=12345, START_VIDS=["https://example.com/welcome.mp4"],
                            get_playmode=AsyncMock(return_value="Direct"), get_playtype=AsyncMock(return_value="Everyone"),
                            is_nonadmin_chat=AsyncMock(return_value=False), set_playmode=AsyncMock(),
                            add_nonadmin_chat=AsyncMock(), remove_nonadmin_chat=AsyncMock())
        languages = handlers("plugins/Manager/language.py", app=self.client, languages_present={code: code for code in self.locales},
                             get_string=lambda code: self.locales[code], get_lang=AsyncMock(return_value="old"), set_lang=AsyncMock())
        for locale, strings in self.locales.items():
            with self.subTest(language=locale):
                await settings["settings_mar"](self.client, self.command, strings)
                message_id = self.check_view(ui["setting_markup"](strings)).id
                await settings["without_admin_rights"](self.client, self.callback("PM"), strings)
                self.check_view(ui["playmode_users_markup"](strings, True, True, None), message_id)
                await settings["playmode_ans"](self.client, self.callback("MODECHANGE"), strings)
                self.check_view(ui["playmode_users_markup"](strings, None, True, False), message_id)
                settings["set_playmode"].assert_awaited_with(-123, "Inline")
                await settings["settings_back_markup"](self.client, self.callback("settingsback_helper"), strings)
                self.check_view(ui["setting_markup"](strings), message_id)
                await settings["without_admin_rights"](self.client, self.callback("AU"), strings)
                self.check_view(ui["auth_users_markup"](strings, True), message_id)
                await settings["authusers_mar"](self.client, self.callback("AUTH"), strings)
                self.check_view(ui["auth_users_markup"](strings), message_id)
                settings["add_nonadmin_chat"].assert_awaited_with(-123)
                await settings["settings_back_markup"](self.client, self.callback("settingsback_helper"), strings)
                self.check_view(ui["setting_markup"](strings), message_id)
                await languages["languagecb"](self.client, self.callback("LG"), strings)
                self.check_view(languages["languages_keyboard"](strings), message_id)
                await languages["language_markup"](self.client, self.callback("languages:" + locale), strings)
                self.check_view(languages["languages_keyboard"](strings), message_id)
                languages["set_lang"].assert_awaited_with(-123, locale)
                callback = self.callback("settingsback_helper")
                callback.message.chat.type = ChatType.PRIVATE
                await settings["settings_back_markup"](self.client, callback, strings)
                self.check_view(start_ui["private_panel"](strings), message_id)

    async def test_song_format_selection_and_back(self):
        class Builder(list):
            def row(self, *buttons):
                self.append(list(buttons))

        ui = builder_namespace("utils/inline/song.py")
        formats = [{"format": "audio", "format_note": "Low", "filesize": 123, "format_id": "140"},
                   {"format": "audio", "format_note": "High", "filesize": 456, "format_id": "141"}]
        songs = handlers("plugins/tools/song.py", app=self.client, song_markup=ui["song_markup"],
                         InlineKeyboardBuilder=Builder, convert_bytes=lambda value: str(value),
                         YouTube=SimpleNamespace(formats=AsyncMock(return_value=(formats, None))))
        for strings in self.locales.values():
            await rich.rich_call(self.command.reply_photo, "https://example.com/song.jpg", caption="Same song information",
                                 reply_markup=keyboard(ui["song_markup"](strings, "video-id")))
            message_id = self.check_view().id
            await songs["song_helper_cb"](self.client, self.callback("song_helper audio|video-id"), strings)
            buttons = rich.rich_markup(self.check_view(message_id=message_id))
            self.assertEqual([len(r) for r in buttons.inline_keyboard], [1, 1, 2])
            self.assertEqual(buttons.inline_keyboard[0][0].callback_data, "song_download audio|140|video-id")
            await songs["songs_back_helper"](self.client, self.callback("song_back audio|video-id"), strings)
            self.check_view(ui["song_markup"](strings, "video-id"), message_id)

    async def test_player_card_pause_resume_timer_queue_back(self):
        strings = self.locales["en"]
        play_ui = builder_namespace("utils/inline/play.py")
        play_ui["time_to_seconds"] = lambda value: sum(int(part) * 60 ** i for i, part in enumerate(reversed(value.split(":"))))
        queue_ui = builder_namespace("utils/inline/queue.py")
        extras = builder_namespace("utils/inline/extras.py")
        playlist = {-123: [{"vidid": "video-id", "file": "live_source", "by": "Same User", "title": "Same song", "streamtype": "audio", "seconds": 0, "played": 0, "dur": "3:00"},
                           {"title": "Next song", "dur": "3:00", "by": "Same User"}]}
        cards = handlers("utils/stream/cards.py", app=self.client, db=playlist, get_thumb=AsyncMock(return_value="https://example.com/player.jpg"), remember_player_message=lambda *a: None)
        controls = play_ui["stream_markup"](strings, -123)
        await cards["_deliver_stream_card"](-123, -123, "video-id", 7, "Same player caption", controls)
        player = self.check_view(controls)
        self.assertIsNotNone(playlist[-123][0]["mystic"].rich_message)
        jarvis = SimpleNamespace(pause_stream=AsyncMock(), resume_stream=AsyncMock())
        admins = handlers("plugins/admins/callback.py", app=self.client, SUDOERS={7}, adminlist={},
                          is_active_chat=AsyncMock(return_value=True), is_nonadmin_chat=AsyncMock(return_value=False),
                          is_music_playing=AsyncMock(return_value=True), music_off=AsyncMock(), music_on=AsyncMock(),
                          JARVIS=jarvis, close_markup=extras["close_markup"])
        await admins["manage_callback"](self.client, self.callback("ADMIN Pause|-123"), strings)
        self.check_view(extras["close_markup"](strings))
        jarvis.pause_stream.assert_awaited_with(-123)
        self.client.views.append(player)
        admins["is_music_playing"].return_value = False
        await admins["manage_callback"](self.client, self.callback("ADMIN Resume|-123"), strings)
        self.check_view(extras["close_markup"](strings))
        jarvis.resume_stream.assert_awaited_with(-123)
        await rich.rich_call(player.edit_reply_markup, keyboard(play_ui["stream_markup_timer"](strings, -123, "0:20", "3:00")))
        self.check_view(message_id=player.id)
        self.assertEqual(len(rich.rich_markup(self.client.views[-1]).inline_keyboard[1]), 5)
        self.assertEqual(rich.rich_text(self.client.views[-1]), "Same player caption")
        queue = handlers("plugins/tools/queue.py", app=self.client, db=playlist, basic={},
                         Path=Path, __file__=str(ROOT / "VIVAANXMUSIC/plugins/tools/queue.py"),
                         queue_markup=queue_ui["queue_markup"], queue_back_markup=queue_ui["queue_back_markup"],
                         is_active_chat=AsyncMock(return_value=True), get_channeplayCB=AsyncMock(return_value=(-123, False)),
                         config=SimpleNamespace(YOUTUBE_IMG_URL="https://example.com/player.jpg"),
                         os=__import__("os"), asyncio=SimpleNamespace(sleep=AsyncMock()))
        self.command.command = ["queue"]
        await queue["get_queue"](self.client, self.command, strings)
        message_id = self.check_view(queue_ui["queue_markup"](strings, "Unknown", "g", "video-id")).id
        await queue["queued_tracks"](self.client, self.callback("GetQueued g|video-id"), strings)
        self.check_view(queue_ui["queue_back_markup"](strings, "g"), message_id)
        await queue["queue_back"](self.client, self.callback("queue_back_timer g"), strings)
        self.check_view(queue_ui["queue_markup"](strings, "Unknown", "g", "video-id"), message_id)

    async def test_fonts_pagination_and_style_after_restart(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("offline_fonts", ROOT / "VIVAANXMUSIC/utils/font_styles.py")
        fonts_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fonts_module)
        fonts = handlers("plugins/Kishu/fonts.py", rich_text=rich.rich_text, rich_markup=rich.rich_markup,
                         Fonts=fonts_module.Fonts, FONT_TEXT_CACHE={})
        tree = ast.parse((ROOT / "VIVAANXMUSIC/plugins/Kishu/fonts.py").read_text(encoding="utf-8"))
        constants = [n for n in tree.body if isinstance(n, ast.Assign)]
        exec(compile(ast.Module(body=constants, type_ignores=[]), "fonts constants", "exec"), fonts)
        self.command.text = "/font Same source text"
        self.command.command = ["font", "Same", "source", "text"]
        await fonts["style_buttons"](self.client, self.command)
        message_id = self.check_view(fonts["_build_buttons"](0)).id
        await fonts["nxt"](None, self.callback("nxt"))
        self.check_view(fonts["_build_buttons"](1), message_id)
        fonts["FONT_TEXT_CACHE"].clear()
        await fonts["style"](None, self.callback("style+typewriter"))
        self.check_view(fonts["_build_buttons"](1), message_id)
        self.assertEqual(rich.rich_text(self.client.views[-1]), fonts["STYLE_MAP"]["typewriter"]("Same source text"))
        await fonts["nxt"](None, self.callback("nxt+0"))
        self.check_view(fonts["_build_buttons"](0), message_id)

    async def test_stats_media_submenu_back(self):
        ui = builder_namespace("utils/inline/stats.py")
        stats = handlers("plugins/tools/stats.py", app=self.client, stats_buttons=ui["stats_buttons"],
                         back_stats_buttons=ui["back_stats_buttons"], SUDOERS={7}, assistants=[1], BANNED_USERS=set(),
                         ALL_MODULES=["existing"], get_served_chats=AsyncMock(return_value=[-123]),
                         get_served_users=AsyncMock(return_value=[7]), InputMediaVideo=types.InputMediaVideo,
                         config=SimpleNamespace(STATS_VID_URL="https://example.com/stats.mp4", AUTO_LEAVING_ASSISTANT=True, DURATION_LIMIT_MIN=10))
        for strings in self.locales.values():
            await stats["stats_global"](self.client, self.command, strings)
            message_id = self.check_view(ui["stats_buttons"](strings, True)).id
            await stats["overall_stats"](self.client, self.callback("TopOverall"), strings)
            self.check_view(ui["back_stats_buttons"](strings), message_id)
            await stats["home_stats"](self.client, self.callback("stats_back"), strings)
            self.check_view(ui["stats_buttons"](strings, True), message_id)
            self.assertIsNotNone(rich.rich_media(self.client.views[-1], "video"))


if __name__ == "__main__":
    unittest.main()

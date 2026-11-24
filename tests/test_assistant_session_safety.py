"""Guard against creating concurrent Pyrogram clients for one auth session."""
import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace as NS


ROOT = Path(__file__).resolve().parents[1]


def _load_call_constructor():
    source = (ROOT / "VIVAANXMUSIC/core/call.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    call_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Call"
    )
    init = next(
        node for node in call_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    call_class.body = [init]
    module = ast.Module(body=[call_class], type_ignores=[])

    class FakePyTgCalls:
        def __init__(self, app):
            self.app = app

    env = {
        "asyncio": asyncio,
        "config": NS(STRING1="session-1", STRING2="session-2", STRING3="", STRING4="", STRING5=""),
        "userbot": NS(
            one=object(), two=object(), three=object(), four=object(), five=object()
        ),
        "PyTgCalls": FakePyTgCalls,
        "VcIdentityResolver": type("VcIdentityResolver", (), {}),
        "PlaybackRecovery": lambda call: ("recovery", call),
    }
    exec(compile(ast.fix_missing_locations(module), "call_constructor_test", "exec"), env)
    return env["Call"](), env


class AssistantSessionSafetyTests(unittest.TestCase):
    def test_call_reuses_authenticated_clients_for_voice_calls(self):
        call, env = _load_call_constructor()
        self.assertIs(call.userbot1, env["userbot"].one)
        self.assertIs(call.userbot2, env["userbot"].two)
        self.assertIsNone(call.userbot3)
        self.assertIs(call.one.app, env["userbot"].one)
        self.assertIs(call.two.app, env["userbot"].two)
        self.assertIsNone(call.three)

    def test_duplicate_session_values_are_detected_without_exposing_them(self):
        source = (ROOT / "VIVAANXMUSIC/core/userbot.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        selected = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_has_session", "_duplicate_session_slots"}
        ]
        env = {"config": NS(
            STRING1="same-session", STRING2="same-session", STRING3=None,
            STRING4="different-session", STRING5=None,
        )}
        exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), "session_guard_test", "exec"), env)
        self.assertEqual(env["_duplicate_session_slots"](), [(1, 2)])

    def test_botschk_uses_live_singleton_and_does_not_stop_it(self):
        source = (ROOT / "VIVAANXMUSIC/plugins/sudo/botschk.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        userbot_imports = [
            alias.name
            for node in tree.body if isinstance(node, ast.ImportFrom)
            and node.module == "VIVAANXMUSIC"
            for alias in node.names
        ]
        self.assertIn("userbot", userbot_imports)
        self.assertNotIn("Userbot", source)
        self.assertFalse(any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stop"
            for node in ast.walk(tree)
        ))


if __name__ == "__main__":
    unittest.main()

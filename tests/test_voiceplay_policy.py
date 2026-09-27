import ast
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "VIVAANXMUSIC"
    / "utils"
    / "voiceplay_policy.py"
)
SPEC = importlib.util.spec_from_file_location("voiceplay_policy", MODULE_PATH)
voiceplay_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voiceplay_policy)


class VoicePlayPolicyTest(unittest.TestCase):
    def test_prompts_only_after_finished_final_track(self):
        self.assertTrue(
            voiceplay_policy.should_prompt_after_track(
                enabled=True,
                call_active=True,
                queue_empty=True,
                track_finished=True,
            )
        )

    def test_does_not_prompt_when_song_starts(self):
        self.assertFalse(
            voiceplay_policy.should_prompt_after_track(
                enabled=True,
                call_active=True,
                queue_empty=True,
                track_finished=False,
            )
        )

    def test_does_not_interrupt_when_another_song_is_queued(self):
        self.assertFalse(
            voiceplay_policy.should_prompt_after_track(
                enabled=True,
                call_active=True,
                queue_empty=False,
                track_finished=True,
            )
        )

    def test_does_not_prompt_when_feature_is_disabled(self):
        self.assertFalse(
            voiceplay_policy.should_prompt_after_track(
                enabled=False,
                call_active=True,
                queue_empty=True,
                track_finished=True,
            )
        )

    def test_call_controller_only_schedules_prompt_from_queue_end(self):
        call_path = MODULE_PATH.parents[1] / "core" / "call.py"
        tree = ast.parse(call_path.read_text(encoding="utf-8"))
        call_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Call"
        )
        scheduling_methods = []
        for method in call_class.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_schedule_voiceplay_round"
                for node in ast.walk(method)
            ):
                scheduling_methods.append(method.name)

        self.assertEqual(scheduling_methods, ["_stop_if_queue_empty"])

    def test_three_failed_attempts_do_not_disable_group_setting(self):
        manager_path = MODULE_PATH.parent / "voiceplay.py"
        tree = ast.parse(manager_path.read_text(encoding="utf-8"))
        manager_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "VoicePlayManager"
        )
        failed_attempt = next(
            node
            for node in manager_class.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_failed_attempt"
        )
        setting_writes = [
            node
            for node in ast.walk(failed_attempt)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "set_voiceplay"
        ]
        self.assertEqual(setting_writes, [])

    def test_autoplay_and_voiceplay_enablers_are_mutually_exclusive(self):
        database_path = MODULE_PATH.parent / "database.py"
        tree = ast.parse(database_path.read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
        }

        def called_names(function_name):
            return [
                getattr(node.func, "id", None)
                for node in ast.walk(functions[function_name])
                if isinstance(node, ast.Call)
            ]

        autoplay_calls = called_names("enable_autoplay_exclusive")
        voiceplay_calls = called_names("enable_voiceplay_exclusive")
        self.assertIn("set_voiceplay", autoplay_calls)
        self.assertIn("set_autoplay", autoplay_calls)
        self.assertLess(
            autoplay_calls.index("set_voiceplay"),
            autoplay_calls.index("set_autoplay"),
        )
        self.assertIn("set_autoplay", voiceplay_calls)
        self.assertIn("set_voiceplay", voiceplay_calls)
        self.assertLess(
            voiceplay_calls.index("set_autoplay"),
            voiceplay_calls.index("set_voiceplay"),
        )

    def test_admin_handlers_use_exclusive_mode_switches(self):
        admins_path = MODULE_PATH.parents[1] / "plugins" / "admins"
        expectations = {
            "autoplay.py": ("autoplay_control", "enable_autoplay_exclusive"),
            "voiceplay.py": ("voiceplay_callback", "enable_voiceplay_exclusive"),
        }

        for filename, (handler_name, exclusive_call) in expectations.items():
            tree = ast.parse((admins_path / filename).read_text(encoding="utf-8"))
            handler = next(
                node
                for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == handler_name
            )
            calls = {
                getattr(node.func, "id", None)
                for node in ast.walk(handler)
                if isinstance(node, ast.Call)
            }
            self.assertIn(exclusive_call, calls)

    def test_queue_end_heals_legacy_both_enabled_state(self):
        call_path = MODULE_PATH.parents[1] / "core" / "call.py"
        tree = ast.parse(call_path.read_text(encoding="utf-8"))
        call_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Call"
        )
        stop_method = next(
            node
            for node in call_class.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_stop_if_queue_empty"
        )
        calls = {
            getattr(node.func, "id", None)
            for node in ast.walk(stop_method)
            if isinstance(node, ast.Call)
        }
        self.assertIn("set_autoplay", calls)


if __name__ == "__main__":
    unittest.main()

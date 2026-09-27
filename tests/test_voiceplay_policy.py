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


if __name__ == "__main__":
    unittest.main()

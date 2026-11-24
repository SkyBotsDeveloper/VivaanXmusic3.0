import ast
import re
import unittest
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "VIVAANXMUSIC/utils/stream/playback_recovery.py"
)
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
FUNCTIONS = {"_safe_int", "_stored_track", "_restore_queue"}
NODES = [
    node
    for node in TREE.body
    if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
]
RECOVERY = {
    "re": re,
    "YOUTUBE_ID": re.compile(r"^[A-Za-z0-9_-]{11}$"),
}
exec(compile(ast.Module(body=NODES, type_ignores=[]), str(SOURCE), "exec"), RECOVERY)


class PlaybackRecoveryMetadataTests(unittest.TestCase):
    def test_checkpoint_keeps_position_and_omits_local_or_signed_source(self):
        stored = RECOVERY["_stored_track"](
            {
                "vidid": "dQw4w9WgXcQ",
                "file": "vid_dQw4w9WgXcQ",
                "source_url": "https://cdn.example/media?signature=temporary-secret",
                "title": "Test Song",
                "dur": "3:32",
                "seconds": 209,
                "played": 74,
                "streamtype": "audio",
                "chat_id": -100123,
                "user_id": 42,
            }
        )
        self.assertEqual(stored["played"], 74)
        self.assertEqual(stored["vidid"], "dQw4w9WgXcQ")
        self.assertNotIn("file", stored)
        self.assertNotIn("signature", repr(stored))

    def test_speed_adjusted_position_is_saved_on_original_youtube_timeline(self):
        stored = RECOVERY["_stored_track"](
            {
                "vidid": "dQw4w9WgXcQ",
                "file": "vid_dQw4w9WgXcQ",
                "title": "Test Song",
                "dur": "3:32",
                "seconds": 209,
                "played": 40,
                "speed": 2.0,
            }
        )
        self.assertEqual(stored["played"], 80)

    def test_restore_rebuilds_canonical_youtube_queue_path(self):
        queue = RECOVERY["_restore_queue"](
            [{
                "vidid": "dQw4w9WgXcQ",
                "title": "Test Song",
                "dur": "3:32",
                "seconds": 209,
                "played": 74,
                "streamtype": "audio",
            }]
        )
        self.assertEqual(queue[0]["file"], "vid_dQw4w9WgXcQ")
        self.assertEqual(queue[0]["played"], 74)

    def test_live_youtube_stream_can_be_rejoined_but_local_media_is_skipped(self):
        live = RECOVERY["_stored_track"](
            {"vidid": "dQw4w9WgXcQ", "file": "live_dQw4w9WgXcQ", "played": 0}
        )
        self.assertTrue(live["live"])
        self.assertEqual(live["dur"], "Live")
        self.assertIsNone(
            RECOVERY["_stored_track"](
                {"vidid": "telegram", "file": "downloads/temporary.mp3", "seconds": 90}
            )
        )


if __name__ == "__main__":
    unittest.main()

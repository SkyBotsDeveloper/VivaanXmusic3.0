import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "VIVAANXMUSIC" / "utils" / "voiceplay_text.py"
)
SPEC = importlib.util.spec_from_file_location("voiceplay_text", MODULE_PATH)
voiceplay_text = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voiceplay_text)


class SongQueryCandidatesTest(unittest.TestCase):
    def test_english_command(self):
        self.assertEqual(
            voiceplay_text.song_query_candidates("play Sanam Re")[0].casefold(),
            "sanam re",
        )

    def test_hinglish_suffix(self):
        self.assertEqual(
            voiceplay_text.song_query_candidates("Sanam Re song bajao")[0].casefold(),
            "sanam re",
        )

    def test_hinglish_phrase(self):
        self.assertEqual(
            voiceplay_text.song_query_candidates("Sanam Re laga do")[0].casefold(),
            "sanam re",
        )

    def test_raw_transcript_is_fallback(self):
        candidates = voiceplay_text.song_query_candidates(
            "please put on Blinding Lights"
        )
        self.assertIn("please put on Blinding Lights", candidates)

    def test_empty_input(self):
        self.assertEqual(voiceplay_text.song_query_candidates("..."), [])

    def test_devanagari_command(self):
        self.assertEqual(
            voiceplay_text.song_query_candidates("सनम रे गाना बजाओ")[0],
            "सनम रे",
        )

    def test_punctuation_is_normalized(self):
        self.assertEqual(
            voiceplay_text.song_query_candidates("Play, Sanam Re!!!")[0].casefold(),
            "sanam re",
        )

    def test_transcript_ranking_prefers_higher_confidence(self):
        ranked = voiceplay_text.rank_transcripts(
            [
                ("wrong title", 0.41, 0, 0),
                ("Aaj Ki Raat", 0.91, 1, 0),
            ]
        )
        self.assertEqual(ranked[0], "Aaj Ki Raat")

    def test_transcript_ranking_deduplicates_locales(self):
        ranked = voiceplay_text.rank_transcripts(
            [
                ("Sanam Re", None, 0, 0),
                ("sanam re", None, 1, 0),
            ]
        )
        self.assertEqual(len(ranked), 1)


if __name__ == "__main__":
    unittest.main()

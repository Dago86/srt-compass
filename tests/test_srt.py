import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.models import Word
from video_sottotitoli.srt import (
    captions_from_response,
    compose_captions,
    detected_language,
    render_srt,
    words_from_response,
)


class SrtTests(unittest.TestCase):
    def test_normalizes_french_language_name_and_code(self) -> None:
        self.assertEqual(detected_language({"language": "French"}), "fr")
        self.assertEqual(detected_language({"language": "fr"}), "fr")

    def test_auto_uses_whisper_japanese_language(self) -> None:
        response = {
            "language": "japanese",
            "segments": [{"text": "これはテストです。", "start": 0, "end": 2}],
            "words": [{"word": "これは", "start": 0, "end": 1}],
        }
        self.assertEqual(detected_language(response), "ja")
        captions = captions_from_response(response, 2400, "auto")
        self.assertEqual(captions[0].lines, ("これはテストです。",))

    def test_japanese_uses_timed_segments_without_artificial_spaces(self) -> None:
        response = {
            "text": "これはテストです。次です。",
            "segments": [
                {"text": "これはテストです。", "start": 0, "end": 2},
                {"text": "次です。", "start": 2, "end": 3},
            ],
            "words": [],
        }
        captions = captions_from_response(response, 2400, "ja")
        self.assertEqual(captions[0].lines, ("これはテストです。",))
        self.assertEqual(captions[0].start, 2400)
        self.assertEqual(captions[1].end, 2403)
    def test_renders_standard_timestamp_and_utf8_text(self) -> None:
        captions = compose_captions(
            [
                Word("Hello", 0.1, 0.5),
                Word("world.", 0.6, 1.2),
                Word("Café", 2.0, 2.4),
            ]
        )
        output = render_srt(captions)
        self.assertIn("00:00:00,100 --> 00:00:01,200", output)
        self.assertIn("Hello world.", output)
        self.assertIn("Café", output)

    def test_keeps_captions_in_time_order_without_overlap(self) -> None:
        captions = compose_captions(
            [
                Word("One.", 0.0, 1.0),
                Word("Two.", 0.8, 1.4),
            ]
        )
        self.assertGreaterEqual(captions[1].start, captions[0].end)

    def test_wraps_long_caption_on_words(self) -> None:
        words = [
            Word(word, index * 0.2, index * 0.2 + 0.1)
            for index, word in enumerate(
                [
                    "This",
                    "sentence",
                    "has",
                    "enough",
                    "separate",
                    "words",
                    "to",
                    "need",
                    "two",
                    "subtitle",
                    "lines",
                    "for",
                    "readability.",
                ]
            )
        ]
        captions = compose_captions(words)
        self.assertTrue(all(len(caption.lines) <= 2 for caption in captions))

    def test_punctuation_and_absolute_offset_are_preserved(self) -> None:
        response = {
            "text": "Hello world.",
            "segments": [{"text": "Hello world."}],
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.4},
                {"word": "world", "start": 0.5, "end": 0.9},
            ],
        }

        words = words_from_response(response, 40 * 60)

        self.assertEqual([word.text for word in words], ["Hello", "world."])
        self.assertEqual(words[0].start, 2400.0)
        self.assertEqual(words[1].end, 2400.9)


if __name__ == "__main__":
    unittest.main()

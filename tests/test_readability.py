import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.models import Caption
from video_sottotitoli.readability import grapheme_count, segment_captions
from video_sottotitoli.srt import format_srt_file, parse_srt, render_srt


class ReadabilityTests(unittest.TestCase):
    def test_long_italian_cue_is_split_without_losing_text_or_outer_times(self) -> None:
        text = (
            "Nello stesso periodo comincia anche la storia di Satoshi. "
            "Lo schema è identico: un ragazzino vivace che vive un'estate senza fine. "
            "Dopo lo scoppio della bolla economica arrivano tempi difficili."
        )
        source = Caption(600.0, 628.82, (text,))
        result = segment_captions([source], "it")
        self.assertGreater(len(result.captions), 1)
        self.assertEqual(result.captions[0].start, source.start)
        self.assertEqual(result.captions[-1].end, source.end)
        self.assertTrue(all(len(c.lines) <= 2 for c in result.captions))
        self.assertTrue(all(len(line) <= 42 for c in result.captions for line in c.lines))
        self.assertTrue(all(c.end > c.start for c in result.captions))
        self.assertTrue(all(
            result.captions[i].end == result.captions[i + 1].start
            for i in range(len(result.captions) - 1)
        ))
        restored = "".join("".join("".join(c.lines).split()) for c in result.captions)
        self.assertEqual(restored, "".join(text.split()))
        self.assertEqual(result.id_map[1], (1, len(result.captions)))
        self.assertEqual(segment_captions(result.captions, "it").captions, result.captions)

    def test_japanese_without_spaces_and_unicode_combining_marks(self) -> None:
        japanese = "これは長い説明です。次の話題に進みます。" * 8
        combining = "e\u0301" * 48
        result = segment_captions([
            Caption(2400, 2430, (japanese,)),
            Caption(2431, 2440, (combining,)),
        ], "auto")
        self.assertTrue(all(
            grapheme_count(line) <= (21 if i <= result.id_map[1][1] else 42)
            for i, caption in enumerate(result.captions, 1) for line in caption.lines
        ))
        self.assertEqual(
            "".join("".join(c.lines) for c in result.captions[:result.id_map[1][1]]),
            japanese,
        )
        self.assertEqual(
            "".join("".join(c.lines) for c in result.captions[result.id_map[2][0] - 1:]),
            combining,
        )
        self.assertTrue(all(not line.startswith("\u0301")
                            for c in result.captions for line in c.lines))
        self.assertEqual(grapheme_count("🇮🇹"), 1)
        self.assertEqual(grapheme_count("👩‍💻"), 1)

    def test_existing_japanese_line_breaks_do_not_insert_spaces(self) -> None:
        source = "1\n00:00:01,000 --> 00:00:05,000\nこれは長い説明です。\n次の話題です。\n"
        captions = parse_srt(source)
        self.assertEqual(captions[0].lines, ("これは長い説明です。次の話題です。",))

    def test_format_existing_srt_preserves_source_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.srt"
            output = Path(temporary) / "input_formatted.srt"
            text = "Una frase lunga, con molte parole, che continua per parecchio tempo. " * 5
            original = render_srt([Caption(20.0, 40.0, (text,))])
            source.write_text(original, encoding="utf-8")
            original_report = source.with_name("input.problemi.txt")
            original_report.write_text("Problema originale: nome incerto.\n", encoding="utf-8")
            format_srt_file(source, output)
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertEqual(
                original_report.read_text(encoding="utf-8"),
                "Problema originale: nome incerto.\n",
            )
            companion = output.with_name("input_formatted.problemi.txt")
            report = companion.read_text(encoding="utf-8")
            self.assertIn("Originale 1 → finale 1–", report)
            self.assertIn("Problema originale: nome incerto.", report)
            captions = parse_srt(output.read_text(encoding="utf-8"))
            self.assertGreater(len(captions), 1)
            self.assertEqual(captions[0].start, 20.0)
            self.assertEqual(captions[-1].end, 40.0)
            with self.assertRaises(FileExistsError):
                format_srt_file(source, output)
            with self.assertRaises(ValueError):
                format_srt_file(source, source)

    def test_english_interval_and_unbreakable_word(self) -> None:
        word = "A" * 100
        source = [Caption(2400.0, 3000.0, (f"First sentence. {word} Last sentence.",))]
        result = segment_captions(source, "en")
        self.assertEqual(result.captions[0].start, 2400.0)
        self.assertEqual(result.captions[-1].end, 3000.0)
        self.assertTrue(all(2400 <= c.start < c.end <= 3000 for c in result.captions))
        self.assertTrue(any("parola lunga divisa" in note for note in result.warnings))
        self.assertTrue(all(len(line) <= 42 for c in result.captions for line in c.lines))
        joined = "".join("".join(c.lines).replace(" ", "") for c in result.captions)
        self.assertEqual(joined, "".join(source[0].lines).replace(" ", ""))

    def test_short_interval_warns_when_millisecond_timing_is_impossible(self) -> None:
        source = Caption(1.0, 1.001, ("parola " * 40,))
        result = segment_captions([source], "it")
        self.assertEqual(result.captions, [source])
        self.assertTrue(any("durata troppo breve" in item for item in result.warnings))


if __name__ == "__main__":
    unittest.main()

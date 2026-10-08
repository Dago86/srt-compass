import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.config import MODEL_MINI
from video_sottotitoli.models import Caption
from video_sottotitoli.revision import (
    OPERATION_TRANSLATION,
    REVISION_MODE_LINGUISTIC,
    apply_revisions,
    build_groups,
    build_units,
    estimate_revision,
    japanese_signature,
    parse_revision_srt,
    quality_warnings,
    revision_instructions,
    suggest_source_language,
    validate_revised_items,
    word_signature,
)


class RevisionTests(unittest.TestCase):
    def test_japanese_srt_suggests_source_without_guessing_english(self) -> None:
        self.assertEqual(
            suggest_source_language([Caption(0, 2, ("これは日本語の文章です。もう一度書きます。",))]),
            "ja",
        )
        self.assertIsNone(
            suggest_source_language([Caption(0, 2, ("This is English.",))])
        )

    def test_translation_directions_build_with_sol(self) -> None:
        captions = [Caption(0, 2, ("sample 12",))]
        for source in ("en", "it", "ja"):
            for target in ("en", "it", "ja"):
                if source == target:
                    continue
                estimate = estimate_revision(
                    captions, operation=OPERATION_TRANSLATION,
                    source_language=source, target_language=target,
                )
                self.assertGreater(estimate.cost_usd, 0)

    def test_french_source_builds_translation_to_existing_targets(self) -> None:
        captions = [Caption(0, 2, ("Bonjour à tous.",))]
        for target in ("en", "it", "ja"):
            with self.subTest(target=target):
                instructions = revision_instructions(
                    REVISION_MODE_LINGUISTIC,
                    operation=OPERATION_TRANSLATION,
                    source_language="fr",
                    target_language=target,
                )
                self.assertIn("Francese", instructions)
                estimate = estimate_revision(
                    captions,
                    operation=OPERATION_TRANSLATION,
                    source_language="fr",
                    target_language=target,
                )
                self.assertGreater(estimate.cost_usd, 0)

    def test_contextual_units_follow_limits_and_pauses(self) -> None:
        captions = [Caption(i * 2, i * 2 + 1, (str(i),)) for i in range(7)]
        units = build_units(captions)
        self.assertEqual([(u["start"], u["end"]) for u in units], [(0, 6), (6, 7)])

    def test_flexible_validation_applies_number_change_with_warning(self) -> None:
        originals = [
            {"id": 1, "unit": 1, "text": "Episode 12 begins"},
            {"id": 2, "unit": 1, "text": "right now"},
        ]
        result = validate_revised_items(
            originals,
            [{"id": 1, "text": "L'episodio 13"}, {"id": 2, "text": "inizia ora"}],
            operation=OPERATION_TRANSLATION,
        )
        self.assertEqual(result["counts"]["rejected"], 0)
        self.assertEqual(result["captions"][0]["text"], "L'episodio 13")
        self.assertTrue(result["captions"][0]["warnings"])

    def test_japanese_numeric_expressions_allow_exact_natural_translation(self) -> None:
        originals = [
            {"id": 1, "unit": 1, "text": "1つ目の本は失敗、2つ目の本は成功"},
            {"id": 2, "unit": 2, "text": "卒論を1週間で書いた"},
            {"id": 3, "unit": 3, "text": "8月に出た"},
        ]
        result = validate_revised_items(
            originals,
            [
                {"id": 1, "text": "Il primo libro fallì, il secondo ebbe successo."},
                {"id": 2, "text": "Scrissi la tesi in una settimana."},
                {"id": 3, "text": "Uscì in agosto."},
            ],
            operation=OPERATION_TRANSLATION,
            source_language="ja", target_language="it",
        )
        self.assertEqual(result["counts"]["rejected"], 0)

    def test_japanese_numeric_expressions_warn_on_wrong_values(self) -> None:
        cases = [
            ("8月に出た", "Uscì in settembre."),
            ("2つ目の本", "Il primo libro."),
            ("1週間で書いた", "Lo scrissi in un mese."),
            ("89年に40人", "Nel 89 c'erano 4 persone."),
        ]
        for source, proposal in cases:
            with self.subTest(source=source):
                result = validate_revised_items(
                    [{"id": 1, "text": source}],
                    [{"id": 1, "text": proposal}],
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                self.assertEqual(result["counts"]["rejected"], 0)
                self.assertTrue(result["captions"][0]["warnings"])

    def test_japanese_signature_ignores_spacing_and_punctuation(self) -> None:
        self.assertEqual(japanese_signature("これは、テスト。"), japanese_signature("これ はテスト"))
    def test_estimate_includes_all_groups_without_api_calls(self) -> None:
        captions = [Caption(0, 1, ("hello world",)) for _ in range(20)]
        groups = build_groups(captions, target_tokens=20)
        estimate = estimate_revision(captions, groups)
        self.assertGreater(len(groups), 1)
        self.assertEqual(estimate.group_count, len(groups))
        self.assertGreater(estimate.input_tokens, 0)
        self.assertGreater(estimate.output_tokens, 0)
        self.assertGreater(estimate.cost_usd, 0)

    def test_accepts_only_punctuation_and_capitalization(self) -> None:
        originals = [
            {"id": 1, "text": "hello world"},
            {"id": 2, "text": "don't stop 12-men"},
        ]
        result = validate_revised_items(
            originals,
            [
                {"id": 1, "text": "Hello, world!"},
                {"id": 2, "text": "Don't stop, 12-men."},
            ],
        )
        self.assertEqual(
            result["counts"], {"modified": 2, "unchanged": 0, "rejected": 0}
        )
        self.assertTrue(
            all(item["outcome"] == "modified" for item in result["captions"])
        )

    def test_rejects_changed_words_ids_numbers_apostrophes_and_hyphens(self) -> None:
        originals = [{"id": 1, "text": "don't stop 12-men"}]
        invalid = [
            [{"id": 1, "text": "do not stop 12-men"}],
            [{"id": 2, "text": "don't stop 12-men"}],
            [{"id": 1, "text": "don't stop 13-men"}],
            [{"id": 1, "text": "dont stop 12-men"}],
            [{"id": 1, "text": "don't stop 12 men"}],
        ]
        for revised in invalid:
            with self.subTest(revised=revised):
                result = validate_revised_items(originals, revised)
                self.assertEqual(result["counts"]["rejected"], 1)
                self.assertEqual(result["captions"][0]["text"], originals[0]["text"])

    def test_words_cannot_move_between_caption_ids(self) -> None:
        originals = [
            {"id": 1, "text": "hello"},
            {"id": 2, "text": "world"},
        ]
        result = validate_revised_items(
            originals,
            [{"id": 1, "text": "hello world"}, {"id": 2, "text": ""}],
        )
        self.assertEqual(result["counts"]["rejected"], 2)

    def test_mixed_response_keeps_valid_items_and_source_order(self) -> None:
        originals = [
            {"id": 1, "text": "hello world"},
            {"id": 2, "text": "goodbye"},
            {"id": 3, "text": "same"},
        ]
        result = validate_revised_items(
            originals,
            [
                {"id": 3, "text": "same"},
                {"id": 99, "text": "foreign"},
                "malformed",
                {"id": 2, "text": "Goodbye!"},
                {"id": 1, "text": "different words"},
            ],
        )
        self.assertEqual(
            result["counts"], {"modified": 1, "unchanged": 1, "rejected": 1}
        )
        self.assertEqual([item["id"] for item in result["captions"]], [1, 2, 3])
        self.assertEqual(result["captions"][0]["text"], "hello world")
        self.assertEqual(result["captions"][1]["text"], "Goodbye!")
        self.assertEqual(len(result["anomalies"]), 2)

    def test_duplicate_missing_and_invalid_ids_only_reject_affected_items(self) -> None:
        originals = [
            {"id": 1, "text": "one"},
            {"id": 2, "text": "two"},
            {"id": 3, "text": "three"},
            {"id": 4, "text": "four"},
        ]
        result = validate_revised_items(
            originals,
            [
                {"id": 1, "text": "One."},
                {"id": 1, "text": "One!"},
                {"id": 3, "text": "Three?"},
                {"id": True, "text": "two"},
                {"id": "4", "text": "four"},
            ],
        )
        self.assertEqual(
            result["counts"], {"modified": 1, "unchanged": 0, "rejected": 3}
        )
        reasons = {item["id"]: item["reason"] for item in result["captions"]}
        self.assertIn("duplicato", reasons[1])
        self.assertIn("mancante", reasons[2])
        self.assertIn("mancante", reasons[4])
        self.assertEqual(len(result["anomalies"]), 2)

    def test_apply_revisions_preserves_exact_times(self) -> None:
        captions = [Caption(2400.123, 2402.456, ("hello world",))]
        revised = apply_revisions(captions, {1: "Hello, world!"})
        self.assertEqual(revised[0].start, 2400.123)
        self.assertEqual(revised[0].end, 2402.456)
        self.assertEqual(revised[0].lines, ("Hello, world!",))

    def test_parser_preserves_invalid_duration_for_warning(self) -> None:
        captions = parse_revision_srt("1\n00:40:02,000 --> 00:40:01,000\nhello world\n")
        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0].start, 2402.0)
        self.assertEqual(captions[0].end, 2401.0)
        self.assertTrue(
            any("durata non valida" in item for item in quality_warnings(captions))
        )

    def test_quality_warnings_do_not_change_captions(self) -> None:
        captions = [
            Caption(1.0, 1.5, ("x" * 90,)),
            Caption(1.4, 1.3, ("bad",)),
        ]
        warnings = quality_warnings(captions)
        self.assertTrue(any("20 caratteri" in warning for warning in warnings))
        self.assertTrue(any("sovrapposto" in warning for warning in warnings))
        self.assertTrue(any("durata non valida" in warning for warning in warnings))
        self.assertTrue(any("42 caratteri" in warning for warning in warnings))

    def test_signature_keeps_internal_marks(self) -> None:
        self.assertEqual(word_signature("Hello, WORLD!"), ["hello", "world"])
        self.assertNotEqual(word_signature("don't"), word_signature("dont"))
        self.assertNotEqual(word_signature("12-men"), word_signature("12 men"))

    def test_linguistic_mode_allows_small_word_changes(self) -> None:
        originals = [{"id": 1, "text": "he go to store"}]
        result = validate_revised_items(
            originals,
            [{"id": 1, "text": "He goes to the store."}],
            mode=REVISION_MODE_LINGUISTIC,
        )
        self.assertEqual(result["counts"]["modified"], 1)
        self.assertEqual(result["captions"][0]["original_text"], "he go to store")
        self.assertEqual(result["captions"][0]["text"], "He goes to the store.")

    def test_linguistic_mode_warns_on_changed_numbers_but_rejects_empty_text(self) -> None:
        originals = [
            {"id": 1, "text": "we have 12 minutes"},
            {"id": 2, "text": "keep this"},
        ]
        result = validate_revised_items(
            originals,
            [{"id": 1, "text": "We have 13 minutes."}, {"id": 2, "text": ""}],
            mode=REVISION_MODE_LINGUISTIC,
        )
        self.assertEqual(result["counts"]["rejected"], 1)
        self.assertTrue(result["captions"][0]["warnings"])

    def test_linguistic_estimate_reflects_larger_output_margin(self) -> None:
        captions = [Caption(0, 1, ("hello world",)) for _ in range(20)]
        conservative = estimate_revision(captions, model=MODEL_MINI)
        linguistic = estimate_revision(
            captions, mode=REVISION_MODE_LINGUISTIC, model=MODEL_MINI
        )
        self.assertGreater(linguistic.output_tokens, conservative.output_tokens)
        self.assertGreater(linguistic.cost_usd, conservative.cost_usd)

    def test_instruction_versions_preserve_old_jobs_and_use_sentence_context(
        self,
    ) -> None:
        legacy = revision_instructions("conservative", version=1)
        current = revision_instructions("conservative", version=2)
        self.assertNotIn("sentences that span", legacy)
        self.assertIn("sentences that span", current)


if __name__ == "__main__":
    unittest.main()

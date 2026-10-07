import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.config import MODEL_SOL
from video_sottotitoli.revision import OPERATION_TRANSLATION
from video_sottotitoli.revision_worker import RevisionWorker, load_revision_for_resume

SOURCE = """1
00:40:00,000 --> 00:40:02,000
これはテストです

2
00:40:02,200 --> 00:40:04,000
番号は12です
"""


class TranslationWorkerTests(unittest.TestCase):
    def test_translation_splits_final_srt_without_extra_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.srt"
            output = root / "input.it.srt"
            source.write_text(
                "1\n00:40:00,000 --> 00:40:20,000\nこれは長い話です。\n",
                encoding="utf-8",
            )
            translated = (
                "Questa è una spiegazione molto lunga. "
                "La prima parte introduce l'argomento e la seconda aggiunge i dettagli. "
                "Infine arriva una conclusione comprensibile per chi guarda il video."
            )
            calls = 0

            def request(_payload):
                nonlocal calls
                calls += 1
                return {
                    "captions": [{"id": 1, "text": translated}],
                    "usage": {"input_tokens": 100, "output_tokens": 100},
                }

            with patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", root / "jobs"):
                worker = RevisionWorker(
                    str(source), str(output), "unused", request,
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                worker.run()

            self.assertEqual(calls, 1)
            rendered = output.read_text(encoding="utf-8")
            blocks = [block.splitlines() for block in rendered.strip().split("\n\n")]
            self.assertGreater(len(blocks), 1)
            self.assertTrue(all(len(block) <= 4 for block in blocks))
            self.assertTrue(all(len(line) <= 42 for block in blocks for line in block[2:]))
            self.assertIn("00:40:00,000 -->", rendered)
            self.assertIn("--> 00:40:20,000", rendered)
            manifest = json.loads(next((root / "jobs").glob("*/revision.json")).read_text())
            self.assertEqual(manifest["readability_version"], 1)
            self.assertEqual(manifest["readability_id_map"]["1"], [1, len(blocks)])
            report = Path(manifest["issue_report"]).read_text(encoding="utf-8")
            self.assertIn("Originale 1 → finale 1–", report)

    def test_resume_recovers_previously_paid_natural_number_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.srt"
            output = root / "input.it.srt"
            source.write_text(
                "1\n00:05:00,000 --> 00:05:02,000\n8月に出た\n", encoding="utf-8"
            )
            jobs = root / "jobs"
            with patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", jobs):
                first = RevisionWorker(
                    str(source), str(output), "unused",
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                job_dir, manifest = first._create_job()
            record_name = "group-0000.json"
            (job_dir / record_name).write_text(json.dumps({
                "raw_captions": [{"id": 1, "text": "Uscì in agosto."}],
                "captions": [], "counts": {"modified": 0, "unchanged": 0, "rejected": 1},
                "anomalies": [], "ambiguities": [],
            }), encoding="utf-8")
            manifest["status"] = "error"
            manifest["groups"][0].update({
                "status": "pending", "response": record_name,
                "usage": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.0007},
            })
            (job_dir / "revision.json").write_text(json.dumps(manifest), encoding="utf-8")

            _saved_manifest, estimate = load_revision_for_resume(job_dir)
            self.assertEqual(estimate.group_count, 0)
            self.assertEqual(estimate.cost_usd, 0)

            def must_not_request(_payload):
                self.fail("La risposta salvata deve essere riutilizzata senza API")

            resumed = RevisionWorker(
                str(source), str(output), "unused", must_not_request,
                operation=OPERATION_TRANSLATION,
                source_language="ja", target_language="it",
            )
            resumed.job_dir = job_dir
            resumed.run()
            saved = json.loads((job_dir / "revision.json").read_text())
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["groups"][0]["usage"]["input_tokens"], 100)
            self.assertIn("Uscì in agosto.", output.read_text())

    def test_number_difference_is_applied_and_reported_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "numbers.srt"
            output = root / "numbers.it.srt"
            source.write_text(
                "1\n00:05:00,000 --> 00:05:02,000\n89年に40の事件\n",
                encoding="utf-8",
            )
            calls: list[dict] = []

            def request(payload):
                calls.append(payload)
                translated = (
                    "Nel 89 ci fu il caso di 4 persone."
                    if len(calls) == 1 else
                    "Nel 89 ci fu il caso di 40 persone."
                )
                return {
                    "captions": [{"id": 1, "text": translated}],
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                }

            with patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", root / "jobs"):
                worker = RevisionWorker(
                    str(source), str(output), "unused", request,
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                worker.run()

            self.assertEqual(len(calls), 1)
            self.assertIn("00:05:00,000 --> 00:05:02,000", output.read_text())
            self.assertIn("4 persone", output.read_text())
            job = next((root / "jobs").iterdir())
            manifest = json.loads((job / "revision.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["completion_status"], "completed_with_warnings")
            self.assertEqual(manifest["groups"][0]["usage"]["input_tokens"], 100)
            self.assertEqual(len(manifest["groups"][0]["attempts"]), 1)
            self.assertTrue(Path(manifest["issue_report"]).is_file())
            self.assertIn("Numeri diversi", Path(manifest["issue_report"]).read_text())
            self.assertTrue(all((job / name).is_file() for name in manifest["groups"][0]["attempts"]))

    def test_structural_failure_after_retry_saves_original_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "numbers.srt"
            output = root / "numbers.it.srt"
            source.write_text(
                "1\n00:05:00,000 --> 00:05:02,000\n89年に40の事件\n",
                encoding="utf-8",
            )
            output.write_text("previous translation", encoding="utf-8")

            def request(_payload):
                return {
                    "captions": [],
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                }

            with patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", root / "jobs"):
                worker = RevisionWorker(
                    str(source), str(output), "unused", request,
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                worker.run()

            self.assertIn("89年に40の事件", output.read_text())
            manifest = json.loads(next((root / "jobs").glob("*/revision.json")).read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(
                manifest["completion_status"], "completed_with_untranslated"
            )
            self.assertEqual(manifest["groups"][0]["usage"]["input_tokens"], 200)
            self.assertTrue(Path(manifest["issue_report"]).is_file())

    def test_api_failure_saves_partial_and_does_not_stop_result_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "long.srt"
            output = root / "long.it.srt"
            entries = []
            for index in range(36):
                start = index * 3
                end = start + 2
                start_stamp = f"00:{start // 60:02}:{start % 60:02}"
                end_stamp = f"00:{end // 60:02}:{end % 60:02}"
                entries.append(
                    f"{index + 1}\n{start_stamp},000 --> {end_stamp},000\n"
                    f"Frase originale {index + 1}. " + ("parola " * 90) + "\n"
                )
            source.write_text("\n".join(entries), encoding="utf-8")
            calls = 0

            def failed_request(_payload):
                nonlocal calls
                calls += 1
                raise RuntimeError("servizio temporaneamente non disponibile")

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR", root / "jobs"
            ):
                worker = RevisionWorker(
                    str(source), str(output), "unused", failed_request,
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                worker.run()

            text = output.read_text(encoding="utf-8")
            manifest = json.loads(
                next((root / "jobs").glob("*/revision.json")).read_text()
            )
            self.assertEqual(calls, 1)
            self.assertGreater(len(manifest["groups"]), 1)
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(
                manifest["completion_status"], "completed_with_untranslated"
            )
            self.assertEqual(manifest["result_counts"]["rejected"], 36)
            self.assertTrue(all(f"Frase originale {i}" in text for i in range(1, 37)))
            self.assertTrue(Path(manifest["issue_report"]).is_file())

    def test_missing_usage_on_first_attempt_stays_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.srt"
            output = root / "input.it.srt"
            source.write_text(
                "1\n00:05:00,000 --> 00:05:02,000\n数字は40です\n",
                encoding="utf-8",
            )
            def request(_payload):
                return {
                    "captions": [{
                        "id": 1,
                        "text": "Il numero è 4.",
                    }],
                    "usage": None,
                }

            with patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", root / "jobs"):
                worker = RevisionWorker(
                    str(source), str(output), "unused", request,
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                worker.run()

            manifest = json.loads(next((root / "jobs").glob("*/revision.json")).read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertFalse(manifest["actual_cost"]["complete"])
            self.assertNotIn("usage", manifest["groups"][0])

    def test_resume_adds_to_previous_failed_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.srt"
            output = root / "input.it.srt"
            source.write_text(
                "1\n00:05:00,000 --> 00:05:02,000\n数字は40です\n",
                encoding="utf-8",
            )

            jobs = root / "jobs"
            with patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", jobs):
                first = RevisionWorker(
                    str(source), str(output), "unused",
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                )
                job_dir, manifest = first._create_job()
            job_dir = next(jobs.iterdir())
            group = manifest["groups"][0]
            previous_attempts = []
            for index, usage in enumerate((
                {"input_tokens": 100, "output_tokens": 50},
                {"input_tokens": 100, "output_tokens": 50},
            ), start=1):
                name = f"old-attempt-{index}.json"
                (job_dir / name).write_text(json.dumps({
                    "usage": usage, "raw_captions": [],
                }), encoding="utf-8")
                previous_attempts.append(name)
            group["attempts"] = previous_attempts
            group["usage"] = {
                "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.0014,
            }
            group["status"] = "pending"
            manifest["status"] = "error"
            (job_dir / "revision.json").write_text(json.dumps(manifest), encoding="utf-8")

            def valid(_payload):
                return {
                    "captions": [{"id": 1, "text": "Il numero è 40."}],
                    "usage": {"input_tokens": 80, "output_tokens": 30},
                }

            resumed = RevisionWorker(
                str(source), str(output), "unused", valid,
                operation=OPERATION_TRANSLATION,
                source_language="ja", target_language="it",
            )
            resumed.job_dir = job_dir
            resumed.run()
            manifest = json.loads((job_dir / "revision.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["groups"][0]["usage"]["input_tokens"], 280)
            self.assertEqual(len(manifest["groups"][0]["attempts"]), 3)

    def test_japanese_to_italian_persists_settings_and_exact_times(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.srt"
            output = root / "input.it.srt"
            source.write_text(SOURCE, encoding="utf-8")

            def request(_payload):
                return {
                    "captions": [
                        {"id": 1, "text": "Questa è una prova."},
                        {"id": 2, "text": "Il numero è 12."},
                    ],
                    "ambiguities": [],
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                }

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR",
                root / "jobs",
            ):
                worker = RevisionWorker(
                    str(source), str(output), "unused", request,
                    operation=OPERATION_TRANSLATION,
                    source_language="ja", target_language="it",
                    model=MODEL_SOL, user_context="Una lezione.",
                )
                worker.run()

            rendered = output.read_text(encoding="utf-8")
            self.assertIn("00:40:00,000 --> 00:40:02,000", rendered)
            self.assertIn("Questa è una prova.", rendered)
            manifest_path = next((root / "jobs").glob("*/revision.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["operation"], OPERATION_TRANSLATION)
            self.assertEqual(manifest["source_language"], "ja")
            self.assertEqual(manifest["target_language"], "it")
            self.assertEqual(manifest["model"], MODEL_SOL)
            self.assertEqual(manifest["reasoning_effort"], "none")
            self.assertEqual(source.read_text(encoding="utf-8"), SOURCE)


if __name__ == "__main__":
    unittest.main()

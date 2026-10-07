import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.revision import (
    REVISION_MODE_LINGUISTIC,
    build_groups,
    source_fingerprint,
)
from video_sottotitoli.revision_worker import RevisionWorker

SOURCE = """1
00:40:00,000 --> 00:40:02,000
hello world

2
00:40:02,500 --> 00:40:04,000
how are you
"""


class RevisionWorkerTests(unittest.TestCase):
    def _paths(self, root: Path) -> tuple[Path, Path]:
        source = root / "input.srt"
        output = root / "input.migliorato.srt"
        source.write_text(SOURCE, encoding="utf-8")
        return source, output

    def test_simulated_revision_preserves_timestamps_and_records_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)

            def request(payload):
                return {
                    "captions": [
                        {"id": 1, "text": "Hello, world!"},
                        {"id": 2, "text": "How are you?"},
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                }

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR",
                root / "jobs",
            ):
                worker = RevisionWorker(str(source), str(output), "unused", request)
                worker.run()

            text = output.read_text(encoding="utf-8")
            self.assertIn("00:40:00,000 --> 00:40:02,000", text)
            self.assertIn("Hello, world!", text)
            self.assertIn("How are you?", text)
            manifest_path = next((root / "jobs").glob("*/revision.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["version"], 4)
            self.assertEqual(manifest["validator_version"], 6)
            self.assertEqual(
                manifest["result_counts"],
                {"modified": 2, "unchanged": 0, "rejected": 0},
            )
            self.assertTrue(manifest["actual_cost"]["complete"])
            self.assertGreater(manifest["actual_cost"]["cost_usd"], 0)
            self.assertEqual(source.read_text(encoding="utf-8"), SOURCE)

    def test_invalid_response_keeps_original_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)
            calls = 0

            def request(_payload):
                nonlocal calls
                calls += 1
                return {
                    "captions": [
                        {"id": 1, "text": "Entirely different words."},
                        {"id": 2, "text": "How are you?"},
                    ],
                    "usage": None,
                }

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR",
                root / "jobs",
            ):
                worker = RevisionWorker(str(source), str(output), "unused", request)
                worker.run()

            self.assertEqual(calls, 1)
            text = output.read_text(encoding="utf-8")
            self.assertIn("hello world", text)
            self.assertIn("How are you?", text)
            manifest_path = next((root / "jobs").glob("*/revision.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["result_counts"],
                {"modified": 1, "unchanged": 0, "rejected": 1},
            )
            self.assertEqual(manifest["rejections"][0]["id"], 1)
            self.assertFalse(manifest["actual_cost"]["complete"])
            record_path = next((root / "jobs").glob("*/group-0000.json"))
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(
                record["raw_captions"][0]["text"], "Entirely different words."
            )

    def test_api_error_still_saves_original_srt_with_problem_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)

            def request(_payload):
                raise RuntimeError("network")

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR",
                root / "jobs",
            ):
                worker = RevisionWorker(str(source), str(output), "unused", request)
                worker.run()

            self.assertTrue(output.exists())
            manifest_path = next((root / "jobs").glob("*/revision.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["completion_status"], "completed_with_untranslated")
            self.assertEqual(manifest["groups"][0]["status"], "rejected")
            self.assertTrue(Path(manifest["issue_report"]).is_file())
            self.assertIn("hello world", output.read_text(encoding="utf-8"))

    def test_unchanged_response_reports_zero_text_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)

            def request(payload):
                return {
                    "captions": payload["targets"],
                    "usage": {"input_tokens": 50, "output_tokens": 20},
                }

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR",
                root / "jobs",
            ):
                worker = RevisionWorker(str(source), str(output), "unused", request)
                worker.run()

            manifest_path = next((root / "jobs").glob("*/revision.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["result_counts"],
                {"modified": 0, "unchanged": 2, "rejected": 0},
            )
            self.assertTrue(output.exists())

    def test_resume_reuses_completed_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)
            source.write_text(SOURCE.replace("00:40:02,500", "00:40:05,000"), encoding="utf-8")
            first_calls = 0
            first_worker = None

            def first_request(payload):
                nonlocal first_calls
                first_calls += 1
                assert first_worker is not None
                first_worker.cancel()
                return {
                    "captions": [
                        {"id": item["id"], "text": item["text"].capitalize() + "."}
                        for item in payload["targets"]
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }

            jobs = root / "jobs"
            with (
                patch("video_sottotitoli.revision_worker.REVISION_JOBS_DIR", jobs),
                patch(
                    "video_sottotitoli.revision_worker.build_groups",
                    lambda captions, mode="conservative": build_groups(
                        captions, target_tokens=3, mode=mode
                    ),
                ),
            ):
                first_worker = RevisionWorker(
                    str(source), str(output), "unused", first_request
                )
                first_worker.run()

            job_dir = next(jobs.iterdir())
            manifest = json.loads((job_dir / "revision.json").read_text())
            self.assertEqual(manifest["status"], "cancelled")
            self.assertEqual(first_calls, 1)
            resumed_calls = 0

            def resumed_request(payload):
                nonlocal resumed_calls
                resumed_calls += 1
                return {
                    "captions": [
                        {"id": item["id"], "text": item["text"].capitalize() + "?"}
                        for item in payload["targets"]
                    ],
                    "usage": {"input_tokens": 11, "output_tokens": 6},
                }

            resumed = RevisionWorker(
                str(source), str(output), "unused", resumed_request
            )
            resumed.job_dir = job_dir
            resumed.run()

            self.assertEqual(resumed_calls, 1)
            self.assertTrue(output.exists())
            finished = json.loads((job_dir / "revision.json").read_text())
            self.assertEqual(finished["status"], "completed")
            self.assertTrue(
                all(group["status"] == "completed" for group in finished["groups"])
            )
            self.assertEqual(
                finished["result_counts"],
                {"modified": 2, "unchanged": 0, "rejected": 0},
            )

    def test_version_one_rejected_group_is_reused_without_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)
            job_dir = root / "old-job"
            job_dir.mkdir()
            groups = build_groups(
                [
                    type("Caption", (), {"lines": ("hello world",)})(),
                    type("Caption", (), {"lines": ("how are you",)})(),
                ]
            )
            groups[0].update({"status": "rejected", "response": "group-0000.json"})
            manifest = {
                "version": 1,
                "status": "cancelled",
                "source": str(source),
                "fingerprint": source_fingerprint(source),
                "output": str(output),
                "model": "gpt-4.1-mini-2025-04-14",
                "pricing": {"input_per_million": 0.40, "output_per_million": 1.60},
                "caption_count": 2,
                "usage_complete": True,
                "groups": groups,
            }
            (job_dir / "revision.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (job_dir / "group-0000.json").write_text(
                json.dumps(
                    {
                        "accepted": False,
                        "reason": "Vecchio gruppo rifiutato.",
                        "captions": [
                            {"id": 1, "text": "hello world"},
                            {"id": 2, "text": "how are you"},
                        ],
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    }
                ),
                encoding="utf-8",
            )
            calls = 0

            def request(_payload):
                nonlocal calls
                calls += 1
                raise AssertionError("Il vecchio gruppo non deve essere reinviato")

            worker = RevisionWorker(str(source), str(output), "unused", request)
            worker.job_dir = job_dir
            worker.run()

            self.assertEqual(calls, 0)
            migrated = json.loads((job_dir / "revision.json").read_text())
            self.assertEqual(migrated["version"], 3)
            self.assertEqual(migrated["original_version"], 1)
            self.assertEqual(migrated["result_counts"]["rejected"], 2)
            self.assertTrue(output.exists())

    def test_version_one_accepted_group_is_classified_without_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)
            job_dir = root / "old-job"
            job_dir.mkdir()
            groups = build_groups(
                [
                    type("Caption", (), {"lines": ("hello world",)})(),
                    type("Caption", (), {"lines": ("how are you",)})(),
                ]
            )
            groups[0].update({"status": "completed", "response": "group-0000.json"})
            manifest = {
                "version": 1,
                "status": "cancelled",
                "source": str(source),
                "fingerprint": source_fingerprint(source),
                "output": str(output),
                "model": "gpt-4.1-mini-2025-04-14",
                "pricing": {"input_per_million": 0.40, "output_per_million": 1.60},
                "caption_count": 2,
                "usage_complete": True,
                "groups": groups,
            }
            (job_dir / "revision.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (job_dir / "group-0000.json").write_text(
                json.dumps(
                    {
                        "accepted": True,
                        "captions": [
                            {"id": 1, "text": "Hello, world!"},
                            {"id": 2, "text": "how are you"},
                        ],
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    }
                ),
                encoding="utf-8",
            )

            def request(_payload):
                raise AssertionError("Il vecchio gruppo non deve essere reinviato")

            worker = RevisionWorker(str(source), str(output), "unused", request)
            worker.job_dir = job_dir
            worker.run()

            migrated = json.loads((job_dir / "revision.json").read_text())
            self.assertEqual(
                migrated["result_counts"],
                {"modified": 1, "unchanged": 1, "rejected": 0},
            )
            self.assertIn("Hello, world!", output.read_text(encoding="utf-8"))

    def test_linguistic_mode_persists_comparisons_and_accepts_word_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._paths(root)

            def request(_payload):
                return {
                    "captions": [
                        {"id": 1, "text": "Hello there, world!"},
                        {"id": 2, "text": "How are you?"},
                    ],
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                }

            with patch(
                "video_sottotitoli.revision_worker.REVISION_JOBS_DIR",
                root / "jobs",
            ):
                worker = RevisionWorker(
                    str(source),
                    str(output),
                    "unused",
                    request,
                    mode=REVISION_MODE_LINGUISTIC,
                )
                worker.run()

            manifest_path = next((root / "jobs").glob("*/revision.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["revision_mode"], REVISION_MODE_LINGUISTIC)
            self.assertEqual(manifest["result_counts"]["modified"], 2)
            self.assertEqual(manifest["applied_changes"][0]["original"], "hello world")
            self.assertEqual(
                manifest["applied_changes"][0]["revised"], "Hello there, world!"
            )


if __name__ == "__main__":
    unittest.main()

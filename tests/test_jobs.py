import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.jobs import create_job, load_job


class JobTests(unittest.TestCase):
    def test_french_source_language_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            with patch("video_sottotitoli.jobs.JOBS_DIR", root / "jobs"), patch(
                "video_sottotitoli.jobs.ensure_app_dirs",
                lambda: (root / "jobs").mkdir(parents=True, exist_ok=True),
            ):
                job_dir, _manifest = create_job(
                    str(video), 60, 0, str(root / "output.srt"),
                    source_language="fr",
                )
                manifest = load_job(job_dir)
        self.assertEqual(manifest["source_language"], "fr")

    def test_new_job_persists_selected_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            video.write_bytes(b"test video fingerprint")
            with patch("video_sottotitoli.jobs.JOBS_DIR", root / "jobs"), patch(
                "video_sottotitoli.jobs.ensure_app_dirs",
                lambda: (root / "jobs").mkdir(parents=True, exist_ok=True),
            ):
                job_dir, manifest = create_job(
                    str(video),
                    60 * 60,
                    0,
                    str(root / "subtitles.srt"),
                    40 * 60,
                    50 * 60,
                )

            self.assertEqual(manifest["version"], 4)
            self.assertEqual(manifest["source_language"], "en")
            self.assertEqual(manifest["target_language"], "original")
            self.assertEqual(manifest["start_at_seconds"], 2400)
            self.assertEqual(manifest["end_at_seconds"], 3000)
            self.assertEqual(manifest["chunks"][0]["start"], 2400)
            self.assertEqual(load_job(job_dir)["start_at_seconds"], 2400)
            self.assertEqual(manifest["workflow_stage"], "ready_to_transcribe")
            self.assertEqual(
                manifest["transcription_output"],
                str((root / "subtitles.srt").resolve()),
            )
            self.assertIsNone(manifest["transcription_cost_usd"])

    def test_old_job_defaults_to_start_zero_without_changing_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary)
            legacy_chunks = [{"start": 600, "duration": 600, "status": "completed"}]
            (job_dir / "job.json").write_text(
                json.dumps({"version": 1, "duration": 3600, "chunks": legacy_chunks}),
                encoding="utf-8",
            )

            manifest = load_job(job_dir)

            self.assertEqual(manifest["start_at_seconds"], 0.0)
            self.assertEqual(manifest["end_at_seconds"], 3600)
            self.assertEqual(manifest["chunks"], legacy_chunks)


if __name__ == "__main__":
    unittest.main()

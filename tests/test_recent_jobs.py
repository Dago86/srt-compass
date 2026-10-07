from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli import recent_jobs


class RecentJobsTests(unittest.TestCase):
    def test_completed_transcription_with_translation_target_shows_original_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = root / "jobs"
            job = jobs / "sample"
            job.mkdir(parents=True)
            (job / "job.json").write_text(json.dumps({
                "status": "completed", "video": "/tmp/video.mkv",
                "output": "/tmp/video.srt", "target_language": "it",
            }), encoding="utf-8")
            with (
                patch.object(recent_jobs, "JOBS_DIR", jobs),
                patch.object(recent_jobs, "REVISION_JOBS_DIR", root / "revisions"),
                patch.object(recent_jobs, "DOWNLOAD_JOBS_DIR", root / "downloads"),
            ):
                records = recent_jobs.list_recent_jobs()
            self.assertEqual(records[0]["status"], "Originale pronto")

    def test_corrupt_record_does_not_hide_download_and_shows_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jobs = root / "jobs"
            revisions = root / "revisions"
            downloads = root / "downloads"
            for folder in (jobs, revisions, downloads):
                folder.mkdir()
            broken = jobs / "broken"
            broken.mkdir()
            (broken / "job.json").write_text("{", encoding="utf-8")
            download = downloads / "download-1"
            staging = download / "staging"
            staging.mkdir(parents=True)
            (staging / "video.f398.mp4.part").write_bytes(b"partial")
            (download / "download.json").write_text(json.dumps({
                "status": "cancelled", "title": "Talk", "quality": "720p",
                "source_id": "abc123", "staging_dir": str(staging),
                "destination_dir": str(root / "output"),
            }), encoding="utf-8")
            with (
                patch.object(recent_jobs, "JOBS_DIR", jobs),
                patch.object(recent_jobs, "REVISION_JOBS_DIR", revisions),
                patch.object(recent_jobs, "DOWNLOAD_JOBS_DIR", downloads),
            ):
                records = recent_jobs.list_recent_jobs()
            self.assertEqual(len(records), 2)
            saved = next(item for item in records if item["kind"] == "Download")
            self.assertIn("Temporanei", saved["progress"])
            self.assertEqual(saved["temporary_files"], 1)
            self.assertEqual(saved["status"], "Interrotto")
            self.assertIn("720p", saved["details"])
            self.assertEqual(
                sum(item["name"] == "Registro non leggibile" for item in records), 1
            )


if __name__ == "__main__":
    unittest.main()

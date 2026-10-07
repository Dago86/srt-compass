import fcntl
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.config import MODEL_PRICING, MODEL_SOL, MODEL_SOL_LEGACY
from video_sottotitoli.downloader import (
    DownloadError,
    DownloadWorker,
    _selector,
    cleanup_all_download_staging,
    cleanup_download_staging,
    effective_quality,
    inspect_download_staging,
    parse_info,
    resumable_page_url,
    safe_output_name,
    safe_output_stem,
    validate_page_url,
    validate_selected_format,
)
from video_sottotitoli.event_log import EventLog, sanitize_message
from video_sottotitoli.media import probe_media
from video_sottotitoli.models import AudioTrack, MediaInfo
from video_sottotitoli.revision import (
    OPERATION_TRANSLATION,
    REVISION_MODE_LINGUISTIC,
    default_model,
)


class DownloadAndEventTests(unittest.TestCase):
    def test_stalled_download_restarts_once_and_keeps_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            staging = job / "staging"
            staging.mkdir()
            partial = staging / "media.part"
            partial.write_bytes(b"saved bytes")
            manifest = {
                "status": "downloading", "source_id": "id", "staging_dir": str(staging),
                "destination_dir": str(job / "published"), "filename_template": "download-%(id)s.%(ext)s",
            }
            (job / "download.json").write_text(json.dumps(manifest), encoding="utf-8")
            worker = DownloadWorker("https://example.test/video", operation="download", job_dir=job)
            worker.event_log = EventLog(job, lambda *_: None, "download")
            with (
                patch("video_sottotitoli.media._tool", return_value="ffmpeg"),
                patch("video_sottotitoli.downloader.bundled_binary", return_value="yt-dlp"),
                patch.object(worker, "_run_capture", return_value=("{}", "", 0)),
                patch("video_sottotitoli.downloader.parse_info", return_value={"id": "id"}),
                patch("video_sottotitoli.downloader.validate_selected_format"),
                patch.object(worker, "_new_job", return_value=(job, manifest)),
                patch.object(worker, "_find_completed_staging_file", return_value=None),
                patch.object(worker, "_merge_separate_streams", return_value=None),
                patch.object(worker, "_transfer_attempt", return_value=(-15, [], [], True)) as transfer,
                self.assertRaises(DownloadError),
            ):
                worker._download()
            self.assertEqual(transfer.call_count, 2)
            self.assertEqual(json.loads((job / "download.json").read_text())["transfer_attempt"], 2)
            self.assertEqual(partial.read_bytes(), b"saved bytes")

    def test_transfer_watchdog_stops_process_without_new_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            staging = job / "staging"
            staging.mkdir()
            (job / "download.json").write_text("{}", encoding="utf-8")
            worker = DownloadWorker("https://example.test/video", operation="download")
            worker.event_log = EventLog(job, lambda *_: None, "download")
            command = [sys.executable, "-c", "import time; time.sleep(20)"]
            started = time.monotonic()
            with patch("video_sottotitoli.downloader.DOWNLOAD_IDLE_SECONDS", 0.35):
                code, _paths, _errors, stalled = worker._transfer_attempt(command, staging, job, {})
            self.assertTrue(stalled)
            self.assertNotEqual(code, 0)
            self.assertLess(time.monotonic() - started, 3)

    def test_transfer_watchdog_forces_a_process_ignoring_termination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            staging = job / "staging"
            staging.mkdir()
            (job / "download.json").write_text("{}", encoding="utf-8")
            worker = DownloadWorker("https://example.test/video", operation="download")
            worker.event_log = EventLog(job, lambda *_: None, "download")
            command = [sys.executable, "-c", (
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(20)"
            )]
            started = time.monotonic()
            with (
                patch("video_sottotitoli.downloader.DOWNLOAD_IDLE_SECONDS", 0.35),
                patch("video_sottotitoli.downloader.STOP_GRACE_SECONDS", 0.3),
            ):
                code, _paths, _errors, stalled = worker._transfer_attempt(command, staging, job, {})
            self.assertTrue(stalled)
            self.assertNotEqual(code, 0)
            self.assertLess(time.monotonic() - started, 3)

    def test_transfer_watchdog_accepts_slow_file_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            staging = job / "staging"
            staging.mkdir()
            (job / "download.json").write_text("{}", encoding="utf-8")
            worker = DownloadWorker("https://example.test/video", operation="download")
            worker.event_log = EventLog(job, lambda *_: None, "download")
            command = [sys.executable, "-c", (
                "import pathlib,time; p=pathlib.Path('media.part'); "
                "[(p.open('ab').write(b'x'),time.sleep(.3)) for _ in range(7)]"
            )]
            with patch("video_sottotitoli.downloader.DOWNLOAD_IDLE_SECONDS", 1.5):
                code, _paths, _errors, stalled = worker._transfer_attempt(command, staging, job, {})
            self.assertEqual(code, 0)
            self.assertFalse(stalled)
            self.assertEqual((staging / "media.part").stat().st_size, 7)

    def test_progress_parser_rejects_negative_and_non_finite_values(self) -> None:
        worker = DownloadWorker("https://example.test/video")
        worker._parse_progress("VSTT|download|downloading|-1|100|0|nan|inf")
        kind, value = worker.events.get_nowait()
        self.assertEqual(kind, "progress")
        self.assertIsNone(value["downloaded"])
        self.assertEqual(value["total"], 100)
        self.assertIsNone(value["speed"])
        self.assertIsNone(value["eta"])

    def test_progress_parser_accepts_decimal_scientific_and_fragments(self) -> None:
        worker = DownloadWorker("https://example.test/video")
        worker._parse_progress("VSTT|download|downloading|25000000|NA|1.0e8|1000|30|2|8|vp9")
        _kind, value = worker.events.get_nowait()
        self.assertEqual(value["total"], 100_000_000)
        self.assertTrue(value["total_is_estimate"])
        self.assertEqual(value["fragment_index"], 2)
        self.assertEqual(value["fragment_count"], 8)
        self.assertEqual(value["stream"], "video")
        worker._parse_progress("VSTT|download|downloading|500|1000.0|NA|NA|NA|NA|NA|none")
        _kind, value = worker.events.get_nowait()
        self.assertEqual(value["total"], 1000)
        self.assertFalse(value["total_is_estimate"])
        self.assertEqual(value["stream"], "audio")

    def test_global_cleanup_scans_all_jobs_and_keeps_records_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "downloads"
            for index in range(55):
                job = root / f"job-{index:02}"
                staging = job / "staging"
                staging.mkdir(parents=True)
                (staging / "part.bin").write_bytes(b"partial")
                (job / "events.log").write_text("log", encoding="utf-8")
                (job / "download.json").write_text(json.dumps({
                    "status": "cancelled", "staging_dir": str(staging),
                }), encoding="utf-8")
                (job / "published.mkv").write_bytes(b"published")
            with patch("video_sottotitoli.downloader.DOWNLOAD_JOBS_DIR", root):
                preview = inspect_download_staging()
                self.assertEqual(len(preview), 55)
                result = cleanup_all_download_staging()
            self.assertEqual(result["jobs"], 55)
            self.assertEqual(result["files"], 55)
            self.assertEqual(result["skipped_active"], 0)
            self.assertEqual(result["errors"], [])
            for job in root.iterdir():
                self.assertTrue((job / "download.json").is_file())
                self.assertTrue((job / "events.log").is_file())
                self.assertTrue((job / "published.mkv").is_file())
                self.assertFalse((job / "staging").exists())

    def test_global_cleanup_skips_job_locked_by_another_process_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "downloads"
            job = root / "active"
            staging = job / "staging"
            staging.mkdir(parents=True)
            (staging / "part.bin").write_bytes(b"partial")
            (job / "download.json").write_text(json.dumps({
                "status": "downloading", "staging_dir": str(staging),
            }), encoding="utf-8")
            lock = (job / ".active.lock").open("a+")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with patch("video_sottotitoli.downloader.DOWNLOAD_JOBS_DIR", root):
                    preview = inspect_download_staging()
                    self.assertTrue(preview[0]["active"])
                    result = cleanup_all_download_staging()
                self.assertEqual(result["skipped_active"], 1)
                self.assertTrue((staging / "part.bin").is_file())
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()

    def test_cleanup_removes_only_staging_and_preserves_job_record_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "downloads" / "job-a"
            staging = job / "staging"
            staging.mkdir(parents=True)
            (staging / "partial.part").write_bytes(b"temporary bytes")
            output = root / "published.mkv"
            output.write_bytes(b"keep this")
            manifest_path = job / "download.json"
            manifest_path.write_text(json.dumps({
                "status": "downloading", "staging_dir": str(staging),
                "output": str(output),
            }), encoding="utf-8")
            (job / "events.log").write_text("keep log", encoding="utf-8")
            with patch("video_sottotitoli.downloader.DOWNLOAD_JOBS_DIR", root / "downloads"):
                removed_count, removed_bytes = cleanup_download_staging(manifest_path)
            self.assertEqual((removed_count, removed_bytes), (1, len(b"temporary bytes")))
            self.assertFalse(staging.exists())
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(json.loads(manifest_path.read_text())["status"], "cancelled")
            saved_log = (job / "events.log").read_text()
            self.assertTrue(saved_log.startswith("keep log"))
            self.assertIn("PULIZIA DOWNLOAD", saved_log)
            self.assertEqual(output.read_bytes(), b"keep this")

    def test_cleanup_rejects_staging_path_outside_download_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "downloads" / "job-a"
            job.mkdir(parents=True)
            outside = root / "important"
            outside.mkdir()
            (outside / "keep.txt").write_text("safe", encoding="utf-8")
            manifest_path = job / "download.json"
            manifest_path.write_text(json.dumps({
                "status": "cancelled", "staging_dir": str(outside),
            }), encoding="utf-8")
            with (
                patch("video_sottotitoli.downloader.DOWNLOAD_JOBS_DIR", root / "downloads"),
                self.assertRaises(DownloadError),
            ):
                cleanup_download_staging(manifest_path)
            self.assertTrue((outside / "keep.txt").is_file())

    def test_chosen_name_is_persisted_while_staging_template_stays_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = DownloadWorker(
                "https://example.test/video", operation="download",
                destination_dir=root / "downloads", output_name="Titolo scelto",
            )
            with patch("video_sottotitoli.downloader.DOWNLOAD_JOBS_DIR", root / "jobs"):
                job, manifest = worker._new_job({
                    "id": "source123", "extractor": "Example",
                    "page_url": "https://example.test/video", "title": "Titolo originale",
                    "duration": 60,
                })
            self.assertEqual(manifest["output_name"], "Titolo scelto")
            self.assertEqual(manifest["filename_template"], "download-%(id)s.%(ext)s")
            self.assertEqual(
                json.loads((job / "download.json").read_text()) ["output_name"],
                "Titolo scelto",
            )

    def test_output_name_is_safe_unicode_and_uses_actual_extension(self) -> None:
        self.assertEqual(
            safe_output_name("大塚英志 / 物語:消費.mp4", ".mkv"),
            "大塚英志 物語 消費.mkv",
        )
        self.assertEqual(safe_output_name("Talk", ".webm"), "Talk.webm")
        for invalid in ("", "...", " / "):
            with self.subTest(invalid=invalid), self.assertRaises(DownloadError):
                safe_output_name(invalid, ".mkv")
        with self.assertRaises(DownloadError):
            safe_output_stem("///")

    def test_publish_uses_custom_name_and_adds_number_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            destination = root / "downloads"
            job_dir = root / "job"
            staging.mkdir()
            job_dir.mkdir()
            track = AudioTrack(1, 0, "ja", None, "opus")
            media = MediaInfo(str(staging / "internal-id.mkv"), 1, (track,))
            worker = DownloadWorker("https://example.test/video", operation="download")
            worker.event_log = EventLog(job_dir, lambda *_: None, "download")
            destination.mkdir()
            (destination / "Video leggibile.mkv").write_bytes(b"existing")
            for _ in range(2):
                source = staging / "internal-id.mkv"
                source.write_bytes(b"new verified media")
                with patch("video_sottotitoli.downloader.probe_media", return_value=media):
                    worker._publish(source, destination, job_dir, {
                        "output_name": "Video leggibile"
                    })
            self.assertEqual((destination / "Video leggibile (2).mkv").read_bytes(), b"new verified media")
            self.assertEqual((destination / "Video leggibile (3).mkv").read_bytes(), b"new verified media")

    def test_publish_emits_media_with_the_existing_final_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            destination = root / "downloads"
            job_dir = root / "job"
            staging.mkdir()
            job_dir.mkdir()
            source = staging / "download-video.mkv"
            source.write_bytes(b"verified-media")
            track = AudioTrack(1, 0, "ja", None, "opus")
            events: list[tuple[str, object]] = []
            worker = DownloadWorker("https://example.test/video", operation="download")
            worker.events = queue.Queue()
            worker.event_log = EventLog(job_dir, lambda kind, value: events.append((kind, value)), "download")
            stale_media = MediaInfo(str(source), 1538.0, (track,))
            with patch("video_sottotitoli.downloader.probe_media", return_value=stale_media):
                worker._publish(source, destination, job_dir, {})
            final = destination / source.name
            complete = next(value for kind, value in worker.events.queue if kind == "complete")
            self.assertTrue(final.is_file())
            self.assertEqual(complete["path"], str(final))
            self.assertEqual(complete["media"].path, str(final.resolve()))
            self.assertEqual(complete["media"].audio_tracks, (track,))

    def test_progress_prefers_exact_size_then_estimate_and_handles_unknown(self) -> None:
        worker = DownloadWorker("https://example.test/video", operation="download")
        worker.events = queue.Queue()
        worker._parse_progress("VSTT|download|downloading|25|100|120|8|5")
        exact = worker.events.get_nowait()[1]
        self.assertEqual(exact["total"], 100)
        self.assertFalse(exact["total_is_estimate"])
        worker._parse_progress("VSTT|download|downloading|25|NA|100|120|8")
        estimated = worker.events.get_nowait()[1]
        self.assertEqual(estimated["total"], 100)
        self.assertTrue(estimated["total_is_estimate"])
        worker._parse_progress("VSTT|download|downloading|25|NA|NA|120|8")
        unknown = worker.events.get_nowait()[1]
        self.assertIsNone(unknown["total"])
        self.assertFalse(unknown["total_is_estimate"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg mancante")
    def test_completed_separate_streams_are_merged_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            video = staging / "download-item123.f1.mp4"
            audio = staging / "download-item123.f2.webm"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=16x16:r=1", "-t", "1", "-an", "-c:v",
                 "mpeg4", str(video)], check=True,
            )
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 "anullsrc=r=48000:cl=mono", "-t", "1", "-vn", "-c:a",
                 "libopus", str(audio)], check=True,
            )
            worker = DownloadWorker("https://example.test/watch?id=item123", operation="download")
            merged = worker._merge_separate_streams(staging, {"source_id": "item123"})
            self.assertIsNotNone(merged)
            self.assertTrue(probe_media(merged).audio_tracks)
            self.assertEqual(worker._find_completed_staging_file(
                staging, {"source_id": "item123"}
            ), merged)

    def test_parse_public_recording_and_hide_temporary_query(self) -> None:
        info = parse_info(
            {
                "id": "abc123",
                "extractor_key": "Example",
                "title": "Talk",
                "duration": 3600,
                "webpage_url": "https://example.test/watch/abc?token=secret",
                "formats": [
                    {
                        "format_id": "1",
                        "height": 720,
                        "vcodec": "h264",
                        "acodec": "none",
                        "ext": "mp4",
                    },
                    {
                        "format_id": "2",
                        "vcodec": "none",
                        "acodec": "aac",
                        "language": "ja",
                        "ext": "m4a",
                    },
                ],
            }
        )
        self.assertEqual(info["duration"], 3600)
        self.assertEqual(info["page_url"], "https://example.test/watch/abc")
        self.assertEqual(info["audio_languages"], ["ja"])
        self.assertNotIn("secret", str(info))

    def test_page_url_keeps_public_identity_parameters_but_drops_credentials(self) -> None:
        info = parse_info({
            "id": "abc123", "extractor_key": "Example", "title": "Talk",
            "duration": 60,
            "webpage_url": "https://example.test/watch?id=abc123&lang=ja&token=secret&sig=temporary",
        })
        self.assertEqual(
            info["page_url"], "https://example.test/watch?id=abc123&lang=ja"
        )
        self.assertNotIn("secret", str(info))

    def test_reject_playlist_live_and_long_items(self) -> None:
        base = {"duration": 60, "id": "x"}
        for extra in (
            {"_type": "playlist"},
            {"is_live": True},
            {"duration": 5 * 60 * 60 + 1},
        ):
            with self.subTest(extra=extra), self.assertRaises(DownloadError):
                parse_info({**base, **extra})

    def test_youtube_page_url_keeps_video_id_and_repairs_old_manifest(self) -> None:
        info = parse_info({
            "id": "SVeS3SVLmBg", "extractor_key": "Youtube", "title": "Talk",
            "duration": 60, "webpage_url": "https://www.youtube.com/watch",
        })
        self.assertEqual(
            info["page_url"], "https://www.youtube.com/watch?v=SVeS3SVLmBg"
        )
        self.assertEqual(resumable_page_url({
            "extractor": "Youtube", "source_id": "SVeS3SVLmBg",
            "page_url": "https://www.youtube.com/watch",
        }), "https://www.youtube.com/watch?v=SVeS3SVLmBg")
        self.assertEqual(resumable_page_url({"page_url": ""}), "")

    def test_resume_format_validation_requires_saved_tracks(self) -> None:
        metadata = {"formats": [
            {"video": True, "audio": False, "height": 720},
            {"video": False, "audio": True, "language": "ja"},
        ]}
        validate_selected_format(metadata, "720p", "ja")
        validate_selected_format(metadata, "audio", "ja")
        with self.assertRaises(DownloadError):
            validate_selected_format(metadata, "audio", "en")
        with self.assertRaises(DownloadError):
            validate_selected_format(
                {"formats": [{"video": True, "audio": False, "height": 1080}]},
                "720p", None,
            )

    def test_url_safety_and_format_selectors(self) -> None:
        self.assertEqual(validate_page_url(" https://example.test/a "), "https://example.test/a")
        for url in ("file:///tmp/a", "https://user:pass@example.test/a"):
            with self.subTest(url=url), self.assertRaises(DownloadError):
                validate_page_url(url)
        self.assertIn("height<=1080", _selector("1080p", None))
        self.assertIn("height<=720", _selector("720p", None))
        self.assertEqual(_selector("audio", "ja"), "bestaudio[language=ja]/bestaudio")
        self.assertEqual(_selector("best", None), "bestvideo+bestaudio/best")

    def test_effective_quality_reports_fallback_before_download(self) -> None:
        metadata = {
            "formats": [
                {"video": True, "height": 480},
                {"video": True, "height": 720},
                {"video": False, "height": None},
            ]
        }
        self.assertEqual(effective_quality(metadata, "1080p"), "fino a 720p")
        self.assertEqual(effective_quality(metadata, "720p"), "fino a 720p")
        self.assertEqual(effective_quality(metadata, "audio"), "Solo audio")

    def test_failure_state_retains_resumable_download_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            (job / "download.json").write_text('{"status":"downloading"}', encoding="utf-8")
            worker = DownloadWorker("https://example.test/video", operation="download", job_dir=job)
            worker._save_failure_state()
            self.assertIn('"status": "error"', (job / "download.json").read_text())

    def test_event_log_is_append_only_and_filters_sensitive_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            events: list[tuple[str, object]] = []
            log = EventLog(Path(temporary), lambda kind, value: events.append((kind, value)), "download")
            line = log.write("failed https://example.test/x?token=secret Bearer abc123")
            saved = log.path.read_text(encoding="utf-8")
            self.assertIn("[DOWNLOAD] [INFO]", saved)
            self.assertIn("[link omesso]", line)
            self.assertIn("Bearer [omesso]", line)
            self.assertNotIn("secret", saved)
            self.assertEqual(events[0][0], "log_path")
            self.assertEqual(events[-1][0], "log")
            self.assertEqual(log.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("api_key=private", sanitize_message("api_key=private"))

    def test_sol_prices_and_defaults(self) -> None:
        self.assertEqual(MODEL_PRICING[MODEL_SOL], {"input": 2.0, "output": 10.0})
        self.assertEqual(MODEL_PRICING[MODEL_SOL_LEGACY], {"input": 4.0, "output": 20.0})
        self.assertEqual(default_model(REVISION_MODE_LINGUISTIC, OPERATION_TRANSLATION), MODEL_SOL)


if __name__ == "__main__":
    unittest.main()

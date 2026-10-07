import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.selection import create_chunks
from video_sottotitoli.worker import SubtitleWorker


class WorkerRangeTests(unittest.TestCase):
    def test_selected_french_is_used_for_transcription_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            output = root / "subtitles.srt"
            job_dir = root / "job"
            job_dir.mkdir()
            manifest = {
                "version": 4,
                "status": "preparing",
                "video": str(video),
                "duration": 60,
                "start_at_seconds": 0,
                "end_at_seconds": 60,
                "stream_index": 0,
                "source_language": "fr",
                "target_language": "it",
                "output": str(output),
                "chunks": create_chunks(60, 0, end_at_seconds=60),
            }

            def fake_extract(
                _video: str,
                _stream_index: int,
                _start: float,
                _duration: float,
                destination: Path,
            ) -> None:
                destination.write_bytes(b"audio")

            response = {
                "text": "Bonjour à tous.",
                "language": "French",
                "segments": [
                    {"text": "Bonjour à tous.", "start": 0.0, "end": 1.0}
                ],
                "words": [
                    {"word": "Bonjour", "start": 0.0, "end": 0.4},
                    {"word": "à", "start": 0.4, "end": 0.6},
                    {"word": "tous", "start": 0.6, "end": 1.0},
                ],
            }
            worker = SubtitleWorker(
                str(video), 60, 0, str(output), "test-key",
                source_language="fr", target_language="it",
            )

            with (
                patch(
                    "video_sottotitoli.worker.create_job",
                    return_value=(job_dir, manifest),
                ),
                patch(
                    "video_sottotitoli.worker.extract_audio_chunk",
                    side_effect=fake_extract,
                ),
                patch(
                    "video_sottotitoli.worker.transcribe_audio",
                    return_value=response,
                ) as transcribe_mock,
            ):
                worker.run()

            self.assertEqual(transcribe_mock.call_args.kwargs["language"], "fr")
            completed = next(
                value for kind, value in worker.events.queue if kind == "complete"
            )
            self.assertEqual(completed["effective_language"], "fr")
            self.assertEqual(completed["target_language"], "it")

    def test_simulated_transcription_keeps_selected_absolute_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            output = root / "subtitles.srt"
            job_dir = root / "job"
            job_dir.mkdir()
            manifest = {
                "version": 3,
                "status": "preparing",
                "video": str(video),
                "duration": 60 * 60,
                "start_at_seconds": 40 * 60,
                "end_at_seconds": 50 * 60,
                "stream_index": 0,
                "output": str(output),
                "chunks": create_chunks(60 * 60, 40 * 60, end_at_seconds=50 * 60),
            }

            def fake_extract(
                _video: str,
                _stream_index: int,
                _start: float,
                _duration: float,
                destination: Path,
            ) -> None:
                destination.write_bytes(b"audio")

            response = {
                "text": "Hello world.",
                "language": "english",
                "segments": [{"text": "Hello world."}],
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.4},
                    {"word": "world", "start": 0.5, "end": 0.9},
                    {"word": "goodbye", "start": 599.8, "end": 600.5},
                ],
            }
            worker = SubtitleWorker(
                str(video), 60 * 60, 0, str(output), "test-key", 40 * 60, 50 * 60
            )

            with (
                patch(
                    "video_sottotitoli.worker.create_job",
                    return_value=(job_dir, manifest),
                ) as create_job_mock,
                patch(
                    "video_sottotitoli.worker.extract_audio_chunk",
                    side_effect=fake_extract,
                ),
                patch(
                    "video_sottotitoli.worker.transcribe_audio",
                    return_value=response,
                ),
            ):
                worker.run()

            create_job_mock.assert_called_once_with(
                str(video), 60 * 60, 0, str(output), 40 * 60, 50 * 60,
                "auto", "original", "gpt-6-sol", "", str(output)
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("00:40:00,000 -->", rendered)
            self.assertIn("00:50:00,000", rendered)
            self.assertNotIn("00:50:00,500", rendered)
            self.assertIn("Hello world.", rendered)
            events = list(worker.events.queue)
            completed = next(value for kind, value in events if kind == "complete")
            self.assertEqual(completed["effective_language"], "en")


if __name__ == "__main__":
    unittest.main()

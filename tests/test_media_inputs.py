import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.gui import local_media_filetypes
from video_sottotitoli.media import (
    AUDIO_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaError,
    probe_media,
)


class MediaInputTests(unittest.TestCase):
    def test_local_picker_exposes_webm_and_common_audio_formats(self) -> None:
        patterns = " ".join(pattern for _label, pattern in local_media_filetypes())
        for suffix in (".webm", ".mp3", ".m4a", ".wav", ".flac", ".opus"):
            self.assertIn(f"*{suffix}", patterns)

        self.assertIn(".webm", VIDEO_EXTENSIONS)
        self.assertIn(".mp3", AUDIO_EXTENSIONS)
        self.assertEqual(
            SUPPORTED_EXTENSIONS,
            frozenset((*VIDEO_EXTENSIONS, *AUDIO_EXTENSIONS)),
        )

    def test_probe_accepts_audio_only_and_webm_sources(self) -> None:
        response = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "format": {"duration": "125.5"},
                    "streams": [
                        {
                            "index": 0,
                            "codec_type": "audio",
                            "codec_name": "opus",
                            "tags": {"language": "fra", "title": "Programme"},
                        }
                    ],
                }
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for filename in ("interview.opus", "recording.webm"):
                source = Path(temporary) / filename
                source.write_bytes(b"fixture")
                with (
                    self.subTest(filename=filename),
                    patch("video_sottotitoli.media._tool", return_value="ffprobe"),
                    patch("video_sottotitoli.media._run", return_value=response),
                ):
                    media = probe_media(source)
                    self.assertEqual(media.path, str(source.resolve()))
                    self.assertEqual(media.duration, 125.5)
                    self.assertEqual(len(media.audio_tracks), 1)
                    self.assertEqual(media.audio_tracks[0].codec, "opus")

    def test_probe_rejects_unknown_extension_before_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "notes.txt"
            source.write_text("not media", encoding="utf-8")
            with self.assertRaisesRegex(MediaError, "Formato audio/video non supportato"):
                probe_media(source)


if __name__ == "__main__":
    unittest.main()

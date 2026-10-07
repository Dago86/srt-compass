import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.api_client import post_transcription


class TranscriptionRequestTests(unittest.TestCase):
    def test_french_language_hint_is_sent_to_whisper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "audio.mp3"
            audio.write_bytes(b"audio")
            with patch(
                "video_sottotitoli.api_client._request",
                return_value={"language": "french"},
            ) as request_mock:
                post_transcription("test-key", audio, "fr")

        request = request_mock.call_args.args[0]
        body = request.data
        self.assertIn(b'name="language"', body)
        self.assertIn(b"\r\n\r\nfr\r\n", body)
        self.assertIn(b"whisper-1", body)

    def test_automatic_detection_omits_language_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "audio.mp3"
            audio.write_bytes(b"audio")
            with patch(
                "video_sottotitoli.api_client._request", return_value={}
            ) as request_mock:
                post_transcription("test-key", audio, "auto")

        self.assertNotIn(b'name="language"', request_mock.call_args.args[0].data)


if __name__ == "__main__":
    unittest.main()

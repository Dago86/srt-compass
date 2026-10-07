import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.config import (
    LANGUAGE_CODES_BY_LABEL,
    LANGUAGE_NAMES,
    LANGUAGES,
    SOURCE_LANGUAGE_CODES_BY_LABEL,
    SOURCE_LANGUAGES,
)


class LanguageConfigurationTests(unittest.TestCase):
    def test_french_is_available_only_as_spoken_language(self) -> None:
        self.assertEqual(LANGUAGE_NAMES["fr"], "Francese")
        self.assertEqual(SOURCE_LANGUAGES["fr"], "Francese")
        self.assertEqual(SOURCE_LANGUAGE_CODES_BY_LABEL["Francese"], "fr")
        self.assertNotIn("fr", LANGUAGES)
        self.assertNotIn("Francese", LANGUAGE_CODES_BY_LABEL)

    def test_existing_final_languages_are_unchanged(self) -> None:
        self.assertEqual(
            LANGUAGES,
            {"en": "Inglese", "it": "Italiano", "ja": "Giapponese"},
        )


if __name__ == "__main__":
    unittest.main()

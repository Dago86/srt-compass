from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_sottotitoli.i18n import (
    CATALOGS,
    detect_system_locale,
    get_locale,
    language_code,
    language_label,
    load_locale,
    save_locale,
    set_locale,
    tr,
)


class LocalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = get_locale()

    def tearDown(self) -> None:
        set_locale(self.previous)

    def test_catalogs_have_the_same_message_ids(self) -> None:
        self.assertEqual(set(CATALOGS["en"]), set(CATALOGS["it"]))

    def test_language_labels_round_trip_without_changing_codes(self) -> None:
        for locale_code in ("en", "it"):
            set_locale(locale_code)
            for code in ("auto", "en", "it", "ja", "fr", "original"):
                self.assertEqual(language_code(language_label(code)), code)

    def test_unsupported_system_language_falls_back_to_english(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": '(\n    "de-DE"\n)\n'})()
        with patch("video_sottotitoli.i18n.sys.platform", "darwin"), patch(
            "video_sottotitoli.i18n.subprocess.run", return_value=completed
        ):
            self.assertEqual(detect_system_locale(), "en")

    def test_italian_system_language_is_detected(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": '(\n    "it-IT",\n    "en-GB"\n)\n'})()
        with patch("video_sottotitoli.i18n.sys.platform", "darwin"), patch(
            "video_sottotitoli.i18n.subprocess.run", return_value=completed
        ):
            self.assertEqual(detect_system_locale(), "it")

    def test_preference_is_saved_atomically_and_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            save_locale(path, "it")
            self.assertEqual(load_locale(path), "it")
            self.assertEqual(json.loads(path.read_text())["ui_locale"], "it")
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_translation_uses_selected_catalog(self) -> None:
        set_locale("en")
        self.assertEqual(tr("main.generate"), "Generate subtitles")
        set_locale("it")
        self.assertEqual(tr("main.generate"), "Genera sottotitoli")


if __name__ == "__main__":
    unittest.main()

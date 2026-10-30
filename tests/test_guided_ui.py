"""The guided choices must not start an API operation by themselves."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.gui import App
from video_sottotitoli.i18n import language_label


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class GuidedFlowTests(unittest.TestCase):
    def test_switching_back_to_original_cancels_pending_estimate(self):
        app = SimpleNamespace(
            media=None, transcription_ready=True, translation_source="/tmp/lesson.srt",
            worker=None, translation_worker=None, summary_worker=None,
            _active_download=lambda: None, _busy=True,
            target_language=Variable(language_label("original")),
            target_language_var=Variable(), translation_target_var=Variable(),
            translation_source_var=Variable("fr"), translation_estimate_var=Variable(),
            _set_translation_destination=Mock(), _cancel_translation_estimate=Mock(),
            _update_translation_estimate=Mock(), _set_workflow_controls=Mock(),
            _update_footer_state=Mock(),
        )
        App._final_language_changed(app, object())
        app._cancel_translation_estimate.assert_called_once_with()
        app._update_translation_estimate.assert_not_called()
        self.assertEqual(app.translation_target_var.get(), "original")

    def test_completed_transcription_waits_for_explicit_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "lecture.srt"
            original.write_text(
                "1\n00:00:01,000 --> 00:00:02,000\nBonjour\n",
                encoding="utf-8",
            )
            app = SimpleNamespace(
                _clear_translation_flow=Mock(),
                translation_source=None,
                translation_captions=[],
                translation_source_var=Variable(),
                source_language_var=Variable(),
                source_language=Mock(),
                target_language=Variable(language_label("original")),
                translation_target_var=Variable(),
                transcription_job_path=None,
                status_var=Variable(),
                result_summary_var=Variable(),
                translation_estimate_var=Variable(),
                _set_workflow_controls=Mock(),
                _update_translation_estimate=Mock(),
                _update_footer_state=Mock(),
                _set_translation_destination=lambda target: App._set_translation_destination(app, target),
            )
            App._prepare_guided_translation(app, {
                "output": str(original), "effective_language": "fr",
            })
            self.assertEqual(app.guided_page, "translation")
            self.assertTrue(app.ready_to_translate)
            self.assertEqual(app.final_output_path, original)
            app._update_translation_estimate.assert_not_called()

            app.target_language.set(language_label("it"))
            App._set_translation_destination(app, "it")
            self.assertEqual(app.final_output_path, original.with_name("lecture.it.srt"))
            self.assertTrue(original.is_file())

    def test_translation_destination_never_reuses_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "lecture.original.srt"
            original.write_text("original", encoding="utf-8")
            existing = Path(folder) / "lecture.it.srt"
            existing.write_text("existing", encoding="utf-8")
            app = SimpleNamespace(
                translation_source=str(original),
                translation_source_var=Variable("fr"),
                final_output_path=None,
            )
            App._set_translation_destination(app, "it")
            self.assertEqual(app.final_output_path.name, "lecture.it-2.srt")
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing")

    def test_original_result_requires_no_translation_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "lecture.srt"
            original.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
            app = SimpleNamespace(
                transcription_ready=True,
                translation_source=str(original),
                transcription_job_path=None,
                _set_result=Mock(),
                status_var=Variable(),
                summary_requested=False,
                _update_footer_state=Mock(),
            )
            App._use_original(app)
            self.assertEqual(app.guided_page, "result")
            app._set_result.assert_called_once_with(original)


if __name__ == "__main__":
    unittest.main()

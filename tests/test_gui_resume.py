import queue
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.gui import (
    App,
    DownloadDialog,
    EventLogPanel,
    RecentJobsDialog,
    TimeRangeScale,
    _download_progress_display,
)
from video_sottotitoli.models import MediaInfo


class GuiResumeTests(unittest.TestCase):
    def test_work_summary_tracks_source_language_and_phase(self) -> None:
        summary = Mock()
        app = SimpleNamespace(
            media=SimpleNamespace(path="/tmp/lesson.mp4"),
            video_var=SimpleNamespace(get=lambda: "/tmp/lesson.mp4"),
            target_language=SimpleNamespace(get=lambda: "Italiano"),
            work_summary_var=summary, worker=None, translation_worker=None,
            _active_download=lambda: None, _read_interval=lambda: (2400, 3000),
        )
        App._refresh_work_summary(app)
        self.assertIn("intervallo 00:40:00–00:50:00", summary.set.call_args.args[0])
        app.translation_worker = object()
        App._refresh_work_summary(app)
        self.assertEqual(
            summary.set.call_args.args[0], "Traduzione in italiano · lesson.mp4"
        )

    def test_details_hide_secondary_controls_when_collapsed(self) -> None:
        panel = SimpleNamespace(
            expanded=False, details=Mock(), body=Mock(), toggle_button=Mock(),
        )
        EventLogPanel.toggle(panel)
        panel.details.pack.assert_called_once()
        panel.body.pack.assert_called_once()
        EventLogPanel.toggle(panel)
        panel.details.pack_forget.assert_called_once()
        panel.body.pack_forget.assert_called_once()

    def test_details_filter_has_explicit_choices(self) -> None:
        panel = SimpleNamespace(
            filter_var=SimpleNamespace(get=lambda: "Avvisi ed errori"),
            filter_errors=False, text=Mock(), _render=Mock(),
        )
        EventLogPanel._filter_changed(panel)
        self.assertTrue(panel.filter_errors)
        panel._render.assert_called_once_with(keep_position=False)

    def test_resume_shortcut_does_not_open_unrelated_job(self) -> None:
        app = SimpleNamespace(
            job_resumable=False, current_job_path=None,
            download_state="inattivo", download_dialog=None, resume=Mock(),
        )
        self.assertEqual(App._resume_shortcut(app, None), "break")
        app.resume.assert_not_called()

    def test_new_work_is_hidden_while_summary_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            srt = Path(temporary) / "ready.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
            controls = {
                name: Mock() for name in (
                    "show_finder_button", "show_issues_button", "open_summary_button",
                    "new_work_button", "start_button", "resume_button",
                    "cancel_button", "footer_open_button", "summary_button",
                )
            }
            app = SimpleNamespace(
                **controls, work_summary_var=Mock(), _refresh_work_summary=Mock(),
                final_output_path=srt, result_report_path=None, summary_output=None,
                worker=None, translation_worker=None, summary_worker=object(),
                _active_download=lambda: None, _busy=False, cancel_requested=False,
            )
            App._update_footer_state(app)
            app.show_finder_button.pack.assert_called_once()
            app.new_work_button.pack.assert_not_called()
            app.cancel_button.pack.assert_called_once()

    def test_changing_link_after_interruption_detaches_old_job(self) -> None:
        dialog = SimpleNamespace(
            worker=None, _setting_saved_url=False, _allow_resume_url_edit=False,
            metadata=None, resume_job=Path("/tmp/old-download"),
            _reset_download_selection=Mock(), info_var=Mock(), status_var=Mock(),
        )
        DownloadDialog._url_changed(dialog)
        dialog._reset_download_selection.assert_called_once_with(clear_url=False)
        dialog.info_var.set.assert_called_once_with(
            "Link cambiato. Analizza il nuovo video prima di scaricarlo."
        )
        dialog.status_var.set.assert_called_once_with(
            "Nuovo link: premi Analizza link per continuare."
        )

    def test_new_download_clears_interrupted_video_details(self) -> None:
        app = SimpleNamespace(
            download_state="interrotto", activity_var=Mock(), status_var=Mock(),
            master=SimpleNamespace(after_idle=Mock()), _update_footer_state=Mock(),
        )
        dialog = SimpleNamespace(
            app=app, worker=None, resume_job=Path("/tmp/old-download"),
            metadata={"title": "Vecchio video"}, _allow_resume_url_edit=True,
            download_button=Mock(), quality_var=Mock(), audio_language_var=Mock(),
            audio_combo=Mock(), filename_var=Mock(), log_panel=Mock(),
            progress=Mock(), progress_var=Mock(), url_var=Mock(), status_var=Mock(),
            download=Mock(), _set_running=Mock(),
        )
        DownloadDialog._reset_download_selection(dialog, clear_url=True)
        self.assertIsNone(dialog.resume_job)
        self.assertIsNone(dialog.metadata)
        self.assertEqual(app.download_state, "inattivo")
        dialog.url_var.set.assert_called_once_with("")
        dialog.filename_var.set.assert_called_once_with("")
        dialog.audio_combo.configure.assert_called_with(
            values=["Traccia predefinita del sito"], state="disabled"
        )
        dialog.download_button.configure.assert_called_with(
            text="Scarica video", command=dialog.download, state="disabled"
        )
        dialog.log_panel.clear.assert_called_once()
        dialog.progress_var.set.assert_called_once_with("")
        dialog.url_var.get.return_value = "https://example.test/watch?v=new"
        with patch("video_sottotitoli.gui.DownloadWorker") as worker_class:
            DownloadDialog.analyze(dialog)
        worker_class.assert_called_once_with(
            "https://example.test/watch?v=new", operation="analyze", job_dir=None
        )

    def test_main_link_action_starts_fresh_after_interruption(self) -> None:
        dialog = SimpleNamespace(
            worker=None, winfo_exists=lambda: True, start_new_download=Mock(),
            deiconify=Mock(), lift=Mock(),
        )
        app = SimpleNamespace(
            worker=None, translation_worker=None, summary_worker=None,
            workflow_active=False, _busy=False, _active_download=lambda: None,
            download_dialog=dialog,
        )
        App.open_download_dialog(app)
        dialog.start_new_download.assert_called_once()

    def test_missing_saved_link_can_be_entered_for_same_job(self) -> None:
        dialog = SimpleNamespace(
            worker=None, _setting_saved_url=False, _allow_resume_url_edit=True,
            resume_job=Path("/tmp/old-download"), url_var=Mock(),
            download_button=Mock(),
        )
        dialog.url_var.get.return_value = "https://example.test/watch?v=1"
        DownloadDialog._url_changed(dialog)
        self.assertEqual(dialog.resume_job, Path("/tmp/old-download"))
        dialog.download_button.configure.assert_called_once_with(state="normal")

    def test_saved_download_resumes_without_separate_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "download.json"
            path.write_text('{"status":"cancelled","page_url":"https://example.test/watch?v=1",'
                            '"quality":"1080p","title":"Saved"}', encoding="utf-8")
            dialog = SimpleNamespace(
                QUALITY=DownloadDialog.QUALITY,
                worker=None, resume_job=None, metadata=None, progress=Mock(),
                progress_var=Mock(), url_var=Mock(), quality_var=Mock(),
                audio_language_var=Mock(), destination_var=Mock(), filename_var=Mock(),
                log_panel=Mock(), info_var=Mock(), status_var=Mock(),
                download_button=Mock(), url_entry=Mock(), _set_running=Mock(),
                resume_current=Mock(), download=Mock(),
            )
            dialog.url_var.get.return_value = "https://example.test/watch?v=1"
            dialog.url_var.set.side_effect = lambda _value: DownloadDialog._url_changed(dialog)
            DownloadDialog.load_download(dialog, path)
            self.assertEqual(dialog.resume_job, path.parent)
            dialog.download_button.configure.assert_called_with(
                text="Riprendi", command=dialog.resume_current
            )
            DownloadDialog.resume_current(dialog)
            dialog.download.assert_called_once_with()

    def test_successful_download_loads_final_path_then_closes_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "published.mkv"
            path.write_bytes(b"media")
            media = MediaInfo(
                path="/old/staging/published.mkv", duration=12.0, audio_tracks=(),
            )
            app = SimpleNamespace(
                video_var=Mock(), _receive_media=Mock(), log_panel=Mock(),
                status_var=Mock(), master=MagicMock(), _download_stopped=Mock(),
            )
            worker = SimpleNamespace(event_log=SimpleNamespace(write=Mock(return_value="loaded")))
            dialog = SimpleNamespace(
                progress=Mock(), progress_var=Mock(), status_var=Mock(), app=app,
                _set_running=Mock(), destroy=Mock(), worker=worker,
                resume_job=Path("/tmp/job"), started_at=1.0,
            )
            result = DownloadDialog._finish_download_success(dialog, {
                "path": str(path), "media": media, "job_dir": temporary,
            }, worker)
            self.assertTrue(result)
            app.video_var.set.assert_called_once_with(str(path.resolve()))
            loaded_media = app._receive_media.call_args.args[0]
            self.assertEqual(loaded_media.path, str(path.resolve()))
            dialog.destroy.assert_called_once()
            self.assertIsNone(dialog.worker)

    def test_failed_media_load_keeps_download_dialog_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "published.mkv"
            path.write_bytes(b"media")
            app = SimpleNamespace(
                video_var=Mock(), _receive_media=Mock(side_effect=RuntimeError("probe errato")),
                log_panel=Mock(), status_var=Mock(), master=MagicMock(),
                _download_stopped=Mock(),
            )
            dialog = SimpleNamespace(
                progress=Mock(), progress_var=Mock(), status_var=Mock(), app=app,
                _set_running=Mock(), destroy=Mock(), deiconify=Mock(), worker=object(),
                resume_job=Path("/tmp/job"), started_at=1.0,
            )
            result = DownloadDialog._finish_download_success(dialog, {
                "path": str(path),
                "media": MediaInfo(path="/staging/published.mkv", duration=12, audio_tracks=()),
                "job_dir": temporary,
            }, None)
            self.assertFalse(result)
            dialog.destroy.assert_not_called()
            self.assertIn("caricare il video", dialog.status_var.set.call_args.args[0])

    def test_completed_transcription_opens_saved_translation_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "original.srt"
            output.write_text("1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n", encoding="utf-8")
            manifest = {
                "status": "completed", "video": "/missing/video.mkv",
                "output": str(output), "source_language": "ja",
                "target_language": "it", "detected_languages": ["ja"],
            }
            app = SimpleNamespace(
                worker=None, translation_worker=None,
                video_var=Mock(), output_var=Mock(), target_language=Mock(),
                translation_target_var=Mock(), translation_model_var=Mock(),
                translation_model_combo=Mock(), translation_context_var=Mock(),
                _prepare_translation=Mock(),
            )
            with (
                patch("video_sottotitoli.gui.load_job", return_value=manifest),
                patch("video_sottotitoli.gui.load_api_key") as key,
            ):
                App._resume_selected_job(app, Path(temporary) / "job.json")
            key.assert_not_called()
            app._prepare_translation.assert_called_once_with({
                "output": str(output), "target_language": "it",
                "effective_language": "ja",
                "target_model": None, "translation_context": "",
                "final_output": str(output),
            })
            app.target_language.set.assert_called_once_with("Italiano")

    def test_download_poll_survives_analysis_before_next_download(self) -> None:
        events: queue.Queue[tuple[str, object]] = queue.Queue()
        events.put(("analysis", {
            "job_dir": "/tmp/download-job", "duration": 90,
            "size": 28_000_000, "title": "Talk", "site": "Example",
            "audio_languages": [], "formats": [],
        }))
        dialog = SimpleNamespace(
            worker=SimpleNamespace(events=events),
            progress=Mock(), progress_var=Mock(), status_var=Mock(),
            audio_combo=Mock(), audio_language_var=Mock(), log_panel=Mock(),
            filename_var=Mock(), download_button=Mock(), download=Mock(),
            _quality_changed=Mock(), _set_running=Mock(),
            app=SimpleNamespace(download_state="analisi"),
            started_at=None, winfo_exists=lambda: True, after=Mock(), _poll=Mock(),
        )
        dialog.audio_language_var.get.return_value = "Traccia predefinita del sito"
        dialog.filename_var.get.return_value = ""
        DownloadDialog._poll(dialog)
        self.assertIsNone(dialog.worker)
        self.assertNotIn("28", dialog.metadata["summary"])
        self.assertIn("dimensione finale non disponibile", dialog.metadata["summary"])
        dialog.status_var.set.assert_called_with(
            "Analisi completata. Controlla la qualità prevista e premi Scarica."
        )
        dialog.filename_var.set.assert_called_once_with("Talk")
        dialog.after.assert_called_once_with(100, dialog._poll)

    def test_download_poll_continues_after_worker_finishes(self) -> None:
        events: queue.Queue[tuple[str, object]] = queue.Queue()
        events.put(("cancelled", "saved job"))
        dialog = SimpleNamespace(
            worker=SimpleNamespace(events=events, job_dir=Path("/tmp/download-job")),
            progress=Mock(), status_var=Mock(), started_at=1.0,
            download_button=Mock(), resume_current=Mock(), resume_job=None,
            _set_running=Mock(), winfo_exists=lambda: True, after=Mock(), _poll=Mock(),
            app=SimpleNamespace(_download_stopped=Mock()),
        )
        DownloadDialog._poll(dialog)
        self.assertIsNone(dialog.worker)
        dialog.status_var.set.assert_called_with(
            "Download interrotto. I file parziali sono conservati. "
            "Puoi riprendere il trasferimento."
        )
        self.assertEqual(dialog.resume_job, Path("/tmp/download-job"))
        dialog.download_button.configure.assert_called_with(text="Riprendi", command=dialog.resume_current)
        dialog.after.assert_called_once_with(100, dialog._poll)

    def test_main_resume_starts_revision_job_directly(self) -> None:
        job_dir = Path("/tmp/revision-jobs/example")
        manifest = {
            "status": "error", "source": "/tmp/original.srt",
            "operation": "translation", "source_language": "ja",
            "target_language": "it",
        }
        app = SimpleNamespace(
            worker=None, translation_worker=None, master=MagicMock(),
            _resume_revision_job=Mock(),
        )
        with (
            patch("video_sottotitoli.gui.load_api_key", return_value="unused"),
            patch("video_sottotitoli.gui.load_revision_for_resume",
                  return_value=(manifest, MagicMock())),
        ):
            App._resume_selected_job(app, job_dir / "revision.json")
        app._resume_revision_job.assert_called_once_with(
            job_dir, manifest, "unused"
        )

    def test_download_progress_is_visible_with_estimated_and_fragment_totals(self) -> None:
        detail, percent = _download_progress_display({
            "downloaded": 30, "total": 100, "total_is_estimate": True,
            "stream": "video", "speed": 10, "eta": 7,
        })
        self.assertEqual(percent, 30)
        self.assertIn("Flusso video · circa 30.0%", detail)
        detail, percent = _download_progress_display({
            "downloaded": 0, "total": None,
            "fragment_index": 2, "fragment_count": 4, "stream": "audio",
        })
        self.assertEqual(percent, 50)
        self.assertIn("Flusso audio · 50.0%", detail)
        detail, percent = _download_progress_display({"downloaded": 1024, "total": None})
        self.assertIsNone(percent)
        self.assertIn("Percentuale non disponibile", detail)
        self.assertNotIn("rimanenti", detail)

    def test_progress_event_reaches_main_window_widgets(self) -> None:
        events: queue.Queue[tuple[str, object]] = queue.Queue()
        events.put(("progress", {
            "stage": "download", "downloaded": 25, "total": 100,
            "total_is_estimate": False, "speed": None, "eta": None,
            "stream": "video",
        }))
        app = SimpleNamespace(_show_download_progress=Mock())
        dialog = SimpleNamespace(
            worker=SimpleNamespace(events=events), app=app,
            progress=Mock(), progress_var=Mock(), status_var=Mock(),
            started_at=None, winfo_exists=lambda: True, after=Mock(), _poll=Mock(),
            _mirror_download_progress=lambda value, detail:
                DownloadDialog._mirror_download_progress(dialog, value, detail),
        )
        DownloadDialog._poll(dialog)
        app._show_download_progress.assert_called_once()
        self.assertEqual(app._show_download_progress.call_args.args[1], 25)
        self.assertIn("25.0%", app._show_download_progress.call_args.args[0])

    def test_download_eta_disappears_during_merge_and_verification(self) -> None:
        events: queue.Queue[tuple[str, object]] = queue.Queue()
        events.put(("progress", {
            "stage": "download", "downloaded": 25, "total": 100,
            "stream": "video", "eta": 20,
        }))
        events.put(("progress", {"stage": "postprocess"}))
        events.put(("progress", {"stage": "verifica"}))
        app = SimpleNamespace(
            _show_download_progress=Mock(), _show_download_phase=Mock(),
        )
        dialog = SimpleNamespace(
            worker=SimpleNamespace(events=events), app=app,
            progress=Mock(), progress_var=Mock(), status_var=Mock(),
            winfo_exists=lambda: True, after=Mock(), _poll=Mock(),
            _mirror_download_progress=lambda value, detail:
                DownloadDialog._mirror_download_progress(dialog, value, detail),
        )
        DownloadDialog._poll(dialog)
        self.assertIn("20 s rimanenti", app._show_download_progress.call_args.args[0])
        app._show_download_phase.assert_any_call("unione", "Unione e preparazione del file…")
        app._show_download_phase.assert_any_call("verifica", "Verifico il file scaricato…")
        dialog.progress_var.set.assert_called_with("Verifico il file scaricato…")

    def test_footer_shows_interrupt_even_with_known_download_percent(self) -> None:
        app = SimpleNamespace(
            start_button=Mock(), resume_button=Mock(), cancel_button=Mock(),
            footer_open_button=Mock(), summary_button=Mock(),
            worker=None, translation_worker=None, summary_worker=None,
            cancel_requested=False, _busy=False, _active_download=lambda: object(),
        )
        App._update_footer_state(app)
        app.cancel_button.pack.assert_called_once_with(side="right")

    def test_download_does_not_replace_progress_with_elapsed_clock(self) -> None:
        app = SimpleNamespace(
            activity_started_at=100.0, phase_started_at=110.0,
            last_activity_event_at=120.0, activity_var=Mock(),
            _active_download=lambda: object(),
        )
        with patch("video_sottotitoli.gui.time.monotonic", return_value=160.0):
            App._refresh_activity_clock(app)
        app.activity_var.set.assert_not_called()
        app._active_download = lambda: None
        with patch("video_sottotitoli.gui.time.monotonic", return_value=160.0):
            App._refresh_activity_clock(app)
        self.assertIn("Tempo totale 00:01:00", app.activity_var.set.call_args.args[0])

    def test_video_controls_follow_media_and_work_state(self) -> None:
        controls = (
            "choose_video_button", "link_button", "choose_output_button",
            "reset_range_button", "summary_check_button", "advanced_toggle",
            "copy_source_path_button", "output_path_button", "output_entry",
            "track", "source_language", "target_language",
            "translation_model_combo", "translation_context_entry",
            "start_entry", "end_entry", "range_scale", "start_button",
        )
        app = SimpleNamespace(**{name: Mock() for name in controls})
        app.media = None
        app.video_var = Mock()
        app.output_var = Mock()
        app.video_var.get.return_value = ""
        app.output_var.get.return_value = ""
        app.source_language.get.return_value = "Automatico"
        app.target_language.get.return_value = "Originale"
        app.master = SimpleNamespace(tools_menu=Mock(), after_idle=Mock())
        app.master.tools_menu.index.return_value = 1
        app._update_footer_state = Mock()
        app._update_output_path = Mock()
        app._enable_start = Mock()
        app._translation_options_needed = lambda: App._translation_options_needed(app)

        App._set_workflow_controls(app, True)
        app.choose_video_button.configure.assert_called_with(state="normal")
        app.link_button.configure.assert_called_with(state="normal")
        app.source_language.configure.assert_called_with(state="disabled")
        app.choose_output_button.configure.assert_called_with(state="disabled")
        app.start_entry.configure.assert_called_with(state="disabled")
        app.advanced_toggle.configure.assert_called_with(state="disabled")

        app.media = SimpleNamespace(audio_tracks=(object(),))
        app.video_var.get.return_value = "/tmp/video.mkv"
        app.output_var.get.return_value = "/tmp/video.srt"
        App._set_workflow_controls(app, True)
        app.track.configure.assert_called_with(state="readonly")
        app.start_entry.configure.assert_called_with(state="normal")
        app.translation_model_combo.configure.assert_called_with(state="disabled")
        app.output_path_button.configure.assert_called_with(state="normal")

        app.target_language.get.return_value = "Italiano"
        App._set_workflow_controls(app, True)
        app.translation_model_combo.configure.assert_called_with(state="readonly")
        app.translation_context_entry.configure.assert_called_with(state="normal")
        App._set_workflow_controls(app, False)
        app.choose_video_button.configure.assert_called_with(state="disabled")
        app.translation_model_combo.configure.assert_called_with(state="disabled")

    def test_disabled_range_ignores_mouse_and_keyboard(self) -> None:
        scale = SimpleNamespace(cget=lambda _name: "disabled", focus_set=Mock())
        TimeRangeScale._press(scale, SimpleNamespace(x=20))
        self.assertEqual(TimeRangeScale._nudge(scale, 1), "break")
        scale.focus_set.assert_not_called()

    def test_main_close_cancels_active_download_before_destroying(self) -> None:
        worker = SimpleNamespace(operation="download")
        dialog = SimpleNamespace(worker=worker, cancel=Mock())
        app = SimpleNamespace(
            worker=None, translation_worker=None, summary_worker=None,
            download_dialog=dialog, master=MagicMock(), status_var=Mock(),
            cancel_requested=False, cancel_button=Mock(), _close_after_cancel=False,
            _active_download=lambda: worker, cancel=Mock(),
        )
        with patch("video_sottotitoli.gui.messagebox.askyesno", return_value=True):
            App._request_close(app)
        app.cancel.assert_called_once_with()
        app.master.destroy.assert_not_called()

    def test_main_interrupt_routes_to_download_worker(self) -> None:
        dialog = SimpleNamespace(cancel=Mock())
        app = SimpleNamespace(
            worker=None, translation_worker=None, summary_worker=None,
            download_dialog=dialog, _active_download=lambda: object(),
            cancel_requested=False, cancel_button=Mock(), status_var=Mock(),
            master=SimpleNamespace(after_idle=Mock()), _update_footer_state=Mock(),
        )
        App.cancel(app)
        dialog.cancel.assert_called_once_with()
        self.assertTrue(app.cancel_requested)
        app.cancel_button.configure.assert_called_with(state="disabled")

    def test_recent_resume_requires_selection(self) -> None:
        recent = SimpleNamespace(
            tree=SimpleNamespace(selection=lambda: ()), rows={},
            cleanup_in_progress=False, cleanup_button=Mock(),
            resume_button=Mock(), app=SimpleNamespace(_resume_selected_job=Mock()),
            destroy=Mock(), _selected=lambda: None,
        )
        RecentJobsDialog._selection_changed(recent)
        recent.resume_button.configure.assert_called_with(state="disabled")
        recent.resume_button.instate.return_value = False
        RecentJobsDialog.resume(recent)
        recent.app._resume_selected_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()

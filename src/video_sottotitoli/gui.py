from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, ClassVar

from .config import (
    AI_PROVIDERS,
    DEFAULT_DOWNLOAD_DIR,
    DOWNLOAD_JOBS_DIR,
    LANGUAGE_NAMES,
    LANGUAGES,
    LOG_DIR,
    MODEL_MINI,
    MODEL_SOL,
    MODEL_SOL_LEGACY,
    PREFERENCES_PATH,
    PROVIDER_DEEPSEEK,
    PROVIDER_MODELS,
    PROVIDER_OPENAI,
    REVISION_JOBS_DIR,
    SOURCE_LANGUAGES,
    estimate_cost_usd,
    load_api_key,
    load_provider_api_key,
    save_provider_api_key,
)
from .downloader import (
    DownloadError,
    DownloadWorker,
    cleanup_all_download_staging,
    cleanup_download_staging,
    effective_quality,
    inspect_download_staging,
    resumable_page_url,
    safe_output_stem,
    validate_selected_format,
)
from .i18n import (
    get_locale,
    language_code,
    language_label,
    load_locale,
    save_locale,
    set_locale,
    tr,
)
from .jobs import fingerprint, load_job, save_job
from .media import probe_media
from .models import MediaInfo
from .platform import open_path, secret_store_label
from .recent_jobs import list_recent_jobs
from .revision import (
    OPERATION_REVISION,
    OPERATION_TRANSLATION,
    REVISION_MODE_CONSERVATIVE,
    REVISION_MODE_LINGUISTIC,
    RevisionError,
    default_model,
    estimate_revision,
    load_captions,
    suggest_source_language,
)
from .revision_worker import RevisionWorker, load_revision_for_resume
from .selection import (
    StartTimeError,
    format_time_value,
    parse_time_range,
)
from .srt import format_srt_file, format_srt_text
from .video_summary import SummaryWorker, estimate_summary, summary_output_path
from .worker import SubtitleWorker


class EventLogPanel(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.path: str | None = None
        self.expanded = False
        self.lines: list[str] = []
        self.filter_errors = False
        self.has_new_lines = False
        header = ttk.Frame(self)
        header.pack(fill="x")
        self.toggle_button = ttk.Button(
            header, text=tr("details.show"), command=self.toggle
        )
        self.toggle_button.pack(side="left")
        self.details = ttk.Frame(self)
        self.filter_var = tk.StringVar(value=tr("details.all"))
        self.filter_combo = ttk.Combobox(
            self.details, textvariable=self.filter_var, state="readonly", width=19,
            values=(tr("details.all"), tr("details.warnings")),
        )
        self.filter_combo.pack(side="left", padx=(8, 0))
        self.filter_combo.bind("<<ComboboxSelected>>", self._filter_changed)
        self.latest_button = ttk.Button(
            self.details, text=tr("details.latest"), command=self.go_latest,
            state="disabled",
        )
        self.latest_button.pack(side="left", padx=(8, 0))
        self.copy_button = ttk.Button(
            self.details, text=tr("details.copy"), command=self.copy_diagnostics
        )
        self.copy_button.pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(
            self.details, text=tr("details.open_log"), command=self.open_log, state="disabled"
        )
        self.open_button.pack(side="right")
        body = ttk.Frame(self)
        self.body = body
        self.text = tk.Text(body, height=7, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.details.pack(fill="x", pady=(6, 0))
            self.body.pack(fill="both", expand=True, pady=(6, 0))
            self.toggle_button.configure(text=tr("details.hide"))
        else:
            self.body.pack_forget()
            self.details.pack_forget()
            self.toggle_button.configure(text=tr("details.show"))

    def set_log(self, path: str) -> None:
        if not path or self.path == path:
            return
        self.path = path
        self.open_button.configure(state="normal")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError:
            content = "Il file di log non è disponibile."
        self.lines = content.splitlines()[-1000:]
        self._render(keep_position=False)
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.path = None
        self.lines.clear()
        self.open_button.configure(state="disabled")
        self.latest_button.configure(state="disabled")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def add_line(self, line: str) -> None:
        was_at_bottom = self.text.yview()[1] >= 0.99
        self.lines.append(line)
        overflow = len(self.lines) > 1000
        self.lines = self.lines[-1000:]
        if not was_at_bottom:
            self.has_new_lines = True
            self.latest_button.configure(state="normal")
        if self.filter_errors and "[WARNING]" not in line and "[ERROR]" not in line:
            return
        self.text.configure(state="normal")
        if overflow:
            self.text.delete("1.0", "2.0")
        self.text.insert("end", line + "\n")
        if was_at_bottom:
            self.text.see("end")
        self.text.configure(state="disabled")

    def _render(self, *, keep_position: bool) -> None:
        self.text.delete("1.0", "end")
        visible = [
            line for line in self.lines
            if not self.filter_errors or "[WARNING]" in line or "[ERROR]" in line
        ]
        self.text.insert("end", "\n".join(visible) + ("\n" if visible else ""))
        if keep_position:
            return
        self.text.see("end")

    def _filter_changed(self, _event: object | None = None) -> None:
        self.filter_errors = self.filter_var.get() in {
            tr("details.warnings"), "Avvisi ed errori", "Warnings and errors"
        }
        self.text.configure(state="normal")
        self._render(keep_position=False)
        self.text.configure(state="disabled")

    def go_latest(self) -> None:
        self.has_new_lines = False
        self.latest_button.configure(state="disabled")
        self.text.configure(state="normal")
        self.text.see("end")
        self.text.configure(state="disabled")

    def copy_diagnostics(self) -> None:
        visible = [
            line for line in self.lines
            if not self.filter_errors or "[WARNING]" in line or "[ERROR]" in line
        ]
        self.clipboard_clear()
        self.clipboard_append("\n".join(visible[-1000:]))

    def open_log(self) -> None:
        if self.path and Path(self.path).is_file():
            open_path(self.path)


class HelpButton(ttk.Button):
    """Small keyboard-accessible help popover attached to one control."""

    def __init__(self, master: tk.Misc, title: str, body: str):
        super().__init__(master, text="?", width=3)
        self.title_text = title
        self.body_text = body
        self.popover: tk.Toplevel | None = None
        self.configure(command=self.toggle)
        self.bind("<Return>", self._keyboard_toggle)
        self.bind("<space>", self._keyboard_toggle)
        self.bind("<Escape>", self.close)

    def toggle(self) -> None:
        if self.popover and self.popover.winfo_exists():
            self.close()
            return
        popup = tk.Toplevel(self)
        self.popover = popup
        popup.title(self.title_text)
        popup.transient(self.winfo_toplevel())
        popup.resizable(False, False)
        frame = ttk.Frame(popup, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.title_text, font=("TkDefaultFont", 12, "bold")).pack(
            anchor="w", pady=(0, 6)
        )
        ttk.Label(frame, text=self.body_text, wraplength=340, justify="left").pack(
            anchor="w"
        )
        popup.bind("<Escape>", self.close)
        popup.protocol("WM_DELETE_WINDOW", self.close)
        popup.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 4
        popup.geometry(f"+{x}+{y}")
        popup.focus_set()

    def _keyboard_toggle(self, _event: object | None = None) -> str:
        self.toggle()
        return "break"

    def close(self, _event: object | None = None) -> str:
        if self.popover and self.popover.winfo_exists():
            self.popover.destroy()
        self.popover = None
        if self.winfo_exists():
            self.focus_set()
        return "break"


def _format_bytes(value: int | None) -> str:
    if value is None:
        return ""
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def _download_progress_display(value: dict[str, Any]) -> tuple[str, float | None]:
    """Describe one transfer stream without implying that the whole job is done."""
    stream = value.get("stream")
    stream_label = "Flusso audio" if stream == "audio" else "Flusso video" if stream == "video" else "Flusso corrente"
    downloaded = value.get("downloaded") or 0
    total = value.get("total")
    fragments = value.get("fragment_count")
    fragment_index = value.get("fragment_index")
    percent: float | None = None
    if total and total > 0:
        percent = min(100.0, downloaded * 100 / total)
        qualifier = "di circa" if value.get("total_is_estimate") else "di"
        detail = (f"{stream_label} · {'circa ' if value.get('total_is_estimate') else ''}"
                  f"{percent:.1f}% · {_format_bytes(downloaded)} {qualifier} {_format_bytes(total)}")
    elif fragments and fragment_index is not None and fragments > 0:
        percent = min(100.0, fragment_index * 100 / fragments)
        detail = f"{stream_label} · {percent:.1f}% dei frammenti ({fragment_index}/{fragments})"
        if downloaded:
            detail += f" · {_format_bytes(downloaded)}"
    else:
        detail = (f"{stream_label} · Percentuale non disponibile · scaricati {_format_bytes(downloaded)}"
                  if downloaded else f"{stream_label} · Percentuale non disponibile")
    speed = value.get("speed")
    eta = value.get("eta")
    if speed:
        detail += f" · {_format_bytes(int(speed))}/s"
    if eta is not None:
        detail += f" · circa {int(eta)} s rimanenti"
    return detail, percent


class DownloadDialog(tk.Toplevel):
    # Kept for compatibility with callers that inspect the former public map.
    QUALITY: ClassVar[dict[str, str]] = {
        "Video e audio · max 1080p": "1080p",
        "Video e audio · max 720p": "720p",
        "Video e audio · migliore disponibile": "best",
        "Solo audio": "audio",
    }
    QUALITY_CODES: ClassVar[tuple[str, ...]] = ("1080p", "720p", "best", "audio")

    @staticmethod
    def quality_labels() -> dict[str, str]:
        if get_locale() == "it":
            return {
                "Video e audio · max 1080p": "1080p",
                "Video e audio · max 720p": "720p",
                "Video e audio · migliore disponibile": "best",
                "Solo audio": "audio",
            }
        return {
            "Video and audio · max 1080p": "1080p",
            "Video and audio · max 720p": "720p",
            "Video and audio · best available": "best",
            "Audio only": "audio",
        }

    def __init__(self, master: tk.Tk, app: App):
        super().__init__(master)
        self.app = app
        self.title(tr("dialog.download.title"))
        self.minsize(650, 640)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: DownloadWorker | None = None
        self.metadata: dict[str, Any] | None = None
        self.resume_job: Path | None = None
        self._setting_saved_url = False
        self._allow_resume_url_edit = False
        self.close_after_cancel = False
        self.cleanup_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cleanup_in_progress = False
        self.url_var = tk.StringVar()
        self.quality_var = tk.StringVar(value=next(iter(self.quality_labels())))
        self.audio_language_var = tk.StringVar(value=tr("dialog.download.default_track"))
        self.destination_var = tk.StringVar(
            value=str(DEFAULT_DOWNLOAD_DIR)
        )
        self.filename_var = tk.StringVar(value="")
        self.info_var = tk.StringVar(value=tr("dialog.download.paste"))
        self.progress_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value=tr("dialog.download.ready"))
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self.after(100, self._poll)

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=tr("dialog.download.heading"), font=("Helvetica", 16, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        ttk.Label(frame, text=tr("dialog.download.public_link")).grid(row=1, column=0, sticky="w")
        entry_row = ttk.Frame(frame)
        entry_row.grid(row=2, column=0, sticky="ew", pady=(3, 8))
        entry_row.columnconfigure(0, weight=1)
        self.url_entry = ttk.Entry(entry_row, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_var.trace_add("write", self._url_changed)
        self.analyze_button = ttk.Button(
            entry_row, text=tr("dialog.download.analyze"), command=self.analyze
        )
        self.analyze_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(frame, textvariable=self.info_var, wraplength=590).grid(
            row=3, column=0, sticky="w", pady=(3, 10)
        )
        settings = ttk.LabelFrame(frame, text=tr("dialog.download.video"), padding=10)
        settings.grid(row=4, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text=tr("dialog.download.format")).grid(row=0, column=0, sticky="w")
        self.quality_combo = ttk.Combobox(
            settings, state="readonly", textvariable=self.quality_var,
            values=list(self.quality_labels()),
        )
        self.quality_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.quality_combo.bind("<<ComboboxSelected>>", self._quality_changed)
        ttk.Label(settings, text=tr("dialog.download.audio")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.audio_combo = ttk.Combobox(
            settings, state="readonly", textvariable=self.audio_language_var,
            values=[tr("dialog.download.default_track")],
        )
        self.audio_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(settings, text=tr("dialog.download.filename")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.filename_entry = ttk.Entry(settings, textvariable=self.filename_var)
        self.filename_entry.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(settings, text=tr("dialog.download.extension")).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=(2, 0)
        )
        destination = ttk.LabelFrame(frame, text=tr("dialog.download.save"), padding=10)
        destination.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        destination.columnconfigure(1, weight=1)
        ttk.Label(destination, text=tr("dialog.download.folder")).grid(row=0, column=0, sticky="w")
        ttk.Entry(destination, textvariable=self.destination_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
        self.destination_button = ttk.Button(
            destination, text=tr("main.choose"), command=self.choose_destination
        )
        self.destination_button.grid(row=0, column=2, padx=(8, 0))
        activity = ttk.LabelFrame(frame, text=tr("main.activity"), padding=10)
        activity.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        activity.columnconfigure(0, weight=1)
        ttk.Label(activity, textvariable=self.progress_var, font=("TkDefaultFont", 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 3)
        )
        self.progress = ttk.Progressbar(activity, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew")
        ttk.Label(activity, textvariable=self.status_var, wraplength=590).grid(
            row=2, column=0, sticky="w", pady=(6, 2)
        )
        self.log_panel = EventLogPanel(activity)
        self.log_panel.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        utilities = ttk.Frame(buttons)
        utilities.pack(fill="x")
        actions = ttk.Frame(buttons)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(utilities, text=tr("menu.recent_jobs"), command=self.app.open_recent_jobs).pack(side="left")
        self.cleanup_all_button = ttk.Button(
            utilities, text=tr("menu.storage"),
            command=self.app.open_storage_dialog,
        )
        self.cleanup_all_button.pack(side="left", padx=(6, 0))
        self.new_download_button = ttk.Button(
            utilities, text=tr("dialog.download.another"), command=self.start_new_download
        )
        self.new_download_button.pack(side="left", padx=(6, 0))
        self.cancel_button = ttk.Button(actions, text=tr("main.cancel"), command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=(6, 0))
        self.download_button = ttk.Button(actions, text=tr("dialog.download.download"), command=self.download, state="disabled")
        self.download_button.pack(side="right")

    def cleanup_all_temporary(self) -> None:
        if self.cleanup_in_progress:
            return
        self.cleanup_in_progress = True
        self.cleanup_all_button.configure(state="disabled")
        self.status_var.set("Controllo i temporanei e i lavori attivi…")

        def inspect() -> None:
            self.cleanup_events.put(("preview", inspect_download_staging()))

        threading.Thread(target=inspect, daemon=True).start()

    def _poll_cleanup(self) -> None:
        try:
            kind, value = self.cleanup_events.get_nowait()
        except queue.Empty:
            return
        if kind == "preview":
            eligible = [row for row in value if row["files"] and not row["active"] and not row["error"]]
            count = sum(row["files"] for row in eligible)
            size = sum(row["bytes"] for row in eligible)
            active = sum(row["active"] for row in value)
            confirmed = count > 0 and messagebox.askyesno(
                "Eliminare tutti i temporanei?",
                f"Trovati {len(eligible)} lavori con {count} file temporanei "
                f"(circa {size / (1024 * 1024):.0f} MB). {active} lavori attivi saranno saltati. "
                "I parziali eliminati non saranno più riprendibili; registri e video pubblicati restano. Continuare?",
                parent=self,
            )
            if confirmed:
                self.status_var.set("Elimino i temporanei dei lavori inattivi…")
                threading.Thread(
                    target=lambda: self.cleanup_events.put(("done", cleanup_all_download_staging())),
                    daemon=True,
                ).start()
                return
            self.status_var.set(f"Nessun temporaneo eliminato. Lavori attivi saltati: {active}.")
        else:
            self.status_var.set(
                f"Pulizia: {value['files']} file, {value['bytes'] / (1024 * 1024):.0f} MB liberati; "
                f"{value['skipped_active']} lavori attivi saltati; {len(value['errors'])} errori."
            )
            if value["errors"]:
                messagebox.showwarning(
                    "Pulizia completata con problemi",
                    "Alcuni lavori non sono stati puliti:\n\n" + "\n".join(value["errors"][:12]),
                    parent=self,
                )
        self.cleanup_in_progress = False
        self.cleanup_all_button.configure(state="normal")

    def _quality_changed(self, _event: object | None = None) -> None:
        quality_labels = self.quality_labels()
        is_audio = quality_labels[self.quality_var.get()] == "audio"
        self.audio_combo.configure(state="readonly" if is_audio and self.metadata and self.metadata["audio_languages"] else "disabled")
        if self.metadata:
            selected = quality_labels[self.quality_var.get()]
            actual = effective_quality(self.metadata, selected)
            self.info_var.set(f"{self.metadata['summary']} · Qualità effettiva prevista: {actual}.")

    def _url_changed(self, *_args: object) -> None:
        if self.worker or self._setting_saved_url:
            return
        if self.resume_job and self._allow_resume_url_edit:
            self.download_button.configure(
                state="normal" if self.url_var.get().strip() else "disabled"
            )
            return
        if self.metadata or self.resume_job:
            self._reset_download_selection(clear_url=False)
            self.info_var.set("Link cambiato. Analizza il nuovo video prima di scaricarlo.")
            self.status_var.set("Nuovo link: premi Analizza link per continuare.")

    def _reset_download_selection(self, *, clear_url: bool) -> None:
        self.app.download_state = "inattivo"
        self.resume_job = None
        self.metadata = None
        self._allow_resume_url_edit = False
        self.download_button.configure(
            text=tr("dialog.download.download"), command=self.download, state="disabled"
        )
        self.quality_var.set("Video e audio · max 1080p")
        self.audio_language_var.set("Traccia predefinita del sito")
        self.audio_combo.configure(values=["Traccia predefinita del sito"], state="disabled")
        self.filename_var.set("")
        self.log_panel.clear()
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.progress_var.set("")
        if clear_url:
            self.url_var.set("")
        self.app.activity_var.set("")
        self.app.status_var.set("Pronto per un nuovo link.")
        self.app.master.after_idle(self.app._update_footer_state)

    def start_new_download(self) -> None:
        if self.worker:
            return
        self._reset_download_selection(clear_url=True)
        self.status_var.set("Nuovo download: analizza il link per creare un lavoro separato.")
        self.info_var.set("I dati del download precedente restano conservati.")
        self.url_entry.focus_set()

    def choose_destination(self) -> None:
        selected = filedialog.askdirectory(
            title="Scegli dove salvare il file",
            initialdir=self.destination_var.get(),
            mustexist=True,
        )
        if selected:
            self.destination_var.set(selected)

    def analyze(self) -> None:
        if self.worker:
            return
        try:
            self.worker = DownloadWorker(
                self.url_var.get(), operation="analyze", job_dir=self.resume_job
            )
        except DownloadError as exc:
            messagebox.showerror("Link non valido", str(exc), parent=self)
            return
        self.app.download_state = "analisi"
        self._set_running(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status_var.set("Analizzo i metadati; il file non viene scaricato.")
        self.worker.start()

    def download(self) -> None:
        if self.worker or (not self.metadata and not self.resume_job):
            return
        quality = self.quality_labels()[self.quality_var.get()]
        audio_language = None
        if quality == "audio" and self.audio_language_var.get() != "Traccia predefinita del sito":
            audio_language = self.audio_language_var.get()
        if self.metadata:
            try:
                validate_selected_format(self.metadata, quality, audio_language)
            except DownloadError as exc:
                messagebox.showerror("Formato non disponibile", str(exc), parent=self)
                return
        if self.resume_job and not self._confirm_restart_if_needed():
            return
        try:
            output_name = safe_output_stem(self.filename_var.get())
        except DownloadError as exc:
            messagebox.showerror("Nome non valido", str(exc), parent=self)
            self.filename_entry.focus_set()
            return
        self.filename_var.set(output_name)
        try:
            self.worker = DownloadWorker(
                self.url_var.get(), operation="download", job_dir=self.resume_job,
                destination_dir=Path(self.destination_var.get()),
                quality=quality, audio_language=audio_language,
                output_name=output_name,
            )
        except (DownloadError, OSError) as exc:
            messagebox.showerror("Download non avviato", str(exc), parent=self)
            return
        self._set_running(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.progress_var.set("Preparo il download e aggiorno le informazioni del sito…")
        self.status_var.set("Download in preparazione…")
        self.worker.start()
        # Keep the worker and its event loop alive while the main window shows
        # progress and the interruption action.
        self.withdraw()
        self.app.master.deiconify()
        self.app.master.lift()
        self.app._download_started()

    def _confirm_restart_if_needed(self) -> bool:
        manifest_path = self.resume_job / "download.json"
        try:
            import json
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        if manifest.get("status") == "analyzed":
            return True
        staging = Path(str(manifest.get("staging_dir") or self.resume_job / "staging"))
        if staging.is_dir():
            if any(path.is_file() and path.name.endswith(".part") for path in staging.rglob("*")):
                return True
            source_id = str(manifest.get("source_id") or "")
            media_suffixes = {".mkv", ".mp4", ".webm", ".m4a", ".mp3", ".opus"}
            if any(
                path.is_file() and source_id and source_id in path.name
                and path.suffix.casefold() in media_suffixes
                for path in staging.rglob("*")
            ):
                return True
        return messagebox.askyesno(
            "Nuovo download necessario",
            "Non trovo file parziali riprendibili. Per continuare sarà necessario "
            "scaricare il contenuto da zero. I dati del lavoro precedente resteranno "
            "conservati. Vuoi avviare il nuovo download?",
            parent=self if self.winfo_viewable() else self.app.master,
        )

    def resume_download(self) -> None:
        selected = filedialog.askopenfilename(
            title="Scegli un download interrotto", initialdir=DOWNLOAD_JOBS_DIR,
            filetypes=[("Lavoro di download", "download.json")],
        )
        if not selected:
            return
        self.load_download(Path(selected))

    def load_download(self, selected: Path) -> None:
        if self.worker:
            self.lift()
            self.status_var.set("Un download è già in corso. Attendi o interrompilo prima di riprendere un altro lavoro.")
            return
        self.resume_job = Path(selected).parent
        try:
            import json
            manifest = json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Lavoro non leggibile", str(exc), parent=self)
            self.resume_job = None
            return
        if manifest.get("status") == "completed":
            messagebox.showinfo("Download completato", "Questo download è già completato.", parent=self)
            self.resume_job = None
            return
        self.metadata = None
        self._allow_resume_url_edit = False
        self.download_button.configure(text=tr("main.resume"), command=self.resume_current)
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.progress_var.set("")
        saved_url = resumable_page_url(manifest)
        self._setting_saved_url = True
        try:
            self.url_var.set(saved_url)
        finally:
            self._setting_saved_url = False
        self._allow_resume_url_edit = not bool(saved_url)
        quality_labels = DownloadDialog.quality_labels()
        self.quality_var.set(next(
            (label for label, quality in quality_labels.items() if quality == manifest.get("quality")),
            next(iter(quality_labels)),
        ))
        saved_audio_language = manifest.get("audio_language")
        self.audio_language_var.set(
            str(saved_audio_language) if saved_audio_language
            else tr("dialog.download.default_track")
        )
        self.destination_var.set(str(manifest.get("destination_dir", self.destination_var.get())))
        self.filename_var.set(str(manifest.get("output_name") or manifest.get("title") or ""))
        self.log_panel.set_log(str(self.resume_job / "events.log"))
        if self.url_var.get():
            self.info_var.set(
                f"Ripresa di {manifest.get('title', 'contenuto salvato')}. "
                "Il link è stato ricostruito e verrà verificato prima di riusare i parziali."
            )
            self.status_var.set("Premi Riprendi: controllerò il link e continuerò dai parziali disponibili.")
            self._set_running(False)
        else:
            self.info_var.set(
                f"Ripresa di {manifest.get('title', 'contenuto salvato')}. "
                "Inserisci il link originale: sito e ID saranno verificati prima della ripresa."
            )
            self.url_entry.focus_set()
            self.status_var.set("In attesa del link del lavoro da riprendere.")
            self._set_running(False)

    def resume_current(self) -> None:
        """Continue a saved download without a separate manual analysis step."""
        if self.worker or not self.resume_job:
            return
        if not self.url_var.get().strip():
            self.status_var.set("Inserisci il link originale di questo contenuto, poi premi Riprendi.")
            self.url_entry.focus_set()
            return
        self.download()

    def cancel(self) -> None:
        if self.worker:
            self.status_var.set("Interruzione richiesta. Salvo lo stato del download…")
            self.worker.cancel()
            self.cancel_button.configure(
                text="Stop requested…" if get_locale() == "en" else "Interruzione richiesta…"
            )
            self.cancel_button.configure(state="disabled")

    def _request_close(self) -> None:
        if not self.worker:
            self.destroy()
            return
        if messagebox.askyesno(
            "Download in corso",
            "Vuoi interrompere il download e chiudere quando lo stato sarà salvato?",
            parent=self,
        ):
            self.close_after_cancel = True
            self.cancel()

    def _set_running(self, running: bool) -> None:
        self.analyze_button.configure(state="disabled" if running else "normal")
        self.download_button.configure(
            state="disabled" if running else "normal"
            if self.metadata or (self.resume_job and self.url_var.get().strip()) else "disabled"
        )
        self.destination_button.configure(state="disabled" if running else "normal")
        self.quality_combo.configure(state="disabled" if running else "readonly")
        self.audio_combo.configure(state="disabled" if running else "readonly")
        self.filename_entry.configure(state="disabled" if running else "normal")
        self.url_entry.configure(state="disabled" if running else "normal")
        self.cleanup_all_button.configure(
            state="disabled" if running or self.cleanup_in_progress else "normal"
        )
        self.new_download_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(
            text=tr("main.cancel"),
            state="normal" if running else "disabled",
        )
        self.app._set_workflow_controls(not running)
        self.app._set_busy(running)
        if running:
            self.app._clear_activity_clock()
            self.app.status_var.set("Download: " + self.status_var.get())
        elif self.app.worker is None and self.app.translation_worker is None:
            self.app.status_var.set(self.status_var.get())

    def _poll(self) -> None:
        poll_cleanup = getattr(self, "_poll_cleanup", None)
        if poll_cleanup:
            poll_cleanup()
        active_worker = self.worker
        if active_worker:
            try:
                for _ in range(100):
                    kind, value = active_worker.events.get_nowait()
                    if kind == "status":
                        self.status_var.set(str(value))
                        self.app.status_var.set("Download: " + str(value))
                        self.app.activity_var.set(str(value))
                    elif kind == "log_path":
                        self.log_panel.set_log(str(value))
                        if active_worker.operation == "download":
                            self.app.log_panel.set_log(str(value))
                    elif kind == "log":
                        self.log_panel.add_line(str(value["line"]))
                        if active_worker.operation == "download":
                            self.app.log_panel.add_line(str(value["line"]))
                    elif kind == "analysis":
                        self.app.download_state = "inattivo"
                        self.metadata = value
                        self.resume_job = Path(value["job_dir"])
                        if not self.filename_var.get().strip():
                            self.filename_var.set(value.get("title", "Video senza titolo"))
                        self.log_panel.set_log(str(self.resume_job / "events.log"))
                        duration = int(value["duration"])
                        mm, ss = divmod(duration, 60)
                        hh, mm = divmod(mm, 60)
                        value["summary"] = (
                            f"{value['title']} · {value['site']} · "
                            f"{hh:02}:{mm:02}:{ss:02} · dimensione finale non disponibile"
                        )
                        languages = ["Traccia predefinita del sito", *value["audio_languages"]]
                        saved_language = self.audio_language_var.get()
                        self.audio_combo.configure(values=languages)
                        self.audio_language_var.set(
                            saved_language if saved_language in languages else languages[0]
                        )
                        self._quality_changed()
                        self.download_button.configure(
                            text=tr("dialog.download.download"), command=self.download
                        )
                        self.status_var.set(
                            "Analisi completata. Controlla la qualità prevista e premi Scarica."
                        )
                        self._set_running(False)
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=100, value=0)
                        self.worker = None
                    elif kind == "progress":
                        stage = value.get("stage")
                        if stage == "verifica":
                            self.progress.configure(mode="indeterminate")
                            self.progress.start(10)
                            self.progress_var.set("Verifico il file scaricato…")
                            self.app._show_download_phase("verifica", "Verifico il file scaricato…")
                            continue
                        if stage == "postprocess":
                            self.progress.configure(mode="indeterminate")
                            self.progress.start(10)
                            self.progress_var.set("Unione e preparazione del file…")
                            self.app._show_download_phase("unione", "Unione e preparazione del file…")
                            continue
                        self.progress.stop()
                        self.progress.configure(mode="determinate")
                        details, percent = _download_progress_display(value)
                        if percent is None:
                            self.progress.configure(mode="indeterminate")
                            self.progress.start(10)
                        else:
                            self.progress.configure(maximum=100, value=percent)
                        self.progress_var.set(details)
                        self.status_var.set(
                            "Download in corso. Video e audio possono essere trasferiti separatamente; "
                            "la dimensione finale può essere maggiore."
                        )
                        self._mirror_download_progress(value, details)
                    elif kind == "complete":
                        self._finish_download_success(value, active_worker)
                        return
                    elif kind == "cancelled":
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=100, value=0)
                        self.resume_job = active_worker.job_dir or self.resume_job
                        self.status_var.set(
                            "Download interrotto. I file parziali sono conservati. "
                            "Puoi riprendere il trasferimento."
                        )
                        self.app._download_stopped("interrotto", self.status_var.get())
                        self.download_button.configure(
                            text=tr("main.resume"), command=self.resume_current
                        )
                        self._set_running(False)
                        self.worker = None
                        if getattr(self, "close_after_cancel", False):
                            self.destroy()
                            return
                    elif kind == "error":
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=100, value=0)
                        self.resume_job = active_worker.job_dir or self.resume_job
                        self.status_var.set(
                            "Download non riuscito. I file parziali sono conservati. "
                            "Puoi riprendere il trasferimento; apri i dettagli per la causa."
                        )
                        self.app._download_stopped("errore", self.status_var.get())
                        self.download_button.configure(
                            text=tr("main.resume"), command=self.resume_current
                        )
                        self._set_running(False)
                        self.worker = None
                        if getattr(self, "close_after_cancel", False):
                            self.destroy()
                            return
            except queue.Empty:
                pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _mirror_download_progress(self, value: dict[str, Any], details: str) -> None:
        try:
            _description, percent = _download_progress_display(value)
            self.app._show_download_progress(details, percent)
        except (AttributeError, tk.TclError):
            return

    def _finish_download_success(
        self, value: dict[str, Any], worker: DownloadWorker | None,
    ) -> bool:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=100)
        published = Path(str(value["path"])).expanduser().resolve()
        self.progress_var.set(published.name)
        try:
            if not published.is_file():
                raise FileNotFoundError(
                    "Il file pubblicato non si trova più nella destinazione scelta."
                )
            # Defend the GUI boundary too: never pass a staging path to transcription.
            media = replace(value["media"], path=str(published))
            self.app.video_var.set(str(published))
            self.app._receive_media(media)
            self.app.log_panel.set_log(str(Path(value["job_dir"]) / "events.log"))
            if worker and worker.event_log:
                line = worker.event_log.write(
                    "Il video verificato è stato caricato nella schermata principale."
                )
                self.app.log_panel.add_line(line)
            self.status_var.set("Video pronto: ritorno alla schermata principale.")
            self.app.status_var.set("Video pronto. Controlla l’intervallo e avvia la trascrizione.")
            self.app._download_stopped("pronto", "Video scaricato e pronto.")
            self._set_running(False)
            self.worker = None
            self.resume_job = None
            self.app.master.deiconify()
            self.app.master.lift()
            self.app.master.focus_force()
            self.destroy()
            return True
        except Exception as exc:  # noqa: BLE001 - lascia aperta la finestra per il recupero
            self.deiconify()
            self.app._download_stopped("errore", "Video scaricato, ma caricamento non riuscito.")
            self.status_var.set(
                f"Download completato, ma non riesco a caricare il video: {exc}"
            )
            self.app.status_var.set(
                "Il download è completo, ma il caricamento nella schermata principale "
                "non è riuscito. Il file è conservato nella destinazione indicata."
            )
            self._set_running(False)
            self.worker = None
            self.resume_job = None
            return False


class RecentJobsDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, app: App, *, storage_only: bool = False):
        super().__init__(master)
        self.app = app
        self.storage_only = storage_only
        self.title(tr("dialog.storage") if storage_only else tr("dialog.recent"))
        self.minsize(700, 430)
        self.events: queue.Queue[Any] = queue.Queue()
        self.cleanup_in_progress = False
        self.rows: dict[str, dict[str, Any]] = {}
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(
            frame,
            text=tr("dialog.storage") if storage_only else tr("dialog.recent"),
            font=("TkDefaultFont", 16, "bold"),
        ).grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        columns = ("kind", "name", "status", "progress", "cost", "modified")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        for column, title, width in (
            ("kind", tr("dialog.operation"), 115),
            ("name", tr("dialog.source"), 230),
            ("status", tr("dialog.status"), 90),
            ("progress", tr("dialog.progress"), 100),
            ("cost", tr("dialog.cost"), 80),
            ("modified", tr("dialog.modified"), 100),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, stretch=column == "name")
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")
        self.summary = tk.StringVar(value=tr("dialog.loading_jobs"))
        ttk.Label(frame, textvariable=self.summary, wraplength=650).grid(
            row=2, column=0, sticky="w", pady=(8, 12)
        )
        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, sticky="e")
        ttk.Button(actions, text=tr("dialog.refresh"), command=self.refresh).pack(side="left", padx=6)
        self.cleanup_button = ttk.Button(
            actions, text=tr("dialog.cleanup_selected"), command=self.cleanup_temporary,
            state="disabled",
        )
        self.cleanup_button.pack(side="left", padx=6)
        self.cleanup_all_button = ttk.Button(
            actions, text=tr("dialog.cleanup_all"), command=self.cleanup_all_temporary
        )
        self.cleanup_all_button.pack(side="left", padx=6)
        self.open_record_button = ttk.Button(
            actions, text=tr("dialog.open_record"), command=self.open_record,
            state="disabled",
        )
        if not storage_only:
            self.open_record_button.pack(side="left", padx=6)
        self.resume_button = ttk.Button(
            actions, text=tr("main.resume"), command=self.resume, state="disabled"
        )
        if not storage_only:
            self.resume_button.pack(side="left", padx=6)
        ttk.Button(actions, text=tr("dialog.close"), command=self.destroy).pack(side="left", padx=6)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", lambda _event: self.resume())
        self.after(100, self._poll)
        self.refresh()

    def refresh(self) -> None:
        self.summary.set("Aggiorno l’elenco…")
        def read_jobs() -> None:
            records = list_recent_jobs(limit=100_000 if self.storage_only else 50)
            if self.storage_only:
                records = [row for row in records if row.get("kind") == "Download"]
            self.events.put(records)

        threading.Thread(
            target=read_jobs, daemon=True
        ).start()

    def _poll(self) -> None:
        try:
            records = self.events.get_nowait()
        except queue.Empty:
            records = None
        if isinstance(records, tuple) and records and records[0] in {
            "cleanup_done", "cleanup_error", "cleanup_preview", "cleanup_all_done"
        }:
            kind, value = records
            if kind == "cleanup_preview":
                eligible = [row for row in value if row["files"] and not row["active"] and not row["error"]]
                count = sum(row["files"] for row in eligible)
                size = sum(row["bytes"] for row in eligible)
                active = sum(row["active"] for row in value)
                if count and messagebox.askyesno(
                    "Eliminare tutti i temporanei?",
                    f"Trovati {len(eligible)} lavori con {count} file temporanei "
                    f"(circa {size / (1024 * 1024):.0f} MB). {active} lavori attivi saranno saltati. "
                    "I parziali eliminati non saranno più riprendibili; registri e video pubblicati restano. Continuare?",
                    parent=self,
                ):
                    self.summary.set("Elimino i temporanei dei lavori inattivi…")
                    threading.Thread(
                        target=lambda: self.events.put(("cleanup_all_done", cleanup_all_download_staging())),
                        daemon=True,
                    ).start()
                else:
                    self.cleanup_in_progress = False
                    self.cleanup_all_button.configure(state="normal")
                if not count:
                    self.summary.set(f"Nessun temporaneo eliminabile. Lavori attivi saltati: {active}.")
                    self.cleanup_in_progress = False
                    self.cleanup_all_button.configure(state="normal")
                records = None
            elif kind == "cleanup_all_done":
                self.cleanup_in_progress = False
                report = value
                self.summary.set(
                    f"Pulizia: {report['files']} file, {report['bytes'] / (1024 * 1024):.0f} MB liberati; "
                    f"{report['skipped_active']} lavori attivi saltati; {len(report['errors'])} errori."
                )
                if report["errors"]:
                    messagebox.showwarning(
                        "Pulizia completata con problemi",
                        "Alcuni lavori non sono stati puliti:\n\n" + "\n".join(report["errors"][:12]),
                        parent=self,
                    )
                self.cleanup_all_button.configure(state="normal")
                self.refresh()
                records = None
            if records is None:
                pass
            elif kind == "cleanup_error":
                self.cleanup_in_progress = False
                self.summary.set(f"Pulizia non riuscita: {value}")
            elif kind == "cleanup_done":
                self.cleanup_in_progress = False
                count, size = value
                self.summary.set(
                    f"Eliminati {count} file temporanei ({size / (1024 * 1024):.0f} MB)."
                )
                self.refresh()
            self.cleanup_all_button.configure(state="normal" if not self.cleanup_in_progress else "disabled")
        elif records is not None:
            self.rows.clear()
            self.tree.delete(*self.tree.get_children())
            for index, record in enumerate(records):
                item = str(index)
                self.rows[item] = record
                self.tree.insert("", "end", iid=item, values=(
                    record["kind"], record["name"], record["status"],
                    record["progress"], record["cost"], record["modified_label"],
                ))
            total_bytes = sum(record.get("temporary_bytes", 0) for record in records)
            if self.storage_only:
                self.summary.set(
                    f"Temporanei nei lavori visualizzati: circa {total_bytes / (1024 * 1024):.0f} MB. "
                    "Seleziona un download per pulirlo, oppure elimina i temporanei di tutti i lavori inattivi."
                )
            else:
                self.summary.set(
                    f"{len(records)} lavori salvati. Selezionane uno per i dettagli e la ripresa."
                )
            self._selection_changed()
        if self.winfo_exists():
            self.after(100, self._poll)

    def cleanup_all_temporary(self) -> None:
        if self.cleanup_in_progress:
            return
        self.cleanup_in_progress = True
        self.cleanup_all_button.configure(state="disabled")
        self.summary.set("Controllo i temporanei e i lavori attivi…")
        threading.Thread(
            target=lambda: self.events.put(("cleanup_preview", inspect_download_staging())),
            daemon=True,
        ).start()

    def _selected(self) -> dict[str, Any] | None:
        selected = self.tree.selection()
        return self.rows.get(selected[0]) if selected else None

    def _selection_changed(self, _event: object | None = None) -> None:
        record = self._selected()
        can_resume = bool(
            record and record.get("status") not in {
                "Completato", "SRT e scheda pronti", "Completato con avvisi",
                "Completato con parti non tradotte", "In download",
                "In trascrizione", "In revisione", "Traduzione in corso",
            }
            and record.get("name") != "Registro non leggibile"
        )
        self.resume_button.configure(state="normal" if can_resume else "disabled")
        if can_resume and record:
            operation = {
                "Download": "download", "Trascrizione": "trascrizione",
                "Traduzione": "traduzione", "Revisione SRT": "revisione",
            }.get(record["kind"], "lavoro")
            if record["kind"] == "Trascrizione" and "Traduzione" in record["status"]:
                operation = "traduzione"
            self.resume_button.configure(text=f"Riprendi {operation}")
        if hasattr(self, "open_record_button"):
            self.open_record_button.configure(
                state="normal" if record else "disabled"
            )
        can_clean = bool(
            record and record.get("kind") == "Download"
            and record.get("temporary_files", 0)
            and not getattr(self, "cleanup_in_progress", False)
        )
        self.cleanup_button.configure(state="normal" if can_clean else "disabled")
        if record:
            self.summary.set(
                f"{record['kind']} · {record['status']} · {record['progress']} · "
                f"costo registrato {record['cost']}. {record.get('details', '')}"
            )

    def open_record(self) -> None:
        record = self._selected()
        if record:
            open_path(record["path"])

    def cleanup_temporary(self) -> None:
        record = self._selected()
        if not record or record.get("kind") != "Download" or not record.get("temporary_files"):
            return
        selected_path = Path(record["path"])
        dialog = getattr(self.app, "download_dialog", None)
        active_worker = getattr(dialog, "worker", None)
        active_job = getattr(active_worker, "job_dir", None)
        if active_worker and active_job and Path(active_job).resolve() == selected_path.parent.resolve():
            messagebox.showwarning(
                "Download in corso",
                "Interrompi il download prima di eliminare i suoi file temporanei.",
                parent=self,
            )
            return
        size_mb = record.get("temporary_bytes", 0) / (1024 * 1024)
        answer = messagebox.askyesno(
            "Eliminare i file temporanei?",
            f"Verranno eliminati {record['temporary_files']} file temporanei "
            f"(circa {size_mb:.0f} MB). Il registro e gli eventuali file finali resteranno. "
            "Non sarà più possibile riprendere dai dati parziali; potrai comunque avviare "
            "un nuovo download da zero.",
            parent=self,
        )
        if not answer:
            return
        self.cleanup_in_progress = True
        self.cleanup_button.configure(state="disabled")
        self.summary.set("Elimino i file temporanei…")

        def cleanup() -> None:
            try:
                result = ("cleanup_done", cleanup_download_staging(selected_path))
            except (DownloadError, OSError) as exc:
                result = ("cleanup_error", str(exc))
            self.events.put(result)

        threading.Thread(target=cleanup, daemon=True).start()

    def resume(self) -> None:
        record = self._selected()
        if record and self.resume_button.instate(["!disabled"]):
            self.app._resume_selected_job(Path(record["path"]))
            self.destroy()


class TimeRangeScale(tk.Canvas):
    """Barra temporale con due cursori, controllabile anche da tastiera."""

    def __init__(self, master: tk.Misc, command: Any):
        super().__init__(
            master,
            height=44,
            background="systemWindowBackgroundColor",
            highlightthickness=0,
            takefocus=True,
        )
        self.command = command
        self.duration = 1.0
        self.start_value = 0.0
        self.end_value = 1.0
        self.active = "start"
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<FocusIn>", lambda _event: self._draw())
        self.bind("<FocusOut>", lambda _event: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Left>", lambda _event: self._nudge(-1))
        self.bind("<Right>", lambda _event: self._nudge(1))
        self.bind("<Home>", lambda _event: self._move_active(0))
        self.bind("<End>", lambda _event: self._move_active(self.duration))

    def set_range(
        self,
        duration: float,
        start: float = 0.0,
        end: float | None = None,
        notify: bool = False,
    ) -> None:
        self.duration = max(0.001, duration)
        self.start_value = max(0.0, min(start, self.duration))
        self.end_value = max(
            self.start_value, min(self.duration if end is None else end, self.duration)
        )
        self._draw()
        if notify:
            self.command(self.start_value, self.end_value)

    def _track_bounds(self) -> tuple[float, float]:
        return 14.0, max(15.0, float(self.winfo_width()) - 14.0)

    def _x(self, value: float) -> float:
        left, right = self._track_bounds()
        return left + (right - left) * value / self.duration

    def _value(self, x: float) -> float:
        left, right = self._track_bounds()
        ratio = (min(right, max(left, x)) - left) / (right - left)
        return float(round(ratio * self.duration))

    def _draw(self) -> None:
        self.delete("all")
        left, right = self._track_bounds()
        y = 22
        start_x, end_x = self._x(self.start_value), self._x(self.end_value)
        self.create_line(left, y, right, y, fill="#b9b9b9", width=6)
        self.create_line(start_x, y, end_x, y, fill="#0a84ff", width=8)
        for name, x in (("start", start_x), ("end", end_x)):
            outline = (
                "#111111" if name == self.active and self.focus_get() else "#ffffff"
            )
            self.create_oval(
                x - 8,
                y - 8,
                x + 8,
                y + 8,
                fill="#0a84ff",
                outline=outline,
                width=2,
            )

    def _press(self, event: tk.Event) -> None:
        if self.cget("state") == "disabled":
            return
        self.focus_set()
        value = self._value(float(event.x))
        self.active = (
            "start"
            if abs(value - self.start_value) <= abs(value - self.end_value)
            else "end"
        )
        self._move_active(value)

    def _drag(self, event: tk.Event) -> None:
        if self.cget("state") == "disabled":
            return
        self._move_active(self._value(float(event.x)))

    def _nudge(self, amount: int) -> str:
        if self.cget("state") == "disabled":
            return "break"
        current = self.start_value if self.active == "start" else self.end_value
        self._move_active(current + amount)
        return "break"

    def _move_active(self, value: float) -> str:
        if self.cget("state") == "disabled":
            return "break"
        minimum_gap = min(1.0, self.duration)
        if self.active == "start":
            self.start_value = max(0.0, min(value, self.end_value - minimum_gap))
        else:
            self.end_value = min(
                self.duration, max(value, self.start_value + minimum_gap)
            )
        self._draw()
        self.command(self.start_value, self.end_value)
        return "break"


class RevisionDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, source: str,
                 operation: str = OPERATION_REVISION,
                 source_language: str | None = "en", target_language: str = "en"):
        super().__init__(master)
        self.operation = operation
        self.title(tr("dialog.translation") if operation == OPERATION_TRANSLATION else tr("dialog.revision"))
        self.minsize(700, 570)
        self.source = source
        self.worker: RevisionWorker | None = None
        self.current_job_dir: Path | None = None
        self.preview_events: queue.Queue[tuple[int, list[Any], Any, str | None]] = queue.Queue()
        self.preview_revision = 0
        self.preview_after_id: str | None = None
        self.caption_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=REVISION_MODE_CONSERVATIVE)
        if operation == OPERATION_TRANSLATION:
            self.mode_var.set(REVISION_MODE_LINGUISTIC)
        self.source_language_var = tk.StringVar(value=source_language or "")
        self.target_language_var = tk.StringVar(value=target_language)
        self.model_var = tk.StringVar(value=default_model(self.mode_var.get(), operation))
        self.provider_var = tk.StringVar(value=PROVIDER_OPENAI)
        self.context_var = tk.StringVar()
        self.mode_help_var = tk.StringVar()
        self.estimate_var = tk.StringVar()
        self.cost_var = tk.StringVar(value=tr("dialog.actual_cost"))
        self.results_var = tk.StringVar(
            value="Esiti: nessun sottotitolo ancora elaborato."
        )
        self.status_var = tk.StringVar(
            value=("Pronto per la traduzione."
                   if operation == OPERATION_TRANSLATION
                   else "Pronto per la revisione.")
        )
        self.last_result: dict[str, Any] | None = None
        self.captions: list[Any] = []
        self.started_at: float | None = None
        self._build()
        self._schedule_preview(delay=0)
        self.after(100, self._poll)

    def _build(self) -> None:
        container = ttk.Frame(self, padding=20)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        ttk.Label(
            container,
            text=(tr("dialog.translation") if self.operation == OPERATION_TRANSLATION
                  else tr("dialog.revision")),
            font=("Helvetica", 16, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))
        ttk.Label(
            container,
            text=str(Path(self.source)),
            wraplength=600,
            foreground="#555555",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))
        ttk.Label(container, textvariable=self.caption_var).grid(
            row=2, column=0, sticky="w"
        )
        settings = ttk.Frame(container)
        settings.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        if self.operation == OPERATION_TRANSLATION:
            ttk.Label(settings, text=tr("dialog.from")).pack(side="left")
            self.source_language = ttk.Combobox(
                settings, width=12, state="readonly",
                values=[language_label(code) for code in LANGUAGES],
            )
            self.source_language.set(
                language_label(self.source_language_var.get())
                if self.source_language_var.get() in LANGUAGES else ""
            )
            self.source_language.pack(side="left", padx=(5, 12))
            ttk.Label(settings, text=tr("dialog.to")).pack(side="left")
            self.target_language = ttk.Combobox(
                settings, width=12, state="readonly",
                values=[language_label(code) for code in LANGUAGES],
            )
            self.target_language.set(language_label(self.target_language_var.get()))
            self.target_language.pack(side="left", padx=(5, 12))
            self.source_language.bind("<<ComboboxSelected>>", self._settings_changed)
            self.target_language.bind("<<ComboboxSelected>>", self._settings_changed)
        ttk.Label(settings, text=tr("dialog.model")).pack(side="left")
        self.provider_combo = ttk.Combobox(
            settings, width=12, state="readonly", textvariable=self.provider_var,
            values=list(AI_PROVIDERS),
        )
        self.provider_combo.pack(side="left", padx=(4, 6))
        self.provider_combo.bind("<<ComboboxSelected>>", self._provider_changed)
        self.model_combo = ttk.Combobox(
            settings, width=25, state="readonly", textvariable=self.model_var,
            values=list(PROVIDER_MODELS[PROVIDER_OPENAI]),
        )
        self.model_combo.pack(side="left", padx=5)
        self.model_combo.bind("<<ComboboxSelected>>", self._settings_changed)
        mode_frame = ttk.LabelFrame(container, text=tr("dialog.revision_type"), padding=8)
        mode_frame.grid(row=4, column=0, sticky="ew", pady=(10, 4))
        self.conservative_button = ttk.Radiobutton(
            mode_frame,
            text=tr("dialog.conservative"),
            variable=self.mode_var,
            value=REVISION_MODE_CONSERVATIVE,
            command=self._mode_changed,
        )
        self.conservative_button.pack(anchor="w")
        self.linguistic_button = ttk.Radiobutton(
            mode_frame,
            text=tr("dialog.linguistic"),
            variable=self.mode_var,
            value=REVISION_MODE_LINGUISTIC,
            command=self._mode_changed,
        )
        self.linguistic_button.pack(anchor="w", pady=(4, 0))
        if self.operation == OPERATION_TRANSLATION:
            mode_frame.grid_remove()
        context_frame = ttk.Frame(container) if self.operation == OPERATION_TRANSLATION else mode_frame
        if self.operation == OPERATION_TRANSLATION:
            context_frame.grid(row=4, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(context_frame, text=tr("main.context")).pack(
            anchor="w", pady=(8, 2)
        )
        self.context_entry = ttk.Entry(context_frame, textvariable=self.context_var)
        self.context_entry.pack(fill="x")
        self.context_var.trace_add("write", lambda *_: self._settings_changed())
        ttk.Label(
            container,
            textvariable=self.mode_help_var,
            wraplength=650,
            foreground="#8a4b00",
        ).grid(row=5, column=0, sticky="w", pady=(2, 4))
        ttk.Label(container, textvariable=self.estimate_var).grid(
            row=6, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(
            container,
            text=(
                "Stima, non limite massimo di spesa. Nessuna richiesta parte "
                "prima del comando esplicito di avvio. In traduzione, un secondo "
                "tentativo può aumentare il costo."
            ),
            foreground="#555555",
            wraplength=600,
        ).grid(row=7, column=0, sticky="w", pady=(4, 12))
        progress_row = ttk.Frame(container)
        progress_row.grid(row=8, column=0, sticky="ew")
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_row, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.busy_progress = ttk.Progressbar(progress_row, mode="indeterminate", length=74)
        self.busy_progress.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self._busy = False
        ttk.Label(container, textvariable=self.cost_var).grid(
            row=9, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(container, textvariable=self.results_var).grid(
            row=10, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(container, textvariable=self.status_var, wraplength=600).grid(
            row=11, column=0, sticky="w", pady=(6, 16)
        )
        self.elapsed_var = tk.StringVar(value="")
        ttk.Label(container, textvariable=self.elapsed_var, foreground="#555555").grid(
            row=12, column=0, sticky="w", pady=(0, 6)
        )
        self.log_panel = EventLogPanel(container)
        self.log_panel.grid(row=13, column=0, sticky="ew", pady=(0, 8))
        buttons = ttk.Frame(container)
        buttons.grid(row=14, column=0, sticky="e")
        self.cancel_button = ttk.Button(
            buttons, text=tr("main.cancel"), command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        self.start_button = ttk.Button(
            buttons,
            text=(tr("dialog.start_translation") if self.operation == OPERATION_TRANSLATION
                  else tr("dialog.start_revision")),
            command=self.start_revision,
        )
        self.start_button.pack(side="right", padx=(0, 8))
        self.resume_button = ttk.Button(
            buttons, text=tr("main.resume"), command=self.resume_revision
        )
        self.resume_button.pack(side="right", padx=(0, 8))
        self.details_button = ttk.Button(
            buttons,
            text=tr("dialog.details"),
            command=self.show_details,
            state="disabled",
        )
        self.details_button.pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text=tr("dialog.close"), command=self.destroy).pack(
            side="right", padx=(0, 8)
        )

    def _load_preview(self) -> None:
        self._schedule_preview(delay=0)

    def _schedule_preview(self, _event: object | None = None, delay: int = 300) -> None:
        if self.worker:
            return
        self.preview_revision += 1
        revision = self.preview_revision
        if self.preview_after_id:
            self.after_cancel(self.preview_after_id)
        self.start_button.configure(state="disabled")
        self.estimate_var.set("Aggiorno la stima…")
        self.status_var.set("Leggo il file e calcolo la stima in background…")
        self._set_busy(True)
        snapshot = (
            revision, self.source, self.mode_var.get(), self.operation,
            self.source_language_var.get(), self.target_language_var.get(),
            self.model_var.get(), self.context_var.get(),
        )
        self.preview_after_id = self.after(
            delay, lambda: self._launch_preview(snapshot)
        )

    def _launch_preview(self, snapshot: tuple[Any, ...]) -> None:
        self.preview_after_id = None
        threading.Thread(
            target=self._compute_preview, args=snapshot, daemon=True
        ).start()

    def _compute_preview(
        self, revision: int, source: str, mode: str, operation: str,
        source_language: str, target_language: str, model: str, context: str,
    ) -> None:
        try:
            captions = load_captions(source)
            if operation == OPERATION_TRANSLATION and not source_language:
                estimate, error = None, None
            else:
                estimate = estimate_revision(
                    captions, mode=mode, operation=operation, model=model,
                    source_language=source_language, target_language=target_language,
                    user_context=context,
                )
                error = None
        except (OSError, ValueError, RevisionError) as exc:
            captions, estimate, error = [], None, str(exc)
        self.preview_events.put((revision, captions, estimate, error))

    def _show_preview_result(self) -> None:
        try:
            revision, captions, estimate, error = self.preview_events.get_nowait()
        except queue.Empty:
            return
        if revision != self.preview_revision:
            return
        self._set_busy(False)
        self.captions = captions
        if error:
            self.estimate_var.set("Stima non disponibile.")
            self.status_var.set(f"SRT non utilizzabile: {error}")
            self.start_button.configure(state="disabled")
            return
        self.caption_var.set(tr("dialog.captions", count=len(captions)))
        self._update_mode_help()
        if estimate is None:
            self.estimate_var.set("Scegli la lingua originale per vedere la stima.")
            self.start_button.configure(state="disabled")
        else:
            self._show_estimate(estimate)
            self.progress.configure(maximum=max(1, estimate.group_count), value=0)
            self.start_button.configure(state="normal")
            self.status_var.set("Pronto. Controlla la stima prima di avviare.")

    def _show_estimate(self, estimate: Any) -> None:
        qualifier = " (approssimativa)" if estimate.approximate else ""
        self.estimate_var.set(
            f"Costo stimato per {estimate.group_count} gruppi: "
            f"${estimate.cost_usd:.4f} USD{qualifier}"
        )

    def _mode_changed(self) -> None:
        self.model_var.set(default_model(self.mode_var.get(), self.operation))
        self._update_mode_help()
        self._schedule_preview()

    def _provider_changed(self, _event: object | None = None) -> None:
        provider = self.provider_var.get() if hasattr(self, "provider_var") else self.translation_provider_var.get()
        models = list(PROVIDER_MODELS.get(provider, PROVIDER_MODELS[PROVIDER_OPENAI]))
        combo = self.model_combo if hasattr(self, "model_combo") else self.translation_model_combo
        combo.configure(values=models)
        current = self.model_var.get() if hasattr(self, "model_var") else self.translation_model_var.get()
        if current not in models:
            current = models[0]
            (self.model_var if hasattr(self, "model_var") else self.translation_model_var).set(current)
        if hasattr(self, "_schedule_preview"):
            self._schedule_preview()
        else:
            self._update_translation_estimate()

    def _settings_changed(self, _event: object | None = None) -> None:
        if self.operation == OPERATION_TRANSLATION:
            source_label = self.source_language.get()
            source_code = language_code(source_label, include_source=False)
            target_code = language_code(self.target_language.get(), include_source=False)
            if source_code not in LANGUAGES or target_code not in LANGUAGES:
                self.estimate_var.set("Scegli la lingua originale per vedere la stima.")
                self.start_button.configure(state="disabled")
                return
            self.source_language_var.set(source_code)
            self.target_language_var.set(target_code)
        self._schedule_preview()

    def _estimate(self) -> Any:
        return estimate_revision(
            self.captions, mode=self.mode_var.get(), operation=self.operation,
            model=self.model_var.get(), source_language=self.source_language_var.get(),
            target_language=self.target_language_var.get(),
            user_context=self.context_var.get(),
        )

    def _update_mode_help(self) -> None:
        if (self.operation == OPERATION_TRANSLATION
                or self.mode_var.get() == REVISION_MODE_LINGUISTIC):
            self.mode_help_var.set(
                "Può modificare alcune parole interpretando il contesto. "
                "Non verifica il parlato originale."
            )
        else:
            self.mode_help_var.set(
                "Corregge punteggiatura e maiuscole senza cambiare le parole."
            )

    def _choose_output(self) -> str | None:
        source = Path(self.source)
        suffix = (self.target_language_var.get()
                  if self.operation == OPERATION_TRANSLATION else "migliorato")
        destination = source.with_name(f"{source.stem}.{suffix}.srt")
        if not destination.exists():
            return str(destination)
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Il file migliorato esiste già: scegli un'altra destinazione",
            defaultextension=".srt",
            initialfile=f"{source.stem}.{suffix}-2.srt",
            filetypes=[("Sottotitoli SRT", "*.srt")],
        )
        if selected and Path(selected).resolve() == source.resolve():
            messagebox.showerror(
                "Destinazione non valida", "Il file originale non può essere sovrascritto.",
                parent=self,
            )
            return None
        return selected or None

    def start_revision(self) -> None:
        if (self.operation == OPERATION_TRANSLATION
                and self.source_language_var.get() not in LANGUAGES):
            messagebox.showerror("Lingua originale", "Scegli la lingua del file SRT.", parent=self)
            return
        provider = self.provider_var.get() or PROVIDER_OPENAI
        api_key = load_provider_api_key(provider)
        if not api_key:
            messagebox.showerror(
                "Chiave API mancante",
                f"Configura prima la chiave API {provider}.",
                parent=self,
            )
            return
        output = self._choose_output()
        if not output:
            return
        self._prepare_run()
        if (self.operation == OPERATION_TRANSLATION
                and self.source_language_var.get() == self.target_language_var.get()):
            messagebox.showerror(
                "Lingue uguali",
                "Per la stessa lingua usa Migliora sottotitoli…",
                parent=self,
            )
            return
        self.worker = RevisionWorker(
            self.source, output, api_key, mode=self.mode_var.get(),
            operation=self.operation, source_language=self.source_language_var.get(),
            target_language=self.target_language_var.get(), model=self.model_var.get(),
            user_context=self.context_var.get(),
            provider=provider,
        )
        self.worker.start()
        self.started_at = time.monotonic()
        self._set_running(True)
        self.status_var.set("Creo il lavoro di revisione…")

    def resume_revision(self, job_dir: Path | None = None) -> None:
        if job_dir is None:
            job_dir = self.current_job_dir or self._find_resumable_job()
        if job_dir is None:
            messagebox.showinfo(
                "Nessun lavoro da riprendere",
                "Non trovo un lavoro interrotto per questo file. "
                "Puoi aprire Lavori recenti dalla finestra principale.",
                parent=self,
            )
            return
        try:
            manifest, estimate = load_revision_for_resume(job_dir)
            # Discard any preview started while opening the dialog; it must not
            # overwrite the state of the job being resumed.
            self.preview_revision += 1
            if self.preview_after_id:
                self.after_cancel(self.preview_after_id)
                self.preview_after_id = None
            if manifest.get("status") == "completed":
                raise ValueError("Questa revisione è già completata.")
            self.source = manifest["source"]
            self.captions = load_captions(self.source)
            self.mode_var.set(
                str(manifest.get("revision_mode", REVISION_MODE_CONSERVATIVE))
            )
            self.operation = str(manifest.get("operation", OPERATION_REVISION))
            self.source_language_var.set(str(manifest.get("source_language", "en")))
            self.target_language_var.set(
                str(manifest.get("target_language", self.source_language_var.get()))
            )
            if self.operation == OPERATION_TRANSLATION:
                self.source_language.set(language_label(self.source_language_var.get()))
                self.target_language.set(language_label(self.target_language_var.get()))
            self.model_var.set(str(manifest["model"]))
            provider = str(manifest.get("provider", PROVIDER_OPENAI))
            self.provider_var.set(provider)
            self.provider_combo.set(provider)
            self._provider_changed()
            api_key = load_provider_api_key(provider)
            if not api_key:
                raise ValueError(f"Manca la chiave API {provider} per riprendere il lavoro.")
            self.context_var.set(str(manifest.get("user_context", "")))
            self._update_mode_help()
            self.caption_var.set(tr("dialog.captions", count=manifest["caption_count"]))
            self._show_estimate(estimate)
            self.progress.configure(
                maximum=len(manifest["groups"]),
                value=sum(
                    group.get("status") in {"completed", "rejected"}
                    for group in manifest["groups"]
                ),
            )
            self.worker = RevisionWorker(
                manifest["source"],
                manifest["output"],
                api_key,
                mode=self.mode_var.get(),
                operation=self.operation,
                source_language=self.source_language_var.get(),
                target_language=self.target_language_var.get(),
                model=self.model_var.get(), user_context=self.context_var.get(),
                provider=provider,
            )
            self.current_job_dir = job_dir
            self._prepare_run()
            self.worker.resume(job_dir)
        except (OSError, ValueError, KeyError, RevisionError) as exc:
            self.worker = None
            messagebox.showerror("Revisione non utilizzabile", str(exc), parent=self)
            return
        self._set_running(True)
        self.started_at = time.monotonic()
        self.status_var.set("Riprendo la revisione salvata…")

    def _find_resumable_job(self) -> Path | None:
        source = str(Path(self.source).resolve())
        candidates: list[tuple[float, Path]] = []
        if not REVISION_JOBS_DIR.is_dir():
            return None
        for record in REVISION_JOBS_DIR.glob("*/revision.json"):
            try:
                manifest = json.loads(record.read_text(encoding="utf-8"))
                if (
                    str(Path(str(manifest.get("source", ""))).resolve()) == source
                    and manifest.get("status") != "completed"
                    and manifest.get("operation", OPERATION_REVISION) == self.operation
                ):
                    candidates.append((record.stat().st_mtime, record.parent))
            except (OSError, ValueError, TypeError):
                continue
        return max(candidates, default=(0.0, None))[1]

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.cancel_button.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.resume_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")
        mode_state = (
            "disabled"
            if running or self.operation == OPERATION_TRANSLATION
            else "normal"
        )
        self.conservative_button.configure(state=mode_state)
        self.linguistic_button.configure(state=mode_state)
        self.model_combo.configure(state="disabled" if running else "readonly")
        self.context_entry.configure(state="disabled" if running else "normal")
        self._set_busy(running)

    def _set_busy(self, running: bool) -> None:
        if running == self._busy:
            return
        self._busy = running
        if running:
            self.busy_progress.start(12)
            self.last_activity_event_at = time.monotonic()
        else:
            self.busy_progress.stop()

    def _prepare_run(self) -> None:
        self.last_result = None
        self.details_button.configure(state="disabled")
        self.results_var.set("Esiti: nessun sottotitolo ancora elaborato.")

    def _poll(self) -> None:
        self._show_preview_result()
        active_worker = self.worker
        if active_worker:
            try:
                for _ in range(100):
                    kind, value = active_worker.events.get_nowait()
                    if kind == "status":
                        self.status_var.set(str(value))
                        self._set_busy(True)
                    elif kind == "job_dir":
                        self.current_job_dir = Path(str(value))
                    elif kind == "log_path":
                        self.log_panel.set_log(str(value))
                    elif kind == "log":
                        self.log_panel.add_line(str(value["line"]))
                    elif kind == "progress":
                        current, total = value
                        self._set_busy(False)
                        self.progress.configure(maximum=total, value=current)
                    elif kind == "cost":
                        suffix = "" if value["complete"] else " (dati incompleti)"
                        self.cost_var.set(
                            f"Costo effettivo ricevuto: ${value['cost_usd']:.4f} USD{suffix}"
                        )
                    elif kind == "stats":
                        self._show_stats(value)
                    elif kind == "complete":
                        self._complete(value)
                    elif kind == "cancelled":
                        self.status_var.set(
                            "Interrotto. La revisione può essere ripresa dai gruppi mancanti."
                        )
                        self.worker = None
                        self._set_running(False)
                        self.started_at = None
                    elif kind == "error":
                        self.status_var.set(
                            f"Errore: {value} Il lavoro resta disponibile per la ripresa."
                        )
                        self.worker = None
                        self._set_running(False)
                        self.started_at = None
            except queue.Empty:
                pass
        if self.winfo_exists():
            if self.started_at is not None:
                elapsed = int(time.monotonic() - self.started_at)
                minutes, seconds = divmod(elapsed, 60)
                hours, minutes = divmod(minutes, 60)
                self.elapsed_var.set(f"Tempo trascorso: {hours:02}:{minutes:02}:{seconds:02}")
            self.after(100, self._poll)

    def _complete(self, result: dict[str, Any]) -> None:
        self.started_at = None
        self.last_result = result
        self.details_button.configure(state="normal")
        cost = result["cost"]
        counts = result["counts"]
        self._show_stats(counts)
        incomplete = " (dati incompleti)" if not cost["complete"] else ""
        details = [
            f"File salvato in:\n{result['output']}",
            (
                f"Modificati: {counts['modified']} · Validi ma invariati: "
                f"{counts['unchanged']} · Originali mantenuti: {counts['rejected']}"
            ),
            f"Costo registrato: ${cost['cost_usd']:.4f} USD{incomplete}",
            (
                f"Avvisi sui contenuti: {len(result.get('content_warnings', []))} · "
                f"Parti non tradotte: {counts['rejected']}"
            ),
        ]
        if counts["modified"] == 0:
            details.append(
                "Nessuna modifica testuale applicata; il file può contenere soltanto "
                "nuovi a capo."
            )
        if result["warnings"]:
            details.append(f"Avvisi di leggibilità: {len(result['warnings'])}")
        if result.get("ambiguities"):
            details.append(f"Passaggi ambigui segnalati: {len(result['ambiguities'])}")
        if result.get("mode") == REVISION_MODE_LINGUISTIC:
            details.append(
                "Le modifiche linguistiche applicate sono consultabili in Dettagli."
            )
        if result.get("operation") == OPERATION_TRANSLATION:
            title = {
                "completed_with_untranslated": "Traduzione completata con parti non tradotte",
                "completed_with_warnings": "Traduzione completata con avvisi",
            }.get(result.get("completion_status"), "Traduzione completata")
        else:
            title = ("Nessuna modifica testuale applicata"
                     if counts["modified"] == 0 else "Revisione completata")
        self.status_var.set(title + ".")
        self.status_var.set(title + ". " + details[-1])
        self.worker = None
        self._set_running(False)

    def _show_stats(self, counts: dict[str, int]) -> None:
        self.results_var.set(
            f"Modificati: {counts['modified']} · Validi ma invariati: "
            f"{counts['unchanged']} · Originali mantenuti: {counts['rejected']}"
        )

    def show_details(self) -> None:
        if not self.last_result:
            return
        result = self.last_result
        lines: list[str] = []
        if (result.get("operation") == OPERATION_TRANSLATION
                or result.get("mode") == REVISION_MODE_LINGUISTIC) and result.get(
            "applied_changes"
        ):
            lines.append("TRADUZIONI E MODIFICHE APPLICATE")
            for item in result["applied_changes"]:
                lines.append(f"ID {item['id']}")
                lines.append(f"  Originale: {item['original']}")
                lines.append(f"  Revisione: {item['revised']}")
        if result.get("ambiguities"):
            if lines:
                lines.append("")
            lines.append("PASSAGGI AMBIGUI")
            lines.extend(
                f"ID {item.get('id')}: {item.get('note')}"
                for item in result["ambiguities"]
            )
        if result["rejections"]:
            if lines:
                lines.append("")
            lines.append("SOTTOTITOLI ORIGINALI MANTENUTI")
            lines.extend(
                f"ID {item['id']}: {item['reason']}" for item in result["rejections"]
            )
        if result["anomalies"]:
            if lines:
                lines.append("")
            lines.append("ANOMALIE DELLE RISPOSTE")
            lines.extend(str(item) for item in result["anomalies"])
        if result["warnings"]:
            if lines:
                lines.append("")
            lines.append("AVVISI DI LEGGIBILITÀ")
            lines.extend(str(item) for item in result["warnings"])
        if not lines:
            lines.append("Nessun rifiuto, anomalia o avviso di leggibilità.")

        dialog = tk.Toplevel(self)
        dialog.title("Dettagli della revisione")
        dialog.minsize(680, 420)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", width=85, height=22)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=20)
        self.master = master
        self.pack(fill="both", expand=True)
        self.media: MediaInfo | None = None
        self.worker: SubtitleWorker | None = None
        self.translation_worker: RevisionWorker | None = None
        self.translation_source: str | None = None
        self.translation_captions: list[Any] = []
        self.translation_source_var = tk.StringVar()
        self.translation_target_var = tk.StringVar(value="it")
        self.translation_model_var = tk.StringVar(value=MODEL_SOL)
        self.translation_provider_var = tk.StringVar(value=PROVIDER_OPENAI)
        self.translation_context_var = tk.StringVar()
        self.summary_checkbox_var = tk.BooleanVar(value=False)
        self.summary_worker: SummaryWorker | None = None
        self.summary_requested = False
        self.summary_waiting_for_approval = False
        self.summary_srt_path: Path | None = None
        self.summary_output: Path | None = None
        self.summary_parent_job: Path | None = None
        self.summary_language = ""
        self.summary_interval = (0.0, 0.0)
        self.summary_estimate_revision = 0
        self.summary_estimate_events: queue.Queue[tuple[int, Any, str | None]] = queue.Queue()
        self.summary_estimate_var = tk.StringVar(value="")
        self.summary_result_var = tk.StringVar(value="")
        self.translation_estimate_var = tk.StringVar()
        self.translation_estimate_events: queue.Queue[tuple[int, Any, str | None]] = queue.Queue()
        self.translation_estimate_revision = 0
        self.translation_estimate_after: str | None = None
        self.translation_status_var = tk.StringVar()
        self.translation_cost_var = tk.StringVar()
        self.result_report_path: Path | None = None
        self.translation_context_var = tk.StringVar()
        self.translation_model_var = tk.StringVar(value=MODEL_SOL)
        self.translation_provider_var = tk.StringVar(value=PROVIDER_OPENAI)
        self.current_job_path: Path | None = None
        self.transcription_job_path: Path | None = None
        self.translation_job_path: Path | None = None
        self.final_output_path: Path | None = None
        # True only after the original transcript is available and the user can
        # explicitly start the separate translation step.
        self.ready_to_translate = False
        self.workflow_active = False
        self.probe_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.video_var = tk.StringVar()
        self.video_display_var = tk.StringVar(value=tr("main.no_video"))
        self.video_folder_var = tk.StringVar(value=tr("main.choose_source"))
        self.output_var = tk.StringVar()
        self.output_display_var = tk.StringVar(value=tr("main.choose_destination"))
        self.output_folder_var = tk.StringVar(value="")
        self.model_summary_var = tk.StringVar(
            value=tr("main.model_selected", model=MODEL_SOL)
        )
        self.track_var = tk.StringVar()
        self.source_language_var = tk.StringVar(value="auto")
        self.target_language_var = tk.StringVar(value="original")
        self.start_time_var = tk.StringVar(value="00:00:00")
        self.end_time_var = tk.StringVar(value="00:00:00")
        self._syncing_range = False
        self.cost_var = tk.StringVar(value=tr("main.estimate_video"))
        self.status_var = tk.StringVar(value=tr("main.ready"))
        self.activity_var = tk.StringVar(value="")
        self.result_count_events: queue.Queue[tuple[Path, int | None]] = queue.Queue()
        self.work_summary_var = tk.StringVar(value=tr("main.choose_source"))
        self.source_hint_var = tk.StringVar(value=tr("main.video_required"))
        self.final_hint_var = tk.StringVar(value=tr("main.video_required"))
        self.activity_started_at: float | None = None
        self.last_activity_event_at: float | None = None
        self.phase_started_at: float | None = None
        self.phase_label = ""
        self._close_after_cancel = False
        self.cancel_requested = False
        self.job_resumable = False
        self.download_dialog: DownloadDialog | None = None
        self.download_state = "inattivo"
        self._workflow_controls_enabled = True
        self._build_v08()
        self.video_var.trace_add("write", self._update_source_path)
        self.output_var.trace_add("write", self._update_output_path)
        self.translation_model_var.trace_add("write", self._refresh_model_summary)
        self.start_time_var.trace_add("write", self._on_time_field_changed)
        self.end_time_var.trace_add("write", self._on_time_field_changed)
        self._set_workflow_controls(True)
        self.master.after(100, self._poll)

    def _build_v08(self) -> None:
        self.master.title(tr("app.name"))
        self.master.geometry("960x740")
        self.master.minsize(760, 630)
        self._build_menu()

        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        canvas_frame = ttk.Frame(shell)
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
        canvas = tk.Canvas(canvas_frame, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        layout = ttk.Frame(canvas, padding=(22, 18, 22, 20))
        self.layout = layout
        window = canvas.create_window((0, 0), window=layout, anchor="nw")
        layout.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        self.master.bind_all("<MouseWheel>", self._scroll_main, add="+")
        layout.columnconfigure(0, weight=1)

        header = ttk.Frame(layout)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text=tr("app.name"), font=("TkDefaultFont", 20, "bold")
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.work_summary_var, wraplength=680).grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )
        ttk.Button(
            header, text=tr("menu.recent_jobs"), command=self.open_recent_jobs
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        source = ttk.LabelFrame(layout, text=tr("main.source"), padding=12)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(1, weight=1)
        ttk.Label(source, textvariable=self.source_hint_var, wraplength=760).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(7, 0)
        )
        self.video_entry = ttk.Entry(source, textvariable=self.video_display_var, state="readonly")
        self.video_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Label(source, text=tr("main.video")).grid(row=0, column=0, sticky="w")
        self.choose_video_button = ttk.Button(
            source, text=tr("main.choose_video"), command=self.choose_video
        )
        self.choose_video_button.grid(row=0, column=2, padx=(0, 6))
        self.link_button = ttk.Button(
            source, text=tr("main.from_link"), command=self.open_download_dialog
        )
        self.link_button.grid(row=0, column=3)
        ttk.Label(source, textvariable=self.video_folder_var).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(5, 0)
        )
        self.copy_source_path_button = ttk.Button(
            source, text=tr("main.copy_path"), command=self._copy_source_path, state="disabled"
        )
        self.copy_source_path_button.grid(row=1, column=3, sticky="e", pady=(4, 0))
        ttk.Label(source, text=tr("main.audio_track")).grid(row=2, column=0, sticky="w", pady=(9, 0))
        self.track = ttk.Combobox(source, textvariable=self.track_var, state="disabled")
        self.track.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(9, 0))
        speech_row = ttk.Frame(source)
        speech_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(9, 0))
        ttk.Label(speech_row, text=tr("main.spoken_language")).pack(side="left")
        self.source_language = ttk.Combobox(
            speech_row, width=14, state="readonly",
            values=[language_label(code) for code in ("auto", "en", "it", "ja", "fr")],
        )
        self.source_language.set(language_label("auto"))
        self.source_language.bind("<<ComboboxSelected>>", self._source_language_changed)
        self.source_language.pack(side="left", padx=(8, 6))
        HelpButton(
            speech_row, tr("help.spoken.title"), tr("help.spoken.body"),
        ).pack(side="left")

        final = ttk.LabelFrame(layout, text=tr("main.final_subtitles"), padding=12)
        final.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        final.columnconfigure(1, weight=1)
        ttk.Label(final, textvariable=self.final_hint_var, wraplength=760).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )
        target_row = ttk.Frame(final)
        target_row.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(target_row, text=tr("main.final_language")).pack(side="left")
        self.target_language = ttk.Combobox(
            target_row, width=14, state="readonly",
            values=[language_label(code) for code in ("original", "en", "it", "ja")],
        )
        self.target_language.set(language_label("original"))
        self.target_language.bind("<<ComboboxSelected>>", self._final_language_changed)
        self.target_language.pack(side="left", padx=(8, 6))
        HelpButton(
            target_row, tr("help.final.title"), tr("help.final.body"),
        ).pack(side="left")
        ttk.Label(final, text=tr("main.range")).grid(row=1, column=0, sticky="nw", pady=(12, 0))
        range_frame = ttk.Frame(final)
        range_frame.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(12, 0))
        range_frame.columnconfigure(1, weight=1)
        range_frame.columnconfigure(3, weight=1)
        ttk.Label(range_frame, text=tr("main.start")).grid(row=0, column=0, sticky="w")
        self.start_entry = ttk.Entry(range_frame, textvariable=self.start_time_var, width=12)
        self.start_entry.grid(row=0, column=1, sticky="w", padx=(6, 14))
        ttk.Label(range_frame, text=tr("main.end")).grid(row=0, column=2, sticky="w")
        self.end_entry = ttk.Entry(range_frame, textvariable=self.end_time_var, width=12)
        self.end_entry.grid(row=0, column=3, sticky="w", padx=6)
        self.reset_range_button = ttk.Button(
            range_frame, text=tr("main.whole_video"), command=self._reset_range
        )
        self.reset_range_button.grid(row=0, column=4, sticky="e")
        self.range_scale = TimeRangeScale(range_frame, self._range_changed)
        self.range_scale.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 3))
        HelpButton(
            range_frame, tr("help.range.title"), tr("help.range.body"),
        ).grid(row=2, column=0, sticky="w", pady=(3, 0))
        ttk.Label(
            range_frame, text=tr("main.range_hint"),
        ).grid(row=2, column=1, columnspan=4, sticky="w", pady=(3, 0))
        ttk.Label(final, text=tr("main.save_srt")).grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.output_entry = ttk.Entry(
            final, textvariable=self.output_display_var, state="readonly"
        )
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=(12, 0))
        self.choose_output_button = ttk.Button(final, text=tr("main.choose"), command=self.choose_output)
        self.choose_output_button.grid(row=2, column=2, pady=(12, 0))
        self.output_path_button = ttk.Button(
            final, text=tr("main.copy_path"), command=self._copy_output_path, state="disabled"
        )
        ttk.Label(final, textvariable=self.output_folder_var).grid(
            row=3, column=1, sticky="w", padx=(8, 8), pady=(5, 0)
        )
        self.output_path_button.grid(row=3, column=2, sticky="e", pady=(4, 0))

        self.advanced_toggle = ttk.Button(
            final, text=tr("main.advanced_show"), command=self._toggle_advanced
        )
        self.summary_check_button = ttk.Checkbutton(
            final,
            text=tr("main.summary_option"),
            variable=self.summary_checkbox_var,
            command=self._summary_option_changed,
        )
        self.summary_check_button.grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )
        ttk.Label(
            final,
            text=tr("main.summary_help"),
            wraplength=760,
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=(20, 0), pady=(2, 0))
        self.advanced_toggle.grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.advanced_frame = ttk.Frame(final, padding=(8, 8, 0, 0))
        self.advanced_visible = False
        self.advanced_frame.columnconfigure(1, weight=1)
        model_row = ttk.Frame(self.advanced_frame)
        model_row.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(model_row, text="Provider AI").pack(side="left")
        self.translation_provider_combo = ttk.Combobox(
            model_row, width=12, state="readonly",
            textvariable=self.translation_provider_var,
            values=list(AI_PROVIDERS),
        )
        self.translation_provider_combo.pack(side="left", padx=(8, 8))
        self.translation_provider_combo.bind(
            "<<ComboboxSelected>>", self._provider_changed
        )
        ttk.Label(model_row, text=tr("main.translation_model")).pack(side="left")
        self.translation_model_combo = ttk.Combobox(
            model_row, width=23, state="readonly", textvariable=self.translation_model_var,
            values=list(PROVIDER_MODELS[PROVIDER_OPENAI]),
        )
        self.translation_model_combo.pack(side="left", padx=(8, 6))
        self.translation_model_combo.bind("<<ComboboxSelected>>", self._update_translation_estimate)
        HelpButton(
            model_row, tr("help.model.title"), tr("help.model.body"),
        ).pack(side="left")
        ttk.Label(self.advanced_frame, text=tr("main.context")).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.translation_context_entry = ttk.Entry(
            self.advanced_frame, textvariable=self.translation_context_var
        )
        self.translation_context_entry.grid(
            row=1, column=1, sticky="ew", padx=(8, 6), pady=(8, 0)
        )
        HelpButton(
            self.advanced_frame, tr("help.context.title"), tr("help.context.body"),
        ).grid(row=1, column=2, pady=(8, 0))
        self.translation_estimate_label = ttk.Label(
            self.advanced_frame, textvariable=self.translation_estimate_var,
            wraplength=780, justify="left",
        )
        self.translation_estimate_label.grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        self.model_summary_label = ttk.Label(final, textvariable=self.model_summary_var)
        self.model_summary_label.grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        activity = ttk.LabelFrame(layout, text=tr("main.activity"), padding=12)
        self.activity_frame = activity
        activity.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        activity.columnconfigure(0, weight=1)
        activity_header = ttk.Frame(activity)
        activity_header.grid(row=0, column=0, sticky="ew")
        activity_header.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(
            activity_header, textvariable=self.status_var, wraplength=760, justify="left"
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.cost_label = ttk.Label(activity_header, textvariable=self.cost_var, wraplength=760)
        self.cost_label.grid(row=1, column=0, sticky="w", pady=(5, 0))
        HelpButton(
            activity_header, tr("help.cost.title"), tr("help.cost.body"),
        ).grid(row=1, column=1, padx=(8, 0))
        progress_row = ttk.Frame(activity)
        progress_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        progress_row.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_row, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        self.busy_progress = ttk.Progressbar(progress_row, mode="indeterminate", length=72)
        self.busy_progress.grid(row=0, column=1, padx=(9, 0))
        self._busy = False
        self.activity_message_label = ttk.Label(
            activity, textvariable=self.activity_var
        )
        self.activity_message_label.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.log_panel = EventLogPanel(activity)
        self.log_panel.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        result = ttk.LabelFrame(layout, text=tr("main.result"), padding=12)
        result.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        result.columnconfigure(0, weight=1)
        self.result_summary_var = tk.StringVar(value=tr("main.result_pending"))
        ttk.Label(result, textvariable=self.result_summary_var, wraplength=780).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(result, textvariable=self.summary_estimate_var, wraplength=780).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Label(result, textvariable=self.summary_result_var, wraplength=780).grid(
            row=2, column=0, sticky="w", pady=(5, 0)
        )
        result_buttons = ttk.Frame(result)
        result_buttons.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.open_result_button = ttk.Button(
            result_buttons, text=tr("main.open_srt"), command=self._open_result, state="disabled"
        )
        # The fixed footer owns the primary action; result actions remain secondary.
        self.show_finder_button = ttk.Button(
            result_buttons, text=tr("main.show_finder"), command=self._show_result,
            state="disabled",
        )
        self.show_issues_button = ttk.Button(
            result_buttons, text=tr("main.view_issues"), command=self._open_issues,
            state="disabled",
        )
        self.open_summary_button = ttk.Button(
            result_buttons, text=tr("main.open_txt"), command=self._open_summary,
            state="disabled",
        )
        self.new_work_button = ttk.Button(
            result_buttons, text=tr("main.new_job"), command=self._new_work
        )

        footer = ttk.Frame(shell, padding=(12, 8))
        footer.grid(row=1, column=0, sticky="ew")
        ttk.Separator(footer).pack(fill="x", pady=(0, 8))
        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        self.cancel_button = ttk.Button(
            actions, text=tr("main.cancel"), command=self.cancel, state="disabled"
        )
        self.resume_button = ttk.Button(actions, text=tr("main.resume"), command=self.resume)
        self.start_button = ttk.Button(
            actions, text=tr("main.generate_transcription"), command=self.start, state="disabled"
        )
        self.footer_open_button = ttk.Button(
            actions, text=tr("main.open_srt"), command=self._open_result
        )
        self.summary_button = ttk.Button(
            actions, text=tr("main.create_txt"), command=self._start_summary
        )

        self.master.protocol("WM_DELETE_WINDOW", self._request_close)
        self.master.after_idle(self._update_footer_state)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.master)
        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label=tr("menu.translate_srt"), command=self.translate_existing_srt)
        tools_menu.add_command(label=tr("menu.improve_srt"), command=self.improve_existing_srt)
        tools_menu.add_command(
            label=tr("menu.readability"), command=self.format_existing_srt
        )
        self.master.tools_menu = tools_menu
        menu.add_cascade(label=tr("menu.tools"), menu=tools_menu)
        settings_menu = tk.Menu(menu, tearoff=False)
        api_menu = tk.Menu(settings_menu, tearoff=False)
        api_menu.add_command(label="OpenAI…", command=lambda: self.configure_provider_key(PROVIDER_OPENAI))
        api_menu.add_command(label="DeepSeek…", command=lambda: self.configure_provider_key(PROVIDER_DEEPSEEK))
        settings_menu.add_cascade(label=tr("menu.api_key"), menu=api_menu)
        language_menu = tk.Menu(settings_menu, tearoff=False)
        self.ui_locale_var = tk.StringVar(value=get_locale())
        language_menu.add_radiobutton(
            label=tr("menu.language.english"), variable=self.ui_locale_var,
            value="en", command=lambda: self._change_ui_locale("en"),
        )
        language_menu.add_radiobutton(
            label=tr("menu.language.italian"), variable=self.ui_locale_var,
            value="it", command=lambda: self._change_ui_locale("it"),
        )
        self.language_menu = language_menu
        settings_menu.add_cascade(label=tr("menu.interface_language"), menu=language_menu)
        menu.add_cascade(label=tr("menu.settings"), menu=settings_menu)
        jobs_menu = tk.Menu(menu, tearoff=False)
        jobs_menu.add_command(label=tr("menu.recent_jobs"), command=self.open_recent_jobs)
        jobs_menu.add_command(
            label=tr("menu.storage"), command=self.open_storage_dialog
        )
        menu.add_cascade(label=tr("menu.jobs"), menu=jobs_menu)
        self.master.configure(menu=menu)
        self.master.bind("<Command-o>", lambda _event: self.choose_video())
        self.master.bind("<Command-r>", self._resume_shortcut)
        self.master.bind("<Escape>", self._escape_help)

    def _change_ui_locale(self, locale_code: str) -> None:
        if locale_code == get_locale():
            return
        if self.worker or self.translation_worker or self.summary_worker or self._active_download() or self._busy:
            self.ui_locale_var.set(get_locale())
            return
        save_locale(PREFERENCES_PATH, locale_code)
        set_locale(locale_code)
        try:
            if getattr(sys, "frozen", False):
                command = [sys.executable]
            else:
                command = [sys.executable, *sys.argv]
            subprocess.Popen(command, close_fds=True, start_new_session=True)
        except OSError as exc:
            messagebox.showwarning(
                tr("restart.title"), tr("restart.failed", error=str(exc)),
                parent=self.master,
            )
            return
        self.master.destroy()

    def _scroll_main(self, event: tk.Event) -> str | None:
        try:
            if event.widget.winfo_toplevel() is not self.master:
                return None
        except tk.TclError:
            return None
        delta = int(-event.delta / 120) if abs(event.delta) >= 120 else -int(event.delta)
        if delta == 0:
            delta = -1 if event.delta > 0 else 1
        self.layout.master.yview_scroll(delta, "units")
        return "break"

    def _resume_shortcut(self, _event: tk.Event) -> str:
        if (
            self.job_resumable and self.current_job_path
            and self.current_job_path.is_file()
            and not (self.worker or self.translation_worker or self.summary_worker
                     or self._active_download() or self._busy)
        ):
            self.resume()
        elif (
            self.download_state in {"interrotto", "errore"}
            and self.download_dialog and self.download_dialog.winfo_exists()
            and not self.download_dialog.worker
        ):
            self._resume_current_download()
        return "break"

    def _toggle_advanced(self) -> None:
        if self.advanced_toggle.instate(["disabled"]):
            return
        if self.advanced_visible:
            self.advanced_frame.grid_forget()
            self.advanced_toggle.configure(text=tr("main.advanced_show"))
        else:
            self.advanced_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 0))
            self.advanced_toggle.configure(text=tr("main.advanced_hide"))
        self.advanced_visible = not self.advanced_visible

    def _copy_output_path(self) -> None:
        value = self.output_var.get()
        if value:
            self.master.clipboard_clear()
            self.master.clipboard_append(value)
            self.status_var.set("Percorso copiato negli appunti.")

    def _update_output_path(self, *_args: object) -> None:
        value = self.output_var.get()
        if not value:
            self.output_display_var.set(tr("main.choose_destination"))
            self.output_folder_var.set("")
            self.output_path_button.configure(state="disabled")
            return
        path = Path(value)
        self.output_display_var.set(path.name)
        self.output_folder_var.set(tr("main.folder", name=path.parent.name))
        self.output_path_button.configure(
            state="normal" if self._workflow_controls_enabled and self.media else "disabled"
        )

    def _refresh_model_summary(self, *_args: object) -> None:
        model = self.translation_model_var.get() or MODEL_SOL
        provider = self.translation_provider_var.get() or PROVIDER_OPENAI
        text = tr("main.model_selected", model=f"{provider} · {model}")
        if hasattr(self, "model_summary_var"):
            self.model_summary_var.set(text)

    def _provider_changed(self, _event: object | None = None) -> None:
        provider = self.translation_provider_var.get() or PROVIDER_OPENAI
        models = list(PROVIDER_MODELS.get(provider, PROVIDER_MODELS[PROVIDER_OPENAI]))
        self.translation_model_combo.configure(values=models)
        if self.translation_model_var.get() not in models:
            self.translation_model_var.set(models[0])
        self._refresh_model_summary()
        self._update_translation_estimate()

    def _refresh_work_summary(self) -> None:
        if self._active_download():
            title = "Video da link"
            dialog = self.download_dialog
            if dialog and dialog.metadata:
                title = str(dialog.metadata.get("title") or title)
            self.work_summary_var.set(f"Download · {title}")
            return
        if not self.media:
            self.work_summary_var.set("Scegli un video o scaricalo da un link.")
            return
        name = Path(self.video_var.get() or self.media.path).name
        language = self.target_language.get()
        if language_code(language) == "original":
            language = "lingua originale"
        interval = ""
        try:
            start, end = self._read_interval()
            interval = f" · intervallo {format_time_value(start)}–{format_time_value(end)}"
        except StartTimeError:
            pass
        if self.translation_worker:
            self.work_summary_var.set(f"Traduzione in {language.lower()} · {name}")
        elif self.worker:
            self.work_summary_var.set(f"Trascrizione · {name}{interval}")
        else:
            self.work_summary_var.set(
                f"Sottotitoli in {language.lower()} · {name}{interval}"
            )

    def _update_source_path(self, *_args: object) -> None:
        value = self.video_var.get()
        if not value:
            self.video_display_var.set(tr("main.no_video"))
            self.video_folder_var.set(tr("main.choose_source"))
            self.copy_source_path_button.configure(state="disabled")
            return
        path = Path(value)
        self.video_display_var.set(path.name)
        self.video_folder_var.set(tr("main.folder", name=path.parent.name))
        self.copy_source_path_button.configure(
            state="normal" if self._workflow_controls_enabled else "disabled"
        )

    def _copy_source_path(self) -> None:
        value = self.video_var.get()
        if value:
            self.master.clipboard_clear()
            self.master.clipboard_append(value)
            self.status_var.set("Percorso del video copiato negli appunti.")

    def _new_work(self) -> None:
        if self.worker or self.translation_worker or getattr(self, "summary_worker", None) or self._active_download():
            return
        self.download_state = "inattivo"
        self.media = None
        self.video_var.set("")
        self.output_var.set("")
        self.track_var.set("")
        self.track.configure(values=(), state="disabled")
        self.start_time_var.set("00:00:00")
        self.end_time_var.set("00:00:00")
        self.translation_estimate_var.set("")
        self.cost_var.set("Scegli un video o importa un link per vedere la stima.")
        self.status_var.set("Scegli un video per iniziare.")
        self.result_summary_var.set("Il file comparirà qui al termine del lavoro.")
        self.summary_checkbox_var.set(False)
        self.summary_requested = False
        self.summary_waiting_for_approval = False
        self.summary_srt_path = None
        self.summary_output = None
        self.summary_parent_job = None
        self.summary_estimate_var.set("")
        self.summary_result_var.set("")
        self.open_summary_button.configure(state="disabled")
        self.current_job_path = None
        self.transcription_job_path = None
        self.translation_job_path = None
        self.final_output_path = None
        self.result_report_path = None
        self.job_resumable = False
        self.translation_source = None
        self.translation_captions = []
        self.ready_to_translate = False
        self.open_result_button.configure(state="disabled")
        self.show_finder_button.configure(state="disabled")
        self.show_issues_button.configure(state="disabled")
        self.output_path_button.configure(state="disabled")
        self.progress.configure(value=0, maximum=1)
        self._set_workflow_controls(True)
        self._enable_start()

    def _request_close(self) -> None:
        if not self.worker and not self.translation_worker and not self.summary_worker and not self._active_download():
            self.master.destroy()
            return
        if messagebox.askyesno(
            "Lavoro in corso",
            "Vuoi interrompere il lavoro e chiudere dopo aver salvato i progressi?",
            parent=self.master,
        ):
            self._close_after_cancel = True
            self.status_var.set("Interruzione richiesta; salvo il lavoro prima di chiudere…")
            self.cancel()

    def _active_download(self) -> DownloadWorker | None:
        dialog = self.download_dialog
        return dialog.worker if dialog and dialog.worker else None

    def _download_started(self) -> None:
        self.download_state = "preparazione"
        self.cancel_requested = False
        self._clear_activity_clock()
        self.status_var.set("Preparo il download…")
        self.activity_var.set("Controllo il link e preparo il trasferimento.")
        self.progress.configure(maximum=100, value=0)
        self._set_busy(True)
        self.master.after_idle(self._update_footer_state)
        self.master.after_idle(self._scroll_to_activity)

    def _clear_activity_clock(self) -> None:
        self.activity_started_at = None
        self.phase_started_at = None
        self.last_activity_event_at = None

    def _scroll_to_activity(self) -> None:
        canvas = self.layout.master
        self.master.update_idletasks()
        scrollable = self.layout.winfo_height() - canvas.winfo_height()
        if scrollable > 0:
            canvas.yview_moveto(min(1.0, self.activity_frame.winfo_y() / scrollable))

    def _show_download_phase(self, stage: str, description: str) -> None:
        self.download_state = stage
        self.status_var.set(description)
        self.activity_var.set("Il trasferimento è terminato; preparo il file finale.")
        self.progress.configure(maximum=100, value=0)
        self._set_busy(True)

    def _show_download_progress(self, description: str, percent: float | None) -> None:
        self.download_state = "trasferimento"
        self.status_var.set("Download in corso…")
        self.activity_var.set(description)
        self.progress.configure(maximum=100, value=percent if percent is not None else 0)
        self._set_busy(percent is None)

    def _download_stopped(self, state: str, description: str) -> None:
        self.download_state = state
        self.cancel_requested = False
        self.activity_var.set(description)
        self.status_var.set(description)
        self.progress.configure(maximum=100, value=0)
        self.master.after_idle(self._update_footer_state)
        if self._close_after_cancel:
            self.master.after_idle(self._finish_close_after_download)

    def _finish_close_after_download(self) -> None:
        if self._close_after_cancel and not self._active_download():
            self.master.destroy()

    def _resume_current_download(self) -> None:
        dialog = self.download_dialog
        if not dialog or not dialog.winfo_exists() or dialog.worker:
            return
        if not dialog.url_var.get().strip():
            dialog.deiconify()
            dialog.lift()
            dialog.status_var.set("Inserisci il link originale, poi premi Riprendi.")
            return
        dialog.resume_current()

    def _escape_help(self, _event: object | None = None) -> str | None:
        focused = self.master.focus_get()
        if isinstance(focused, HelpButton):
            return focused.close()
        return None

    def _build(self) -> None:
        self.master.title(tr("app.name"))
        self.master.minsize(760, 630)
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        canvas = tk.Canvas(shell, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        layout = ttk.Frame(canvas, padding=20)
        self.layout = layout
        window = canvas.create_window((0, 0), window=layout, anchor="nw")
        layout.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        canvas.bind_all(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"),
        )
        layout.columnconfigure(1, weight=1)
        ttk.Label(
            layout,
            text="Crea e traduci sottotitoli in formato SRT",
            font=("Helvetica", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        ttk.Button(layout, text="Lavori recenti…", command=self.open_recent_jobs).grid(
            row=0, column=2, sticky="e", pady=(0, 16)
        )

        ttk.Label(layout, text="Video").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(layout, textvariable=self.video_var, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=8
        )
        file_buttons = ttk.Frame(layout)
        file_buttons.grid(row=1, column=2, sticky="e")
        ttk.Button(file_buttons, text="Scegli…", command=self.choose_video).pack(side="left")
        ttk.Button(file_buttons, text="Da link…", command=self.open_download_dialog).pack(
            side="left", padx=(6, 0)
        )

        ttk.Label(layout, text="Traccia audio").grid(row=2, column=0, sticky="w", pady=5)
        self.track = ttk.Combobox(layout, textvariable=self.track_var, state="disabled")
        self.track.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0))

        ttk.Label(layout, text="Lingua parlata").grid(row=3, column=0, sticky="w", pady=5)
        language_frame = ttk.Frame(layout)
        language_frame.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Label(language_frame, text="Parlato").pack(side="left")
        self.source_language = ttk.Combobox(
            language_frame,
            width=13,
            state="readonly",
            values=list(SOURCE_LANGUAGES.values()),
        )
        self.source_language.set(SOURCE_LANGUAGES["auto"])
        self.source_language.bind("<<ComboboxSelected>>", self._source_language_changed)
        self.source_language.pack(side="left", padx=(5, 16))
        ttk.Label(layout, text="Intervallo").grid(row=4, column=0, sticky="nw", pady=5)
        range_frame = ttk.Frame(layout)
        range_frame.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        range_frame.columnconfigure(1, weight=1)
        range_frame.columnconfigure(3, weight=1)
        ttk.Label(range_frame, text="Inizio").grid(row=0, column=0, sticky="w")
        ttk.Entry(range_frame, textvariable=self.start_time_var, width=12).grid(
            row=0, column=1, sticky="w", padx=(6, 16)
        )
        ttk.Label(range_frame, text="Fine").grid(row=0, column=2, sticky="w")
        ttk.Entry(range_frame, textvariable=self.end_time_var, width=12).grid(
            row=0, column=3, sticky="w", padx=6
        )
        ttk.Button(range_frame, text="Tutto il video", command=self._reset_range).grid(
            row=0, column=4, sticky="e"
        )
        self.range_scale = TimeRangeScale(range_frame, self._range_changed)
        self.range_scale.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 2))
        ttk.Label(
            range_frame,
            text=(
                "Formato HH:MM:SS o minuti decimali. Seleziona un cursore e usa "
                "←/→ per spostarlo di un secondo."
            ),
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=5, sticky="w")

        ttk.Label(layout, text="SRT finale").grid(
            row=5, column=0, sticky="w", pady=5
        )
        ttk.Entry(layout, textvariable=self.output_var, state="readonly").grid(
            row=5, column=1, sticky="ew", padx=8
        )
        ttk.Button(layout, text="Salva in…", command=self.choose_output).grid(
            row=5, column=2, sticky="e"
        )

        settings = ttk.LabelFrame(layout, text="Lingua dei sottotitoli finali", padding=8)
        settings.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(settings, text="Sottotitoli").grid(row=0, column=0, sticky="w")
        self.target_language = ttk.Combobox(
            settings, width=13, state="readonly",
            values=["Originale", *LANGUAGES.values()],
        )
        self.target_language.set("Originale")
        self.target_language.grid(row=0, column=1, sticky="w", padx=(6, 18))
        self.target_language.bind("<<ComboboxSelected>>", self._final_language_changed)
        ttk.Label(settings, text="Modello").grid(row=0, column=2, sticky="w")
        self.translation_model_combo = ttk.Combobox(
            settings, width=24, state="readonly",
            textvariable=self.translation_model_var,
            values=[MODEL_SOL, MODEL_SOL_LEGACY, MODEL_MINI],
        )
        self.translation_model_combo.grid(row=0, column=3, sticky="ew", padx=6)
        settings.columnconfigure(3, weight=1)
        ttk.Label(settings, text="Contesto e terminologia (facoltativo)").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )
        self.translation_context_entry = ttk.Entry(
            settings, textvariable=self.translation_context_var
        )
        self.translation_context_entry.grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(3, 0)
        )
        ttk.Label(
            settings, textvariable=self.translation_estimate_var, wraplength=760
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Separator(layout).grid(row=7, column=0, columnspan=3, sticky="ew", pady=12)
        ttk.Label(layout, textvariable=self.cost_var).grid(
            row=8, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            layout,
            text="La trascrizione viene salvata prima della traduzione. Avvia traduzione è sempre un comando esplicito.",
            foreground="#555555",
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(4, 10))
        self.progress = ttk.Progressbar(layout, mode="determinate")
        self.progress.grid(row=10, column=0, columnspan=2, sticky="ew")
        self.busy_progress = ttk.Progressbar(layout, mode="indeterminate", length=80)
        self.busy_progress.grid(row=10, column=2, sticky="e", padx=(8, 0))
        self._busy = False
        ttk.Label(layout, textvariable=self.status_var, wraplength=760).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(8, 10)
        )
        ttk.Label(layout, textvariable=self.activity_var, foreground="#555555").grid(
            row=12, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        buttons = ttk.Frame(layout)
        buttons.grid(row=13, column=0, columnspan=3, sticky="e", pady=(8, 0))
        self.cancel_button = ttk.Button(
            buttons, text="Interrompi", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        self.start_button = ttk.Button(
            buttons, text=tr("main.generate_transcription"), command=self.start, state="disabled"
        )
        self.start_button.pack(side="right", padx=(0, 8))
        self.resume_button = ttk.Button(buttons, text="Riprendi", command=self.resume)
        self.resume_button.pack(
            side="right", padx=(0, 8)
        )

        tools = ttk.Frame(layout)
        tools.grid(row=14, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(
            tools,
            text="Migliora sottotitoli…",
            command=self.improve_existing_srt,
        ).pack(side="left")
        ttk.Button(
            tools, text="Traduci SRT…", command=self.translate_existing_srt
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            tools,
            text="Formatta SRT…",
            command=self.format_existing_srt,
        ).pack(side="left", padx=(8, 0))
        self.open_result_button = ttk.Button(
            tools, text="Apri SRT", command=self._open_result, state="disabled"
        )
        self.open_result_button.pack(side="left", padx=(8, 0))
        self.show_finder_button = ttk.Button(
            tools, text="Mostra nel Finder", command=self._show_result, state="disabled"
        )
        self.show_finder_button.pack(side="left", padx=(8, 0))
        self.show_issues_button = ttk.Button(
            tools, text="Vedi problemi", command=self._open_issues, state="disabled"
        )
        self.show_issues_button.pack(side="left", padx=(8, 0))
        ttk.Button(tools, text="Configura chiave…", command=self.configure_key).pack(
            side="left", padx=(8, 0)
        )
        self.log_panel = EventLogPanel(layout)
        self.log_panel.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    def _final_language_changed(self, _event: object | None = None) -> None:
        if _event is not None and (
            not self.media or self.worker or self.translation_worker
            or self.summary_worker or self._active_download() or self._busy
        ):
            return
        target = language_code(self.target_language.get()) or "original"
        self.target_language_var.set(target)
        self.translation_target_var.set(target)
        self.translation_estimate_var.set(
            "Verrà salvata la trascrizione nella lingua parlata."
            if target == "original"
            else "Il costo della traduzione sarà stimato dopo la trascrizione."
        )
        self._refresh_model_summary()
        self._set_workflow_controls(
            not (self.worker or self.translation_worker or self.summary_worker
                 or self._active_download() or self._busy)
        )
        self._enable_start()

    def _translation_options_needed(self) -> bool:
        target = language_code(self.target_language.get()) or "original"
        if target == "original":
            return False
        source = language_code(self.source_language.get()) or "auto"
        return source == "auto" or source != target

    def _set_workflow_controls(self, enabled: bool) -> None:
        self._workflow_controls_enabled = enabled
        video_ready = enabled and self.media is not None
        translation_ready = video_ready and self._translation_options_needed()
        if hasattr(self, "source_hint_var"):
            if not self.media:
                self.source_hint_var.set("Disponibile dopo il caricamento del video.")
                self.final_hint_var.set("Disponibile dopo il caricamento del video.")
            elif not enabled:
                self.source_hint_var.set("Le impostazioni sono bloccate durante il lavoro.")
                self.final_hint_var.set("Le impostazioni sono bloccate durante il lavoro.")
            else:
                self.source_hint_var.set("")
                self.final_hint_var.set(
                    "La lingua finale coincide con quella del parlato: traduzione non necessaria."
                    if not self._translation_options_needed() else ""
                )
            if translation_ready:
                self.advanced_toggle.grid()
                self.model_summary_label.grid()
            else:
                self.advanced_toggle.grid_remove()
                self.advanced_frame.grid_remove()
                self.advanced_visible = False
                self.advanced_toggle.configure(text=tr("main.advanced_show"))
                self.model_summary_label.grid_remove()
            self._refresh_work_summary()
        combo_state = "readonly" if video_ready else "disabled"
        for widget in (self.choose_video_button, self.link_button):
            widget.configure(state="normal" if enabled else "disabled")
        if hasattr(self, "work_summary_var"):
            if self.media:
                self.choose_video_button.grid()
            else:
                self.choose_video_button.grid_remove()
        for widget in (
            self.choose_output_button, self.reset_range_button,
            self.summary_check_button,
        ):
            widget.configure(state="normal" if video_ready else "disabled")
        self.advanced_toggle.configure(
            state="normal" if translation_ready else "disabled"
        )
        self.copy_source_path_button.configure(
            state="normal" if enabled and self.video_var.get() else "disabled"
        )
        self.output_path_button.configure(
            state="normal" if video_ready and self.output_var.get() else "disabled"
        )
        self.output_entry.configure(state="readonly" if video_ready else "disabled")
        self.track.configure(
            state="readonly" if video_ready and self.media.audio_tracks else "disabled"
        )
        self.source_language.configure(state=combo_state)
        self.target_language.configure(state=combo_state)
        self.translation_model_combo.configure(
            state="readonly" if translation_ready else "disabled"
        )
        if hasattr(self, "translation_provider_combo"):
            self.translation_provider_combo.configure(
                state="readonly" if translation_ready else "disabled"
            )
        self.translation_context_entry.configure(
            state="normal" if translation_ready else "disabled"
        )
        for widget in (self.start_entry, self.end_entry):
            widget.configure(state="normal" if video_ready else "disabled")
        self.range_scale.configure(state="normal" if video_ready else "disabled")
        if enabled:
            self._update_output_path()
            self._enable_start()
        else:
            self.start_button.configure(state="disabled")
        for index in range(self.master.tools_menu.index("end") + 1):
            self.master.tools_menu.entryconfigure(
                index, state="normal" if enabled else "disabled"
            )
        language_state = "normal" if enabled and not (
            getattr(self, "worker", None) or getattr(self, "translation_worker", None)
            or getattr(self, "summary_worker", None)
            or (self._active_download() if hasattr(self, "_active_download") else None)
            or getattr(self, "_busy", False)
        ) else "disabled"
        if hasattr(self, "language_menu"):
            for index in range(self.language_menu.index("end") + 1):
                self.language_menu.entryconfigure(index, state=language_state)
        self.master.after_idle(self._update_footer_state)

    def _update_footer_state(self) -> None:
        if hasattr(self, "work_summary_var"):
            self._refresh_work_summary()
            for widget in (
                self.show_finder_button, self.show_issues_button,
                self.open_summary_button, self.new_work_button,
            ):
                widget.pack_forget()
            if self.final_output_path and self.final_output_path.is_file():
                self.show_finder_button.pack(side="left")
                if self.result_report_path and self.result_report_path.is_file():
                    self.show_issues_button.pack(side="left", padx=(6, 0))
                if self.summary_output and self.summary_output.is_file():
                    self.open_summary_button.pack(side="left", padx=(6, 0))
                if not (
                    self.worker or self.translation_worker or self.summary_worker
                    or self._active_download() or self._busy
                ):
                    self.new_work_button.pack(side="left", padx=(6, 0))
        for widget in (
            self.start_button, self.resume_button, self.cancel_button,
            self.footer_open_button, self.summary_button,
        ):
            widget.pack_forget()
        if self.worker or self.translation_worker or self.summary_worker or self._active_download():
            self.cancel_button.configure(
                text=("Stop requested…" if get_locale() == "en" else "Interruzione richiesta…")
                if self.cancel_requested else tr("main.cancel"),
                state="disabled" if self.cancel_requested else "normal",
            )
            self.cancel_button.pack(side="right")
        elif self.download_state in {"interrotto", "errore"} and self.download_dialog and self.download_dialog.winfo_exists():
            self.resume_button.configure(
                text="Riprendi download", command=self._resume_current_download
            )
            self.resume_button.pack(side="right")
        elif self._busy:
            self.start_button.configure(text="Preparazione in corso…", state="disabled")
            self.start_button.pack(side="right")
        elif self.summary_waiting_for_approval:
            self.summary_button.pack(side="right")
        elif self.job_resumable and self.current_job_path and self.current_job_path.is_file():
            label = (
                "Riprendi traduzione" if self.translation_job_path
                else "Riprendi trascrizione"
            )
            self.resume_button.configure(text=label, command=self.resume)
            self.resume_button.pack(side="right")
        elif self.ready_to_translate and self.translation_source:
            self.start_button.configure(
                text=tr("main.start_translation"),
                command=self._start_translation,
                state="normal" if self.translation_captions else "disabled",
            )
            self.start_button.pack(side="right")
        elif self.final_output_path and self.final_output_path.is_file():
            self.footer_open_button.pack(side="right")
        elif self.workflow_active:
            pass
        elif self.media:
            self.start_button.configure(
                text=tr("main.generate_transcription"), command=self.start
            )
            self.start_button.configure(
                state="normal" if self.start_button.instate(["!disabled"]) else "disabled"
            )
            self.start_button.pack(side="right")
        else:
            self.start_button.configure(text=tr("main.choose_video"), command=self.choose_video)
            self.start_button.configure(state="normal")
            self.start_button.pack(side="right")

    def _source_language_changed(self, _event: object | None = None) -> None:
        if _event is not None and (
            not self.media or self.worker or self.translation_worker
            or self.summary_worker or self._active_download() or self._busy
        ):
            return
        self._set_workflow_controls(
            not (self.worker or self.translation_worker or self.summary_worker
                 or self._active_download() or self._busy)
        )
        if not self.translation_captions:
            return
        selected = language_code(self.source_language.get()) or "auto"
        self.source_language_var.set(selected)
        self.translation_source_var.set(selected)
        if selected != "auto" and selected == self.translation_target_var.get():
            if self.translation_source and self.final_output_path:
                self._publish_readable_copy(
                    Path(self.translation_source), self.final_output_path
                )
                self._set_result(self.final_output_path)
            self.ready_to_translate = False
            self.workflow_active = False
            self._set_workflow_controls(True)
            self.status_var.set(
                "La lingua parlata coincide con quella scelta: trascrizione salvata senza traduzione."
            )
            self._set_busy(False)
            return
        self.status_var.set("Lingua parlata selezionata · preparo la traduzione.")
        self._update_translation_estimate()

    @staticmethod
    def _publish_readable_copy(source: Path, destination: Path) -> None:
        formatted = format_srt_text(source.read_text(encoding="utf-8-sig"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(formatted, encoding="utf-8")
        temporary.replace(destination)

    def _prepare_translation(self, result: dict[str, Any]) -> None:
        target = str(result.get("target_language", "original"))
        if target == "original":
            self.status_var.set(f"Sottotitoli salvati: {result['output']}")
            self._set_result(result["output"])
            self.workflow_active = False
            self.ready_to_translate = False
            self._set_workflow_controls(True)
            if self.summary_requested:
                self._prepare_summary_for_srt(
                    result["output"], str(result.get("effective_language") or ""),
                    parent_job=self.transcription_job_path,
                )
            return
        source = result.get("effective_language") or result.get("source_language", "auto")
        if source == "auto":
            source = language_code(self.source_language.get()) or "auto"
        if source == target:
            final_output = Path(
                str(result.get("final_output") or self.final_output_path or self.output_var.get())
            )
            self._publish_readable_copy(Path(result["output"]), final_output)
            self.status_var.set(f"Sottotitoli salvati: {final_output}")
            self._set_result(final_output)
            self.workflow_active = False
            self.ready_to_translate = False
            self._set_workflow_controls(True)
            if self.summary_requested:
                self._prepare_summary_for_srt(
                    final_output, str(source), parent_job=self.transcription_job_path,
                )
            return
        self.translation_source = str(result["output"])
        self.translation_captions = load_captions(self.translation_source)
        self.translation_target_var.set(target)
        self.translation_source_var.set(str(source))
        self.translation_model_var.set(
            str(result.get("target_model") or self.translation_model_var.get())
        )
        self.translation_provider_var.set(
            str(result.get("translation_provider") or PROVIDER_OPENAI)
        )
        self._provider_changed()
        self.translation_context_var.set(
            str(result.get("translation_context") or self.translation_context_var.get())
        )
        self.final_output_path = Path(
            str(result.get("final_output") or self.final_output_path or self.output_var.get())
        )
        self.ready_to_translate = True
        self.workflow_active = False
        try:
            if self.transcription_job_path and self.transcription_job_path.is_dir():
                manifest = load_job(self.transcription_job_path)
                manifest.update({
                    "workflow_stage": "ready_to_translate",
                    "transcription_output": str(Path(result["output"]).resolve()),
                    "final_output": str(self.final_output_path.resolve()),
                })
                save_job(self.transcription_job_path, manifest)
        except (OSError, ValueError, KeyError):
            # The transcript remains usable even if only the phase metadata fails.
            pass
        self.translation_estimate_var.set(
            "Trascrizione completata. Calcolo la stima della traduzione…"
        )
        self.result_summary_var.set(
            f"Trascrizione originale pronta · {Path(result['output']).name}. "
            "La traduzione non è ancora stata avviata."
        )
        self.status_var.set("Trascrizione completata · preparo la traduzione.")
        if source == "auto":
            self.source_language.configure(state="readonly")
        self._set_workflow_controls(True)
        self._update_translation_estimate()

    def open_download_dialog(self) -> None:
        if self.worker or self.translation_worker or self.summary_worker or self._active_download() or self.workflow_active or self._busy:
            messagebox.showinfo(
                "Lavoro in corso",
                "Completa o interrompi il lavoro corrente prima di scaricare un altro file.",
            )
            return
        if self.download_dialog and self.download_dialog.winfo_exists():
            self.download_dialog.start_new_download()
            self.download_dialog.deiconify()
            self.download_dialog.lift()
            return
        self.download_dialog = DownloadDialog(self.master, self)

    def open_recent_jobs(self) -> None:
        RecentJobsDialog(self.master, self)

    def open_storage_dialog(self) -> None:
        RecentJobsDialog(self.master, self, storage_only=True)

    def _set_result(self, path: str | Path, report: str | Path | None = None) -> None:
        result = Path(path)
        self.output_var.set(str(result))
        self.final_output_path = result
        self.result_report_path = Path(report) if report else None
        self.result_summary_var.set(
            f"SRT pronto · {result.name}"
            + (" · rapporto di controllo disponibile" if report else "")
        )
        def count_captions() -> None:
            try:
                count = len(load_captions(str(result)))
            except (OSError, ValueError, RevisionError):
                count = None
            self.result_count_events.put((result, count))

        threading.Thread(target=count_captions, daemon=True).start()
        self.output_path_button.configure(state="normal")
        self.job_resumable = False
        self.master.after_idle(self._update_footer_state)
        self.open_result_button.configure(
            state="normal" if result.is_file() else "disabled"
        )
        self.show_finder_button.configure(
            state="normal" if result.exists() else "disabled"
        )
        self.show_issues_button.configure(
            state="normal"
            if self.result_report_path and self.result_report_path.is_file()
            else "disabled"
        )

    def _open_result(self) -> None:
        if self.final_output_path and self.final_output_path.is_file():
            open_path(self.final_output_path)

    def _show_result(self) -> None:
        if self.final_output_path and self.final_output_path.exists():
            open_path(self.final_output_path, reveal=True)

    def _open_issues(self) -> None:
        if self.result_report_path and self.result_report_path.is_file():
            open_path(self.result_report_path)

    def _summary_option_changed(self) -> None:
        if (not self.media or self.worker or self.translation_worker
                or self.summary_worker or self._active_download() or self._busy):
            self.summary_checkbox_var.set(False)
            return
        if self.summary_checkbox_var.get():
            self.summary_estimate_var.set(
                "Dopo il salvataggio dell’SRT mostrerò costo e richiesta di conferma. "
                "Il testo dei sottotitoli sarà inviato a OpenAI; l’audio non verrà reinviato."
            )
        else:
            self.summary_estimate_var.set("")

    def _prepare_summary_for_srt(
        self, source_srt: str | Path, language: str,
        interval: tuple[float, float] | None = None,
        parent_job: str | Path | None = None,
        saved_output: str | Path | None = None,
    ) -> None:
        if not self.summary_requested:
            return
        source = Path(source_srt)
        parent = Path(parent_job) if parent_job else self.transcription_job_path
        if not source.is_file() or parent is None or not parent.is_dir():
            self.status_var.set(
                "SRT salvato; non trovo il registro del lavoro per preparare la scheda TXT."
            )
            return
        self.summary_srt_path = source
        self.summary_parent_job = parent
        self.summary_language = language
        if interval is None:
            try:
                manifest = load_job(parent)
                interval = (
                    float(manifest.get("start_at_seconds", 0)),
                    float(manifest.get("end_at_seconds", manifest.get("duration", 0))),
                )
            except (OSError, ValueError, KeyError):
                interval = (0.0, 0.0)
        self.summary_interval = interval
        self.summary_output = Path(saved_output) if saved_output else summary_output_path(source)
        try:
            parent_manifest = load_job(parent)
            parent_manifest.update({
                "summary_state": "awaiting_confirmation",
                "summary_srt": str(source.resolve()),
                "summary_output": str(self.summary_output.resolve()),
                "summary_language": language,
                "summary_interval": list(interval),
            })
            save_job(parent, parent_manifest)
        except (OSError, ValueError, KeyError) as exc:
            self.status_var.set(f"SRT salvato; non riesco a registrare la scheda: {exc}")
            return
        self.summary_estimate_revision += 1
        revision = self.summary_estimate_revision
        self.summary_estimate_var.set("Calcolo la stima della scheda…")
        self.summary_waiting_for_approval = False
        self._set_busy(True)
        threading.Thread(
            target=self._calculate_summary_estimate,
            args=(revision, source, language), daemon=True,
        ).start()

    def _calculate_summary_estimate(
        self, revision: int, source: Path, language: str,
    ) -> None:
        try:
            estimate = estimate_summary(source, language)
            self.summary_estimate_events.put((revision, estimate, None))
        except Exception as exc:  # noqa: BLE001 - l'interfaccia visualizza il problema
            self.summary_estimate_events.put((revision, None, str(exc)))

    def _apply_summary_estimate(self) -> None:
        try:
            revision, estimate, error = self.summary_estimate_events.get_nowait()
        except queue.Empty:
            return
        if revision != self.summary_estimate_revision:
            return
        self._set_busy(False)
        if error:
            self.summary_estimate_var.set(
                f"SRT conservato. Stima della scheda non disponibile: {error}"
            )
            self.summary_waiting_for_approval = False
            self.status_var.set("La scheda non è partita; correggi il problema o riprova.")
            return
        self.summary_estimate_var.set(
            f"Scheda TXT: circa ${estimate.cost_usd:.4f} USD "
            f"(ricerca web e token inclusi, stima approssimativa). "
            "Il testo SRT verrà inviato a OpenAI; l’audio non verrà reinviato. "
            "Stima, non limite massimo di spesa."
        )
        self.summary_waiting_for_approval = True
        self.status_var.set(
            "SRT pronto. Avvia la creazione del TXT solo se vuoi procedere con ricerca e sintesi."
        )
        self.master.after_idle(self._update_footer_state)

    def _start_summary(self) -> None:
        if self.summary_worker or self.worker or self.translation_worker:
            return
        if not self.summary_waiting_for_approval:
            return
        api_key = load_api_key()
        if not api_key:
            self.status_var.set("Chiave API mancante; l’SRT è stato conservato.")
            return
        if not self.summary_srt_path or not self.summary_parent_job or not self.summary_output:
            self.status_var.set("Non trovo i dati salvati della scheda; l’SRT è disponibile.")
            return
        self.summary_waiting_for_approval = False
        self.workflow_active = True
        self.cancel_requested = False
        self.current_job_path = self.summary_parent_job / "job.json"
        self.job_resumable = True
        self._set_workflow_controls(False)
        self._set_busy(True)
        self.activity_started_at = time.monotonic()
        self.phase_started_at = self.activity_started_at
        self.last_activity_event_at = self.activity_started_at
        self.status_var.set("Avvio scheda informativa…")
        self.summary_worker = SummaryWorker(
            self.summary_srt_path, self.summary_output, api_key,
            self.summary_parent_job, self.summary_language, self.summary_interval,
        )
        self.summary_worker.start()
        self.master.after_idle(self._update_footer_state)

    def _resume_summary_job(self, parent: Path, child: Path) -> None:
        manifest_path = child / "summary.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = Path(str(manifest["source_srt"]))
        if not source.is_file():
            raise ValueError("L’SRT necessario alla scheda non si trova più.")
        if manifest.get("status") == "completed":
            self._show_summary_completion({
                "output": manifest.get("output", ""),
                "source_status": manifest.get("source_status", "none"),
                "sources": manifest.get("sources", []),
                "cost": manifest.get("actual_cost"),
            })
            return
        api_key = load_api_key()
        if not api_key:
            raise ValueError("Manca la configurazione della chiave API.")
        self.summary_srt_path = source
        self.summary_output = Path(str(manifest["output"]))
        self.summary_parent_job = parent
        self.summary_language = str(manifest.get("language", ""))
        self.summary_interval = tuple(manifest.get("interval", [0.0, 0.0]))  # type: ignore[assignment]
        self.summary_worker = SummaryWorker(
            source, self.summary_output, api_key, parent,
            self.summary_language, self.summary_interval,
        )
        self.summary_waiting_for_approval = False
        self.workflow_active = True
        self.current_job_path = parent / "job.json"
        self.job_resumable = True
        self._set_workflow_controls(False)
        self.activity_started_at = time.monotonic()
        self._set_busy(True)
        self.summary_worker.start()

    def _show_summary_completion(self, result: dict[str, Any]) -> None:
        output = Path(str(result.get("output", "")))
        cost = result.get("cost") or {}
        cost_text = (
            f"${float(cost.get('cost_usd', 0)):.4f} USD"
            + (" · consumo incompleto" if not cost.get("complete", False) else "")
        )
        if result.get("source_status") == "verified":
            source_text = f"{len(result.get('sources', []))} fonti web riportate"
        else:
            source_text = "nessuna fonte web verificabile"
        self.summary_output = output
        self.summary_result_var.set(f"Scheda pronta · {source_text} · costo {cost_text}.")
        self.open_summary_button.configure(
            state="normal" if output.is_file() else "disabled"
        )
        self.summary_waiting_for_approval = False
        self.job_resumable = False
        self.workflow_active = False
        self.status_var.set("Scheda informativa completata.")
        self.master.after_idle(self._update_footer_state)

    def _open_summary(self) -> None:
        if self.summary_output and self.summary_output.is_file():
            open_path(self.summary_output)

    def _update_translation_estimate(self, _event: object | None = None) -> None:
        if self.translation_worker:
            return
        if not self.translation_captions:
            if self.worker is None:
                self._set_busy(False)
            return
        source = self.translation_source_var.get()
        if source not in LANGUAGE_NAMES:
            self.translation_estimate_var.set(
                "Seleziona la lingua parlata in alto per continuare la traduzione."
            )
            self.status_var.set(
                "Lingua parlata non rilevata: selezionala nel menu in alto per proseguire."
            )
            if self.worker is None:
                self._set_busy(False)
            return
        target = self.translation_target_var.get()
        if source == target:
            self.translation_estimate_var.set(
                "La lingua parlata coincide con quella richiesta: uso la trascrizione."
            )
            if self.worker is None:
                self._set_busy(False)
            return
        self.translation_estimate_revision += 1
        revision = self.translation_estimate_revision
        if self.translation_estimate_after:
            self.master.after_cancel(self.translation_estimate_after)
        captions = list(self.translation_captions)
        model = self.translation_model_var.get()
        context = self.translation_context_var.get()
        self.translation_estimate_var.set("Aggiorno la stima…")
        self._set_busy(True)
        self.translation_estimate_after = self.master.after(
            300, lambda: threading.Thread(
                target=self._calculate_translation_estimate,
                args=(revision, captions, model, source, target, context),
                daemon=True,
            ).start()
        )

    def _calculate_translation_estimate(
        self, revision: int, captions: list[Any], model: str,
        source: str, target: str, context: str,
    ) -> None:
        try:
            estimate = estimate_revision(
                captions, mode=REVISION_MODE_LINGUISTIC,
                operation=OPERATION_TRANSLATION, model=model,
                source_language=source, target_language=target,
                user_context=context,
            )
            self.translation_estimate_events.put((revision, estimate, None))
        except Exception as exc:  # noqa: BLE001 - visualizza il problema senza bloccare Tk
            self.translation_estimate_events.put((revision, None, str(exc)))

    def _apply_translation_estimate(self) -> None:
        try:
            revision, estimate, error = self.translation_estimate_events.get_nowait()
        except queue.Empty:
            return
        if revision != self.translation_estimate_revision:
            return
        if error:
            self.translation_estimate_var.set(f"Stima non disponibile: {error}")
            if self.worker is None and self.translation_worker is None:
                self._set_busy(False)
            self.status_var.set(
                "Stima non disponibile. Puoi comunque avviare la traduzione esplicitamente."
            )
            self.master.after_idle(self._update_footer_state)
            return
        qualifier = " (approssimativa)" if estimate.approximate else ""
        self.translation_estimate_var.set(
            f"Traduzione: {estimate.group_count} gruppi · circa "
            + "$" + f"{estimate.cost_usd:.4f} USD{qualifier}. "
            "Stima, non limite massimo di spesa."
        )
        self.progress.configure(maximum=max(1, estimate.group_count), value=0)
        if self.worker is None and self.translation_worker is None:
            self._set_busy(False)
        self.status_var.set(
            "Trascrizione pronta. Premi Avvia traduzione per creare l’SRT finale."
        )
        self.master.after_idle(self._update_footer_state)

    def _start_translation(self) -> None:
        if not self.ready_to_translate or not self.translation_source or self.translation_worker:
            return
        source_code = self.translation_source_var.get()
        if source_code not in LANGUAGE_NAMES:
            return
        provider = self.translation_provider_var.get() or PROVIDER_OPENAI
        api_key = load_provider_api_key(provider)
        if not api_key:
            messagebox.showerror(
                "Chiave API mancante",
                f"Configura la chiave API per {provider} nelle Impostazioni.",
            )
            return
        source = Path(self.translation_source)
        target = self.translation_target_var.get()
        output = self.final_output_path or Path(self.output_var.get())
        if output.resolve() == source.resolve():
            messagebox.showerror(
                "Destinazione non valida", "Il file originale non può essere sovrascritto."
            )
            return
        self.translation_worker = RevisionWorker(
            str(source), str(output), api_key, mode=REVISION_MODE_LINGUISTIC,
            operation=OPERATION_TRANSLATION,
            source_language=source_code,
            target_language=target, model=self.translation_model_var.get(),
            user_context=self.translation_context_var.get(),
            parent_job=str(self.transcription_job_path) if self.transcription_job_path else None,
            provider=provider,
        )
        self.translation_worker.start()
        self.ready_to_translate = False
        self.workflow_active = True
        if self.transcription_job_path and self.transcription_job_path.is_dir():
            try:
                manifest = load_job(self.transcription_job_path)
                manifest["workflow_stage"] = "translation"
                save_job(self.transcription_job_path, manifest)
            except (OSError, ValueError, KeyError):
                pass
        self.cancel_requested = False
        self.cancel_button.configure(text="Interrompi")
        self.activity_started_at = time.monotonic()
        self._set_busy(True)
        self.start_button.configure(state="disabled")
        self.translation_model_combo.configure(state="disabled")
        self.translation_context_entry.configure(state="disabled")
        self.status_var.set("Traduzione in corso…")
        self._set_workflow_controls(False)
        self.cancel_button.configure(state="normal")

    def _cancel_translation(self) -> None:
        if self.translation_worker:
            self.translation_worker.cancel()
            self.cancel_button.configure(state="disabled")

    def _finish_translation(self) -> None:
        self.translation_worker = None
        self.ready_to_translate = False
        self.cancel_requested = False
        self.cancel_button.configure(text="Interrompi")
        self.workflow_active = False
        self._set_busy(False)
        if self.current_job_path and self.current_job_path.is_file():
            try:
                self.job_resumable = json.loads(
                    self.current_job_path.read_text(encoding="utf-8")
                ).get("status") != "completed"
            except (OSError, ValueError):
                self.job_resumable = True
        self._set_workflow_controls(True)
        self.cancel_button.configure(state="disabled")
        self.translation_model_combo.configure(state="readonly")
        self.translation_context_entry.configure(state="normal")
        self._enable_start()
        if self.worker is None:
            self.activity_started_at = None
            self.activity_var.set("")
        if self._close_after_cancel and not self.worker:
            self.master.destroy()

    def choose_video(self) -> None:
        if self.worker or self.translation_worker or self._active_download() or self.workflow_active or self._busy:
            messagebox.showinfo(
                "Lavoro in corso", "Interrompi o completa il lavoro prima di cambiare video."
            )
            return
        selected = filedialog.askopenfilename(
            title="Scegli un video", filetypes=[("Video", "*.mp4 *.mov *.mkv")]
        )
        if not selected:
            return
        self.download_state = "inattivo"
        self.master.minsize(760, 630)
        self.translation_source = None
        self.translation_captions = []
        self.ready_to_translate = False
        self.final_output_path = None
        self.result_report_path = None
        self.current_job_path = None
        self.transcription_job_path = None
        self.translation_job_path = None
        self.workflow_active = False
        self._set_workflow_controls(True)
        self.translation_estimate_var.set("")
        self.open_result_button.configure(state="disabled")
        self.show_finder_button.configure(state="disabled")
        self.show_issues_button.configure(state="disabled")
        self.video_var.set(selected)
        self.media = None
        self.track.configure(state="disabled", values=())
        self.start_button.configure(state="disabled")
        self.status_var.set("Leggo le informazioni del video…")
        self._set_workflow_controls(False)
        self._set_busy(True)
        threading.Thread(target=self._probe, args=(selected,), daemon=True).start()

    def _set_busy(self, running: bool) -> None:
        if running == self._busy:
            return
        self._busy = running
        if running:
            self.busy_progress.start(12)
        else:
            self.busy_progress.stop()
        self.master.after_idle(self._update_footer_state)

    def _probe(self, selected: str) -> None:
        try:
            self.probe_events.put(("media", probe_media(selected)))
        except Exception as exc:  # noqa: BLE001 - inoltra l'errore al thread UI
            self.probe_events.put(("probe_error", str(exc)))

    def choose_output(self) -> None:
        if (not self.media or self.worker or self.translation_worker
                or self.summary_worker or self._active_download()
                or self.workflow_active or self._busy):
            return
        initial = (
            Path(self.video_var.get()).with_suffix(".srt").name
            if self.video_var.get()
            else "sottotitoli.srt"
        )
        selected = filedialog.asksaveasfilename(
            title="Salva sottotitoli",
            defaultextension=".srt",
            initialfile=initial,
            filetypes=[("Sottotitoli SRT", "*.srt")],
        )
        if selected:
            self.output_var.set(selected)
            self.output_path_button.configure(state="normal")
            self._enable_start()

    def _receive_media(self, media: MediaInfo) -> None:
        self._set_busy(False)
        self.media = media
        self._set_workflow_controls(True)
        labels = [track.label for track in media.audio_tracks]
        self.track.configure(
            values=labels, state="readonly" if labels else "disabled"
        )

        # Seleziona la prima traccia disponibile, ma NON usa i metadata ENG/JPN/ITA
        # per decidere la lingua parlata: possono essere errati.
        if media.audio_tracks:
            self.track.current(0)
        self.source_language_var.set("auto")
        self.source_language.set(language_label("auto"))

        default_output = Path(media.path).with_suffix(".srt")
        self.output_var.set(str(default_output))
        self._reset_range()
        self._update_cost()
        self.status_var.set("Pronto. Controlla la traccia audio e avvia quando vuoi.")
        self._enable_start()

    def _on_time_field_changed(self, *_args: object) -> None:
        if self._syncing_range:
            return
        if self.media:
            try:
                start_seconds, end_seconds = parse_time_range(
                    self.start_time_var.get(),
                    self.end_time_var.get(),
                    self.media.duration,
                )
            except StartTimeError:
                pass
            else:
                self.range_scale.set_range(
                    self.media.duration, start_seconds, end_seconds
                )
        self._update_cost()

    def _range_changed(self, start_seconds: float, end_seconds: float) -> None:
        self._syncing_range = True
        try:
            self.start_time_var.set(format_time_value(start_seconds))
            self.end_time_var.set(format_time_value(end_seconds))
        finally:
            self._syncing_range = False
        self._update_cost()

    def _reset_range(self) -> None:
        if not self.media:
            return
        self.range_scale.set_range(self.media.duration, 0.0, self.media.duration)
        self._range_changed(0.0, self.media.duration)

    def _read_interval(self) -> tuple[float, float]:
        if not self.media:
            raise StartTimeError("Seleziona prima un video.")
        return parse_time_range(
            self.start_time_var.get(),
            self.end_time_var.get(),
            self.media.duration,
        )

    def _update_cost(self) -> None:
        if not self.media:
            self.cost_var.set("Seleziona un video per vedere la stima.")
            self._refresh_work_summary()
            return
        try:
            start_seconds, end_seconds = self._read_interval()
        except StartTimeError as exc:
            self.cost_var.set(f"Intervallo non valido: {exc}")
            self.start_button.configure(state="disabled")
            return

        selected_seconds = end_seconds - start_seconds
        self.cost_var.set(
            f"Durata da elaborare: {selected_seconds / 60:.1f} minuti · "
            f"stima trascrizione: ${estimate_cost_usd(selected_seconds):.2f} USD"
            + (
                " · traduzione stimata dopo la trascrizione"
                if self.target_language.get() != "Originale" else ""
            )
        )
        self._enable_start()
        self._refresh_work_summary()

    def _enable_start(self) -> None:
        valid_interval = False
        if self.media:
            try:
                self._read_interval()
            except StartTimeError:
                pass
            else:
                valid_interval = True
        state = (
            "normal"
            if (
                valid_interval and self.output_var.get()
                and self.track.current() >= 0 and not self._busy
                and self.worker is None and self.translation_worker is None and self.summary_worker is None
                and not self._active_download()
                and not self.workflow_active
            )
            else "disabled"
        )
        self.start_button.configure(state=state)
        self.master.after_idle(self._update_footer_state)

    def start(self) -> None:
        if not self.media or self.worker or self.translation_worker or self.summary_worker or self._active_download() or self.workflow_active:
            return
        try:
            start_seconds, end_seconds = self._read_interval()
        except StartTimeError as exc:
            messagebox.showerror("Intervallo non valido", str(exc))
            return
        api_key = load_api_key()
        if not api_key:
            messagebox.showerror(
                "Chiave API mancante",
                "Manca la configurazione della chiave API. Riapri l'app dal progetto configurato.",
            )
            return
        output = Path(self.output_var.get())
        if output.exists() and not messagebox.askyesno(
            "File già presente", "Il file SRT esiste già. Vuoi sostituirlo al termine?"
        ):
            return
        track_index = self.track.current()
        if track_index < 0:
            messagebox.showerror("Traccia audio", "Scegli una traccia audio.")
            return
        track = self.media.audio_tracks[track_index]
        source_language = language_code(self.source_language.get()) or "auto"
        target_language = language_code(self.target_language.get()) or "original"
        self.source_language_var.set(source_language)
        self.target_language_var.set(target_language)
        self.translation_target_var.set(target_language)
        self.summary_requested = bool(self.summary_checkbox_var.get())
        self.summary_waiting_for_approval = False
        self.summary_estimate_var.set("")
        self.summary_result_var.set("")
        self.open_summary_button.configure(state="disabled")
        self.translation_model_var.set(self.translation_model_combo.get() or MODEL_SOL)
        self.translation_provider_var.set(self.translation_provider_combo.get() or PROVIDER_OPENAI)
        self.final_output_path = output
        self.translation_captions = []
        self.translation_source = None
        self.translation_estimate_var.set(
            "La traduzione sarà stimata dopo la trascrizione."
            if target_language != "original"
            else "Verrà salvata la trascrizione nella lingua parlata."
        )
        transcription_output = output
        if target_language != "original":
            transcription_output = output.with_name(f"{output.stem}.original.srt")
            suffix = 2
            while transcription_output.exists():
                transcription_output = output.with_name(
                    f"{output.stem}.original-{suffix}.srt"
                )
                suffix += 1
        self.transcription_job_path = None
        self.current_job_path = None
        self.job_resumable = False
        self.ready_to_translate = False
        self.workflow_active = True
        self._set_workflow_controls(False)
        self.worker = SubtitleWorker(
            self.media.path,
            self.media.duration,
            track.stream_index,
            str(transcription_output),
            api_key,
            start_seconds,
            end_seconds,
            source_language,
            target_language,
            self.translation_model_var.get(),
            self.translation_context_var.get(),
            str(output),
            create_summary=self.summary_requested,
            translation_provider=self.translation_provider_var.get(),
        )
        self.worker.start()
        self.cancel_requested = False
        self.cancel_button.configure(text="Interrompi")
        self.activity_started_at = time.monotonic()
        self._set_busy(True)
        self.progress.configure(maximum=1, value=0)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set("Preparo il lavoro…")
        self.phase_label = "Preparazione"
        self.phase_started_at = time.monotonic()
        self.last_activity_event_at = self.phase_started_at
        self._set_workflow_controls(False)

    def configure_key(self) -> None:
        self.configure_provider_key(PROVIDER_OPENAI)

    def configure_provider_key(self, provider: str) -> None:
        key = simpledialog.askstring(
            "Configura chiave API",
            f"Incolla la chiave API {provider}. Verrà salvata nel {secret_store_label(get_locale())}.",
            show="*",
        )
        if key is None:
            return
        if not key.strip():
            messagebox.showerror(
                "Chiave non valida", "Inserisci una chiave API non vuota."
            )
            return
        try:
            save_provider_api_key(key.strip(), provider)
        except RuntimeError as exc:
            messagebox.showerror("Chiave non salvata", str(exc))
            return
        self.status_var.set(
            f"Chiave {provider} salvata nel {secret_store_label(get_locale())}."
        )

    def cancel(self) -> None:
        download = self._active_download()
        if not self.worker and not self.translation_worker and not self.summary_worker and not download:
            return
        self.cancel_requested = True
        if download and self.download_dialog:
            self.download_dialog.cancel()
            self.status_var.set("Interruzione richiesta; salvo lo stato del download…")
            self.cancel_button.configure(state="disabled")
        if self.worker:
            self.worker.cancel()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("Interruzione richiesta; salvo il blocco corrente…")
        if self.translation_worker:
            self.translation_worker.cancel()
            self.cancel_button.configure(state="disabled")
            self.status_var.set(
                "Interruzione richiesta; la risposta API corrente potrebbe essere addebitata."
            )
        if self.summary_worker:
            self.summary_worker.cancel()
            self.cancel_button.configure(state="disabled")
            self.status_var.set(
                "Interruzione richiesta; la richiesta corrente potrebbe essere addebitata."
            )
        self.master.after_idle(self._update_footer_state)

    def resume(self) -> None:
        if self.worker or self.translation_worker or self.summary_worker or self._active_download():
            self.status_var.set("Il lavoro è già in corso.")
            return
        if self.current_job_path and self.current_job_path.is_file():
            self._resume_selected_job(self.current_job_path)
        else:
            self.open_recent_jobs()

    def _resume_selected_job(self, selected_path: Path) -> None:
        if self.worker or self.translation_worker or getattr(self, "summary_worker", None):
            self.status_var.set("Attendi o interrompi il lavoro già in corso.")
            return
        if selected_path.name == "download.json":
            try:
                if not self.download_dialog or not self.download_dialog.winfo_exists():
                    self.download_dialog = DownloadDialog(self.master, self)
                else:
                    self.download_dialog.deiconify()
                    self.download_dialog.lift()
                    if self.download_dialog.worker:
                        self.download_dialog.status_var.set("Un download è già in corso.")
                        return
                self.download_dialog.load_download(selected_path)
                if self.download_dialog.resume_job == selected_path.parent:
                    self.download_dialog.resume_current()
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("Download non utilizzabile", str(exc))
            return
        job_dir = selected_path.parent
        self.job_resumable = True
        if selected_path.name == "revision.json":
            try:
                manifest, _estimate = load_revision_for_resume(job_dir)
                if manifest.get("status") == "completed":
                    report = manifest.get("issue_report")
                    self._set_result(
                        manifest.get("output", ""), report
                    )
                    self.status_var.set(
                        f"Questo lavoro è già completato: {manifest.get('output', '')}"
                    )
                    return
                api_key = load_api_key()
                if not api_key:
                    raise ValueError("Manca la configurazione della chiave API.")
                self._resume_revision_job(job_dir, manifest, api_key)
            except (OSError, ValueError, KeyError, RevisionError) as exc:
                messagebox.showerror("Lavoro non utilizzabile", str(exc))
            return
        if selected_path.name != "job.json":
            messagebox.showerror(
                "Lavoro non utilizzabile",
                "Seleziona il file job.json oppure revision.json di un lavoro salvato.",
            )
            return
        try:
            manifest = load_job(job_dir)
            self.current_job_path = selected_path
            self.transcription_job_path = job_dir
            self.summary_requested = bool(manifest.get("create_summary", False))
            if hasattr(self, "summary_checkbox_var"):
                self.summary_checkbox_var.set(self.summary_requested)
            summary_child = Path(str(manifest.get("summary_job", ""))) if manifest.get("summary_job") else None
            if self.summary_requested and manifest.get("summary_state") in {"error", "cancelled", "response_received", "running"} and summary_child:
                self._resume_summary_job(job_dir, summary_child)
                return
            if self.summary_requested and manifest.get("summary_state") == "awaiting_confirmation" and manifest.get("summary_srt"):
                self._prepare_summary_for_srt(
                    str(manifest["summary_srt"]),
                    str(manifest.get("summary_language", "")),
                    tuple(manifest.get("summary_interval", [0.0, 0.0])),
                    job_dir,
                    manifest.get("summary_output"),
                )
                return
            if self.summary_requested and manifest.get("summary_state") == "completed" and manifest.get("summary_job"):
                summary_manifest_path = Path(str(manifest["summary_job"])) / "summary.json"
                if summary_manifest_path.is_file():
                    summary_manifest = json.loads(summary_manifest_path.read_text(encoding="utf-8"))
                    self._show_summary_completion(SummaryWorker._completion(summary_manifest))
            self.video_var.set(str(manifest.get("video", "")))
            saved_source = str(manifest.get("source_language", "auto"))
            if hasattr(self, "source_language_var"):
                self.source_language_var.set(saved_source)
            if hasattr(self, "source_language"):
                self.source_language.set(language_label(saved_source))
            target = str(manifest.get("target_language", "original"))
            self.translation_target_var.set(target)
            self.target_language.set(language_label(target))
            self.translation_model_var.set(
                str(manifest.get("target_model", MODEL_SOL))
            )
            self.translation_model_combo.set(self.translation_model_var.get())
            self.translation_context_var.set(
                str(manifest.get("translation_context", ""))
            )
            self.final_output_path = Path(str(manifest.get(
                "final_output", manifest["output"]
            )))
            self.output_var.set(str(self.final_output_path))
            if manifest.get("status") == "completed":
                if target == "original":
                    self.status_var.set(f"Trascrizione completata: {manifest['output']}")
                    self._set_result(manifest["output"])
                    return
                transcript = Path(str(manifest["output"]))
                if not transcript.is_file():
                    raise ValueError("L'SRT originale non si trova più nel percorso salvato.")
                translation_job = manifest.get("translation_job")
                if translation_job:
                    revision_path = Path(str(translation_job)) / "revision.json"
                    if revision_path.is_file():
                        revision_manifest, _estimate = load_revision_for_resume(
                            revision_path.parent
                        )
                        if revision_manifest.get("status") == "completed":
                            self.result_report_path = (
                                Path(revision_manifest["issue_report"])
                                if revision_manifest.get("issue_report") else None
                            )
                            self._set_result(
                                revision_manifest.get("output", self.final_output_path),
                                self.result_report_path,
                            )
                            self.status_var.set(
                                f"{revision_manifest.get('completion_status', 'completed')}: "
                                f"{revision_manifest.get('output', self.final_output_path)}"
                            )
                            return
                        provider = str(revision_manifest.get("provider", PROVIDER_OPENAI))
                        api_key = load_provider_api_key(provider)
                        if not api_key:
                            raise ValueError(f"Manca la chiave API {provider}.")
                        self._resume_revision_job(
                            revision_path.parent, revision_manifest, api_key
                        )
                        return
                detected = manifest.get("detected_languages") or []
                source = str(manifest.get("source_language", "auto"))
                if source == "auto":
                    source = str(detected[0]) if len(detected) == 1 else ""
                translation_result = {
                    "output": str(transcript),
                    "target_language": target,
                    "effective_language": source,
                    "target_model": manifest.get("target_model"),
                    "translation_context": manifest.get("translation_context", ""),
                    "final_output": str(self.final_output_path),
                }
                if manifest.get("translation_provider", PROVIDER_OPENAI) != PROVIDER_OPENAI:
                    translation_result["translation_provider"] = manifest["translation_provider"]
                self._prepare_translation(translation_result)
                return
            api_key = load_api_key()
            if not api_key:
                raise ValueError("Manca la configurazione della chiave API.")
            if not Path(manifest["video"]).is_file():
                raise ValueError(
                    "Il video originale non si trova più nel percorso salvato."
                )
            if fingerprint(manifest["video"]) != manifest["fingerprint"]:
                raise ValueError(
                    "Il video originale è cambiato. Avvia un nuovo lavoro per evitare tempi errati."
                )
            self.worker = SubtitleWorker(
                manifest["video"],
                float(manifest["duration"]),
                int(manifest["stream_index"]),
                manifest["output"],
                api_key,
                float(manifest.get("start_at_seconds", 0.0)),
                float(manifest.get("end_at_seconds", manifest["duration"])),
                str(manifest.get("source_language", "auto")),
                str(manifest.get("target_language", "original")),
                str(manifest.get("target_model", MODEL_SOL)),
                str(manifest.get("translation_context", "")),
                str(manifest.get("final_output", manifest["output"])),
                translation_provider=str(manifest.get("translation_provider", PROVIDER_OPENAI)),
            )
            self.worker.job_dir = job_dir
            self.worker.resume(job_dir)
        except (OSError, ValueError, KeyError) as exc:
            self.worker = None
            messagebox.showerror("Lavoro non utilizzabile", str(exc))
            return
        self.progress.configure(
            maximum=len(manifest["chunks"]),
            value=sum(
                chunk.get("status") == "completed" for chunk in manifest["chunks"]
            ),
        )
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.activity_started_at = time.monotonic()
        self._set_busy(True)
        self.status_var.set("Riprendo il lavoro salvato…")

    def _resume_revision_job(
        self, job_dir: Path, manifest: dict[str, Any], api_key: str
    ) -> None:
        self.current_job_path = job_dir / "revision.json"
        self.translation_job_path = job_dir
        if manifest.get("parent_job"):
            self.transcription_job_path = Path(str(manifest["parent_job"]))
        self.translation_source = str(manifest["source"])
        self.final_output_path = Path(str(manifest["output"]))
        self.output_var.set(str(self.final_output_path))
        self.translation_target_var.set(str(manifest.get("target_language", "it")))
        self.translation_source_var.set(str(manifest.get("source_language", "")))
        self.translation_model_var.set(str(manifest.get("model", MODEL_SOL)))
        self.translation_provider_var.set(
            str(manifest.get("provider", PROVIDER_OPENAI))
        )
        self._provider_changed()
        self.translation_model_combo.set(self.translation_model_var.get())
        self.translation_context_var.set(str(manifest.get("user_context", "")))
        provider = str(manifest.get("provider", PROVIDER_OPENAI))
        api_key = load_provider_api_key(provider)
        if not api_key:
            messagebox.showerror(
                "Chiave API mancante",
                f"Configura la chiave API per {provider} nelle Impostazioni.",
            )
            return
        self.translation_worker = RevisionWorker(
            str(manifest["source"]), str(manifest["output"]), api_key,
            mode=str(manifest.get("revision_mode", REVISION_MODE_LINGUISTIC)),
            operation=str(manifest.get("operation", OPERATION_TRANSLATION)),
            source_language=str(manifest.get("source_language", "ja")),
            target_language=str(manifest.get("target_language", "it")),
            model=str(manifest.get("model", MODEL_SOL)),
            user_context=str(manifest.get("user_context", "")),
            parent_job=manifest.get("parent_job"),
            provider=provider,
        )
        self.translation_worker.resume(job_dir)
        self.activity_started_at = time.monotonic()
        self._set_busy(True)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set("Riprendo il lavoro salvato…")

    def _poll(self) -> None:
        self._apply_translation_estimate()
        self._apply_summary_estimate()
        try:
            while True:
                result, count = self.result_count_events.get_nowait()
                if result == self.final_output_path and count is not None:
                    status = self.result_summary_var.get().split(" · Sottotitoli:")[0]
                    self.result_summary_var.set(f"{status} · Sottotitoli: {count}")
        except queue.Empty:
            pass
        try:
            for _ in range(100):
                kind, value = self.probe_events.get_nowait()
                self.last_activity_event_at = time.monotonic()
                if kind == "media":
                    self._receive_media(value)  # type: ignore[arg-type]
                else:
                    self._set_busy(False)
                    self._set_workflow_controls(True)
                    self.status_var.set(
                        f"Non riesco a leggere il video: {value}. Scegli un altro file e riprova."
                    )
        except queue.Empty:
            pass
        active_worker = self.worker
        if active_worker:
            try:
                for _ in range(100):
                    kind, value = active_worker.events.get_nowait()
                    self.last_activity_event_at = time.monotonic()
                    if kind == "status":
                        self.phase_label = str(value)
                        self.phase_started_at = time.monotonic()
                        self.status_var.set(str(value))
                        self._set_busy(True)
                    elif kind == "job_dir":
                        self.transcription_job_path = Path(str(value))
                        self.current_job_path = self.transcription_job_path / "job.json"
                        self.job_resumable = True
                    elif kind == "log_path":
                        self.log_panel.set_log(str(value))
                    elif kind == "log":
                        self.log_panel.add_line(str(value["line"]))
                    elif kind == "progress":
                        current, total = value
                        self._set_busy(True)
                        self.progress.configure(maximum=total, value=current)
                    elif kind == "complete":
                        self.job_resumable = False
                        result = value if isinstance(value, dict) else {
                            "output": str(value), "source_language": "auto",
                            "target_language": "original",
                        }
                        if result.get("job_dir"):
                            self.transcription_job_path = Path(result["job_dir"])
                            self.current_job_path = self.transcription_job_path / "job.json"
                        self._finish_worker()
                        if result.get("target_language") not in {None, "original"}:
                            try:
                                self.final_output_path = Path(str(
                                    result.get("final_output") or self.output_var.get()
                                ))
                                self._prepare_translation(result)
                            except (OSError, ValueError, RevisionError) as exc:
                                self.status_var.set(
                                    f"Trascrizione salvata; preparazione traduzione non riuscita: {exc}"
                                )
                                self.workflow_active = False
                                self._set_workflow_controls(True)
                        else:
                            self.ready_to_translate = False
                            self.workflow_active = False
                            self.status_var.set(
                                f"Completato: {result['output']}"
                            )
                            self._set_result(result["output"])
                            if self.summary_requested:
                                self._prepare_summary_for_srt(
                                    result["output"],
                                    str(result.get("effective_language") or ""),
                                    parent_job=self.transcription_job_path,
                                )
                    elif kind == "cancelled":
                        self.job_resumable = True
                        self.status_var.set("Interrotto. Premi Riprendi per continuare questo lavoro.")
                        self.workflow_active = False
                        self._finish_worker()
                    elif kind == "error":
                        self.job_resumable = bool(self.current_job_path)
                        self.workflow_active = False
                        self.ready_to_translate = False
                        self.status_var.set(
                            "Trascrizione non completata. I blocchi già elaborati sono "
                            "conservati. Puoi riprendere; apri i dettagli per la causa."
                        )
                        self._finish_worker()
            except queue.Empty:
                pass
        active_translation_worker = self.translation_worker
        if active_translation_worker:
            try:
                for _ in range(100):
                    kind, value = active_translation_worker.events.get_nowait()
                    self.last_activity_event_at = time.monotonic()
                    if kind == "status":
                        self.phase_label = str(value)
                        self.phase_started_at = time.monotonic()
                        self.status_var.set(str(value))
                        self._set_busy(True)
                    elif kind == "job_dir":
                        self.translation_job_path = Path(str(value))
                        self.current_job_path = self.translation_job_path / "revision.json"
                        self.job_resumable = True
                        if self.transcription_job_path:
                            try:
                                manifest = load_job(self.transcription_job_path)
                                manifest["translation_job"] = str(self.translation_job_path)
                                manifest["workflow_stage"] = "translation"
                                save_job(self.transcription_job_path, manifest)
                            except (OSError, ValueError, KeyError):
                                pass
                    elif kind == "log_path":
                        self.log_panel.set_log(str(value))
                    elif kind == "log":
                        self.log_panel.add_line(str(value["line"]))
                    elif kind == "progress":
                        current, total = value
                        self.progress.configure(maximum=total, value=current)
                    elif kind == "cost":
                        suffix = "" if value["complete"] else " (dati incompleti)"
                        prefix = self.translation_estimate_var.get().split(
                            "\nCosto effettivo:"
                        )[0]
                        self.translation_estimate_var.set(
                            prefix + "\nCosto effettivo: $"
                            + f"{value['cost_usd']:.4f} USD{suffix}"
                        )
                    elif kind == "complete":
                        self.job_resumable = False
                        counts = value["counts"]
                        completion = value.get("completion_status", "completed")
                        label = {
                            "completed_with_untranslated":
                                "Completato con parti non tradotte",
                            "completed_with_warnings": "Completato con avvisi",
                        }.get(completion, "Completato")
                        self.status_var.set(
                            f"{label}: {value['output']} · "
                            f"{counts['modified']} modificati, "
                            f"{counts['unchanged']} invariati, "
                            f"{counts['rejected']} non tradotti, "
                            f"{len(value.get('content_warnings', []))} avvisi sul contenuto."
                        )
                        self._set_result(value["output"], value.get("issue_report"))
                        self.result_summary_var.set(
                            f"{label} · {counts['rejected']} parti non tradotte · "
                            f"{len(value.get('content_warnings', []))} avvisi sul contenuto."
                        )
                        self._finish_translation()
                        if self.transcription_job_path and self.transcription_job_path.is_dir():
                            try:
                                manifest = load_job(self.transcription_job_path)
                                manifest["workflow_stage"] = "completed"
                                manifest["final_output"] = str(Path(value["output"]).resolve())
                                cost = value.get("cost") or {}
                                manifest["translation_cost_usd"] = (
                                    cost.get("cost_usd") if isinstance(cost, dict) else None
                                )
                                save_job(self.transcription_job_path, manifest)
                            except (OSError, ValueError, KeyError):
                                pass
                        if self.summary_requested:
                            self._prepare_summary_for_srt(
                                value["output"], self.translation_target_var.get(),
                                parent_job=self.transcription_job_path,
                            )
                    elif kind == "cancelled":
                        self.job_resumable = True
                        self.status_var.set(
                            "Traduzione interrotta. Premi Riprendi per continuare questo lavoro."
                        )
                        self._finish_translation()
                    elif kind == "error":
                        self.job_resumable = bool(self.current_job_path)
                        self.status_var.set(
                            "Traduzione non completata. La trascrizione originale e i "
                            "gruppi riusciti sono conservati. Puoi riprendere; apri i "
                            "dettagli per la causa."
                        )
                        self._finish_translation()
            except queue.Empty:
                pass
        active_summary_worker = self.summary_worker
        if active_summary_worker:
            try:
                for _ in range(100):
                    kind, value = active_summary_worker.events.get_nowait()
                    self.last_activity_event_at = time.monotonic()
                    if kind == "status":
                        self.phase_label = "Scheda informativa"
                        self.status_var.set(str(value))
                        self._set_busy(True)
                    elif kind == "job_dir":
                        self.log_panel.set_log(str(Path(value) / "events.log"))
                    elif kind == "log":
                        self.log_panel.add_line(str(value["line"]))
                    elif kind == "cost":
                        self.summary_estimate_var.set(
                            f"Costo effettivo scheda: ${value['cost_usd']:.4f} USD"
                            + (" · consumo incompleto" if not value.get("complete") else "")
                        )
                    elif kind == "complete":
                        self.summary_worker = None
                        self._set_busy(False)
                        self._show_summary_completion(value)
                        self.workflow_active = False
                        self._set_workflow_controls(True)
                        self.activity_started_at = None
                        self.activity_var.set("")
                    elif kind == "cancelled":
                        self.summary_worker = None
                        self.workflow_active = False
                        self.job_resumable = True
                        self._set_busy(False)
                        self.status_var.set(
                            "Scheda interrotta; l’SRT è conservato. Premi Riprendi per continuare."
                        )
                        self._set_workflow_controls(True)
                    elif kind == "error":
                        self.summary_worker = None
                        self.workflow_active = False
                        self.job_resumable = True
                        self._set_busy(False)
                        self.status_var.set(
                            f"Scheda non completata: {value}. L’SRT è conservato; puoi riprendere."
                        )
                        self._set_workflow_controls(True)
            except queue.Empty:
                pass
        if self._close_after_cancel and not self.worker and not self.translation_worker and not self.summary_worker:
            return
        if self.master.winfo_exists():
            self.master.after(100, self._poll)

        self._refresh_activity_clock()

    def _refresh_activity_clock(self) -> None:
        if self.activity_started_at is None or self._active_download():
            return
        now = time.monotonic()
        elapsed = int(now - self.activity_started_at)
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        phase_elapsed = int(now - (self.phase_started_at or self.activity_started_at))
        phase_minutes, phase_seconds = divmod(phase_elapsed, 60)
        phase_hours, phase_minutes = divmod(phase_minutes, 60)
        idle = bool(self.last_activity_event_at and now - self.last_activity_event_at >= 60)
        idle_message = " · È ancora in corso, anche se non ci sono nuovi aggiornamenti." if idle else ""
        self.activity_var.set(
            f"Tempo totale {hours:02}:{minutes:02}:{seconds:02} · "
            f"Fase {phase_hours:02}:{phase_minutes:02}:{phase_seconds:02}{idle_message}"
        )

    def _finish_worker(self) -> None:
        self.worker = None
        self.cancel_requested = False
        self.cancel_button.configure(text="Interrompi")
        self._set_busy(False)
        self.cancel_button.configure(state="disabled")
        if not self.workflow_active and self.translation_worker is None:
            self._set_workflow_controls(True)
        self._enable_start()
        if self.translation_worker is None:
            self.activity_started_at = None
            self.activity_var.set("")
        if self._close_after_cancel and not self.translation_worker:
            self.master.destroy()

    def format_existing_srt(self) -> None:
        if not self._tools_available():
            return
        source = filedialog.askopenfilename(
            title="Scegli un file SRT",
            filetypes=[("Sottotitoli SRT", "*.srt")],
        )

        if not source:
            return

        source_path = Path(source)

        messagebox.showinfo(
            "Tempi dei nuovi sottotitoli",
            "Divide i blocchi lunghi in sottotitoli di massimo due righe. "
            "I nuovi tempi interni sono stimati; il testo viene conservato.",
        )

        destination = filedialog.asksaveasfilename(
            title="Salva SRT formattato",
            defaultextension=".srt",
            initialfile=f"{source_path.stem}_formatted.srt",
            filetypes=[("Sottotitoli SRT", "*.srt")],
        )

        if not destination:
            return

        try:
            result = format_srt_file(
                source,
                destination,
            )

        except Exception as exc:  # noqa: BLE001 - mostra gli errori del file all'utente
            messagebox.showerror(
                "Errore",
                f"Non è stato possibile formattare il file:\n\n{exc}",
            )
            return

        messagebox.showinfo(
            "SRT formattato",
            f"File salvato in:\n{result}\n\n"
            f"Rapporto con tempi stimati e ID: "
            f"{result.with_name(f'{result.stem}.problemi.txt')}",
        )

    def improve_existing_srt(self) -> None:
        if not self._tools_available():
            return
        source = filedialog.askopenfilename(
            title="Scegli un file SRT da migliorare",
            filetypes=[("Sottotitoli SRT", "*.srt")],
        )
        if source:
            RevisionDialog(self.master, source)

    def translate_existing_srt(self) -> None:
        if not self._tools_available():
            return
        source = filedialog.askopenfilename(
            title="Scegli un file SRT da tradurre",
            filetypes=[("Sottotitoli SRT", "*.srt")],
        )
        if source:
            try:
                language = suggest_source_language(load_captions(source))
            except (OSError, ValueError, RevisionError) as exc:
                messagebox.showerror("SRT non utilizzabile", str(exc))
                return
            RevisionDialog(self.master, source, OPERATION_TRANSLATION, language, "it")

    def _tools_available(self) -> bool:
        if self.worker or self.translation_worker or self.summary_worker or self._active_download() or self.workflow_active or self._busy:
            self.status_var.set("Completa o interrompi il lavoro corrente prima di aprire uno strumento.")
            return False
        return True


def main() -> None:
    log_path = LOG_DIR / "startup.log"
    set_locale(load_locale(PREFERENCES_PATH))

    def startup_log(message: str) -> None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass

    startup_log("Starting SRT Compass interface.")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        from tkinter import messagebox

        messagebox.showerror("SRT Compass", str(exc))
        startup_log(f"Creazione Tk non riuscita: {type(exc).__name__}: {exc}")
        return
    try:
        ttk.Style().theme_use("aqua")
    except tk.TclError:
        pass
    try:
        App(root)
        startup_log("Main widgets created.")
        root.update_idletasks()
        startup_log("Initial Tk update completed.")
    except Exception as exc:  # noqa: BLE001 - mostra gli errori anche nel bundle GUI
        from tkinter import messagebox

        detail = f"{type(exc).__name__}: {exc}"
        startup_log(f"Avvio non riuscito: {detail[:500]}")
        messagebox.showerror(
            "Avvio non riuscito",
            f"L’interfaccia non è stata inizializzata. Riavvia l’app e riprova.\n\n{detail}",
            parent=root,
        )
        root.destroy()
        return
    root.mainloop()

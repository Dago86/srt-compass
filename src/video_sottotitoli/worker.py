from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any

from .event_log import EventLog
from .jobs import atomic_json, create_job, load_job, save_job
from .media import extract_audio_chunk
from .models import Caption
from .readability import segment_captions
from .srt import captions_from_response, detected_language, render_srt
from .transcription import transcribe_audio


class SubtitleWorker(threading.Thread):
    def __init__(
        self,
        video: str,
        duration: float,
        stream_index: int,
        output: str,
        api_key: str,
        start_at_seconds: float = 0.0,
        end_at_seconds: float | None = None,
        source_language: str = "auto",
        target_language: str = "original",
        target_model: str = "gpt-6-sol",
        translation_context: str = "",
        final_output: str | None = None,
        create_summary: bool = False,
    ):
        super().__init__(daemon=True)
        self.video = video
        self.duration = duration
        self.stream_index = stream_index
        self.output = output
        self.api_key = api_key
        self.start_at_seconds = start_at_seconds
        self.end_at_seconds = duration if end_at_seconds is None else end_at_seconds
        self.source_language = source_language
        self.target_language = target_language
        self.target_model = target_model
        self.translation_context = translation_context
        self.final_output = final_output or output
        self.create_summary = bool(create_summary)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancelled = threading.Event()
        self.job_dir: Path | None = None
        self.event_log: EventLog | None = None

    def cancel(self) -> None:
        self.cancelled.set()
        self.events.put(
            ("status", "Interruzione richiesta: termino e salvo il blocco in corso…")
        )

    def _event(self, kind: str, value: Any) -> None:
        self.events.put((kind, value))

    def run(self) -> None:
        try:
            if self.job_dir is not None:
                self._event("job_dir", str(self.job_dir))
                self._process()
            else:
                self.job_dir, manifest = create_job(
                    self.video,
                    self.duration,
                    self.stream_index,
                    self.output,
                    self.start_at_seconds,
                    self.end_at_seconds,
                    self.source_language,
                    self.target_language,
                    self.target_model,
                    self.translation_context,
                    self.final_output,
                    **({"create_summary": True} if self.create_summary else {}),
                )
                self._event("job_dir", str(self.job_dir))
                self._process(manifest)
        except Exception as exc:  # noqa: BLE001 - il thread comunica ogni errore alla UI
            if self.event_log:
                self.event_log.write(exc, level="ERROR")
            self._event("error", str(exc))

    def resume(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.start()

    def _process(self, manifest: dict[str, Any] | None = None) -> None:
        assert self.job_dir is not None
        manifest = manifest or load_job(self.job_dir)
        self.event_log = EventLog(self.job_dir, self._event, "trascrizione")
        self.event_log.write(
            "Riprendo il lavoro di trascrizione."
            if manifest.get("status") != "preparing"
            else "Avvio il lavoro di trascrizione."
        )
        if manifest["status"] == "completed":
            self._event("complete", manifest["output"])
            return
        manifest["status"] = "transcribing"
        save_job(self.job_dir, manifest)
        chunks = manifest["chunks"]
        total = len(chunks)
        for index, chunk in enumerate(chunks):
            if chunk["status"] == "completed":
                self._event("progress", (index + 1, total))
                continue
            if self.cancelled.is_set():
                manifest["status"] = "cancelled"
                save_job(self.job_dir, manifest)
                self._event("cancelled", str(self.job_dir))
                return
            self._event("status", f"Estraggo l'audio: blocco {index + 1} di {total}…")
            self.event_log.write(f"Estrazione audio: blocco {index + 1} di {total}.")
            audio_path = self.job_dir / f"chunk-{index:04}.mp3"
            extract_audio_chunk(
                manifest["video"],
                manifest["stream_index"],
                chunk["start"],
                chunk["duration"],
                audio_path,
            )
            self._event("status", f"Trascrivo: blocco {index + 1} di {total}…")
            self.event_log.write(f"Richiesta di trascrizione: blocco {index + 1} di {total}.")
            response = transcribe_audio(
                audio_path,
                self.api_key,
                None,
                lambda text: self._event("status", text),
                language=str(manifest.get("source_language", "auto")),
            )
            response_path = self.job_dir / f"chunk-{index:04}.json"
            atomic_json(response_path, response)
            audio_path.unlink(missing_ok=True)
            chunk.update({
                "status": "completed",
                "response": response_path.name,
                "detected_language": detected_language(response),
            })
            save_job(self.job_dir, manifest)
            self._event("progress", (index + 1, total))
            self.event_log.write(f"Blocco {index + 1} di {total} completato.")

        self._event("status", "Creo il file SRT…")
        self.event_log.write("Composizione del file SRT.")
        composed: list[Caption] = []
        detected_languages: set[str] = set()
        interval_start = float(manifest.get("start_at_seconds", 0.0))
        interval_end = float(manifest.get("end_at_seconds", manifest["duration"]))
        for chunk in chunks:
            response = json.loads(
                (self.job_dir / chunk["response"]).read_text(encoding="utf-8")
            )
            language = detected_language(response)
            if language:
                detected_languages.add(language)
            for caption in captions_from_response(
                response,
                float(chunk["start"]),
                str(manifest.get("source_language", "auto")),
            ):
                if caption.end <= interval_start or caption.start >= interval_end:
                    continue
                composed.append(
                    Caption(
                        max(caption.start, interval_start),
                        min(caption.end, interval_end),
                        caption.lines,
                    )
                )
        bounded = [
            Caption(
                max(caption.start, interval_start),
                min(caption.end, interval_end),
                caption.lines,
            )
            for caption in composed
            if caption.start < interval_end and caption.end > interval_start
        ]
        requested_language = str(manifest.get("source_language", "en"))
        effective_language = (
            next(iter(detected_languages)) if len(detected_languages) == 1
            else requested_language if not detected_languages and requested_language != "auto"
            else None
        )
        target_language = str(manifest.get("target_language", "original"))
        if target_language == "original" or target_language == effective_language:
            readable = segment_captions(bounded, effective_language or "auto")
            bounded = readable.captions
            manifest["readability_version"] = 1
            manifest["readability_id_map"] = {
                str(source_id): list(final_ids)
                for source_id, final_ids in readable.id_map.items()
            }
            manifest["readability_notes"] = readable.warnings
        srt_text = render_srt(bounded)
        output = Path(manifest["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(srt_text, encoding="utf-8")
        temporary.replace(output)
        manifest["status"] = "completed"
        manifest["detected_languages"] = sorted(detected_languages)
        save_job(self.job_dir, manifest)
        self._event(
            "complete",
            {
                "output": str(output),
                "source_language": manifest.get("source_language", "auto"),
                "effective_language": effective_language,
                "detected_languages": sorted(detected_languages),
                "target_language": manifest.get("target_language", "original"),
                "target_model": manifest.get("target_model", "gpt-6-sol"),
                "translation_context": manifest.get("translation_context", ""),
                "create_summary": bool(manifest.get("create_summary", False)),
                "final_output": manifest.get("final_output", manifest["output"]),
                "job_dir": str(self.job_dir),
            },
        )
        self.event_log.write("Trascrizione completata.")

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .api_client import post_provider_json
from .config import (
    PROVIDER_OPENAI,
    REASONING_MODELS,
    REVISION_JOBS_DIR,
)
from .event_log import EventLog
from .jobs import atomic_json
from .readability import readability_warnings, segment_captions
from .revision import (
    INSTRUCTION_VERSION,
    OPERATION_REVISION,
    OPERATION_TRANSLATION,
    REVISION_MODE_CONSERVATIVE,
    VALIDATOR_VERSION,
    apply_revisions,
    build_groups,
    build_request_payload,
    caption_text,
    default_model,
    estimate_revision,
    load_captions,
    model_rates,
    normalize_revision_mode,
    render_revised_srt,
    response_schema,
    revision_instructions,
    source_fingerprint,
    token_cost,
    validate_revised_items,
)
from .srt import render_srt


class RevisionWorker(threading.Thread):
    def __init__(
        self,
        source: str,
        output: str,
        api_key: str,
        request_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        mode: str = REVISION_MODE_CONSERVATIVE,
        operation: str = OPERATION_REVISION,
        source_language: str = "en",
        target_language: str = "en",
        model: str | None = None,
        user_context: str = "",
        parent_job: str | None = None,
        provider: str = PROVIDER_OPENAI,
    ):
        super().__init__(daemon=True)
        self.source = source
        self.output = output
        self.api_key = api_key
        self.operation = operation
        self.mode = normalize_revision_mode(mode)
        self.model = model or default_model(self.mode, operation)
        self.source_language = source_language
        self.target_language = target_language
        self.user_context = user_context
        self.parent_job = parent_job
        self.provider = provider or PROVIDER_OPENAI
        self.instruction_version = INSTRUCTION_VERSION
        self.request_fn = request_fn or self._request_openai
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancelled = threading.Event()
        self.job_dir: Path | None = None
        self.event_log: EventLog | None = None

    def cancel(self) -> None:
        self.cancelled.set()
        self._event(
            "status",
            "Interruzione richiesta: termino e salvo la richiesta in corso…",
        )

    def resume(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.start()

    def _event(self, kind: str, value: Any) -> None:
        self.events.put((kind, value))

    def run(self) -> None:
        try:
            if self.job_dir is None:
                self.job_dir, manifest = self._create_job()
            else:
                manifest = self._load_job(self.job_dir)
            self._event("job_dir", str(self.job_dir))
            self._process(manifest)
        except Exception as exc:  # noqa: BLE001 - inoltra gli errori al thread UI
            if self.job_dir and (self.job_dir / "revision.json").is_file():
                try:
                    manifest = self._load_job(self.job_dir)
                    manifest["status"] = "error"
                    atomic_json(self.job_dir / "revision.json", manifest)
                except (OSError, ValueError, KeyError):
                    pass
            if self.event_log:
                self.event_log.write(exc, level="ERROR")
            self._event("error", str(exc))

    def _create_job(self) -> tuple[Path, dict[str, Any]]:
        REVISION_JOBS_DIR.mkdir(parents=True, exist_ok=True)
        captions = load_captions(self.source)
        job_dir = REVISION_JOBS_DIR / str(uuid.uuid4())
        job_dir.mkdir(parents=True, exist_ok=False)
        if (self.operation == OPERATION_REVISION
                and self.source_language == "en"
                and self.target_language == "en"
                and not self.user_context
                and self.model == default_model(self.mode, self.operation)):
            groups = build_groups(captions, mode=self.mode)
        else:
            groups = build_groups(
                captions, mode=self.mode, operation=self.operation, model=self.model,
                source_language=self.source_language,
                target_language=self.target_language, user_context=self.user_context,
            )
        input_rate, output_rate = model_rates(self.model)
        manifest = {
            "version": 4,
            "type": "subtitle_translation" if self.operation == OPERATION_TRANSLATION else "subtitle_revision",
            "status": "ready",
            "source": str(Path(self.source).resolve()),
            "fingerprint": source_fingerprint(self.source),
            "output": str(Path(self.output).resolve()),
            "model": self.model,
            "provider": self.provider,
            "pricing": {
                "input_per_million": input_rate,
                "output_per_million": output_rate,
            },
            "instruction_version": INSTRUCTION_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "revision_mode": self.mode,
            "operation": self.operation,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "user_context": self.user_context,
            "parent_job": self.parent_job,
            "reasoning_effort": "none" if self.model in REASONING_MODELS else None,
            "caption_count": len(captions),
            "usage_complete": True,
            "groups": groups,
        }
        atomic_json(job_dir / "revision.json", manifest)
        if self.parent_job:
            parent_path = Path(self.parent_job) / "job.json"
            try:
                parent_manifest = json.loads(parent_path.read_text(encoding="utf-8"))
                parent_manifest["translation_job"] = str(job_dir)
                parent_manifest["workflow_stage"] = "translation"
                atomic_json(parent_path, parent_manifest)
            except (OSError, ValueError):
                pass
        return job_dir, manifest

    @staticmethod
    def _load_job(job_dir: Path) -> dict[str, Any]:
        return json.loads((job_dir / "revision.json").read_text(encoding="utf-8"))

    def _process(self, manifest: dict[str, Any]) -> None:
        assert self.job_dir is not None
        self._migrate_manifest(manifest)
        self.event_log = EventLog(
            self.job_dir,
            self._event,
            "traduzione" if manifest.get("operation") == OPERATION_TRANSLATION
            else "revisione",
        )
        self.event_log.write(
            "Riprendo il lavoro." if manifest.get("status") != "ready"
            else "Avvio il lavoro."
        )
        source = Path(manifest["source"])
        if not source.is_file():
            raise RuntimeError("Il file SRT originale non si trova più.")
        if source_fingerprint(source) != manifest["fingerprint"]:
            raise RuntimeError(
                "Il file SRT originale è cambiato. Avvia una nuova revisione."
            )
        captions = load_captions(source)
        if len(captions) != int(manifest["caption_count"]):
            raise RuntimeError(
                "Il numero di sottotitoli non corrisponde al lavoro salvato."
            )

        self.model = str(manifest["model"])
        self.provider = str(manifest.get("provider", PROVIDER_OPENAI))
        self.mode = normalize_revision_mode(str(manifest["revision_mode"]))
        self.operation = str(manifest.get("operation", OPERATION_REVISION))
        self.source_language = str(manifest.get("source_language", "en"))
        self.target_language = str(manifest.get("target_language", self.source_language))
        self.user_context = str(manifest.get("user_context", ""))
        self.parent_job = manifest.get("parent_job")
        self.instruction_version = int(manifest["instruction_version"])
        manifest["status"] = "revising"
        atomic_json(self.job_dir / "revision.json", manifest)
        groups = manifest["groups"]
        total = len(groups)
        api_failure: str | None = None
        for index, group in enumerate(groups):
            if group.get("status") == "completed" or (
                group.get("status") == "rejected"
                and self.operation != OPERATION_TRANSLATION
            ):
                self._event("progress", (index + 1, total))
                continue
            if self.cancelled.is_set():
                manifest["status"] = "cancelled"
                atomic_json(self.job_dir / "revision.json", manifest)
                self._event("cancelled", str(self.job_dir))
                return

            payload = build_request_payload(
                captions, int(group["start"]), int(group["end"]), group.get("units")
            )
            if self._recover_pending_translation(manifest, group, index, payload):
                self._event("progress", (index + 1, total))
                self._event("cost", self._cost_summary(manifest))
                self._event("stats", self._result_summary(manifest, captions)["counts"])
                continue

            self._event("status", f"Revisione: gruppo {index + 1} di {total}…")
            self.event_log.write(f"Elaborazione gruppo {index + 1} di {total}.")
            if api_failure:
                validation = self._original_fallback(payload, api_failure)
                result = {"captions": [], "ambiguities": [], "usage": None}
                group["status"] = "rejected"
            else:
                try:
                    result = self.request_fn(payload)
                except Exception as exc:  # noqa: BLE001 - conserva un SRT parziale
                    api_failure = f"Richiesta non completata: {exc}"
                    validation = self._original_fallback(payload, api_failure)
                    result = {"captions": [], "ambiguities": [], "usage": None}
                    group["status"] = "rejected"
                    self.event_log.write(
                        f"Errore API nel gruppo {index + 1}; userò il testo originale "
                        "per i gruppi non ancora elaborati.",
                        level="ERROR",
                    )
                    self._event("warning", api_failure)
            if api_failure:
                revised = result.get("captions")
                self._record_attempt(manifest, group, index, result, validation)
                response_record = {
                    "version": 4, "revision_mode": self.mode,
                    "raw_captions": revised, "captions": validation["captions"],
                    "counts": validation["counts"],
                    "anomalies": validation["anomalies"],
                    "warnings": validation.get("warnings", {}),
                    "usage": group.get("usage"), "ambiguities": [],
                    "attempts": len(group.get("attempts", [])),
                }
                response_name = f"group-{index:04}.json"
                atomic_json(self.job_dir / response_name, response_record)
                group.update({
                    "status": "rejected", "response": response_name,
                    "counts": validation["counts"], "fallback_reason": api_failure,
                })
                atomic_json(self.job_dir / "revision.json", manifest)
                self._event("progress", (index + 1, total))
                continue
            if not isinstance(result, dict):
                result = {"captions": None, "ambiguities": [], "usage": None}
            revised = result.get("captions")
            try:
                validation = validate_revised_items(
                    payload["targets"],
                    revised,
                    mode=self.mode,
                    operation=self.operation,
                    source_language=self.source_language,
                    target_language=self.target_language,
                )
            except Exception as exc:  # noqa: BLE001 - non blocca il resto del file
                validation = self._original_fallback(
                    payload, f"Risposta non interpretabile: {exc}"
                )
            self._record_attempt(manifest, group, index, result, validation)
            if (
                self.operation == OPERATION_TRANSLATION
                and validation["counts"]["rejected"] > 0
            ):
                if self.cancelled.is_set():
                    manifest["status"] = "cancelled"
                    atomic_json(self.job_dir / "revision.json", manifest)
                    self._event("cancelled", str(self.job_dir))
                    return
                self._event(
                    "status",
                    f"Traduzione incompleta: ritento il gruppo {index + 1} di {total}…",
                )
                self.event_log.write(
                    f"Secondo tentativo per il gruppo {index + 1} di {total}.",
                    level="WARNING",
                )
                rejected = [
                    item for item in validation["captions"]
                    if item["outcome"] == "rejected"
                ]
                retry_payload = dict(payload)
                retry_payload["retry_guidance"] = {
                    "rejected_ids": [item["id"] for item in rejected],
                    "reasons": sorted({str(item["reason"]) for item in rejected}),
                    "instruction": (
                        "Translate every target again from the original source. "
                        "Correct the listed violations. Preserve every numeric value; "
                        "only common Japanese month, ordinal, and week expressions "
                        "may use their exact written equivalents in the target language. "
                        "Keep all other Arabic digit sequences exactly, even if the "
                        "source may be mistranscribed. "
                        "Report uncertainty instead of silently correcting facts."
                    ),
                }
                try:
                    retry_result = self.request_fn(retry_payload)
                    if not isinstance(retry_result, dict):
                        retry_result = {
                            "captions": None, "ambiguities": [], "usage": None
                        }
                    retry_validation = validate_revised_items(
                        payload["targets"],
                        retry_result.get("captions"),
                        mode=self.mode,
                        operation=self.operation,
                        source_language=self.source_language,
                        target_language=self.target_language,
                    )
                    self._record_attempt(
                        manifest, group, index, retry_result, retry_validation
                    )
                    revised = retry_result.get("captions")
                except Exception as exc:  # noqa: BLE001 - conserva la prima risposta
                    api_failure = f"Secondo tentativo non completato: {exc}"
                    retry_result = {"captions": [], "ambiguities": [], "usage": None}
                    retry_validation = self._original_fallback(
                        payload, api_failure
                    )
                    self._record_attempt(
                        manifest, group, index, retry_result, retry_validation
                    )
                    self._event("warning", api_failure)
                result = retry_result
                validation = self._keep_valid_units(
                    payload["targets"], validation, retry_validation
                )

            response_record = {
                "version": 4,
                "revision_mode": self.mode,
                "raw_captions": revised,
                "captions": validation["captions"],
                "counts": validation["counts"],
                "anomalies": validation["anomalies"],
                "warnings": validation.get("warnings", {}),
                "usage": group.get("usage"),
                "ambiguities": result.get("ambiguities") or [],
                "attempts": len(group.get("attempts", [])),
            }
            response_name = f"group-{index:04}.json"
            atomic_json(self.job_dir / response_name, response_record)

            group["status"] = (
                "rejected" if validation["counts"]["rejected"] else "completed"
            )
            group["response"] = response_name
            group["counts"] = validation["counts"]
            atomic_json(self.job_dir / "revision.json", manifest)
            self._event("progress", (index + 1, total))
            self._event("cost", self._cost_summary(manifest))
            self._event("stats", self._result_summary(manifest, captions)["counts"])
            self.event_log.write(f"Gruppo {index + 1} di {total} completato.")

        summary = self._result_summary(manifest, captions)
        revised_by_id = summary["revised_by_id"]

        output_language = self.target_language if self.operation == OPERATION_TRANSLATION else self.source_language
        id_map: dict[int, tuple[int, int]] = {}
        segmentation_notes: list[str] = []
        if self.operation == OPERATION_TRANSLATION:
            revised = apply_revisions(captions, revised_by_id, output_language)
            readable = segment_captions(revised, output_language)
            srt_text = render_srt(readable.captions)
            warnings = readability_warnings(readable.captions, output_language)
            id_map = readable.id_map
            segmentation_notes = readable.warnings
        else:
            srt_text, warnings = render_revised_srt(
                captions, revised_by_id, output_language
            )
        output = Path(manifest["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(srt_text, encoding="utf-8")
        temporary.replace(output)
        issues = summary.get("content_warnings", [])
        if (summary["rejections"] or summary["anomalies"] or issues or api_failure
                or warnings or segmentation_notes):
            report = self._write_issue_report(
                output, captions, summary, api_failure, warnings,
                id_map, segmentation_notes,
            )
        else:
            report = None
        completion_status = (
            "completed_with_untranslated"
            if summary["rejections"] or api_failure
            else "completed_with_warnings"
            if issues or summary["anomalies"] or warnings
            else "completed"
        )
        manifest.update(
            {
                "status": "completed",
                "completion_status": completion_status,
                "result_counts": summary["counts"],
                "rejections": summary["rejections"],
                "warnings": summary.get("content_warnings", []),
                "response_anomalies": summary["anomalies"],
                "formatting_warnings": warnings,
                "readability_version": 1 if self.operation == OPERATION_TRANSLATION else None,
                "readability_id_map": {
                    str(source_id): list(final_ids)
                    for source_id, final_ids in id_map.items()
                },
                "readability_notes": segmentation_notes,
                "applied_changes": summary["applied_changes"],
                "ambiguities": summary["ambiguities"],
                "actual_cost": self._cost_summary(manifest),
                "issue_report": str(report) if report else None,
                "api_failure": api_failure,
            }
        )
        atomic_json(self.job_dir / "revision.json", manifest)
        self._event(
            "complete",
            {
                "output": str(output),
                "counts": summary["counts"],
                "rejections": summary["rejections"],
                "anomalies": summary["anomalies"],
                "warnings": warnings,
                "applied_changes": summary["applied_changes"],
                "mode": self.mode,
                "operation": self.operation,
                "ambiguities": summary["ambiguities"],
                "content_warnings": summary.get("content_warnings", []),
                "partial": bool(summary["rejections"] or summary.get("content_warnings") or api_failure),
                "completion_status": completion_status,
                "issue_report": str(report) if report else None,
                "api_failure": api_failure,
                "cost": manifest["actual_cost"],
            },
        )
        self.event_log.write("Lavoro completato.")

    @staticmethod
    def _write_issue_report(
        output: Path,
        captions: list[Any],
        summary: dict[str, Any],
        api_failure: str | None,
        formatting_warnings: list[str],
        id_map: dict[int, tuple[int, int]] | None = None,
        segmentation_notes: list[str] | None = None,
    ) -> Path:
        report = output.with_name(f"{output.stem}.problemi.txt")
        lines = ["Rapporto di revisione sottotitoli", ""]
        changed_ids = {
            source_id: final_ids for source_id, final_ids in (id_map or {}).items()
            if final_ids != (source_id, source_id)
        }
        if changed_ids:
            lines.extend([
                "I numeri delle segnalazioni linguistiche si riferiscono ai blocchi originali.",
                "Nel file finale i blocchi lunghi hanno nuovi identificativi e tempi interni stimati:",
            ])
            for source_id, (first, last) in changed_ids.items():
                label = str(first) if first == last else f"{first}–{last}"
                lines.append(f"Originale {source_id} → finale {label}")
            lines.append("")
        by_id = {int(item["id"]): item for item in summary["content_warnings"]}
        rejected = {int(item["id"]): item for item in summary["rejections"]}
        for subtitle_id in sorted(set(by_id) | set(rejected)):
            caption = captions[subtitle_id - 1]
            start = RevisionWorker._report_timestamp(caption.start)
            end = RevisionWorker._report_timestamp(caption.end)
            lines.append(f"Sottotitolo {subtitle_id} · {start} → {end}")
            if subtitle_id in by_id:
                issue = by_id[subtitle_id]
                lines.append(f"Avviso: {'; '.join(issue['warnings'])}")
                lines.append(f"Originale: {issue['original']}")
                lines.append(f"Applicato: {issue['applied']}")
            if subtitle_id in rejected:
                issue = rejected[subtitle_id]
                lines.append(f"Parte non tradotta: {issue['reason']}")
                if issue.get("proposed"):
                    lines.append(f"Proposta non applicata: {issue['proposed']}")
                lines.append(f"Testo mantenuto: {caption_text(caption)}")
            lines.append("")
        lines.extend(summary["anomalies"])
        lines.extend(formatting_warnings)
        lines.extend(segmentation_notes or [])
        if api_failure:
            lines.extend(["", "Richiesta interrotta:", api_failure])
        report.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return report

    @staticmethod
    def _report_timestamp(seconds: float) -> str:
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        whole_seconds, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"

    @staticmethod
    def _original_fallback(payload: dict[str, Any], reason: str) -> dict[str, Any]:
        originals = [
            {
                "id": int(item["id"]), "text": str(item["text"]),
                "outcome": "rejected", "reason": reason,
                "original_text": str(item["text"]), "proposed_text": None,
            }
            for item in payload["targets"]
        ]
        return {
            "captions": originals,
            "counts": {"modified": 0, "unchanged": 0, "rejected": len(originals)},
            "anomalies": [reason],
            "warnings": {},
        }

    @staticmethod
    def _keep_valid_units(
        originals: list[dict[str, Any]],
        first: dict[str, Any],
        retry: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep first-attempt content for entire units valid before a structural retry."""
        first_items = {int(item["id"]): item for item in first["captions"]}
        retry_items = {int(item["id"]): item for item in retry["captions"]}
        units: dict[int, list[int]] = {}
        for item in originals:
            units.setdefault(int(item.get("unit") or item["id"]), []).append(int(item["id"]))
        chosen = dict(retry_items)
        for ids in units.values():
            if ids and all(
                item_id in first_items
                and first_items[item_id]["outcome"] != "rejected"
                for item_id in ids
            ) and any(
                item_id not in retry_items
                or retry_items[item_id]["outcome"] == "rejected"
                for item_id in ids
            ):
                chosen.update({item_id: first_items[item_id] for item_id in ids})
        captions = [chosen[int(item["id"])] for item in originals]
        counts = {"modified": 0, "unchanged": 0, "rejected": 0}
        for item in captions:
            counts[item["outcome"]] += 1
        warnings = dict(first.get("warnings", {}))
        warnings.update(retry.get("warnings", {}))
        return {
            "captions": captions, "counts": counts,
            "anomalies": list(dict.fromkeys(first.get("anomalies", []) + retry.get("anomalies", []))),
            "warnings": warnings,
        }

    def _recover_pending_translation(
        self, manifest: dict[str, Any], group: dict[str, Any], index: int,
        payload: dict[str, Any],
    ) -> bool:
        """Rivalida una risposta già pagata prima di richiedere altro testo."""
        if self.operation != OPERATION_TRANSLATION or not group.get("response"):
            return False
        assert self.job_dir is not None
        response_path = self.job_dir / str(group["response"])
        if not response_path.is_file():
            return False
        record = json.loads(response_path.read_text(encoding="utf-8"))
        raw_captions = record.get("raw_captions")
        if not isinstance(raw_captions, list):
            # Older manifests stored the provider proposal under `captions`.
            raw_captions = record.get("captions")
        if not isinstance(raw_captions, list):
            return False
        validation = validate_revised_items(
            payload["targets"], raw_captions,
            mode=self.mode, operation=self.operation,
            source_language=self.source_language,
            target_language=self.target_language,
        )
        if validation["counts"]["rejected"]:
            return False
        record["raw_captions"] = raw_captions
        record["captions"] = validation["captions"]
        record["counts"] = validation["counts"]
        record["anomalies"] = validation["anomalies"]
        record["validator_version"] = VALIDATOR_VERSION
        atomic_json(response_path, record)
        group["status"] = "completed"
        group["counts"] = validation["counts"]
        group["validator_version"] = VALIDATOR_VERSION
        atomic_json(self.job_dir / "revision.json", manifest)
        assert self.event_log is not None
        self.event_log.write(
            f"Gruppo {index + 1} recuperato dalla risposta salvata, senza nuova richiesta."
        )
        return True

    def _record_attempt(
        self, manifest: dict[str, Any], group: dict[str, Any], index: int,
        result: dict[str, Any], validation: dict[str, Any],
    ) -> None:
        """Salva risposta e costo prima di un'eventuale richiesta successiva."""
        assert self.job_dir is not None
        attempts = group.setdefault("attempts", [])
        attempt_name = f"group-{index:04d}-attempt-{len(attempts) + 1:02d}.json"
        usage = result.get("usage")
        atomic_json(self.job_dir / attempt_name, {
            "raw_captions": result.get("captions"),
            "ambiguities": result.get("ambiguities") or [],
            "validation": validation,
            "usage": usage,
        })
        attempts.append(attempt_name)
        if isinstance(usage, dict):
            previous = group.get("usage") or {}
            input_tokens = int(previous.get("input_tokens", 0)) + int(
                usage.get("input_tokens", 0)
            )
            output_tokens = int(previous.get("output_tokens", 0)) + int(
                usage.get("output_tokens", 0)
            )
            pricing = manifest["pricing"]
            group["usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": token_cost(
                    input_tokens, output_tokens,
                    float(pricing["input_per_million"]),
                    float(pricing["output_per_million"]),
                ),
            }
        else:
            manifest["usage_complete"] = False
        atomic_json(self.job_dir / "revision.json", manifest)
        self._event("cost", self._cost_summary(manifest))
        if self.event_log:
            self.event_log.write("Risposta ricevuta; consumo registrato.")

    @staticmethod
    def _migrate_manifest(manifest: dict[str, Any]) -> None:
        original_version = int(manifest.get("version", 1))
        if original_version < 3:
            manifest.setdefault("original_version", original_version)
            manifest["version"] = 3
        manifest.setdefault("validator_version", 1 if original_version == 1 else 2)
        manifest.setdefault("revision_mode", REVISION_MODE_CONSERVATIVE)
        manifest.setdefault("instruction_version", 1)
        manifest.setdefault("operation", OPERATION_REVISION)
        manifest.setdefault("source_language", "en")
        manifest.setdefault("target_language", manifest["source_language"])
        manifest.setdefault("user_context", "")
        manifest.setdefault("provider", PROVIDER_OPENAI)

    def _validated_group_items(
        self,
        group: dict[str, Any],
        captions: list[Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        assert self.job_dir is not None
        record = json.loads(
            (self.job_dir / group["response"]).read_text(encoding="utf-8")
        )
        items = record.get("captions")
        if isinstance(items, list) and all(
            isinstance(item, dict)
            and item.get("outcome")
            in {
                "modified",
                "unchanged",
                "rejected",
            }
            for item in items
        ):
            return items, [str(item) for item in record.get("anomalies", [])]

        payload = build_request_payload(
            captions, int(group["start"]), int(group["end"]), group.get("units")
        )
        if record.get("accepted") is True:
            validation = validate_revised_items(
                payload["targets"],
                items,
                mode=REVISION_MODE_CONSERVATIVE,
                operation=self.operation,
                source_language=self.source_language,
                target_language=self.target_language,
            )
            return validation["captions"], validation["anomalies"]

        reason = str(
            record.get("reason") or "Gruppo rifiutato dal validatore precedente."
        )
        migrated = [
            {
                "id": int(item["id"]),
                "text": str(item["text"]),
                "outcome": "rejected",
                "reason": reason,
            }
            for item in payload["targets"]
        ]
        return migrated, []

    def _result_summary(
        self, manifest: dict[str, Any], captions: list[Any]
    ) -> dict[str, Any]:
        counts = {"modified": 0, "unchanged": 0, "rejected": 0}
        revised_by_id: dict[int, str] = {}
        rejections: list[dict[str, Any]] = []
        anomalies: list[str] = []
        applied_changes: list[dict[str, Any]] = []
        ambiguities: list[dict[str, Any]] = []
        for group_index, group in enumerate(manifest["groups"], start=1):
            if group.get("status") not in {"completed", "rejected"}:
                continue
            if not group.get("response"):
                continue
            items, group_anomalies = self._validated_group_items(group, captions)
            record = json.loads((self.job_dir / group["response"]).read_text(encoding="utf-8"))
            ambiguities.extend(record.get("ambiguities") or [])
            anomalies.extend(
                f"Gruppo {group_index}: {message}" for message in group_anomalies
            )
            group_counts = {"modified": 0, "unchanged": 0, "rejected": 0}
            for item in items:
                subtitle_id = int(item["id"])
                outcome = str(item["outcome"])
                if outcome not in counts:
                    continue
                counts[outcome] += 1
                group_counts[outcome] += 1
                revised_by_id[subtitle_id] = str(item["text"])
                if outcome == "rejected":
                    rejections.append(
                        {
                            "id": subtitle_id,
                            "reason": str(item.get("reason") or "Proposta rifiutata."),
                            "original": str(
                                item.get("original_text")
                                or caption_text(captions[subtitle_id - 1])
                            ),
                            "proposed": item.get("proposed_text"),
                        }
                    )
                elif outcome == "modified":
                    original_text = str(
                        item.get("original_text")
                        or caption_text(captions[subtitle_id - 1])
                    )
                    applied_changes.append(
                        {
                            "id": subtitle_id,
                            "original": original_text,
                            "revised": str(item["text"]),
                        }
                    )
            group["counts"] = group_counts

        for subtitle_id, caption in enumerate(captions, start=1):
            revised_by_id.setdefault(subtitle_id, caption_text(caption))
        return {
            "counts": counts,
            "revised_by_id": revised_by_id,
            "rejections": rejections,
            "anomalies": anomalies,
            "applied_changes": applied_changes,
            "ambiguities": ambiguities,
            "content_warnings": [
                {
                    "id": int(item["id"]),
                    "warnings": list(item.get("warnings", [])),
                    "original": str(item.get("original_text") or ""),
                    "applied": str(item.get("text") or ""),
                }
                for group in manifest["groups"]
                if group.get("status") in {"completed", "rejected"}
                and group.get("response")
                for item in self._response_items(group, captions)
                if item.get("warnings")
            ],
        }

    def _response_items(self, group: dict[str, Any], captions: list[Any]) -> list[dict[str, Any]]:
        items, _ = self._validated_group_items(group, captions)
        return items

    @staticmethod
    def _cost_summary(manifest: dict[str, Any]) -> dict[str, Any]:
        input_tokens = 0
        output_tokens = 0
        cost = 0.0
        for group in manifest["groups"]:
            usage = group.get("usage")
            if not isinstance(usage, dict):
                continue
            input_tokens += int(usage.get("input_tokens", 0))
            output_tokens += int(usage.get("output_tokens", 0))
            cost += float(usage.get("cost_usd", 0.0))
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "complete": bool(manifest.get("usage_complete", True)),
        }

    def _request_openai(self, payload: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": revision_instructions(
                self.mode, self.instruction_version, self.operation,
                self.source_language, self.target_language, self.user_context,
            ),
            "input": json.dumps(payload, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "subtitle_text_operation",
                    "strict": True,
                    "schema": response_schema(),
                }
            },
        }
        # DeepSeek Responses currently does not accept OpenAI's `store` field.
        if self.provider == PROVIDER_OPENAI:
            request["store"] = False
        if isinstance(payload.get("retry_guidance"), dict):
            guidance = payload["retry_guidance"]
            request["instructions"] += (
                "\nThis is a retry of a rejected translation. "
                + str(guidance["instruction"])
                + " Rejected ids and validation reasons: "
                + json.dumps(
                    {"ids": guidance["rejected_ids"], "reasons": guidance["reasons"]},
                    ensure_ascii=False,
                )
            )
        if self.model in REASONING_MODELS:
            request["reasoning"] = {"effort": "none"}
        response = post_provider_json(
            self.api_key, "/responses", request, self.provider
        )
        output_text = response.get("output_text")
        if not output_text:
            output_text = "".join(
                str(part.get("text", ""))
                for item in response.get("output", [])
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
        if not output_text:
            raise RuntimeError("Il servizio non ha restituito testo revisionato.")
        try:
            data = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Il servizio ha restituito una risposta non valida."
            ) from exc
        usage = response.get("usage")
        return {
            "captions": data.get("captions"),
            "ambiguities": data.get("ambiguities") or [],
            "usage": (
                {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }
                if usage is not None
                else None
            ),
        }


def load_revision_for_resume(job_dir: Path) -> tuple[dict[str, Any], Any]:
    manifest = RevisionWorker._load_job(job_dir)
    captions = load_captions(manifest["source"])
    pricing = manifest["pricing"]
    estimated_groups = [dict(group) for group in manifest["groups"]]
    if manifest.get("operation") == OPERATION_TRANSLATION:
        for group in estimated_groups:
            if group.get("status") != "pending" or not group.get("response"):
                continue
            response_path = job_dir / str(group["response"])
            if not response_path.is_file():
                continue
            record = json.loads(response_path.read_text(encoding="utf-8"))
            if not isinstance(record.get("raw_captions"), list):
                continue
            payload = build_request_payload(
                captions, int(group["start"]), int(group["end"]), group.get("units")
            )
            validation = validate_revised_items(
                payload["targets"], record["raw_captions"],
                mode=str(manifest.get("revision_mode", REVISION_MODE_CONSERVATIVE)),
                operation=OPERATION_TRANSLATION,
                source_language=str(manifest.get("source_language", "en")),
                target_language=str(manifest.get("target_language", "en")),
            )
            if validation["counts"]["rejected"] == 0:
                group["status"] = "completed"
    return manifest, estimate_revision(
        captions,
        estimated_groups,
        float(pricing["input_per_million"]),
        float(pricing["output_per_million"]),
        mode=str(manifest.get("revision_mode", REVISION_MODE_CONSERVATIVE)),
        operation=str(manifest.get("operation", OPERATION_REVISION)),
        model=str(manifest.get("model", default_model(
            str(manifest.get("revision_mode", REVISION_MODE_CONSERVATIVE)),
            str(manifest.get("operation", OPERATION_REVISION)),
        ))),
        source_language=str(manifest.get("source_language", "en")),
        target_language=str(manifest.get("target_language", "en")),
        user_context=str(manifest.get("user_context", "")),
    )

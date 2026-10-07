from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DOWNLOAD_JOBS_DIR, JOBS_DIR, REVISION_JOBS_DIR


def _download_is_active(job_dir: Path) -> bool:
    lock_path = job_dir / ".active.lock"
    if lock_path.is_symlink():
        return True
    try:
        with lock_path.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return True  # An unknown lock state must not be presented as safe to resume.
    return False


def list_recent_jobs(limit: int = 50) -> list[dict[str, Any]]:
    """Legge i registri locali e restituisce una vista breve, anche se alcuni sono rotti."""
    records: list[dict[str, Any]] = []
    roots = (
        (JOBS_DIR, "job.json", "Trascrizione"),
        (REVISION_JOBS_DIR, "revision.json", "Sottotitoli SRT"),
        (DOWNLOAD_JOBS_DIR, "download.json", "Download"),
    )
    for root, filename, default_kind in roots:
        if not root.is_dir():
            continue
        for job_dir in root.iterdir():
            record_path = job_dir / filename
            if not job_dir.is_dir() or not record_path.is_file():
                continue
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
                stat = record_path.stat()
            except (OSError, ValueError):
                records.append({
                    "path": record_path, "kind": default_kind,
                    "name": "Registro non leggibile", "status": "Errore",
                    "progress": "—", "cost": "—", "modified": 0,
                })
                continue
            kind = default_kind
            if filename == "revision.json":
                kind = "Traduzione" if data.get("operation") == "translation" else "Revisione SRT"
                if data.get("parent_job"):
                    continue
            if filename == "download.json":
                done = data.get("status") == "completed"
                active = _download_is_active(job_dir)
                staging = Path(str(data.get("staging_dir") or job_dir / "staging"))
                staging_files = [item for item in staging.rglob("*") if item.is_file()] if staging.is_dir() else []
                partial_bytes = sum(item.stat().st_size for item in staging_files)
                download_status = {
                    "cancelled": "Interrotto", "error": "Errore",
                    "downloading": "In download", "analyzed": "Pronto",
                    "completed": "Completato",
                }.get(str(data.get("status") or ""), str(data.get("status") or "sconosciuto"))
                if data.get("status") == "downloading" and not active:
                    download_status = "Interrotto dopo chiusura inattesa"
                elif active:
                    download_status = "In download"
                records.append({
                    "path": record_path, "kind": kind,
                    "name": str(data.get("title") or "Download senza titolo"),
                    "status": download_status,
                    "progress": "Completato" if done else (
                        f"Temporanei · {partial_bytes / (1024 * 1024):.0f} MB"
                        if partial_bytes else "Da riprendere"
                    ),
                    "cost": "—", "modified": stat.st_mtime,
                    "temporary_files": len(staging_files),
                    "temporary_bytes": partial_bytes,
                    "details": (
                        f"Qualità: {data.get('quality', 'non specificata')}; "
                        f"traccia: {data.get('audio_language') or 'predefinita'}; "
                        f"destinazione: {Path(str(data.get('destination_dir') or 'non specificata')).name}; "
                        f"file pronto: {Path(str(data.get('output'))).name if data.get('output') else 'no'}"
                    ),
                })
                continue
            groups = data.get("groups") or data.get("chunks") or []
            completed = sum(item.get("status") == "completed" for item in groups)
            name = Path(str(data.get("source") or data.get("video") or "Senza nome")).name
            groups_total = len(groups)
            usage = [group.get("usage") or {} for group in groups]
            total_cost = sum(float(item.get("cost_usd") or 0) for item in usage)
            pricing = data.get("pricing") or {}
            missing_input = sum(
                int(group.get("input_tokens_estimate") or 0)
                for group in groups if group.get("status") == "pending"
            )
            missing_output = sum(
                int(group.get("output_tokens_estimate") or 0)
                for group in groups if group.get("status") == "pending"
            )
            remaining_cost = (
                missing_input * float(pricing.get("input_per_million", 0))
                + missing_output * float(pricing.get("output_per_million", 0))
            ) / 1_000_000
            if groups and data.get("type") == "subtitle_translation":
                cost_label = f"${total_cost:.4f} spesi · ~${remaining_cost:.4f} stimati"
            else:
                cost_label = f"${total_cost:.4f}"
            status = str(data.get("status") or "sconosciuto")
            status = {
                "ready": "Pronto", "analyzed": "Pronto",
                "downloading": "In download", "transcribing": "In trascrizione",
                "revising": "In revisione", "cancelled": "Interrotto",
                "error": "Errore", "completed": "Completato",
                "preparing": "In preparazione",
            }.get(status, status)
            if filename == "job.json" and data.get("translation_job"):
                revision_path = Path(str(data["translation_job"])) / "revision.json"
                try:
                    translation = json.loads(revision_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    translation = None
                if translation:
                    translation_groups = translation.get("groups") or []
                    completed = sum(
                        group.get("status") in {"completed", "rejected"}
                        for group in translation_groups
                    )
                    groups_total = len(translation_groups)
                    completion = translation.get("completion_status")
                    if translation.get("status") == "completed":
                        status = {
                            "completed_with_warnings": "Completato con avvisi",
                            "completed_with_untranslated":
                                "Completato con parti non tradotte",
                        }.get(completion, "Completato")
                    elif translation.get("status") in {"error", "cancelled"}:
                        status = "Traduzione da riprendere"
                    else:
                        status = "Traduzione in corso"
                    usage = [group.get("usage") or {} for group in translation_groups]
                    total_cost = sum(float(item.get("cost_usd") or 0) for item in usage)
                    cost_label = "$" + f"{total_cost:.4f}"
            if (
                filename == "job.json" and status == "Completato"
                and data.get("target_language", "original") != "original"
                and not data.get("translation_job")
            ):
                status = "Originale pronto"
            if filename == "job.json" and data.get("create_summary"):
                summary_state = data.get("summary_state")
                if summary_state == "awaiting_confirmation" and status in {
                    "Completato", "Originale pronto", "Completato con avvisi",
                    "Completato con parti non tradotte",
                }:
                    status = "Scheda da creare"
                elif summary_state in {"error", "cancelled", "response_received"}:
                    status = "Scheda da riprendere"
                elif summary_state == "completed" and status in {
                    "Completato", "Originale pronto", "Completato con avvisi",
                    "Completato con parti non tradotte",
                }:
                    status = "SRT e scheda pronti"
            records.append({
                "path": record_path, "kind": kind, "name": name,
                "status": status,
                "progress": f"{completed}/{groups_total}" if groups_total else "—",
                "cost": cost_label, "modified": stat.st_mtime,
                "details": (
                    f"Modello: {data.get('model', 'non specificato')}; "
                    f"lingue: {data.get('source_language', '—')} → "
                    f"{data.get('target_language', 'originale')}; "
                    f"risultato: {Path(str(data.get('final_output') or data.get('output'))).name if data.get('output') else 'incompleto'}"
                ),
            })
    records.sort(key=lambda item: float(item["modified"]), reverse=True)
    for record in records:
        timestamp = float(record["modified"])
        record["modified_label"] = (
            datetime.fromtimestamp(timestamp, tz=UTC).astimezone().strftime("%d/%m %H:%M")
            if timestamp else "—"
        )
    return records[:limit]

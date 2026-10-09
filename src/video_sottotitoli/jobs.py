from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .config import (
    JOBS_DIR,
    PROVIDER_OPENAI,
    WHISPER_COST_PER_MINUTE_USD,
    ensure_app_dirs,
)
from .selection import create_chunks


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def fingerprint(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def create_job(
    video: str,
    duration: float,
    stream_index: int,
    output: str,
    start_at_seconds: float = 0.0,
    end_at_seconds: float | None = None,
    source_language: str = "en",
    target_language: str = "original",
    target_model: str = "gpt-6-sol",
    translation_context: str = "",
    final_output: str | None = None,
    create_summary: bool = False,
    translation_provider: str = PROVIDER_OPENAI,
) -> tuple[Path, dict[str, Any]]:
    ensure_app_dirs()
    job_dir = JOBS_DIR / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=False)
    end_at_seconds = duration if end_at_seconds is None else end_at_seconds
    chunks = create_chunks(duration, start_at_seconds, end_at_seconds=end_at_seconds)
    manifest = {
        "version": 4,
        "status": "preparing",
        "workflow_stage": "ready_to_transcribe",
        "video": str(Path(video).resolve()),
        "fingerprint": fingerprint(video),
        "duration": duration,
        "start_at_seconds": start_at_seconds,
        "end_at_seconds": end_at_seconds,
        "source_language": source_language,
        "target_language": target_language,
        "target_model": target_model,
        "translation_provider": translation_provider or PROVIDER_OPENAI,
        "translation_context": translation_context,
        "create_summary": bool(create_summary),
        "summary_state": "awaiting_confirmation" if create_summary else None,
        "stream_index": stream_index,
        "output": str(Path(output).resolve()),
        "final_output": str(Path(final_output or output).resolve()),
        "transcription_output": str(Path(output).resolve()),
        "transcription_estimate_usd": round(
            max(0.0, end_at_seconds - start_at_seconds)
            / 60.0
            * WHISPER_COST_PER_MINUTE_USD,
            6,
        ),
        "transcription_cost_usd": None,
        "chunks": chunks,
    }
    save_job(job_dir, manifest)
    return job_dir, manifest


def load_job(job_dir: Path) -> dict[str, Any]:
    manifest = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    manifest.setdefault("start_at_seconds", 0.0)
    manifest.setdefault("end_at_seconds", manifest.get("duration"))
    manifest.setdefault("source_language", "en")
    manifest.setdefault("target_language", "original")
    manifest.setdefault("target_model", "gpt-6-sol")
    manifest.setdefault("translation_provider", PROVIDER_OPENAI)
    manifest.setdefault("translation_context", "")
    manifest.setdefault("create_summary", False)
    manifest.setdefault("summary_state", None)
    manifest.setdefault("workflow_stage", _legacy_workflow_stage(manifest))
    manifest.setdefault("transcription_output", manifest.get("output"))
    manifest.setdefault("transcription_estimate_usd", None)
    manifest.setdefault("transcription_cost_usd", None)
    return manifest


def _legacy_workflow_stage(manifest: dict[str, Any]) -> str:
    """Infer the explicit two-step phase for jobs created before 0.14.1."""
    if manifest.get("status") in {"cancelled", "error"}:
        return "interrupted" if manifest.get("status") == "cancelled" else "error"
    if manifest.get("translation_job"):
        return "translation"
    if manifest.get("status") == "completed":
        if manifest.get("target_language", "original") == "original":
            return "completed"
        return "ready_to_translate"
    if manifest.get("status") in {"transcribing", "preparing"}:
        return "transcribing"
    return "ready_to_transcribe"


def save_job(job_dir: Path, manifest: dict[str, Any]) -> None:
    atomic_json(job_dir / "job.json", manifest)

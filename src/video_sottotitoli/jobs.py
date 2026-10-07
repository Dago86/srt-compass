from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .config import JOBS_DIR, ensure_app_dirs
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
) -> tuple[Path, dict[str, Any]]:
    ensure_app_dirs()
    job_dir = JOBS_DIR / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=False)
    end_at_seconds = duration if end_at_seconds is None else end_at_seconds
    chunks = create_chunks(duration, start_at_seconds, end_at_seconds=end_at_seconds)
    manifest = {
        "version": 4,
        "status": "preparing",
        "video": str(Path(video).resolve()),
        "fingerprint": fingerprint(video),
        "duration": duration,
        "start_at_seconds": start_at_seconds,
        "end_at_seconds": end_at_seconds,
        "source_language": source_language,
        "target_language": target_language,
        "target_model": target_model,
        "translation_context": translation_context,
        "create_summary": bool(create_summary),
        "summary_state": "awaiting_confirmation" if create_summary else None,
        "stream_index": stream_index,
        "output": str(Path(output).resolve()),
        "final_output": str(Path(final_output or output).resolve()),
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
    manifest.setdefault("translation_context", "")
    manifest.setdefault("create_summary", False)
    manifest.setdefault("summary_state", None)
    return manifest


def save_job(job_dir: Path, manifest: dict[str, Any]) -> None:
    atomic_json(job_dir / "job.json", manifest)

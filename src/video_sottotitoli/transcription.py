from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .api_client import post_transcription


class TranscriptionError(RuntimeError):
    pass


def _is_transient(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    return status == 429 or (isinstance(status, int) and 500 <= status < 600)


def transcribe_audio(
    audio_file: Path,
    api_key: str,
    prompt: str | None = None,
    on_retry: Callable[[str], None] | None = None,
    language: str = "en",
) -> dict[str, Any]:
    """Restituisce i tempi di parole e segmenti, ritentando solo errori transitori."""
    for attempt in range(3):
        try:
            return post_transcription(api_key, audio_file, language, prompt)
        except Exception as exc:
            if not _is_transient(exc) or attempt == 2:
                raise TranscriptionError(
                    "La trascrizione non è riuscita: " + str(exc)
                ) from exc
            wait_seconds = 2 ** (attempt + 1)
            if on_retry:
                on_retry(
                    f"Servizio temporaneamente occupato. Nuovo tentativo tra {wait_seconds} secondi…"
                )
            time.sleep(wait_seconds)
    raise AssertionError("unreachable")

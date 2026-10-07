from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|token|signature|sig|auth|cookie|password)\b"
    r"([\s:=]+)[^\s,;]+"
)


def sanitize_message(message: object) -> str:
    text = str(message).replace("\r", " ").replace("\n", " ")
    text = _BEARER.sub("Bearer [omesso]", text)
    text = _SECRET.sub(r"\1\2[omesso]", text)
    text = _URL.sub("[link omesso]", text)
    return text[:600]


class EventLog:
    """Append-only, human-readable log for a single persisted job."""

    def __init__(
        self,
        job_dir: Path,
        emit: Callable[[str, Any], None],
        phase: str,
    ) -> None:
        self.path = job_dir / "events.log"
        self.emit = emit
        self.default_phase = phase
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        else:
            self.path.chmod(0o600)
        self.emit("log_path", str(self.path))

    def write(
        self,
        message: object,
        *,
        level: str = "INFO",
        phase: str | None = None,
    ) -> str:
        timestamp = datetime.now(UTC).astimezone().isoformat(
            timespec="seconds"
        )
        line = (
            f"{timestamp} [{(phase or self.default_phase).upper()}] "
            f"[{level.upper()}] {sanitize_message(message)}"
        )
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
        self.emit("log", {"line": line, "path": str(self.path)})
        return line

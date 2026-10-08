"""Fail when publishable files contain secrets or generated/user data."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
MAX_FILE_BYTES = 5 * 1024 * 1024
BLOCKED_SUFFIXES = {
    ".app",
    ".dmg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".opus",
    ".srt",
    ".wav",
    ".webm",
    ".zip",
}
ALLOWED_LARGE_SUFFIXES = {".md"}
SECRET_PATTERNS = (
    re.compile(r"sk-" + r"(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?m)^OPENAI_API_KEY\s*=\s*[^\s#]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"/Users/[^/\s]+/"),
)


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [ROOT / name for name in result.stdout.splitlines() if name]
    return [path for path in ROOT.rglob("*") if path.is_file()]


def main() -> int:
    problems: list[str] = []
    for path in repository_files():
        if path.resolve() == SELF or not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        suffix = path.suffix.casefold()
        if path.name.startswith(".env") and path.name != ".env.example":
            problems.append(f"secret configuration included: {relative}")
        if suffix in BLOCKED_SUFFIXES:
            problems.append(f"generated artifact or user data included: {relative}")
        try:
            size = path.stat().st_size
        except OSError as exc:
            problems.append(f"unreadable file: {relative}: {exc}")
            continue
        if size > MAX_FILE_BYTES and suffix not in ALLOWED_LARGE_SUFFIXES:
            problems.append(f"file larger than 5 MiB: {relative}")
        if size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"possible secret or personal path: {relative}")
                break
    if problems:
        print("Repository check failed:", file=sys.stderr)
        for problem in sorted(set(problems)):
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Repository clean: no secrets or prohibited artifacts found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

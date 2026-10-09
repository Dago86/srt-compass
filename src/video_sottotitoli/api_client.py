from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_ROOT = "https://api.openai.com/v1"
DEEPSEEK_API_ROOT = "https://api.deepseek.com"


class RemoteAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _request(request: Request, timeout: float = 300) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = str(body.get("error", {}).get("message") or exc.reason)
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            message = str(exc.reason)
        raise RemoteAPIError(message, exc.code) from exc
    except URLError as exc:
        raise RemoteAPIError(str(exc.reason)) from exc


def post_json(api_key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return post_provider_json(api_key, path, payload, "openai")


def post_provider_json(
    api_key: str, path: str, payload: dict[str, Any], provider: str = "openai"
) -> dict[str, Any]:
    """Invia una richiesta Responses mantenendo uguale il contratto interno."""
    root = DEEPSEEK_API_ROOT if provider == "deepseek" else API_ROOT
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        root + path,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "srt-compass/0.14.1",
        },
        method="POST",
    )
    return _request(request)


def post_transcription(
    api_key: str,
    audio_file: Path,
    language: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    boundary = "----VideoSottotitoli" + uuid.uuid4().hex
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    field("model", "whisper-1")
    if language and language != "auto":
        field("language", language)
    field("response_format", "verbose_json")
    field("timestamp_granularities[]", "word")
    field("timestamp_granularities[]", "segment")
    if prompt:
        field("prompt", prompt)
    content_type = mimetypes.guess_type(audio_file.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{audio_file.name}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            audio_file.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = Request(
        API_ROOT + "/audio/transcriptions",
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "srt-compass/0.14.1",
        },
        method="POST",
    )
    return _request(request)

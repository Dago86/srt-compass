from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import MAX_VIDEO_SECONDS
from .models import AudioTrack, MediaInfo


class MediaError(RuntimeError):
    pass


SUPPORTED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".ogg",
    ".opus", ".wav", ".flac", ".mka",
}


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        for directory in ("/opt/homebrew/bin", "/usr/local/bin"):
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                found = str(candidate)
                break
    if not found:
        raise MediaError(f"{name} non è disponibile. Installa FFmpeg e riprova.")
    return found


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, check=False, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("La verifica del file multimediale non ha risposto entro un minuto.") from exc


def probe_media(path: str | Path) -> MediaInfo:
    video = Path(path).expanduser().resolve()
    if not video.is_file():
        raise MediaError("Il video selezionato non esiste più.")
    if video.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise MediaError("Formato audio/video non supportato.")

    result = _run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(video),
        ]
    )
    if result.returncode:
        raise MediaError(
            "Non riesco a leggere questo video. Potrebbe essere corrotto o protetto."
        )
    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaError("Non riesco a determinare la durata del video.") from exc
    if not 0 < duration <= MAX_VIDEO_SECONDS:
        raise MediaError("Il video deve durare più di zero e non oltre cinque ore.")

    tracks: list[AudioTrack] = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags") or {}
        tracks.append(
            AudioTrack(
                stream_index=int(stream["index"]),
                ordinal=len(tracks),
                language=tags.get("language"),
                title=tags.get("title"),
                codec=stream.get("codec_name"),
            )
        )
    if not tracks:
        raise MediaError("Il video non contiene alcuna traccia audio.")
    return MediaInfo(str(video), duration, tuple(tracks))


def extract_audio_chunk(
    video: str, stream_index: int, start: float, duration: float, destination: Path
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _tool("ffmpeg"),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        video,
        "-map",
        f"0:{stream_index}",
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "64k",
        str(destination),
    ]
    result = _run(command)
    if (
        result.returncode
        or not destination.is_file()
        or destination.stat().st_size == 0
    ):
        destination.unlink(missing_ok=True)
        raise MediaError("Non riesco a estrarre l'audio dal video selezionato.")
    if destination.stat().st_size > 25 * 1024 * 1024:
        destination.unlink(missing_ok=True)
        raise MediaError("Un blocco audio supera il limite di invio di 25 MB.")

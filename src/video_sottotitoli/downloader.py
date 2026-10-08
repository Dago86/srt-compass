from __future__ import annotations

import errno
import fcntl
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import DOWNLOAD_JOBS_DIR, MAX_VIDEO_SECONDS, ensure_app_dirs
from .event_log import EventLog, sanitize_message
from .jobs import atomic_json
from .media import MediaError, probe_media


class DownloadError(RuntimeError):
    pass


DOWNLOAD_IDLE_SECONDS = 120
STOP_GRACE_SECONDS = 10


def _stop_process(process: subprocess.Popen[str], *, force: bool = False) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if process.poll() is not None:
            return
        try:
            (process.kill if force else process.terminate)()
        except ProcessLookupError:
            pass


def _partial_bytes(staging: Path) -> int:
    """Only real file growth counts as network progress."""
    try:
        return sum(path.stat().st_size for path in staging.rglob("*")
                   if path.is_file() and not path.is_symlink()
                   and (path.name.endswith(".part") or path.suffix.casefold()
                        in {".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".ogg"}))
    except OSError:
        return 0


@contextmanager
def _job_lock(job_dir: Path, *, blocking: bool = False):
    """Cross-process exclusion shared by download workers and staging cleanup."""
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_path = job_dir / ".active.lock"
    if lock_path.is_symlink():
        raise DownloadError("Il file di blocco del lavoro non è sicuro.")
    handle = lock_path.open("a+")
    try:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError as exc:
            raise DownloadError("Questo lavoro è attivo in un’altra finestra dell’app.") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _staging_stats(staging: Path) -> tuple[int, int]:
    if not staging.exists():
        return 0, 0
    if staging.is_symlink() or not staging.is_dir():
        raise DownloadError("La cartella temporanea registrata non è sicura da eliminare.")
    files = [path for path in staging.rglob("*") if path.is_file() and not path.is_symlink()]
    return len(files), sum(path.stat().st_size for path in files)


def inspect_download_staging() -> list[dict[str, Any]]:
    """Scansiona tutti i lavori, non soltanto quelli mostrati in Lavori recenti."""
    root = DOWNLOAD_JOBS_DIR.expanduser().resolve()
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for manifest_path in root.glob("*/download.json"):
        job_dir = manifest_path.parent
        record: dict[str, Any] = {"path": manifest_path, "active": False, "files": 0, "bytes": 0, "error": None}
        try:
            if job_dir.is_symlink() or manifest_path.is_symlink():
                raise DownloadError("Registro o cartella del lavoro collegati simbolicamente.")
            with _job_lock(job_dir):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                staging_value = Path(str(manifest.get("staging_dir") or job_dir / "staging"))
                if staging_value.is_symlink():
                    raise DownloadError("Cartella temporanea collegata simbolicamente.")
                staging = staging_value.resolve()
                if staging.parent != job_dir.resolve() or staging.name != "staging":
                    raise DownloadError("La cartella temporanea registrata non è interna al lavoro.")
                record["files"], record["bytes"] = _staging_stats(staging)
        except DownloadError as exc:
            if "attivo in un’altra finestra" in str(exc):
                record["active"] = True
            else:
                record["error"] = str(exc)
        except (OSError, ValueError, TypeError) as exc:
            record["error"] = str(exc)
        if record["files"] or record["active"] or record["error"]:
            records.append(record)
    return records


def cleanup_all_download_staging() -> dict[str, Any]:
    """Elimina gli staging sicuri e inattivi; un errore non ferma gli altri lavori."""
    records = inspect_download_staging()
    removed_files = removed_bytes = cleaned_jobs = skipped_active = 0
    errors: list[str] = []
    for record in records:
        if record["active"]:
            skipped_active += 1
            continue
        if record["error"]:
            errors.append(f"{record['path'].parent.name}: {record['error']}")
            continue
        if not record["files"]:
            continue
        try:
            count, size = cleanup_download_staging(record["path"])
            removed_files += count
            removed_bytes += size
            cleaned_jobs += 1
        except (DownloadError, OSError) as exc:
            if "attivo in un’altra finestra" in str(exc):
                skipped_active += 1
            else:
                errors.append(f"{record['path'].parent.name}: {exc}")
    return {"jobs": cleaned_jobs, "files": removed_files, "bytes": removed_bytes,
            "skipped_active": skipped_active, "errors": errors}


def bundled_binary(name: str) -> str:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.extend(
            [
                Path(getattr(sys, "_MEIPASS", "")) / "bin" / name,
                Path(sys.executable).resolve().parent / "../Resources/bin" / name,
            ]
        )
    candidates.append(Path(__file__).resolve().parents[2] / "vendor" / "macos-arm64" / name)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    found = shutil.which(name)
    if found:
        return found
    raise DownloadError(f"Manca il componente {name}. Reinstalla l’app aggiornata.")


def _clean_page_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path[:240]
    # Keep ordinary page parameters that identify a public item, but never persist
    # likely credentials, signatures, or short-lived media authorization values.
    sensitive = re.compile(
        r"token|sig(nature)?|auth|cookie|pass(word)?|secret|session|credential|expires|key|lsig",
        re.IGNORECASE,
    )
    query = urlencode([
        (key[:80], value[:500])
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if len(key) <= 80 and not sensitive.search(key)
    ])
    return urlunsplit((parsed.scheme, host, path, query, ""))


def resumable_page_url(manifest: dict[str, Any]) -> str:
    """Restituisce un URL di pagina ripulito, ricostruendo i vecchi link YouTube."""
    extractor = str(manifest.get("extractor") or "").casefold()
    source_id = str(manifest.get("source_id") or "").strip()
    if extractor.startswith("youtube") and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", source_id):
        return f"https://www.youtube.com/watch?v={source_id}"
    page_url = str(manifest.get("page_url") or "")
    if not page_url:
        return ""
    try:
        return validate_page_url(page_url)
    except DownloadError:
        return ""


def validate_page_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise DownloadError("Inserisci un indirizzo web che inizi con http:// o https://.")
    if parsed.username or parsed.password:
        raise DownloadError("Rimuovi nome utente e password dal link.")
    if len(url) > 4096:
        raise DownloadError("Il link è troppo lungo.")
    return url


_MEDIA_EXTENSIONS = {".mkv", ".mp4", ".webm", ".m4a", ".mp3", ".opus", ".mov", ".avi"}


def safe_output_stem(value: str) -> str:
    """Normalizza il nome inserito senza interpretarlo come un percorso."""
    name = str(value or "").strip()
    name = name.replace("/", " ").replace("\\", " ")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if Path(name).suffix.casefold() in _MEDIA_EXTENSIONS:
        name = name[: -len(Path(name).suffix)].rstrip(" .")
    name = name[:180].rstrip(" .")
    if not name or name in {".", ".."}:
        raise DownloadError("Inserisci un nome valido per il file scaricato.")
    return name


def safe_output_name(value: str, extension: str) -> str:
    """Restituisce un nome semplice, senza percorso, conservando Unicode."""
    name = safe_output_stem(value)
    ext = extension.strip().lstrip(".")
    if not ext or not re.fullmatch(r"[A-Za-z0-9]{1,10}", ext):
        raise DownloadError("Il formato del file scaricato non è riconoscibile.")
    return f"{name}.{ext.lower()}"


def cleanup_download_staging(manifest_path: Path) -> tuple[int, int]:
    """Elimina solo lo staging del lavoro selezionato, lasciando registro e log."""
    manifest_path = manifest_path.expanduser().resolve()
    root = DOWNLOAD_JOBS_DIR.expanduser().resolve()
    try:
        job_dir = manifest_path.parent
        job_dir.relative_to(root)
    except ValueError as exc:
        raise DownloadError("Il registro non appartiene a un lavoro di download valido.") from exc
    if manifest_path.name != "download.json" or not manifest_path.is_file():
        raise DownloadError("Il registro del download non è disponibile.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DownloadError("Il registro del download non è leggibile.") from exc
    with _job_lock(job_dir):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        staging_value = Path(str(manifest.get("staging_dir") or job_dir / "staging"))
        if staging_value.is_symlink():
            raise DownloadError("La cartella temporanea registrata non è sicura da eliminare.")
        staging = staging_value.expanduser().resolve()
        if staging.parent != job_dir or staging.name != "staging":
            raise DownloadError("La cartella temporanea registrata non è sicura da eliminare.")
        count, size = _staging_stats(staging)
        if count or staging.exists():
            shutil.rmtree(staging)
        if manifest.get("status") == "downloading":
            manifest["status"] = "cancelled"
        manifest["temporary_files_removed_at"] = time.time()
        atomic_json(manifest_path, manifest)
        EventLog(job_dir, lambda *_: None, "pulizia download").write(
            f"Eliminati {count} file temporanei ({size} byte). Ripresa dai parziali non più disponibile.",
            level="WARNING",
        )
        return count, size


def _safe_int(value: object) -> int | None:
    try:
        number = int(value) if value is not None else None
    except (TypeError, ValueError):
        number = _safe_float(value)
    return int(number) if number is not None and number >= 0 else None


def _safe_float(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
        return number if number is not None and math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _stream_info(path: Path) -> tuple[set[str], float] | None:
    """Legge tipi di flusso e durata senza richiedere una traccia audio."""
    from .media import _tool

    try:
        result = subprocess.run(
            [_tool("ffprobe"), "-v", "error", "-show_entries",
             "format=duration:stream=codec_type", "-of", "json", str(path)],
            text=True, capture_output=True, check=False, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode:
        return None
    try:
        info = json.loads(result.stdout)
        types = {stream["codec_type"] for stream in info["streams"]}
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return (types, duration) if duration > 0 else None


def parse_info(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("_type") in {"playlist", "multi_video"}:
        raise DownloadError("I link a playlist o canali non sono supportati.")
    if raw.get("is_live") or raw.get("live_status") in {"is_live", "is_upcoming"}:
        raise DownloadError("Sono supportati solo contenuti registrati e già pubblicati.")
    duration = _safe_float(raw.get("duration"))
    if duration is None or duration <= 0 or duration > MAX_VIDEO_SECONDS:
        raise DownloadError("La durata deve essere nota e non superare cinque ore.")

    formats: list[dict[str, Any]] = []
    languages: dict[str, str] = {}
    for item in raw.get("formats") or []:
        if not isinstance(item, dict):
            continue
        format_id = str(item.get("format_id") or "")
        if not format_id:
            continue
        audio = item.get("acodec") not in {None, "none"}
        video = item.get("vcodec") not in {None, "none"}
        language = str(item.get("language") or "").strip()
        if language and not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", language):
            language = ""
        if audio and language:
            languages.setdefault(language, language)
        formats.append(
            {
                "format_id": format_id,
                "ext": str(item.get("ext") or ""),
                "height": _safe_int(item.get("height")),
                "audio": audio,
                "video": video,
                "language": language or None,
                "size": _safe_int(item.get("filesize") or item.get("filesize_approx")),
            }
        )
    source_id = str(raw.get("id") or "")
    extractor = str(raw.get("extractor_key") or raw.get("extractor") or "")
    page_url = str(raw.get("webpage_url") or raw.get("original_url") or "")
    if extractor.casefold().startswith("youtube") and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", source_id):
        page_url = f"https://www.youtube.com/watch?v={source_id}"
    elif page_url:
        page_url = _clean_page_url(page_url)
    return {
        "id": source_id,
        "extractor": extractor,
        "title": sanitize_message(raw.get("title") or "Video senza titolo")[:180],
        "site": sanitize_message(raw.get("extractor_key") or raw.get("extractor") or "Sito non identificato"),
        "duration": duration,
        "page_url": page_url,
        "formats": formats,
        "audio_languages": list(languages),
        "size": _safe_int(raw.get("filesize") or raw.get("filesize_approx")),
    }


def _selector(quality: str, audio_language: str | None) -> str:
    if quality == "audio":
        if audio_language:
            return f"bestaudio[language={audio_language}]/bestaudio"
        return "bestaudio/best"
    maximum = {"720p": 720, "1080p": 1080}.get(quality)
    if maximum is None:
        return "bestvideo+bestaudio/best"
    audio = f"bestaudio[language={audio_language}]/bestaudio" if audio_language else "bestaudio"
    return f"bestvideo[height<={maximum}]+{audio}/best[height<={maximum}]"


def effective_quality(metadata: dict[str, Any], quality: str) -> str:
    """Describe the best known resolution the selected format can produce."""
    if quality == "audio":
        return "Solo audio"
    heights = [
        int(item["height"])
        for item in metadata.get("formats", [])
        if item.get("video") and item.get("height")
    ]
    if not heights:
        return "risoluzione non dichiarata dal sito"
    limit = {"720p": 720, "1080p": 1080}.get(quality)
    eligible = [height for height in heights if limit is None or height <= limit]
    if not eligible:
        return "nessun formato conforme al limite scelto"
    height = max(eligible)
    return f"fino a {height}p"


def validate_selected_format(
    metadata: dict[str, Any], quality: str, audio_language: str | None = None
) -> None:
    formats = metadata.get("formats") or []
    if not formats:
        return
    if quality == "audio":
        if not any(
            item.get("audio") and (
                not audio_language or item.get("language") == audio_language
            ) for item in formats
        ):
            raise DownloadError(
                "La traccia audio selezionata non è più disponibile. Scegline un’altra e analizza di nuovo."
            )
        return
    limit = {"720p": 720, "1080p": 1080}.get(quality)
    eligible_video = [
        item for item in formats if item.get("video")
        and (limit is None or not item.get("height") or item["height"] <= limit)
    ]
    combined = any(
        item.get("video") and item.get("audio")
        and (limit is None or not item.get("height") or item["height"] <= limit)
        for item in formats
    )
    eligible_audio = any(
        item.get("audio") and (not audio_language or item.get("language") == audio_language)
        for item in formats
    )
    if not combined and not (eligible_video and eligible_audio):
        raise DownloadError(
            "Il formato salvato non è più disponibile sul sito. Scegli una qualità diversa, "
            "poi avvia un nuovo download per non riutilizzare parziali incompatibili."
        )


def _reader(stream: Any, name: str, events: queue.Queue[tuple[str, str]]) -> None:
    try:
        for line in iter(stream.readline, ""):
            events.put((name, line.rstrip("\r\n")))
    finally:
        events.put((name, "__EOF__"))


class DownloadWorker(threading.Thread):
    def __init__(
        self,
        url: str,
        *,
        operation: str = "analyze",
        job_dir: Path | None = None,
        destination_dir: Path | None = None,
        quality: str = "1080p",
        audio_language: str | None = None,
        output_name: str | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.url = validate_page_url(url)
        self.operation = operation
        self.job_dir = job_dir
        self.destination_dir = destination_dir
        self.quality = quality
        self.audio_language = audio_language
        self.output_name = output_name
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancelled = threading.Event()
        self.process: subprocess.Popen[str] | None = None
        self.event_log: EventLog | None = None
        self._stop_requested_at: float | None = None

    def cancel(self) -> None:
        self.cancelled.set()
        self._event("status", "Interruzione richiesta: fermo il download…")
        process = self.process
        if process and process.poll() is None:
            self._stop_requested_at = time.monotonic()
            _stop_process(process)

    def _event(self, kind: str, value: Any) -> None:
        self.events.put((kind, value))

    def run(self) -> None:
        try:
            lock = (
                _job_lock(self.job_dir)
                if self.job_dir and self.job_dir.joinpath("download.json").is_file()
                else nullcontext()
            )
            with lock:
                if self.operation == "analyze":
                    self._analyze()
                elif self.operation == "download":
                    self._download()
                else:
                    raise DownloadError("Operazione di download sconosciuta.")
        except Exception as exc:  # noqa: BLE001 - l'interfaccia mostra un errore guidato
            self._save_failure_state()
            if self.event_log:
                self.event_log.write(exc, level="ERROR")
            self._event("error", self._friendly_error(exc))

    def _save_failure_state(self) -> None:
        if not self.job_dir:
            return
        path = self.job_dir / "download.json"
        if not path.is_file():
            return
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("status") not in {"completed", "cancelled"}:
                manifest["status"] = "error"
                manifest["failure_reason"] = "download_error"
                atomic_json(path, manifest)
        except (OSError, ValueError):
            return

    def _analyze(self) -> None:
        self._event("status", "Analizzo il link…")
        command = [
            bundled_binary("yt-dlp_macos"), "--js-runtimes",
            f"deno:{bundled_binary('deno')}", "--ignore-config", "--no-plugin-dirs",
            "--no-playlist", "--no-warnings", "--socket-timeout", "30",
            "--retries", "3", "--fragment-retries", "3",
            "--dump-single-json", self.url,
        ]
        result = self._run_capture(command, timeout=180)
        if result is None:
            self._event("cancelled", "Analisi interrotta.")
            return
        stdout, stderr, return_code = result
        if return_code:
            raise DownloadError(self._classify_stderr(stderr))
        try:
            metadata = parse_info(json.loads(stdout))
        except (json.JSONDecodeError, TypeError) as exc:
            raise DownloadError("Il sito non ha restituito metadati leggibili.") from exc
        ensure_app_dirs()
        if self.job_dir and (self.job_dir / "download.json").is_file():
            manifest = json.loads((self.job_dir / "download.json").read_text(encoding="utf-8"))
            if manifest.get("source_id") and manifest["source_id"] != metadata.get("id"):
                raise DownloadError("Il link non corrisponde al lavoro di download salvato.")
            manifest["page_url"] = metadata.get("page_url") or manifest.get("page_url")
            manifest["title"] = metadata.get("title") or manifest.get("title")
            atomic_json(self.job_dir / "download.json", manifest)
            self.event_log = EventLog(self.job_dir, self._event, "analisi link")
            self.event_log.write("Link verificato per la ripresa del download.")
        else:
            self.job_dir = DOWNLOAD_JOBS_DIR / str(uuid.uuid4())
            self.job_dir.mkdir(parents=True, exist_ok=False)
            manifest = {
                "version": 1,
                "status": "analyzed",
                "source_id": metadata.get("id"),
                "extractor": metadata.get("extractor"),
                "page_url": metadata.get("page_url"),
                "filename_template": "download-%(id)s.%(ext)s",
                "title": metadata.get("title"),
                "output_name": None,
                "duration": metadata.get("duration"),
                "created_at": time.time(),
                "yt_dlp_version": "2026.08.19",
                "deno_version": "2.9.7",
            }
            atomic_json(self.job_dir / "download.json", manifest)
            self.event_log = EventLog(self.job_dir, self._event, "analisi link")
            self.event_log.write("Analisi del link completata; nessun media scaricato.")
        metadata["job_dir"] = str(self.job_dir)
        self._event("job", {"job_dir": str(self.job_dir), "log_path": str(self.event_log.path)})
        self._event("analysis", metadata)

    def _new_job(self, metadata: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        ensure_app_dirs()
        job_dir = self.job_dir or DOWNLOAD_JOBS_DIR / str(uuid.uuid4())
        job_dir.mkdir(parents=True, exist_ok=True)
        saved_path = job_dir / "download.json"
        if saved_path.is_file():
            manifest = json.loads(saved_path.read_text(encoding="utf-8"))
            was_analyzed = manifest.get("status") == "analyzed"
            previous_quality = manifest.get("quality")
            previous_audio_language = manifest.get("audio_language")
            manifest["status"] = "downloading"
            manifest["resumed_at"] = time.time()
            staging_dir = Path(manifest.get("staging_dir") or job_dir / "staging")
            partials = list(staging_dir.rglob("*.part")) if staging_dir.exists() else []
            if (not was_analyzed and partials and (
                previous_quality != self.quality
                or previous_audio_language != self.audio_language
            )):
                raise DownloadError(
                    "Qualità o traccia audio diversa dai parziali salvati. "
                    "Usa «Nuovo download» per ricominciare senza cancellare questo lavoro."
                )
            manifest["quality"] = self.quality
            manifest["audio_language"] = self.audio_language
            if self.destination_dir:
                manifest["destination_dir"] = str(self.destination_dir.resolve())
            if self.output_name is not None:
                manifest["output_name"] = self.output_name
            manifest.setdefault("staging_dir", str((job_dir / "staging").resolve()))
            manifest.setdefault("destination_dir", str((Path.home() / "Downloads" / "SRT Compass").resolve()))
            manifest.setdefault(
                "filename_template",
                "download-%(id)s.%(ext)s" if was_analyzed
                else "%(title).120B [%(id)s].%(ext)s",
            )
            if manifest.get("source_id") and manifest["source_id"] != metadata.get("id"):
                raise DownloadError("Il link non corrisponde al lavoro di download salvato.")
            manifest["page_url"] = metadata.get("page_url") or manifest.get("page_url")
            if was_analyzed:
                manifest["title"] = metadata.get("title") or manifest.get("title")
            atomic_json(saved_path, manifest)
            self.job_dir = job_dir
            self.event_log = EventLog(job_dir, self._event, "download")
            self.event_log.write("Riprendo il download salvato.")
            self._event("job", {"job_dir": str(job_dir), "log_path": str(self.event_log.path)})
            return job_dir, manifest
        manifest: dict[str, Any] = {
            "version": 1,
            "status": "downloading",
            "source_id": metadata.get("id"),
            "extractor": metadata.get("extractor"),
            "page_url": metadata.get("page_url"),
            "title": metadata.get("title"),
            "output_name": self.output_name,
            "duration": metadata.get("duration"),
            "quality": self.quality,
            "audio_language": self.audio_language,
            "destination_dir": str((self.destination_dir or Path.home() / "Downloads" / "SRT Compass").resolve()),
            "staging_dir": str((job_dir / "staging").resolve()),
            "filename_template": "download-%(id)s.%(ext)s",
            "created_at": time.time(),
            "yt_dlp_version": "2026.08.19",
            "deno_version": "2.9.7",
        }
        atomic_json(job_dir / "download.json", manifest)
        self.job_dir = job_dir
        self.event_log = EventLog(job_dir, self._event, "download")
        self.event_log.write("Download avviato.")
        self._event("job", {"job_dir": str(job_dir), "log_path": str(self.event_log.path)})
        return job_dir, manifest

    def _download(self) -> None:
        try:
            from .media import _tool

            ffmpeg_binary = _tool("ffmpeg")
            _tool("ffprobe")
        except MediaError as exc:
            raise DownloadError(str(exc)) from exc
        self._event("status", "Aggiorno i metadati prima del download…")
        info_command = [
            bundled_binary("yt-dlp_macos"), "--js-runtimes",
            f"deno:{bundled_binary('deno')}", "--ignore-config", "--no-plugin-dirs",
            "--no-playlist", "--no-warnings", "--socket-timeout", "30",
            "--retries", "3", "--fragment-retries", "3",
            "--dump-single-json", self.url,
        ]
        info_run = self._run_capture(info_command, timeout=180)
        if info_run is None:
            self._event("cancelled", "Analisi interrotta.")
            return
        info_stdout, info_stderr, info_code = info_run
        if info_code:
            raise DownloadError(self._classify_stderr(info_stderr))
        try:
            metadata = parse_info(json.loads(info_stdout))
        except (json.JSONDecodeError, TypeError) as exc:
            raise DownloadError("Il sito non ha restituito metadati leggibili.") from exc

        job_dir, manifest = self._new_job(metadata)
        validate_selected_format(metadata, self.quality, self.audio_language)
        destination = Path(manifest["destination_dir"])
        destination.mkdir(parents=True, exist_ok=True)
        staging = Path(manifest["staging_dir"])
        staging.mkdir(parents=True, exist_ok=True)
        if manifest.get("status") == "downloading":
            recovered = self._find_completed_staging_file(staging, manifest)
            if not recovered:
                recovered = self._merge_separate_streams(staging, manifest)
            if self.cancelled.is_set():
                manifest["status"] = "cancelled"
                manifest["failure_reason"] = "user_cancelled"
                atomic_json(job_dir / "download.json", manifest)
                self._event("cancelled", str(job_dir))
                return
            if recovered:
                self._publish(recovered, destination, job_dir, manifest)
                return
        manifest["status"] = "downloading"
        atomic_json(job_dir / "download.json", manifest)

        command = [
            bundled_binary("yt-dlp_macos"), "--js-runtimes",
            f"deno:{bundled_binary('deno')}", "--ignore-config", "--no-plugin-dirs",
            "--no-playlist", "--no-warnings", "--socket-timeout", "30",
            "--retries", "3", "--fragment-retries", "3",
            "--newline", "--progress", "--progress-delta", "1",
            "--progress-template",
            "download:VSTT|download|%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(progress.fragment_index)s|%(progress.fragment_count)s|%(info_dict.vcodec)s",
            "--progress-template",
            "postprocess:VSTT|postprocess|%(progress.status)s|0|0|0|0|0|0|0|NA",
            "--format", _selector(self.quality, self.audio_language),
            "--ffmpeg-location", ffmpeg_binary,
            "--no-overwrites", "--continue", "--paths", f"home:{staging}",
            "--paths", f"temp:{staging}", "--output",
            manifest.get("filename_template", "%(title).120B [%(id)s].%(ext)s"),
            "--print", "after_move:filepath",
            "--merge-output-format", "mkv", self.url,
        ]
        self.event_log.write("Download multimediale in corso.")
        self._event("status", "Download in corso…")
        final_paths: list[str] = []
        for attempt in range(2):
            manifest["transfer_attempt"] = attempt + 1
            manifest["failure_reason"] = None
            atomic_json(job_dir / "download.json", manifest)
            return_code, paths, error_lines, stalled = self._transfer_attempt(
                command, staging, job_dir, manifest
            )
            final_paths.extend(paths)
            if self.cancelled.is_set():
                break
            if return_code == 0:
                break
            transient = (stalled and "local postprocess timeout" not in error_lines) or any(
                term in "\n".join(error_lines).lower()
                for term in ("timed out", "timeout", "network", "connection reset", "temporarily unavailable")
            )
            if transient and attempt == 0:
                manifest["failure_reason"] = "no_bytes" if stalled else "network_error"
                atomic_json(job_dir / "download.json", manifest)
                self.event_log.write("Trasferimento fermo; un solo riavvio automatico con i parziali.", level="WARNING")
                self._event("status", "Il trasferimento non avanza. Riprovo una volta usando i parziali…")
                continue
            break
        if self.cancelled.is_set():
            manifest["status"] = "cancelled"
            manifest["failure_reason"] = "user_cancelled"
            atomic_json(job_dir / "download.json", manifest)
            self.event_log.write("Download interrotto dall’utente.", level="WARNING")
            self._event("cancelled", str(job_dir))
            return
        if return_code:
            manifest["status"] = "error"
            manifest["failure_reason"] = "no_bytes" if stalled else "transfer_failed"
            atomic_json(job_dir / "download.json", manifest)
            if stalled:
                if "local postprocess timeout" in error_lines:
                    raise DownloadError("L'unione non è terminata entro 15 minuti. I file scaricati restano disponibili per Riprendi.")
                raise DownloadError("Il download non ha ricevuto nuovi dati per due minuti, anche dopo un tentativo automatico. Premi Riprendi per continuare dai parziali.")
            raise DownloadError(self._classify_stderr("\n".join(error_lines)))
        if not final_paths:
            final_paths = [str(path) for path in staging.rglob("*") if path.is_file() and not path.name.endswith(".part")]
        final_path = Path(final_paths[-1]).resolve() if final_paths else None
        if final_path and final_path.is_file() and final_path.stat().st_size:
            stream_info = _stream_info(final_path)
            if (stream_info is None or "audio" not in stream_info[0]
                    or (self.quality != "audio" and "video" not in stream_info[0])):
                final_path = None
        else:
            final_path = None
        if not final_path:
            final_path = self._find_completed_staging_file(staging, manifest)
        if not final_path:
            final_path = self._merge_separate_streams(staging, manifest)
        if not final_path:
            raise DownloadError("Il download è terminato ma il file finale non è stato trovato.")
        self._publish(final_path, destination, job_dir, manifest)

    def _transfer_attempt(
        self, command: list[str], staging: Path, job_dir: Path,
        manifest: dict[str, Any],
    ) -> tuple[int, list[str], list[str], bool]:
        self.process = subprocess.Popen(
            command, cwd=staging, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=1, start_new_session=True,
        )
        process = self.process
        assert process.stdout and process.stderr
        output_events: queue.Queue[tuple[str, str]] = queue.Queue()
        readers = [
            threading.Thread(target=_reader, args=(process.stdout, "stdout", output_events), daemon=True),
            threading.Thread(target=_reader, args=(process.stderr, "stderr", output_events), daemon=True),
        ]
        for reader in readers:
            reader.start()
        finished_streams: set[str] = set()
        final_paths: list[str] = []
        error_lines: list[str] = []
        last_bytes = _partial_bytes(staging)
        last_growth = time.monotonic()
        stopped_at: float | None = None
        exited_at: float | None = None
        stalled = False
        postprocess_started: float | None = None
        try:
            while True:
                now = time.monotonic()
                current_bytes = _partial_bytes(staging)
                if current_bytes > last_bytes:
                    last_bytes = current_bytes
                    last_growth = now
                    manifest["last_progress_at"] = time.time()
                    manifest["received_bytes"] = current_bytes
                    atomic_json(job_dir / "download.json", manifest)
                elif current_bytes < last_bytes:
                    # yt-dlp may rename a completed .part before starting the next stream.
                    last_bytes = current_bytes
                    last_growth = now
                if process.poll() is None:
                    timed_out = (now - postprocess_started >= 900 if postprocess_started is not None
                                 else now - last_growth >= DOWNLOAD_IDLE_SECONDS)
                    if (self.cancelled.is_set() or timed_out) and stopped_at is None:
                        stalled = not self.cancelled.is_set()
                        stopped_at = now
                        if stalled:
                            message = ("Unione non conclusa entro 15 minuti." if postprocess_started is not None
                                       else "Nessun nuovo byte da due minuti.")
                            if postprocess_started is not None:
                                error_lines.append("local postprocess timeout")
                            self.event_log.write(message + " Termino il processo.", level="WARNING")
                            self._event("status", message + " Arresto il processo…")
                        _stop_process(process)
                    if stopped_at is not None and now - stopped_at >= STOP_GRACE_SECONDS:
                        _stop_process(process, force=True)
                elif exited_at is None:
                    exited_at = now
                try:
                    stream_name, line = output_events.get(timeout=0.2)
                except queue.Empty:
                    if process.poll() is not None and (len(finished_streams) == 2 or
                            (exited_at is not None and now - exited_at >= 2)):
                        break
                    continue
                if line == "__EOF__":
                    finished_streams.add(stream_name)
                elif line.startswith("VSTT|"):
                    if line.startswith("VSTT|postprocess|") and postprocess_started is None:
                        postprocess_started = now
                    self._parse_progress(line)
                elif stream_name == "stdout":
                    if line and Path(line).is_absolute():
                        final_paths.append(line)
                elif line.strip():
                    error_lines.append(line.strip())
                    error_lines = error_lines[-20:]
                if process.poll() is not None and len(finished_streams) == 2 and output_events.empty():
                    break
            if process.poll() is None:
                _stop_process(process, force=True)
            try:
                return_code = process.wait(timeout=STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired as exc:
                _stop_process(process, force=True)
                raise DownloadError("Il processo di download non si è chiuso correttamente.") from exc
            return return_code, final_paths, error_lines, stalled
        finally:
            if process.poll() is None:
                _stop_process(process, force=True)
                try:
                    process.wait(timeout=STOP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
            # Reader threads are daemonized. Closing a TextIOWrapper while a reader
            # holds its lock can itself block when a descendant kept the pipe open.
            for reader, pipe in zip(readers, (process.stdout, process.stderr), strict=True):
                reader.join(timeout=0.1)
                if not reader.is_alive() and pipe:
                    pipe.close()
            self.process = None

    def _merge_separate_streams(
        self, staging: Path, manifest: dict[str, Any]
    ) -> Path | None:
        """Recupera localmente un video e un audio già scaricati da yt-dlp."""
        from .media import _tool

        source_id = str(manifest.get("source_id") or "")
        if not source_id:
            return None
        video_files: list[tuple[Path, float]] = []
        audio_files: list[tuple[Path, float]] = []
        for path in staging.rglob("*"):
            if (not path.is_file() or source_id not in path.name
                    or path.name.endswith(".part")
                    or path.suffix.casefold() not in {".mp4", ".webm", ".m4a", ".mp3", ".opus"}):
                continue
            info = _stream_info(path)
            if info is None:
                continue
            types, duration = info
            if types == {"video"}:
                video_files.append((path, duration))
            elif types == {"audio"}:
                audio_files.append((path, duration))
        if len(video_files) != 1 or len(audio_files) != 1:
            return None
        if abs(video_files[0][1] - audio_files[0][1]) > 2:
            raise DownloadError("I flussi completi hanno durate diverse; non li unisco automaticamente.")
        output = staging / "recovered-media.mkv"
        if output.exists():
            raise DownloadError(
                "Esiste già un file di recupero. Verifica i file temporanei prima di riprovare."
            )
        command = (
            [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
             "-n", "-i", str(video_files[0][0]), "-i", str(audio_files[0][0]),
             "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(output)]
        )
        self.process = subprocess.Popen(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        process = self.process
        started = time.monotonic()
        stopped_at: float | None = None
        timed_out = False
        try:
            while True:
                try:
                    _stdout, _stderr = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    now = time.monotonic()
                    if self.cancelled.is_set() or now - started >= 900:
                        timed_out = not self.cancelled.is_set()
                        if stopped_at is None:
                            stopped_at = now
                            _stop_process(process)
                        elif now - stopped_at >= STOP_GRACE_SECONDS:
                            _stop_process(process, force=True)
                        if stopped_at is not None and now - stopped_at >= 2 * STOP_GRACE_SECONDS:
                            raise DownloadError("Il processo di unione non si è chiuso correttamente.")
        finally:
            self.process = None
        if self.cancelled.is_set():
            output.unlink(missing_ok=True)
            return None
        if timed_out:
            raise DownloadError("L'unione ha superato 15 minuti; i flussi scaricati restano disponibili.")
        if process.returncode or not output.is_file() or not output.stat().st_size:
            raise DownloadError(
                "Audio e video sono scaricati, ma FFmpeg non è riuscito a unirli. "
                "I file temporanei sono conservati per la ripresa."
            )
        if self.event_log:
            self.event_log.write("Flussi audio e video completi uniti localmente con FFmpeg.")
        self._event("status", "Completo localmente il video scaricato…")
        return output

    def _find_completed_staging_file(
        self, staging: Path, manifest: dict[str, Any]
    ) -> Path | None:
        source_id = str(manifest.get("source_id") or "")
        candidates = sorted(
            (path for path in staging.rglob("*")
             if path.is_file() and not path.name.endswith(".part")
             and ((source_id and source_id in path.name)
                  or path.name == "recovered-media.mkv")
             and path.suffix.casefold() in {".mkv", ".mp4", ".webm", ".m4a", ".mp3", ".opus"}),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            info = _stream_info(candidate)
            if info is None or "audio" not in info[0]:
                continue
            if self.quality != "audio" and "video" not in info[0]:
                continue
            try:
                media = probe_media(candidate)
            except MediaError:
                continue
            if media.duration > 0 and media.audio_tracks:
                self._event("status", "Riprendo dalla verifica del file già scaricato…")
                if self.event_log:
                    self.event_log.write("Trovato un file completo in staging; salto il download.")
                return candidate
        return None

    def _publish(
        self, final_path: Path, destination: Path, job_dir: Path,
        manifest: dict[str, Any],
    ) -> None:
        final_path = final_path.resolve()
        if not final_path.is_file() or not final_path.stat().st_size:
            raise DownloadError("Il file finale non è presente o è vuoto.")
        try:
            media = probe_media(final_path)
        except MediaError as exc:
            raise DownloadError(f"File scaricato non valido: {exc}") from exc
        destination.mkdir(parents=True, exist_ok=True)
        output_name = manifest.get("output_name")
        if output_name:
            filename = safe_output_name(str(output_name), final_path.suffix)
        else:
            # I lavori preesistenti mantengono il nome prodotto dalla versione
            # yt-dlp con cui erano stati creati.
            filename = final_path.name
        stem, suffix = Path(filename).stem, Path(filename).suffix
        index = 1
        while True:
            candidate_name = filename if index == 1 else f"{stem} ({index}){suffix}"
            published = destination / candidate_name
            try:
                os.link(final_path, published)
                break
            except FileExistsError:
                index += 1
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                # La destinazione può trovarsi su un volume diverso: la
                # creazione esclusiva evita comunque di sovrascrivere file.
                try:
                    with published.open("xb") as output, final_path.open("rb") as source:
                        shutil.copyfileobj(source, output)
                except FileExistsError:
                    index += 1
                    continue
                except Exception:
                    published.unlink(missing_ok=True)
                    raise
                break
        final_path.unlink()
        # `media` was probed before the move. Its old path now points into staging,
        # so carry forward the same metadata with the published path instead.
        media = replace(media, path=str(published.resolve()))
        manifest.update({
            "status": "completed", "output": str(published),
            "actual_duration": media.duration,
        })
        atomic_json(job_dir / "download.json", manifest)
        self.event_log.write("File verificato e pubblicato nella destinazione scelta.")
        self._event("progress", {"stage": "verifica", "percent": 100})
        self._event("complete", {"path": str(published), "media": media, "job_dir": str(job_dir)})

    def _parse_progress(self, line: str) -> None:
        parts = line.split("|")
        fragment_index = fragment_count = None
        codec = None
        if len(parts) == 11:
            (_, stage, status, downloaded, total_bytes, total_estimate,
             speed, eta, fragment_index, fragment_count, codec) = parts
            total = _safe_int(total_bytes) or _safe_int(total_estimate)
            total_is_estimate = not bool(_safe_int(total_bytes)) and bool(
                _safe_int(total_estimate)
            )
        elif len(parts) == 10:
            (_, stage, status, downloaded, total_bytes, total_estimate,
             speed, eta, fragment_index, fragment_count) = parts
            total = _safe_int(total_bytes) or _safe_int(total_estimate)
            total_is_estimate = not bool(_safe_int(total_bytes)) and bool(
                _safe_int(total_estimate)
            )
        elif len(parts) == 8:
            _, stage, status, downloaded, total_bytes, total_estimate, speed, eta = parts
            total = _safe_int(total_bytes) or _safe_int(total_estimate)
            total_is_estimate = not bool(_safe_int(total_bytes)) and bool(
                _safe_int(total_estimate)
            )
        elif len(parts) == 7:  # compatibilità con il vecchio formato di progresso
            _, stage, status, downloaded, total_value, speed, eta = parts
            total = _safe_int(total_value)
            total_is_estimate = bool(total)
        else:
            return
        progress = {
            "stage": stage,
            "status": status,
            "downloaded": _safe_int(downloaded),
            "total": total,
            "total_is_estimate": total_is_estimate,
            "speed": _safe_float(speed),
            "eta": _safe_float(eta),
            "fragment_index": _safe_int(fragment_index),
            "fragment_count": _safe_int(fragment_count),
            "stream": "audio" if codec == "none" else "video" if codec and codec != "NA" else None,
        }
        self._event("progress", progress)

    @staticmethod
    def _classify_stderr(stderr: str) -> str:
        low = stderr.lower()
        if "unsupported url" in low or "no suitable extractor" in low:
            return "Questo sito o formato di link non è supportato da questa versione."
        if "private video" in low or "login" in low or "sign in" in low:
            return "Il contenuto richiede accesso. Questa versione scarica solo contenuti pubblici."
        if "video unavailable" in low or "not available" in low:
            return "Il contenuto è rimosso, non disponibile o non accessibile."
        if "ffmpeg" in low or "ffprobe" in low:
            return "FFmpeg o ffprobe non è disponibile. Installa la dipendenza e riprova."
        if "disk is full" in low or "no space left" in low:
            return "Lo spazio libero sul disco non è sufficiente."
        if "timed out" in low or "network" in low or "connection" in low:
            return "Problema di rete durante l’accesso al sito. Verifica la connessione e riprova."
        return "Il sito ha rifiutato o interrotto il download. Consulta il log e riprova più tardi."

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, DownloadError):
            return str(exc)
        if isinstance(exc, subprocess.TimeoutExpired):
            return "Il sito non ha risposto in tempo. Verifica la connessione e riprova."
        return "Operazione non riuscita. Consulta il log diagnostico del lavoro."

    def _run_capture(
        self, command: list[str], *, timeout: float
    ) -> tuple[str, str, int] | None:
        self.process = subprocess.Popen(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        started = time.monotonic()
        stop_at: float | None = None
        expired = False
        try:
            while True:
                try:
                    stdout, stderr = self.process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    now = time.monotonic()
                    if self.cancelled.is_set() or now - started >= timeout:
                        expired = not self.cancelled.is_set()
                        if stop_at is None:
                            stop_at = now
                            _stop_process(self.process)
                        elif now - stop_at >= STOP_GRACE_SECONDS:
                            _stop_process(self.process, force=True)
                        if stop_at is not None and now - stop_at >= 2 * STOP_GRACE_SECONDS:
                            raise DownloadError("Il processo di analisi non si è chiuso correttamente.")
            if expired:
                raise DownloadError("Il sito non ha risposto in tempo. Verifica la connessione.")
        finally:
            process = self.process
            self.process = None
        if self.cancelled.is_set():
            return None
        return stdout, stderr, process.returncode if process else 1

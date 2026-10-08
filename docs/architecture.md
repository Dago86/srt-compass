# Architecture — SRT Compass 0.13.0

SRT Compass is a Python 3.11+ macOS application built with Tkinter. Long-running
media, network and file operations execute outside the Tk event loop and report
events through queues. Only the main thread updates widgets.

## Main components

- `gui.py` owns the main window, dialogs, state transitions and result actions.
- `i18n.py` owns English and Italian catalogs, macOS language detection and the
  persisted UI preference. Interface labels never act as business identifiers.
- `media.py`, `transcription.py` and `worker.py` probe media, prepare audio and
  create resumable transcription jobs.
- `revision.py` and `revision_worker.py` estimate, translate and revise SRT text.
- `downloader.py` wraps the bundled yt-dlp and Deno executables and validates
  completed media with ffprobe.
- `readability.py` locally splits long cues without an API request.

Language codes (`auto`, `original`, `en`, `it`, `ja`, `fr`) are stable values in
jobs and model requests. Their visible labels come from the active catalog.

## Persistence and compatibility

For upgrade compatibility, application data remains in
`~/Library/Application Support/VideoSottotitoli/` and the OpenAI key remains in
the legacy `VideoSottotitoli` Keychain service. `preferences.json` stores only
interface preferences, currently `ui_locale`.

Transcription, revision and download jobs use separate subdirectories. A resume
always uses the settings saved in its manifest. Logs are diagnostic data and do
not replace manifest state.

## Packaging

`build-mac-app.sh` creates `SRT Compass.app` and `SRT Compass 0.13.0.dmg` while
retaining the existing bundle identifier for upgrade compatibility. yt-dlp and
Deno are fetched from pinned upstream versions and checksum-verified. FFmpeg and
ffprobe remain external prerequisites.

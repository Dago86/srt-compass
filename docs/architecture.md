# Architecture — SRT Compass 0.16.4

## Text providers

Subtitle translation and contextual revision use a provider adapter boundary. The
OpenAI adapter remains the default; the DeepSeek adapter targets its Responses
endpoint and returns the same structured subtitle contract, usage shape and
validation inputs. Provider, model, pricing and reasoning parameters are saved
in each revision manifest so resume never silently changes service. Whisper
transcription and the TXT web brief remain OpenAI-only.

SRT Compass is a Python 3.11+ cross-platform application built with Tkinter. Long-running
media, network and file operations execute outside the Tk event loop and report
events through queues. Only the main thread updates widgets.

## Main components

- `gui.py` owns the main window, dialogs, state transitions and result actions.
- `i18n.py` owns English and Italian catalogs, system language detection and the
  persisted UI preference. Interface labels never act as business identifiers.
- `media.py`, `transcription.py` and `worker.py` probe media, prepare audio and
  create resumable transcription jobs.
- `revision.py` and `revision_worker.py` estimate, translate and revise SRT text.
- `model_catalog.py` loads reviewed model metadata, refreshes its public copy at
  most once per day, queries account-visible model IDs, chooses applicable
  DeepSeek price bands and converts display amounts through a dated ECB
  reference rate.
- `downloader.py` wraps the bundled yt-dlp and Deno executables and validates
  completed media with ffprobe.
- `readability.py` locally splits long cues without an API request.

The main video flow is an explicit state machine: `ready_to_transcribe`,
`transcribing`, `transcription_completed`, `ready_to_translate`,
`translating` and `completed`. `SubtitleWorker` owns only audio transcription
and writes the original SRT before `RevisionWorker` is constructed. The latter
is created only by the **Start translation** action (or its resume action).
Translation estimates run locally and never start a request.

Existing-SRT translation is a separate entry point into `RevisionDialog`. It
loads and estimates the selected SRT directly, without constructing a media or
transcription job. Its availability follows running workers rather than the
presence of a video or an idle video workflow state.

Language codes (`auto`, `original`, `en`, `it`, `ja`, `fr`) are stable values in
jobs and model requests. Their visible labels come from the active catalog.

The local source path may point to a video container or an audio-only file.
`media.py` owns the supported extension groups and validates the selected file
with ffprobe. Downstream workers use the selected audio stream and therefore do
not require a video stream. The legacy `video` manifest field is retained so
existing jobs remain resumable.

## Persistence and compatibility

For upgrade compatibility, macOS application data remains in
`~/Library/Application Support/VideoSottotitoli/` and provider keys remain in
the legacy `VideoSottotitoli` Keychain service. Linux uses XDG data, config and
state directories and stores keys through Secret Service. `preferences.json`
stores only interface preferences, currently `ui_locale`.

Transcription, revision and download jobs use separate subdirectories. A resume
always uses the settings saved in its manifest. Logs are diagnostic data and do
not replace manifest state.

A provider connection failure stops subsequent text requests, writes a partial
SRT from accepted groups plus source-language fallbacks, and leaves the revision
manifest in the `error` state. Rejected fallback groups remain eligible for a
later resume. Legacy manifests that recorded the same condition as completed
are recognized through `api_failure` and their rejected groups, without changing
historical usage or accepted responses.

Provider `/models` responses are availability evidence only: they do not
provide reliable structured-output support, prices or subtitle quality. The
operational selector therefore intersects account-visible IDs with the reviewed
catalog. A revision manifest saves provider, model, effective reasoning
parameter, catalog version, prices and quality evidence. Historical costs never
change during a resume; only the estimate for remaining groups can use the
current verified price.

## Packaging

`build-mac-app.sh` creates an architecture-specific `SRT Compass.app` and DMG
while retaining the existing bundle identifier for upgrade compatibility.
`build-linux-appimage.sh` creates an x86_64 AppImage. yt-dlp and Deno are fetched
from pinned upstream versions and checksum-verified. FFmpeg and ffprobe remain
external prerequisites.

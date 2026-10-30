# SRT Compass

SRT Compass is a cross-platform desktop application for creating, translating and
improving SRT subtitles. It accepts local video, WebM and audio files, or
individual public video links, lets you select a time range, and keeps
timestamps aligned to the original media timeline.

> **Status:** beta for macOS Apple Silicon, macOS Intel and Linux x86_64. Release
> artifacts are ad-hoc signed macOS DMGs and an unsigned Linux AppImage. The
> app is not signed with an Apple Developer ID and is not notarized.

The interface is available in English and Italian. On first launch it follows
the primary system language, falling back to English. Change it from
**Settings → Interface Language**; SRT language choices remain independent.

## Features

- Transcribe speech in English, Italian, Japanese and French.
- Use local video or audio sources, including WebM, MP3, M4A, WAV, FLAC and
  Ogg/Opus files.
- Produce final subtitles in the original language, English, Italian or Japanese.
- Select a start and end time while preserving absolute video timestamps.
- Translate, contextually revise and improve the readability of existing SRT files.
- Download public videos with yt-dlp, including progress, cancellation and
  resumable transfers when the source supports them.
- Split long cues into readable subtitles of at most two lines and report any
  estimated internal timing.
- Optionally create a TXT brief with topics, a summary and web sources.
- Resume saved transcription, translation and download jobs.
- Compare reviewed OpenAI and DeepSeek models by indicative subtitle quality and
  local cost estimate before starting a text operation.

## Requirements

- macOS on Apple Silicon or Intel, or Linux x86_64 (Ubuntu 22.04 or compatible).
- Python 3.11, 3.12 or 3.13.
- [FFmpeg](https://ffmpeg.org/) and `ffprobe` available in `PATH`.
- An OpenAI API key with available credit for paid operations.
- An optional DeepSeek API key for subtitle translation or contextual revision
  with DeepSeek Flash or DeepSeek Pro.
- Internet access for OpenAI operations and link downloads.

Install FFmpeg on macOS with Homebrew:

```bash
brew install ffmpeg
```

On Ubuntu/Debian, install the system packages instead:

```bash
sudo apt install ffmpeg python3-tk
```

## Install from source

```bash
git clone https://github.com/Dago86/srt-compass.git
cd srt-compass
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
srt-compass
```

You can also run `python run.py` from a checkout.

On first use, open **Settings → Configure API key…** and choose OpenAI or
DeepSeek. SRT Compass stores each key in the macOS Keychain or a Linux Secret
Service keyring and never writes keys to application logs. If no desktop
keyring is available, configure the corresponding environment variable.
Developers can copy `.env.example` to
`.env.local`; that file is ignored by Git and must never be shared.

## Basic workflow

The opening screen offers two paths: **Create subtitles from audio or video**
and **Work on an existing SRT**. Recent jobs are available separately.

1. For new subtitles, choose a local video/audio file or select **From link…**.
2. After the source is ready, choose the spoken language, time range and SRT
   destination. Review the audio estimate next to **Generate transcription**.
3. Generate the original-language SRT. Translation does not start automatically.
4. Choose the final language and review the local translation estimate. Select
   **Start translation** only if you want a translated SRT; otherwise use the
   original transcription.
5. Open the result and review its issue report if it contains warnings or
   untranslated parts. A requested TXT brief has its own estimate and start.

If you already have an SRT, choose **Work on an existing SRT**, then
**Translate SRT…**, **Improve subtitles…** or **Improve SRT readability…**.
Translation and revision estimate the text-provider cost locally and wait for
an explicit start. They require no video, audio track or time range.

Incomplete jobs remain in the platform data directory and are available from
**Recent jobs**. macOS keeps the legacy
`~/Library/Application Support/VideoSottotitoli/` directory; Linux uses
`$XDG_DATA_HOME/SRT Compass` (or `~/.local/share/SRT Compass`). Temporary-file
cleanup does not remove published media or SRT results.

## Costs, privacy and external services

OpenAI and DeepSeek usage is billed to the respective API key owner. Estimates
shown by the app are not spending limits. Audio transcription and the TXT web
brief use OpenAI; subtitle translation and contextual revision can use either
OpenAI or DeepSeek. Downloading a video does not start an AI request.

For subtitle operations, **Advanced options** offers a provider and a reviewed
model. SRT Compass refreshes its model catalog in the background at most once
every 24 hours; **Refresh models** checks again on demand. It also asks the
selected providers which models the configured API keys can access. Newly found
models remain unavailable until the project catalog records verified structured
output support and pricing. The expected-quality label is an application-level,
documented indication for the listed language pairs; it is not a guarantee that
the subtitle text matches the audio. After a job, the app reports structural,
numeric, language and readability checks without assigning a fabricated
fidelity score.

Costs are shown primarily in EUR using a dated European Central Bank reference
rate, with the underlying USD amount available in the same detail. If that rate
is unavailable, the app explains the fallback to USD. OpenAI and DeepSeek
prices, including DeepSeek peak/off-peak bands, are stored with the job. A
resume preserves historical costs and only recalculates the estimate of work
that remains. See [PRIVACY.md](PRIVACY.md) for the data sent during each
operation.

Website support depends on yt-dlp and may change. Playlists, live streams, DRM,
cookies and authenticated sources are outside the supported workflow. Not every
website supports resuming from partial bytes. Users are responsible for having
the right to download and process the selected content.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check src tests run.py
python -m compileall -q src run.py
python -m unittest discover -s tests
python scripts/check_repository.py
```

Tests use simulated services and must not make paid API requests or real media
downloads. See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

## Local builds

```bash
python -m pip install -e '.[packaging]'
./scripts/prepare-vendor-macos.sh
./build-mac-app.sh
```

On Linux x86_64, install `appimagetool` and run:

```bash
./scripts/prepare-vendor-linux.sh
./scripts/build-linux-appimage.sh
```

The macOS build selects Apple Silicon or Intel from the host architecture and
creates a separate DMG. The Linux build creates an x86_64 AppImage. Preparation
scripts download pinned yt-dlp and Deno releases from their official upstream
sources and verify checksums.

Downloaded binaries and generated packages are ignored by Git. macOS builds use
an ad-hoc local signature and are not notarized public binaries.

## Beta limitations

- Linux support targets x86_64 desktop systems; ARM Linux is not included yet.
- FFmpeg and ffprobe are external prerequisites on every platform.
- Timing created when splitting very long cues is estimated from text and is not
  realigned against the audio.
- Contextual translation still requires human review for names, numbers and
  ambiguous passages.
- `whisper-1` is scheduled for retirement on February 26, 2027; its replacement
  must preserve timestamps and saved-job compatibility.

## Documentation

- [Architecture](docs/architecture.md)
- [Requirements](docs/requirements.md)
- [Test plan](docs/test-plan.md)
- [Model catalog and review policy](docs/model-catalog.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## License

SRT Compass is available under the [MIT License](LICENSE). yt-dlp, Deno and
other components retain the licenses listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

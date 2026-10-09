# SRT Compass

SRT Compass is a macOS desktop application for creating, translating and
improving SRT subtitles. It accepts local videos or individual public video
links, lets you select a time range, and keeps timestamps aligned to the
original media timeline.

> **Status:** beta for Apple Silicon Macs. The first public release contains
> source code only. The app is not signed with an Apple Developer ID and is not
> notarized.

The interface is available in English and Italian. On first launch it follows
the primary macOS language, falling back to English. Change it from
**Settings → Interface Language**; SRT language choices remain independent.

## Features

- Transcribe speech in English, Italian, Japanese and French.
- Produce final subtitles in the original language, English, Italian or Japanese.
- Select a start and end time while preserving absolute video timestamps.
- Translate, contextually revise and improve the readability of existing SRT files.
- Download public videos with yt-dlp, including progress, cancellation and
  resumable transfers when the source supports them.
- Split long cues into readable subtitles of at most two lines and report any
  estimated internal timing.
- Optionally create a TXT brief with topics, a summary and web sources.
- Resume saved transcription, translation and download jobs.

## Requirements

- macOS on Apple Silicon.
- Python 3.11, 3.12 or 3.13.
- [FFmpeg](https://ffmpeg.org/) and `ffprobe` available in `PATH`.
- An OpenAI API key with available credit for paid operations.
- An optional DeepSeek API key for subtitle translation or contextual revision
  with DeepSeek Flash or DeepSeek Pro.
- Internet access for OpenAI operations and link downloads.

Install FFmpeg with Homebrew:

```bash
brew install ffmpeg
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
DeepSeek. SRT Compass stores each key in a separate macOS Keychain entry and
never writes keys to application logs. Developers can copy `.env.example` to
`.env.local`; that file is ignored by Git and must never be shared.

## Basic workflow

1. Choose a local video or select **From link…**.
2. Select the spoken language, final language and time range.
3. Choose the SRT destination and review the estimate.
4. Select **Generate transcription**. The original-language SRT is saved first.
5. Review the local translation estimate and select **Start translation** when
   you want the final-language SRT. If you selected **Original**, this step is
   skipped.
6. Review the issue report if the result contains warnings or untranslated
   parts.

Incomplete jobs remain under the legacy-compatible directory
`~/Library/Application Support/VideoSottotitoli/` and are available from
**Recent jobs**. Temporary-file cleanup does not remove published media or SRT
results.

## Costs, privacy and external services

OpenAI and DeepSeek usage is billed to the respective API key owner. Estimates
shown by the app are not spending limits. Audio transcription and the TXT web
brief use OpenAI; subtitle translation and contextual revision can use either
OpenAI or DeepSeek. Downloading a video does not start an AI request. See
[PRIVACY.md](PRIVACY.md) for the data sent during each operation.

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

## Local macOS build

```bash
python -m pip install -e '.[packaging]'
./scripts/prepare-vendor-macos.sh
./build-mac-app.sh
```

The preparation script downloads pinned yt-dlp and Deno releases from their
official upstream sources and verifies their checksums. Downloaded binaries and
the generated DMG are ignored by Git. The build uses an ad-hoc local signature
and is not intended as a notarized public binary.

## Beta limitations

- Packaging and interface testing currently focus on Apple Silicon Macs.
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
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## License

SRT Compass is available under the [MIT License](LICENSE). yt-dlp, Deno and
other components retain the licenses listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

# Requirements — SRT Compass 0.16.4

Subtitle translation and contextual revision may use OpenAI or DeepSeek. OpenAI
remains the default and is required for audio transcription and the optional TXT
web brief. Provider keys are stored separately in the macOS Keychain or Linux
Secret Service keyring; no provider
fallback or automatic retry on another provider is performed.

## Runtime

- macOS Apple Silicon or Intel, or Linux x86_64 (Ubuntu 22.04 or compatible).
- Python 3.11–3.13 when running from source.
- FFmpeg and ffprobe available in `PATH`.
- Network access and a user-provided OpenAI API key for transcription and TXT
  briefs; a DeepSeek key is optional for DeepSeek subtitle operations.
- Network access for public-link downloads.

The app supports English and Italian interface languages. It detects the first
system language on initial launch and falls back to English. Changing the UI
language must never change a transcription or translation language code.

Local transcription sources may be video containers (`.mp4`, `.mov`, `.mkv`,
`.webm`) or common audio formats (`.mp3`, `.m4a`, `.aac`, `.wav`, `.flac`,
`.ogg`, `.oga`, `.opus`, `.mka`, `.aif`, `.aiff`, `.caf`, `.wma`). A source
must contain at least one audio stream, have a readable duration and remain
within the existing five-hour limit.

## Development

Install the `dev` optional dependency group for Ruff, tests and dependency
checks. Automated tests use simulated services and must not perform paid API
requests or real media downloads.

The video workflow has two explicit paid steps. **Generate transcription** sends
audio to OpenAI and always saves the original-language SRT first. When a
different final language is selected, the app then shows a local translation
estimate and waits for the user to press **Start translation**. No text-provider
request is made merely because transcription finished or because the estimate
was calculated.

Existing SRT files can be translated as an independent workflow. The action is
available without loading a video and must not read video, audio-track, range or
transcription state. Starting another SRT operation is blocked only while an
actual download, transcription, translation, revision or TXT generation is in
progress.

If the text provider cannot be reached, the app saves a partial SRT using the
translations already accepted and the original text for the remaining groups.
The job remains in an error state and must be shown as resumable. A provider
outage must never be labelled as a completed translation.

## Model catalog and costs

The app includes a reviewed model catalog and may refresh it in the background
at most every 24 hours. The catalog and optional provider `/models` discovery
do not start text generation. A model is selectable only when the catalog
records support for the structured SRT contract, pricing and a documented
quality assessment. New account-visible models without those data are reported
but cannot be used.

Estimates include input, anticipated output, model-specific reasoning reserve
and applicable DeepSeek peak/off-peak rates. They are shown in EUR from a dated
ECB USD/EUR reference, with USD retained for audit; USD is shown alone when the
reference rate is unavailable. The app records token-derived consumption when
providers supply it and identifies incomplete consumption data. Estimates are
not a spending limit.

## Packaging

Install the `packaging` optional dependency group. The packaging process fetches
pinned yt-dlp and Deno binaries from official upstream sources, verifies their
checksums and excludes downloaded executables from Git. macOS builds produce
architecture-specific DMGs; Linux builds produce an x86_64 AppImage. FFmpeg
and ffprobe remain installed by the operating system.

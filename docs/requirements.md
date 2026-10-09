# Requirements — SRT Compass 0.15.0

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

## Packaging

Install the `packaging` optional dependency group. The packaging process fetches
pinned yt-dlp and Deno binaries from official upstream sources, verifies their
checksums and excludes downloaded executables from Git. macOS builds produce
architecture-specific DMGs; Linux builds produce an x86_64 AppImage. FFmpeg
and ffprobe remain installed by the operating system.

# Requirements — SRT Compass 0.13.0

## Runtime

- Apple Silicon Mac running macOS.
- Python 3.11–3.13 when running from source.
- FFmpeg and ffprobe available in `PATH`.
- Network access and a user-provided OpenAI API key for paid operations.
- Network access for public-link downloads.

The app supports English and Italian interface languages. It detects the first
macOS language on initial launch and falls back to English. Changing the UI
language must never change a transcription or translation language code.

## Development

Install the `dev` optional dependency group for Ruff, tests and dependency
checks. Automated tests use simulated services and must not perform paid API
requests or real media downloads.

## Packaging

Install the `packaging` optional dependency group. The packaging process fetches
pinned yt-dlp and Deno binaries from official upstream sources, verifies their
checksums and excludes downloaded executables from Git.

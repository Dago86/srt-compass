# Test plan — SRT Compass 0.15.0

Provider coverage includes simulated OpenAI and DeepSeek structured responses,
separate usage and pricing, missing-key errors, interruption, resume and legacy
jobs without a provider field. Tests assert that DeepSeek selection does not
change Whisper transcription or the OpenAI-only TXT web brief.

The two-step workflow is covered separately: transcription creates an
original-language SRT and stops; the translation estimate is local and no text
request is sent until the user starts translation. Resume tests cover both a
transcription in progress and a translation job with already completed groups.

## Automated checks

- Run the complete unittest suite on Python 3.11, 3.12 and 3.13.
- Run Ruff, module compilation, repository policy checks and dependency audit.
- Verify that English and Italian catalogs contain identical message IDs.
- Test macOS and Linux Italian, English and unsupported-language detection.
- Test XDG data, config and state directories on Linux and legacy storage on macOS.
- Test Linux Secret Service key lookup/save and the environment-variable fallback.
- Test platform file opening through `xdg-open` and macOS `open` adapters.
- Test atomic preference persistence and invalid preference fallback.
- Verify that changing UI locale does not change stored source or target codes.
- Resume legacy transcription, revision and download jobs without migrating
  their manifests, storage directory or Keychain service.
- Exercise download, transcription, translation and SRT tools with simulated
  workers in both interface languages.
- Run the Linux x86_64 AppImage smoke test and the two architecture-specific
  macOS build checks; verify the bundled yt-dlp and Deno checksums.

## Visual checks

- Open the packaged app in English and Italian.
- Inspect the main window, download dialog, recent jobs, SRT tools, help popovers,
  errors and completed results at the minimum window size.
- Check keyboard focus, long paths, light/dark appearance and menu availability.
- Confirm that a language change is disabled during active work and restarts the
  idle app automatically.

No acceptance check may use a paid API request or modify a real saved download.

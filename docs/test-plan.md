# Test plan — SRT Compass 0.17.0

The guided-view regression suite covers the initial path selection, saved
transcription followed by an explicit translation decision, unchanged original
SRT, a target-language change without a paid request and collision-safe final
names. Existing media-switch and resume tests cover a second source in the same
session. The screen sequence and bilingual copy are specified in
[the guided UX document](ux-guided-0.17.0.md).

The download regression suite covers Dailymotion HLS metadata whose audio-only
format has an unknown codec but a valid audio extension. All quality choices
must recognize the track. A metadata-only selector check must choose video and
audio without downloading the media.

The three-person usability check is a release follow-up until three people
actually try the paths without instructions. Automated widget and worker tests
do not count as human usability evidence.

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
- From a fresh launch with no video, open **Translate SRT…**, load a simulated
  SRT and verify that preview, local estimate and explicit start are independent
  of media, audio-track and interval state. Keep the command available for an
  idle video workflow and disable it while a worker is active.
- Complete a transcription for video A, start a link download for video B and
  verify that A is detached immediately. After B is loaded, its media path and
  default SRT destination must be selected while A's result, TXT state, log and
  resume references remain cleared.
- Verify that the local picker exposes WebM and common audio formats. Probe
  audio-only and WebM fixtures with no video stream, select their audio stream,
  derive the default SRT name and preserve the selected interval timestamps.
- Run the Linux x86_64 AppImage smoke test and the two architecture-specific
  macOS build checks; verify the bundled yt-dlp and Deno checksums.
- Test catalog refresh, a valid cached catalog, malformed remote data and
  offline fallback without making provider generation requests.
- Test account-specific model lists, reviewed-model filtering, missing prices
  and a retired selected model during resume.
- Test immediate estimate changes for provider, model and context changes,
  including DeepSeek peak and off-peak periods, reasoning reserves, missing
  usage and a dated ECB EUR conversion fallback.
- Test that the result distinguishes structural rejections, numeric warnings,
  language warnings and readability warnings without claiming an audio-fidelity
  score.
- Simulate a provider connection failure in the first of several translation
  groups. Verify that only one request is attempted, a partial SRT is saved, the
  manifest remains resumable, remaining cost is estimated, and Recent jobs
  offers **Resume translation**. Repeat with a legacy completed manifest carrying
  `api_failure` and rejected fallback groups.

## Visual checks

- Open the packaged app in English and Italian.
- Inspect the main window, download dialog, recent jobs, SRT tools, help popovers,
  errors and completed results at the minimum window size.
- Check keyboard focus, long paths, light/dark appearance and menu availability.
- Confirm that a language change is disabled during active work and restarts the
  idle app automatically.

No acceptance check may use a paid API request or modify a real saved download.

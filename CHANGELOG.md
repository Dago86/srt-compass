# Changelog

The project follows [Semantic Versioning](https://semver.org/).

## [0.17.0] - 2026-10-30

- Reorganized the main window around creating subtitles from media and working
  on an existing SRT, with one visible page and a fixed primary action.
- Moved the final-language decision and translation estimate after the saved
  transcription; choosing a language does not start a paid request.
- Put the relevant estimate next to the current action and made the original
  transcript directly accessible at the translation step.
- Reduced competing cleanup controls in Recent jobs and widened the status
  column; storage actions have their own secondary area.
- Added bilingual guided labels and regression coverage for the new decision
  point and collision-safe output names.
- Recognized Dailymotion audio-only HLS tracks when the codec is unspecified,
  preventing a false format-unavailable error on a new download.

## [0.16.4] - 2026-10-19

- Fixed provider connection failures being presented as completed translations
  even when every subtitle had fallen back to the source language.
- Saved a usable partial SRT after an API outage while keeping the translation
  job resumable from Recent jobs.
- Stopped issuing further requests after the first provider connection failure
  and stopped recording local fallbacks as received provider responses.
- Made legacy all-original fallbacks caused by an API failure resumable without
  modifying their historical usage records.

## [0.16.3] - 2026-10-16

- Added local audio files and WebM as first-class transcription sources.
- Expanded the source picker to common audio formats including MP3, M4A, AAC,
  WAV, FLAC, Ogg/Opus, AIFF, CAF, MKA and WMA.
- Updated the English and Italian interface to describe local media files rather
  than requiring a video, while preserving existing transcription jobs.
- Added regression coverage for audio-only probing and local media filters.

## [0.16.2] - 2026-10-16

- Fixed the transition from a completed video job to a newly downloaded video:
  the previous transcript, result, TXT brief, log and resume references are now
  cleared before the new source can be transcribed.
- Detached the previous media as soon as a new download starts, preventing an
  interrupted transfer from leaving the old video available as the apparent
  source of a new transcription.
- Added regression coverage for the complete video A to downloaded video B
  state transition.

## [0.16.1] - 2026-10-13

- Made existing-SRT translation directly accessible from the initial screen,
  without loading a video first.
- Kept standalone SRT tools available while an idle video workflow waits for
  the next explicit action, while still blocking concurrent processing.
- Added regression coverage proving that SRT preview and translation setup do
  not depend on video, audio-track or interval state.

## [0.16.0] - 2026-10-10

- Added a reviewed model catalog that refreshes in the background at most once
  every 24 hours and can be refreshed manually.
- Added account-availability checks for OpenAI and DeepSeek models without
  making a paid subtitle request.
- Added an indicative, documented subtitle-quality tier and result checks for
  structure, numbers, language and readability.
- Added EUR-first estimates and recorded costs using a dated ECB exchange rate,
  while retaining auditable USD details.
- Saved model catalog metadata, effective parameters and historical prices in
  new revision jobs so resume never silently changes a prior job.
- Reset in-memory translation and resume references when loading a new video,
  including a video returned from the download dialog.

## [0.15.0] - 2026-10-09

- Added macOS Intel support alongside Apple Silicon.
- Added Linux x86_64 support with an AppImage build.
- Made application data, system-language detection and file opening portable.
- Added native Linux Secret Service keyring integration with environment-variable fallback.
- Added architecture-specific vendor preparation and packaging scripts.

## [0.14.1] - 2026-10-09

- Separated transcription and translation into two explicit user actions.
- Saved the original transcript before any optional text-provider request.
- Saved resumable workflow phases and separate transcription/translation costs.
- Removed automatic translation after the local estimate is calculated.

## [0.14.0] - 2026-10-09

- Added DeepSeek as an optional provider for subtitle translation and contextual revision.
- Added provider-aware model selection, estimates, usage recording and job resume.
- Kept OpenAI as the default provider for subtitles, transcription and TXT web briefs.
- Added separate OpenAI and DeepSeek Keychain entries.

## [0.13.0] - 2026-10-08

- Renamed the project and macOS application to SRT Compass.
- Added English and Italian interface catalogs.
- Added macOS language detection and a persisted interface-language setting.
- Separated stable media language codes from localized display labels.
- Rewrote the public README and current project documentation in English.
- Preserved the legacy application data directory, Keychain service and bundle
  identifier for upgrades from Video Sottotitoli.

## [0.12.1] - 2026-10-07

- Added French as a supported spoken language.
- Kept Italian, English and Japanese as translation targets.

## [0.12.0] - 2026-09-29

- Reorganized the interface around source, activity and result.
- Improved job history and temporary file management.

## [0.11.0] - 2026-09-29

- Added local segmentation for overly long subtitle cues.

## [0.10.0] - 2026-09-26

- Improved downloader progress and state handling.

## [0.9.0] - 2026-09-24

- Added the optional TXT information brief.

## [0.7.1] - 2026-09-24

- Introduced the unified video-to-final-SRT workflow with partial recovery.

## [0.6.0] - 2026-09-23

- Added link downloads, event history and persistent logs.

## [0.5.0] - 2026-09-22

- Added multilingual transcription, translation and contextual revision.

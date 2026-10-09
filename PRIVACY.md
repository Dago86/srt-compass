# Privacy and external services

SRT Compass is a local application and does not operate its own server. Some
features send data to external services only after an explicit user action.

## OpenAI and DeepSeek

- Transcription sends audio extracted from the selected time range.
- Translation and revision send subtitle text and optional context to the
  provider selected for that job. OpenAI is the default; DeepSeek is optional.
- The optional TXT brief sends SRT text and may use web search.
- The API key is read from the environment or the platform secret store. The
  `.env.local` fallback is for development only.
- OpenAI and DeepSeek keys are stored under separate accounts in the macOS
  Keychain or Linux Secret Service.

## Link downloads

The public page URL is passed to the local yt-dlp process. The source website
receives normal connection data such as the user's IP address. SRT Compass
filters likely credentials and temporary media URLs from logs.

## Local data

Jobs, responses and temporary files remain under the platform data directory
for resume support. macOS keeps `~/Library/Application Support/VideoSottotitoli/`;
Linux follows XDG data directories. The
**Storage and temporary files** window can remove partial files from inactive
downloads. Final files are saved only to the chosen destination.

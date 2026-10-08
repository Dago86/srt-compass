# Privacy and external services

SRT Compass is a local application and does not operate its own server. Some
features send data to external services only after an explicit user action.

## OpenAI

- Transcription sends audio extracted from the selected time range.
- Translation and revision send subtitle text and optional context.
- The optional TXT brief sends SRT text and may use web search.
- The API key is read from the environment or macOS Keychain. The
  `.env.local` fallback is for development only.

## Link downloads

The public page URL is passed to the local yt-dlp process. The source website
receives normal connection data such as the user's IP address. SRT Compass
filters likely credentials and temporary media URLs from logs.

## Local data

Jobs, responses and temporary files remain under
`~/Library/Application Support/VideoSottotitoli/` for resume support. The
**Storage and temporary files** window can remove partial files from inactive
downloads. Final files are saved only to the chosen destination.

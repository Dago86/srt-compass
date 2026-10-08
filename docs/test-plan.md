# Test plan — SRT Compass 0.13.0

## Automated checks

- Run the complete unittest suite on Python 3.11, 3.12 and 3.13.
- Run Ruff, module compilation, repository policy checks and dependency audit.
- Verify that English and Italian catalogs contain identical message IDs.
- Test macOS Italian, English and unsupported-language detection.
- Test atomic preference persistence and invalid preference fallback.
- Verify that changing UI locale does not change stored source or target codes.
- Resume legacy transcription, revision and download jobs without migrating
  their manifests, storage directory or Keychain service.
- Exercise download, transcription, translation and SRT tools with simulated
  workers in both interface languages.

## Visual checks

- Open the packaged app in English and Italian.
- Inspect the main window, download dialog, recent jobs, SRT tools, help popovers,
  errors and completed results at the minimum window size.
- Check keyboard focus, long paths, light/dark appearance and menu availability.
- Confirm that a language change is disabled during active work and restarts the
  idle app automatically.

No acceptance check may use a paid API request or modify a real saved download.

# Contributing

Thank you for your interest in SRT Compass.

## Development environment

Python 3.11–3.13 on macOS is supported:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

FFmpeg and ffprobe are required for media workflows but not for most unit tests.

## Before opening a pull request

```bash
ruff check src tests run.py
python -m compileall -q src run.py
python -m unittest discover -s tests
python scripts/check_repository.py
```

- Do not use real APIs or network downloads in automated tests.
- Do not commit media, SRT files, logs, job records or credentials.
- Add tests for fixes and visible behavior changes.
- Preserve saved-job compatibility or document the migration.
- Keep English and Italian catalogs in sync.
- Update documentation and the changelog when user-visible behavior changes.

Use the GitHub issue templates for public bugs. Follow [SECURITY.md](SECURITY.md)
for security reports.

# Requisiti

## Ambiente supportato

- macOS su Apple Silicon.
- Python 3.11–3.13 per l'esecuzione dal sorgente.
- Tkinter disponibile nella distribuzione Python.
- FFmpeg e ffprobe nel `PATH`.
- Connessione Internet per OpenAI e importazione da link.

## Credenziali

La chiave OpenAI viene salvata nel Portachiavi macOS. In sviluppo può essere
fornita dalla variabile `OPENAI_API_KEY` o da `.env.local`, che non deve essere
versionato. I test non richiedono credenziali.

## Dipendenze

Le dipendenze Python sono dichiarate in `pyproject.toml`. yt-dlp e Deno non sono
conservati nel repository: `scripts/prepare-vendor-macos.sh` li scarica dagli
upstream ufficiali e verifica i checksum elencati in `vendor/versions.txt`.

## Limiti funzionali

- Video e intervalli fino a cinque ore.
- Singoli contenuti pubblici per l'importazione da link.
- Nessun supporto per DRM, login, cookie, live o playlist complete.
- Nessuna garanzia di ripresa byte per byte su ogni sito.
- I sottotitoli generati o tradotti richiedono controllo umano.

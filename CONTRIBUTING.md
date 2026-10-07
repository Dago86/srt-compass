# Contribuire

Grazie per l'interesse verso Video Sottotitoli.

## Ambiente di sviluppo

Sono supportati Python 3.11–3.13 su macOS. Creare un ambiente virtuale e
installare gli strumenti di sviluppo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

FFmpeg e ffprobe sono necessari per i flussi multimediali, ma non per la
maggior parte dei test unitari.

## Prima di una pull request

```bash
ruff check src tests run.py
python -m compileall -q src run.py
python -m unittest discover -s tests
python scripts/check_repository.py
```

- Non usare API reali o download di rete nei test automatici.
- Non aggiungere media, SRT, log, registri di lavori o credenziali.
- Aggiungere test per correzioni e cambiamenti di comportamento.
- Conservare compatibilità con i registri esistenti oppure documentare la
  migrazione.
- Aggiornare documentazione e changelog quando cambia il comportamento visibile.

## Segnalazioni

Per bug pubblici usare il template GitHub e una diagnostica già filtrata. Per
problemi di sicurezza seguire [SECURITY.md](SECURITY.md).

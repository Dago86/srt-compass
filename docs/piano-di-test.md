# Piano di test

## Controlli automatici

Eseguire per ogni modifica:

```bash
ruff check src tests run.py
python -m compileall -q src run.py
python -m unittest discover -s tests
python scripts/check_repository.py
```

La suite usa servizi e risposte simulate. Non deve effettuare richieste OpenAI,
download reali o modificare i lavori dell'utente.

## Casi principali

- Video locale: caricamento, selezione intervallo, trascrizione e risultato.
- Lingue originali e traduzioni fra le combinazioni supportate.
- Conservazione dei timestamp assoluti e segmentazione a massimo due righe.
- Interruzione, errore, ripresa e compatibilità dei registri precedenti.
- Download: analisi, progresso noto e ignoto, unione, verifica, interruzione,
  ripresa e passaggio a un nuovo contenuto.
- Risposte API valide, parziali, non interpretabili e con consumi mancanti.
- Nessuna sovrascrittura silenziosa di SRT, TXT o video.
- Filtraggio di chiavi, URL temporanei e percorsi personali nei log.

## Verifica manuale macOS

Prima di una release controllare finestra minima, tastiera, tema chiaro/scuro,
trackpad, percorsi lunghi e chiusura durante un lavoro. La build locale deve
superare verifica della firma ad hoc e aprirsi su un Mac Apple Silicon.

Le prove API reali e i download pubblici sono verifiche separate, avviate solo
consapevolmente e mai in CI.

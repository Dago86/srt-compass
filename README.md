# Video Sottotitoli

Applicazione desktop macOS per creare, tradurre e migliorare sottotitoli SRT.
Accetta video locali oppure singoli video pubblici tramite yt-dlp, permette di
selezionare un intervallo e conserva i timestamp assoluti del contenuto.

> **Stato:** beta per macOS Apple Silicon. Il progetto è distribuito inizialmente
> come codice sorgente. Non è firmato con Developer ID e non è notarizzato.

## Funzioni principali

- Trascrizione di audio in italiano, inglese, giapponese e francese.
- Traduzione finale in italiano, inglese o giapponese.
- Selezione di inizio e fine del video, con stima del costo prima dell'avvio.
- Traduzione, revisione contestuale e miglioramento della leggibilità di SRT.
- Download da link con yt-dlp, avanzamento, interruzione e ripresa quando il sito
  lo consente.
- Risultato finale di massimo due righe per sottotitolo, con rapporto separato
  per avvisi e parti non tradotte.
- Scheda TXT facoltativa con temi, riassunto e fonti web.

## Requisiti

- macOS su Apple Silicon.
- Python 3.11, 3.12 o 3.13.
- [FFmpeg](https://ffmpeg.org/) e `ffprobe` disponibili nel `PATH`.
- Una chiave API OpenAI con credito disponibile per trascrizione, traduzione,
  revisione e scheda informativa.
- Connessione Internet per le API e per l'importazione da link.

Con Homebrew è possibile installare FFmpeg con:

```bash
brew install ffmpeg
```

## Installazione dal sorgente

```bash
git clone https://github.com/Dago86/video-sottotitoli.git
cd video-sottotitoli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
video-sottotitoli
```

In alternativa, dal checkout si può eseguire `python run.py`.

Al primo utilizzo aprire **Impostazioni → Configura chiave API…**. La chiave
viene salvata nel Portachiavi macOS e non nei registri dell'app. Durante lo
sviluppo è possibile copiare `.env.example` in `.env.local`; quest'ultimo è
escluso da Git e non deve mai essere condiviso.

## Uso essenziale

1. Scegliere un video locale oppure **Da link…**.
2. Selezionare lingua parlata, lingua finale e intervallo.
3. Scegliere la destinazione dell'SRT e controllare la stima.
4. Premere **Genera sottotitoli**.
5. Consultare il rapporto se il risultato contiene avvisi o parti non tradotte.

I lavori incompleti vengono conservati sotto
`~/Library/Application Support/VideoSottotitoli/` e possono essere ripresi da
**Lavori recenti**. La pulizia dei file temporanei non elimina i risultati già
pubblicati.

## Costi e servizi esterni

Le operazioni OpenAI sono a carico dell'utente. Le stime mostrate dall'app non
sono limiti massimi di spesa. Il download non avvia automaticamente richieste
OpenAI. Per maggiori dettagli sui dati trattati vedere [PRIVACY.md](PRIVACY.md).

Il supporto dei siti dipende da yt-dlp e può cambiare. Sono esclusi playlist,
live, DRM, cookie e flussi che richiedono autenticazione. Il recupero dei byte
parziali non è garantito da ogni sito. L'utente è responsabile di avere il
diritto di scaricare e trattare i contenuti scelti.

## Sviluppo

```bash
python -m pip install -e '.[dev]'
ruff check src tests run.py
python -m compileall -q src run.py
python -m unittest discover -s tests
python scripts/check_repository.py
```

I test usano risposte simulate e non devono effettuare chiamate API a pagamento
o download reali. Le istruzioni per contribuire sono in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Build macOS locale

```bash
python -m pip install -e '.[packaging]'
./scripts/prepare-vendor-macos.sh
./build-mac-app.sh
```

Lo script di preparazione scarica yt-dlp e Deno dalle release ufficiali e ne
verifica i checksum. I binari e il DMG generato restano esclusi dal repository.
La build risultante usa una firma locale ad hoc e non è destinata alla
distribuzione pubblica.

## Limiti della beta

- Interfaccia e packaging sono verificati principalmente su Apple Silicon.
- I tempi creati dividendo blocchi molto lunghi sono stimati dal testo e non
  riallineati all'audio.
- Una traduzione contestuale può richiedere controllo umano, soprattutto per
  nomi propri, numeri e passaggi ambigui.
- `whisper-1` è previsto in disattivazione il 26 febbraio 2027; la migrazione
  dovrà conservare i timestamp e la compatibilità dei lavori.

## Documentazione

- [Architettura](docs/architettura.md)
- [Requisiti](docs/requisiti.md)
- [Piano di test](docs/piano-di-test.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [Avvisi di terze parti](THIRD_PARTY_NOTICES.md)

## Licenza

Il codice è distribuito con licenza [MIT](LICENSE). yt-dlp, Deno e gli altri
componenti mantengono le rispettive licenze descritte in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

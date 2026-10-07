# Privacy e servizi esterni

Video Sottotitoli è un'applicazione locale e non gestisce un proprio server.
Alcune funzioni inviano dati a servizi esterni soltanto dopo un'azione esplicita
dell'utente.

## OpenAI

- La trascrizione invia l'audio estratto dall'intervallo selezionato.
- Traduzione e revisione inviano testo dei sottotitoli e contesto facoltativo.
- La scheda informativa invia il testo dell'SRT e può usare la ricerca web.
- La chiave API viene letta dall'ambiente o dal Portachiavi macOS. Il fallback
  `.env.local` è destinato esclusivamente allo sviluppo.

Consultare le condizioni e la documentazione sulla privacy di OpenAI prima
dell'uso. Non allegare chiavi API, sottotitoli o log a segnalazioni pubbliche.

## Download da link

L'URL pubblico viene passato al processo locale yt-dlp. Il sito di origine può
ricevere indirizzo IP e altri normali dati della connessione. L'app filtra dal
registro parametri che sembrano credenziali o URL multimediali temporanei.

## Banca Centrale Europea

Le versioni che convertono le stime in euro possono recuperare il cambio di
riferimento pubblico della BCE. La richiesta non contiene audio, sottotitoli o
chiavi API.

## Dati locali

Registri, risposte e file temporanei sono conservati sotto
`~/Library/Application Support/VideoSottotitoli/` per consentire la ripresa. La
finestra **Spazio e file temporanei** permette di rimuovere i parziali dei
download inattivi. I file finali vengono salvati nella destinazione scelta.

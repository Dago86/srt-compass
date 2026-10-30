# Guided interface — SRT Compass 0.17.0

The interface has one visible next action. Its cost or consequence appears
immediately above the fixed action bar. Paths and file names are summarized in
the page; complete paths belong in file details. These decisions apply Krug's
visual hierarchy and familiar conventions and Norman's discoverability,
mapping and feedback to the actual subtitle workflow.

At the minimum 760 × 630 window size, the title, current content, phase,
decision summary and action bar remain visible. The central settings area may
scroll. Each view has the same left-to-right action order: **Back** on the left,
secondary file actions in the center, and the current primary action on the
right. During paid work, **Stop** occupies the primary position. Stopping never
implies that an in-flight API request is free.

## 1. Initial view / Vista iniziale

```text
SRT Compass                                           Recent jobs / Lavori recenti
What would you like to do? / Cosa vuoi fare?

Create subtitles from audio or video / Crea sottotitoli da audio o video
  Choose a local file or download one public video from a link.

Work on an existing SRT / Lavora su un SRT esistente
  Translate · Revise · Improve readability

                                               [Create subtitles / Crea sottotitoli]
```

The SRT choice opens three clearly named operations before choosing a file.
No media settings or disabled media controls appear on this view.

## 2. Transcription setup / Preparazione trascrizione

```text
Source / Sorgente → Transcription / Trascrizione → Translation / Traduzione → Result / Risultato
Selected file name and duration / Nome del file e durata

Spoken language / Lingua parlata        Audio track / Traccia audio
Time range / Intervallo                 SRT destination / Destinazione SRT

Audio estimate / Stima audio: €… (USD details; dated exchange rate)
Translation will be estimated after transcription / Stima traduzione dopo la trascrizione
Estimate, not a spending limit / Stima, non limite massimo di spesa
[Back / Indietro]                           [Generate transcription / Genera trascrizione]
```

Before a file is loaded, the source step shows **Choose file** and **From
link**. The link step shows title, actual quality, file name and folder after
analysis; download activity and Stop replace setup controls during transfer.
After the file is verified, the same flow advances to transcription setup.

## 3. Translation decision / Attesa traduzione

```text
Source ✓ → Transcription ✓ → Translation → Result
Original transcript: file name · subtitle count [Open original / Apri originale]

Final language / Lingua finale
Advanced options / Opzioni avanzate: provider · model · context
Selected model / Modello scelto: …

Translation estimate / Stima traduzione: €… (USD details)
Estimate, not a spending limit / Stima, non limite massimo di spesa
[Back / Indietro]                             [Start translation / Avvia traduzione]
```

Changing target language, provider, model or context updates the local
estimate before Start. If translation is unnecessary, the original transcript
is the final result. Back preserves the original transcript and never repeats
transcription merely to change translation settings.

## 4. Processing / Elaborazione

```text
Current content / Contenuto corrente · current phase / fase corrente
Real progress or a busy indicator / Avanzamento reale o attesa
Received cost / Costo registrato: €… (USD details)
Show details / Mostra dettagli: events, attempts, diagnostics, log

The current request may finish and be billed / La richiesta in corso può essere addebitata
                                                   [Stop / Interrompi]
```

Download uses bytes, percent and a real ETA when supplied; merging and
verification have named phases. Transcription and translation show the current
block/group and elapsed time. A stopped or recoverable job offers **Resume /
Riprendi** for its saved record without a file picker.

## 5. Result / Risultato

```text
Completed / Completato [with warnings / con avvisi, or partial / parziale]
Final SRT: file name · subtitle count · issues to review
Original transcription: file name (when separate)
Recorded audio cost · recorded translation cost

[Issues / Problemi] [Show folder / Mostra cartella] [New job / Nuovo lavoro]
                                                      [Open SRT / Apri SRT]
```

The optional TXT brief is offered after the SRT with its own estimate and
explicit **Create TXT / Crea TXT** action. Missing external service access may
leave a labelled partial SRT and a direct Resume action.

## Existing SRT and recent jobs

Existing SRT starts with **Translate / Traduci**, **Revise / Migliora testo**,
or **Improve readability / Migliora leggibilità**. Each operation asks for a
file and displays only relevant settings; translation never asks for media.

Recent jobs prioritize title, operation, readable status, progress and
available action. A selected resumable job offers one direct Resume action.
Record paths and temporary-file removal live in a secondary details/storage
area. Download, transcription and translation rows are linked only by saved
manifest references, never by matching titles.

This document defines interface copy and hierarchy, not a new manifest format.
Older jobs retain their saved provider, language, cost and results.

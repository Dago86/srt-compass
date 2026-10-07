# Architettura — versione 0.12.1

## Configurazione delle lingue

`config.py` mantiene separate le destinazioni di traduzione (`LANGUAGES`) dai nomi delle lingue accettate internamente (`LANGUAGE_NAMES`) e dal selettore della lingua parlata (`SOURCE_LANGUAGES`). Il francese (`fr`) appartiene alle ultime due mappe, ma non alle destinazioni. In questo modo il flusso video può trascrivere francese e tradurlo verso italiano, inglese o giapponese senza modificare lo strumento di traduzione degli SRT esistenti.

Il codice lingua scelto viene salvato nel `job.json`, passato invariato a Whisper e riutilizzato alla ripresa. Con rilevamento automatico, `srt.detected_language()` normalizza sia `French` sia `fr` nello stesso codice interno.

La GUI attiva è costruita da `App._build_v08()`. Il riepilogo del lavoro deriva dalle impostazioni e dallo stato correnti; la barra inferiore sceglie l'unica azione principale. `EventLogPanel` mantiene i controlli diagnostici dentro la sezione espandibile. `RecentJobsDialog` offre anche una vista dedicata ai temporanei, riutilizzando scansione e pulizia protette. Il conteggio dei sottotitoli finali viene letto fuori dal thread grafico e applicato solo se il risultato è ancora corrente. I registri non cambiano.

`readability.py` segmenta le caption solo per l'esportazione: restituisce caption finali, mappa fra ID originali e finali e note sui tempi stimati o tagli forzati. La traduzione continua a validare, persistere e riprendere sui blocchi originali; dopo l'ultima risposta il worker applica il passaggio locale e registra la mappa nel manifest. Il rapporto distingue ID originali delle segnalazioni linguistiche e ID finali degli avvisi di leggibilità. La trascrizione applica il passaggio al proprio output solo quando questo è il risultato finale, lasciando invariata la sorgente SRT usata per una traduzione successiva. **Migliora leggibilità SRT…** usa lo stesso motore e crea una nuova copia esclusiva.

Il dialogo distingue il cambio del link da un URL inserito per riprendere un registro storico che ne è privo. Il cambio ordinario svincola `resume_job` e i metadati, ripristina selettori e progresso e richiede una nuova analisi. L'apertura tramite **Da link…** riutilizza la finestra esistente ma la inizializza come nuovo lavoro; **Riprendi** mantiene invece il registro salvato. Il reset non elimina parziali o manifest del lavoro interrotto.

Nella 0.10.1 un unico metodo applica lo stato abilitato/disabilitato ai controlli della trascrizione in base a presenza di `MediaInfo`, lavoro attivo e necessità della traduzione. Le azioni richiamabili da menu o tastiera verificano anche lo stato, e il cursore dell'intervallo ignora gli eventi quando è disabilitato. Il timer dell'attività non aggiorna la vista durante un download: la fase e l'eventuale ETA arrivano soltanto dagli eventi del downloader. La stima del tempo residuo viene azzerata quando cambia fase o flusso.

Nella 0.10.0 il dialogo da link raccoglie URL, formato, nome e cartella. Dopo l'avvio del trasferimento resta nascosto ma continua a leggere gli eventi del worker; la finestra principale mostra fase, progresso e comando di interruzione. Il dialogo viene distrutto solo dopo che il file pubblicato è stato caricato. In caso di interruzione o errore, **Riprendi** nella finestra principale usa lo stesso dialogo e registro; se manca il link, il dialogo torna visibile per richiederlo.

Il parser del progresso accetta totali di byte interi, decimali o in notazione scientifica, scartando valori negativi e non finiti. Il template include indice/numero di frammenti e codec del flusso. La presentazione sceglie byte effettivi, byte stimati, frammenti oppure percentuale non disponibile, in quest'ordine. Unione e verifica azzerano il progresso del singolo flusso e usano attesa indeterminata. La chiusura della finestra principale considera anche il download: chiede l'interruzione, attende l'evento finale e solo dopo chiude.

L'interfaccia non usa `metadata.size` come stima del file scelto: quel dato a livello generale può descrivere un formato diverso dal selettore 1080p/720p/audio. Gli eventi di progresso di yt-dlp restano riferiti al singolo flusso e non vengono sommati in una percentuale artificiale del video completo.

Il trasferimento yt-dlp ha un watchdog indipendente dai messaggi del processo: osserva la crescita dei file multimediali nello staging. Salva `last_progress_at`, `received_bytes`, `transfer_attempt` e `failure_reason` come campi facoltativi del registro esistente. Analisi del link, trasferimento e unione hanno limiti temporali distinti. La ripresa usa il registro già selezionato e l'aggiornamento dei metadati eseguito dal worker di download; il blocco esclusivo impedisce una seconda ripresa concorrente. I registri precedenti senza questi campi restano leggibili.

## Tecnologia e componenti

Applicazione Python con Tkinter per l'interfaccia, FFmpeg/ffprobe per lettura ed estrazione audio, yt-dlp ufficiale per i download, chiamate HTTPS dirette alle API OpenAI e PyInstaller per il pacchetto Mac. Non è previsto un backend ospitato.

La GUI 0.9.2 mantiene Tkinter e usa una finestra principale con canvas scorrevole, barra azioni fissa, sezioni funzionali, aiuti contestuali accessibili da tastiera e un pannello condiviso di stato/risultato. Lo stato del flusso guida abilitazione dei controlli e dei comandi Strumenti; le finestre di importazione e strumenti conservano i propri dialoghi, con stili nativi coerenti.

Componenti separati: interfaccia, coordinatore dei lavori, importazione con yt-dlp, gestione multimediale, client di trascrizione, compositore SRT, revisore/traduttore testuale, archivio dei progressi, log diagnostico e accesso al Portachiavi. Il lavoro pesante avviene fuori dal thread dell'interfaccia; gli aggiornamenti tornano alla finestra tramite una coda di eventi.

## Importazione da link

`downloader.py` convalida URL HTTP/HTTPS, esclude playlist e live e richiede una durata nota entro cinque ore. Analisi e download sono operazioni separate: l'analisi usa yt-dlp con configurazioni/plugin locali disabilitati e salva ID e URL pagina filtrato. Per YouTube genera il link canonico dall'ID anche quando un vecchio registro contiene `/watch` senza `v`; per altri siti mantiene parametri pubblici d'identità ed esclude query che sembrano credenziali o firme. La selezione qualità viene trasformata in un selettore di formato interno; il processo non passa da una shell.

Il download usa una cartella di staging persistente per il lavoro, emette esplicitamente progresso yt-dlp con `--progress` e template strutturati, e interpreta tali eventi su stdout e stderr prima delle righe di percorso. La GUI del dialogo e quella principale condividono fase, percentuale e dati di trasferimento. I totali stimati sono distinti dai reali e non si inventa una percentuale quando il totale manca. Alla ripresa riottiene i metadati e verifica ID e formato/traccia. I nuovi lavori salvano nel manifest `output_name`; il nome scelto viene applicato soltanto alla pubblicazione, mentre il template yt-dlp resta stabile per riutilizzare i parziali. I vecchi registri conservano il nome prodotto dal template esistente. Un file completo nello staging viene verificato e pubblicato senza nuovo download. Parziali incompatibili richiedono un nuovo download esplicito; la continuazione dai byte dipende dal sito. Prima del download verifica FFmpeg e ffprobe; dopo il completamento verifica il file con ffprobe e lo pubblica con un nome libero senza sovrascrivere file esistenti.

`recent_jobs.py` legge registri `job.json`, `revision.json` e `download.json` indipendentemente: un registro malformato non nasconde gli altri. La vista recente espone stato, avanzamento, spesa e instrada la ripresa al gestore corretto.

La pulizia singola e globale condivide un lock `fcntl.flock` per lavoro tra download/ripresa e rimozione. La pulizia globale scandisce tutti i manifest, non il limite della lista Lavori recenti; per ogni lavoro acquisisce un lock non bloccante, valida che staging sia la cartella figlia `staging` del job e salta lavori attivi o non verificabili. Conserva manifest, log e output pubblicato, registra la rimozione e marca come interrotto un lavoro ancora in download. Un errore su un job non ferma gli altri.

Al termine, `DownloadWorker._publish` verifica il media in staging, lo sposta nella destinazione e aggiorna il percorso della struttura `MediaInfo` al file pubblicato prima di emettere `complete`. `DownloadDialog` convalida anche il file ricevuto e normalizza il percorso al confine della GUI; chiude il proprio dialogo solo dopo che `_receive_media` ha caricato il video. Gli eventi distinguono pubblicazione e caricamento in finestra. Il dialogo mostra un indicatore di attesa durante metadati/unione/verifica e avanzamento determinato per il trasferimento. La cronologia è secondaria e chiusa inizialmente; i lavori riprendibili si selezionano da Lavori recenti, non cercando a mano i registri nel percorso ordinario.

## Avanzamento e diagnostica

Ogni worker emette eventi di stato per l'interfaccia. Percentuale/ETA sono presentati solo se forniti dal processo; le richieste API senza progresso espongono solo fase ed elapsed time. `event_log.py` scrive righe append-only con data, fase e livello in `events.log` del lavoro, con permessi utente e filtro per token, chiavi e URL. Il file è diagnostico e non è usato per riprendere il lavoro; il manifest JSON rimane la fonte dello stato.

## Flusso

1. ffprobe verifica il file, legge durata e tracce e conserva il riferimento temporale della traccia scelta rispetto al video.
2. L'utente sceglie traccia, inizio, fine e destinazione e avvia il lavoro dopo aver visto durata selezionata e stima. Barra e campi temporali si aggiornano reciprocamente al secondo.
3. FFmpeg estrae audio mono compresso in MP3 a 64 kbit/s, senza caricare l'intera registrazione in memoria.
4. Si creano blocchi contigui di dieci minuti tra gli estremi selezionati; l'ultimo può essere più breve. Gli offset restano assoluti e ogni blocco viene verificato sotto 25 MB. Un intervallo 40–50 minuti produce un solo blocco con inizio assoluto a 2400 secondi.
5. Trascrivere sequenzialmente con `whisper-1`, usando la lingua selezionata (`en`, `it` o `ja`), formato `verbose_json` e tempi di parole e segmenti. Per il giapponese comporre dai segmenti per non introdurre spazi artificiali.
6. Salvare atomicamente ogni risposta completata. Convertire i tempi locali in tempi del video usando gli offset effettivi, compreso l'eventuale ritardo iniziale della traccia audio.
7. Comporre le didascalie ed esportare atomicamente l'SRT originale. Se la lingua finale coincide, questo è il risultato. Altrimenti stimare la traduzione nella stessa finestra, avviarla e salvare progressivamente un SRT finale completo o parziale con rapporto separato.
8. Se la casella della scheda TXT era selezionata, salvare nel `job.json` l'SRT finale, lingua, intervallo, destinazione e stato `awaiting_confirmation`. Stimare la scheda fuori dal thread Tkinter e presentare costo e informativa. Solo il pulsante **Crea TXT** avvia `SummaryWorker`; questi invia il testo dell'SRT al Responses API di GPT-6 Sol con `web_search` obbligatoria e nessun nuovo invio dell'audio.

`video_summary.py` salva il lavoro figlio in `summary/summary.json` insieme alla risposta grezza, `events.log`, fonti, consumi e output. Le citazioni e i risultati web restituiti dalla risposta sono l'unica origine dei link inclusi nel TXT. Prima di finalizzare verifica il fingerprint dell'SRT; pubblica il TXT con creazione senza sovrascrittura e sceglie un suffisso alternativo in caso di collisione. `job.json` mantiene il puntatore al lavoro figlio e lo stato, così **Riprendi** può riaprire la scheda senza ricreare SRT o ripetere la richiesta se è già disponibile la risposta salvata. Una scheda fallita non invalida il risultato SRT.

I blocchi sono contigui, senza sovrapposizione intenzionale; la verifica dei confini è obbligatoria. Non eliminare ripetizioni del parlato soltanto perché il testo è uguale.

## Revisione di un SRT

1. Leggere tutti i blocchi SRT conservando tempi anche quando sono sovrapposti o hanno durata non valida; una riga temporale illeggibile interrompe il caricamento.
2. Creare unità di massimo sei sottotitoli e trenta secondi, interrotte da pause di due secondi, e raggrupparle in richieste di circa 4.000 token con fino a 1.000 token di contesto per lato.
3. Dopo l'avvio esplicito inviare identificativi, unità, durata e testo. Sol è predefinito per traduzione e revisione contestuale; mini per la conservativa. Timestamp e percorsi non vengono inviati.
4. Associare la risposta tramite identificativi interi e validare struttura, ordine e testo non vuoto. La modalità conservativa mantiene i controlli lessicali. Nelle modalità linguistiche e di traduzione, differenze numeriche sono avvisi; non attivano tentativi aggiuntivi. Un'unità strutturalmente non valida provoca al massimo il secondo tentativo già previsto. Unità valide vengono conservate; per unità non valide si mantiene l'originale e si prosegue.
5. Salvare separatamente ogni tentativo, l'esito per identificativo, i conteggi, le anomalie e i consumi prima di un'altra richiesta. I costi si sommano anche dopo un rifiuto e una ripresa; consumi mancanti rendono il totale incompleto. I gruppi completati non vengono reinviati. Alla ripresa un gruppo pendente con risposta salvata viene rivalidato con le regole correnti; se ora è valido, si riutilizza senza nuova richiesta. I gruppi già completati mantengono gli esiti salvati.
6. Ricostruire e salvare l'SRT anche se alcuni gruppi restano non tradotti. Per errori API, non avviare altre richieste; usare gli originali per i gruppi mancanti. Creare un rapporto separato con ID, tempi, testo originale, proposta applicata o rifiutata e motivo/avviso. I timestamp restano invariati.

Le tariffe configurate sono `$0,40/$1,60` per mini, `$2/$10` per GPT-6 Sol e `$4/$20` per GPT-5.6 Sol, per milione di token in ingresso/uscita. GPT-6 Sol è predefinito per traduzione e revisione contestuale; GPT-4.1 mini per la conservativa. Il client usa Responses API e `reasoning.effort="none"` per entrambi i modelli Sol. La stima usa `tiktoken` quando riconosce il modello e ricorre a una stima prudente altrimenti. Il costo effettivo usa i consumi restituiti; dati mancanti rendono il totale incompleto.

## Interfacce e dati

Nessuna API pubblica. L'ingresso è un percorso video con selezione della traccia; l'uscita è un percorso SRT scelto dall'utente. Internamente le parole sono rappresentate da testo, inizio e fine; le didascalie da indice, inizio, fine e righe.

Il registro persistente di ogni lavoro contiene impronta del sorgente, durata, inizio e fine in secondi, traccia, destinazione, stato e blocchi con offset assoluti. Non contiene la chiave API. Nei registri precedenti, inizio assente vale `0` e fine assente vale la durata completa, senza rigenerare i blocchi esistenti.

Stati del lavoro: preparazione, trascrizione, interrotto, errore, esportazione e completato. Ogni blocco è da elaborare oppure completato con risposta valida e persistita. La ripresa richiede sorgente e parametri coerenti con il registro; se il file è cambiato, avviare un nuovo lavoro.

## Interruzioni ed errori

- Salvare i dati sotto `~/Library/Application Support/VideoSottotitoli/jobs/`, in cartelle per lavoro.
- Salvare le revisioni separatamente sotto `~/Library/Application Support/VideoSottotitoli/revision-jobs/`, con modalità, impronta del sorgente, modello, tariffe, versioni delle istruzioni e del validatore, gruppi, risposte grezze e validate, confronti testuali e consumi. Il formato versione 3 legge i lavori precedenti senza reinviare i gruppi già elaborati e usa la modalità e le istruzioni salvate per quelli ancora da completare.
- In caso di interruzione richiesta, non iniziare nuovi blocchi; lasciare terminare e salvare la richiesta già in corso, comunicandolo nella finestra.
- Su riavvio proporre la ripresa dei lavori incompleti. Se manca la sorgente consentire di individuarla e verificarne l'impronta.
- Ritentare errori transitori di rete, HTTP 429 e 5xx fino a tre volte con attesa crescente, rispettando `Retry-After`; poi rendere disponibile la ripresa manuale. Fermarsi su credenziali invalide o credito insufficiente.
- Un arresto improvviso durante una richiesta può rendere necessario ripetere il blocco: non garantire assenza assoluta di doppi addebiti per richieste dall'esito ignoto.
- I lavori download si salvano separatamente sotto `download-jobs/`, senza chiave API e senza URL temporanei. `events.log` registra fasi/errori depurati; il manifest `download.json` conserva opzioni, ID sorgente e stato di ripresa.
- Conservare i blocchi dei lavori incompleti per la ripresa; eliminare audio temporaneo e risposte dopo esportazione riuscita. Consentire di eliminare esplicitamente un lavoro incompleto.
- Non registrare chiavi o contenuti audio nei log. Il video resta locale; l'audio viene inviato a OpenAI.

## Confezionamento

Preparare una `.app` per l'architettura del Mac dell'utente, includendo runtime e strumenti multimediali compatibili. La chiave viene letta dall'ambiente o dal file locale `.env.local` durante lo sviluppo e non è inclusa nella build. Verificare le licenze della build FFmpeg scelta e includere gli avvisi richiesti. Firma Developer ID, notarizzazione e distribuzione pubblica non fanno parte della prima versione; documentare le eventuali operazioni di apertura richieste da macOS senza disattivarne le protezioni.

## Riferimenti verificati il 17 settembre 2026

- [Trascrizione OpenAI](https://developers.openai.com/api/docs/guides/speech-to-text): tempi delle parole, limite di 25 MB e gestione delle registrazioni lunghe.
- [Whisper](https://developers.openai.com/api/docs/models/whisper-1): modello e prezzo di riferimento.

Riconfermare compatibilità e limiti prima dell'implementazione; questa documentazione non comporta richieste API.

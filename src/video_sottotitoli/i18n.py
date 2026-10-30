"""Small, dependency-free localization layer for the Tk interface."""

from __future__ import annotations

import json
import locale as system_locale
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SUPPORTED_LOCALES = ("en", "it")
DEFAULT_LOCALE = "en"

# Message identifiers are intentionally stable. Jobs store language codes and never
# store these labels, so changing copy cannot alter transcription behaviour.
CATALOGS: dict[str, dict[str, str]] = {
    "en": {
        "app.name": "SRT Compass",
        "guided.home.title": "What would you like to do?",
        "guided.media.title": "Create subtitles from audio or video",
        "guided.media.description": "Choose a local file or download a video, then transcribe it.",
        "guided.srt.title": "Work on an existing SRT",
        "guided.srt.description": "Translate, revise, or improve readability without a video.",
        "guided.srt.choose": "Choose what to do with your subtitle file.",
        "guided.srt.active": "Finish the SRT tool first",
        "guided.back": "Back",
        "guided.open_original": "Open transcription",
        "guided.use_original": "Use transcription",
        "guided.continue": "Continue to translation",
        "guided.cost.disclaimer": "Estimate, not a spending limit.",
        "guided.phase.home": "Choose a path",
        "guided.phase.source": "Source → Transcription → Translation",
        "guided.phase.transcription": "Source ✓ · Transcription → Translation",
        "guided.phase.translation": "Source ✓ · Transcription ✓ · Translation",
        "guided.phase.processing": "Working · {name}",
        "guided.phase.result": "Source ✓ · Transcription ✓ · Result",
        "guided.phase.result_translation": "Source ✓ · Transcription ✓ · Translation ✓ · Result",
        "guided.phase.srt": "Existing SRT · Choose an operation",
        "guided.phase.srt_result": "Existing SRT ✓ · Result",
        "guided.transcription_ready": "Transcription saved. Choose the final subtitle language; translation starts only when you ask.",
        "guided.captions.count": "{count} subtitles · {name}",
        "guided.original_ready": "The original-language transcription is ready.",
        "guided.audio_cost": "Audio estimate: {cost}",
        "guided.translation_cost": "Translation estimate: {cost}",
        "guided.transcription.estimate": "Selected: {minutes:.1f} min · audio estimate: {cost}",
        "guided.translation.estimate": "Translation: {groups} groups · about {cost}{qualifier}. Estimate, not a spending limit.",
        "guided.translation.pending": "Transcription ready. Select Start translation to create the final SRT.",
        "guided.translation.calculating": "Calculating translation estimate…",
        "guided.resume.transcription": "Resume transcription",
        "guided.resume.translation": "Resume translation",
        "guided.result.ready": "SRT ready · {name}",
        "guided.summary.download": "Download · {name}",
        "guided.summary.transcription": "Transcription · {name}{interval}",
        "guided.summary.translation": "Translation into {language} · {name}",
        "guided.summary.ready": "Subtitles in {language} · {name}{interval}",
        "guided.range.summary": " · range {start}–{end}",
        "menu.tools": "Tools",
        "menu.settings": "Settings",
        "menu.jobs": "Jobs",
        "menu.translate_srt": "Translate SRT…",
        "menu.improve_srt": "Improve subtitles…",
        "menu.readability": "Improve SRT readability…",
        "menu.api_key": "Configure API key…",
        "menu.interface_language": "Interface Language",
        "menu.language.english": "English",
        "menu.language.italian": "Italian",
        "menu.recent_jobs": "Recent jobs…",
        "menu.storage": "Storage and temporary files…",
        "main.no_video": "No media file selected",
        "main.choose_source": "Choose a video or audio file, or download a video from a link.",
        "main.choose_video": "Choose file…",
        "main.from_link": "From link…",
        "main.existing_srt": "Already have subtitles? Translate an SRT without loading a video.",
        "main.source": "Source",
        "main.video": "Media file",
        "main.copy_path": "Copy path",
        "main.audio_track": "Audio track",
        "main.spoken_language": "Spoken language",
        "main.final_subtitles": "Final subtitles",
        "main.final_language": "Final language",
        "main.range": "Range",
        "main.start": "Start",
        "main.end": "End",
        "main.whole_video": "Whole file",
        "main.save_srt": "Save SRT to",
        "main.choose": "Choose…",
        "main.choose_destination": "Choose a destination",
        "main.folder": "Folder: {name}",
        "main.advanced_show": "Show advanced options",
        "main.advanced_hide": "Hide advanced options",
        "main.summary_option": "Also create a summary with topics and links (.txt)",
        "main.summary_help": "Topics, summary and web links · separate estimate and start after the SRT.",
        "main.translation_model": "Translation model",
        "main.refresh_models": "Refresh models",
        "main.model_quality": "Expected quality: {quality} · reviewed {date} for {languages}.",
        "main.model_quality_unrated": "Expected quality: not evaluated for subtitles.",
        "main.model_unverified": "New account-visible models need verified price and compatibility before use: {models}.",
        "main.catalog_partial": "Model catalog updated partially; the last verified prices remain in use.",
        "main.context": "Context and terminology (optional)",
        "main.range_hint": "Decimal minutes are also accepted; use ←/→ to adjust by one second.",
        "main.model_selected": "Selected translation model: {model}.",
        "main.activity": "Activity",
        "main.result": "Result",
        "main.result_pending": "The file will appear here when the job finishes.",
        "main.generate": "Generate subtitles",
        "main.generate_transcription": "Generate transcription",
        "main.start_translation": "Start translation",
        "main.resume": "Resume",
        "main.cancel": "Stop",
        "main.open_srt": "Open SRT",
        "main.open_txt": "Open TXT",
        "main.create_txt": "Create TXT",
        "main.show_finder": "Show in Finder",
        "main.view_issues": "View issues",
        "main.new_job": "New job",
        "main.ready": "Ready.",
        "main.video_required": "Available after a video or audio file is loaded.",
        "main.estimate_video": "Select a video or audio file to see the estimate.",
        "main.select_media_to_start": "Choose a video or audio file to begin.",
        "main.select_media_first": "Select a video or audio file first.",
        "main.reading_media": "Reading media information…",
        "main.media_ready": "Ready. Check the audio track and start when you want.",
        "main.path_copied": "Media file path copied to the clipboard.",
        "help.spoken.title": "Spoken language",
        "help.spoken.body": "The language spoken in the audio. Automatic lets the service detect it; if the result is ambiguous, you can select it after transcription.",
        "help.final.title": "Final language",
        "help.final.body": "The language of the SRT you will receive. If it matches the spoken language, the app uses the transcription directly.",
        "help.range.title": "Range",
        "help.range.body": "Enter HH:MM:SS or decimal minutes, using a comma or period. Final timestamps remain relative to the original media file.",
        "help.model.title": "Model",
        "help.model.body": "The model is used for translation and contextual revision. Models have different prices; price does not guarantee a specific linguistic result.",
        "help.context.title": "Context",
        "help.context.body": "Add useful translation information, for example: “botany lesson; X is a person's name”. Context is optional.",
        "help.cost.title": "Estimate and cost",
        "help.cost.body": "The audio estimate is shown before starting. Translation is estimated after the text is available. It is an estimate, not a spending limit.",
        "language.auto": "Automatic",
        "language.original": "Original",
        "language.en": "English",
        "language.it": "Italian",
        "language.ja": "Japanese",
        "language.fr": "French",
        "quality.economy": "economy",
        "quality.balanced": "balanced",
        "quality.advanced": "advanced",
        "quality.unrated": "not evaluated",
        "details.show": "Show details",
        "details.hide": "Hide details",
        "details.all": "All events",
        "details.warnings": "Warnings and errors",
        "details.latest": "Go to latest events",
        "details.copy": "Copy diagnostics",
        "details.open_log": "Open log",
        "dialog.download.title": "Download from a link",
        "dialog.download.heading": "Download a video",
        "dialog.download.public_link": "Public link",
        "dialog.download.analyze": "Analyze link",
        "dialog.download.video": "Video to download",
        "dialog.download.format": "Format",
        "dialog.download.audio": "Audio track",
        "dialog.download.filename": "File name",
        "dialog.download.extension": "The extension is added automatically",
        "dialog.download.save": "Save",
        "dialog.download.folder": "Folder",
        "dialog.download.download": "Download video",
        "dialog.download.another": "Download another video",
        "dialog.download.default_track": "Website default track",
        "dialog.download.paste": "Paste the link to one public video and analyze it.",
        "dialog.download.ready": "Ready.",
        "dialog.recent": "Recent jobs",
        "dialog.storage": "Storage and temporary files",
        "dialog.refresh": "Refresh",
        "dialog.open_record": "Open record…",
        "dialog.operation": "Operation",
        "dialog.source": "Source",
        "dialog.status": "Status",
        "dialog.progress": "Progress",
        "dialog.cost": "Cost",
        "dialog.modified": "Modified",
        "dialog.loading_jobs": "Loading saved jobs…",
        "dialog.cleanup_selected": "Delete temporary files…",
        "dialog.cleanup_all": "Delete all temporary files…",
        "dialog.close": "Close",
        "dialog.translation": "Translate subtitles",
        "dialog.revision": "Improve subtitles",
        "dialog.media.choose": "Choose a video or audio file",
        "dialog.from": "From",
        "dialog.to": "To",
        "dialog.model": "Model",
        "dialog.revision_type": "Revision type",
        "dialog.conservative": "Conservative — keeps every word",
        "dialog.linguistic": "Linguistic — may correct small parts of a sentence",
        "dialog.actual_cost": "Actual cost: $0.0000 USD",
        "dialog.start_translation": "Start translation",
        "dialog.start_revision": "Start revision",
        "dialog.details": "Details…",
        "dialog.captions": "Subtitles: {count}",
        "filetype.media": "Video and audio",
        "filetype.video": "Video",
        "filetype.audio": "Audio",
        "filetype.all": "All files",
        "restart.title": "Restart SRT Compass",
        "restart.failed": "The language was saved but the app could not restart automatically. It will be used next time you open SRT Compass.\n\n{error}",
    },
    "it": {
        "app.name": "SRT Compass",
        "guided.home.title": "Cosa vuoi fare?",
        "guided.media.title": "Crea sottotitoli da audio o video",
        "guided.media.description": "Scegli un file locale o scarica un video, poi trascrivilo.",
        "guided.srt.title": "Lavora su un SRT esistente",
        "guided.srt.description": "Traduci, revisiona o migliora la leggibilità senza un video.",
        "guided.srt.choose": "Scegli che cosa fare con il file di sottotitoli.",
        "guided.srt.active": "Completa prima lo strumento SRT",
        "guided.back": "Indietro",
        "guided.open_original": "Apri trascrizione",
        "guided.use_original": "Usa trascrizione",
        "guided.continue": "Continua alla traduzione",
        "guided.cost.disclaimer": "Stima, non limite massimo di spesa.",
        "guided.phase.home": "Scegli un percorso",
        "guided.phase.source": "Sorgente → Trascrizione → Traduzione",
        "guided.phase.transcription": "Sorgente ✓ · Trascrizione → Traduzione",
        "guided.phase.translation": "Sorgente ✓ · Trascrizione ✓ · Traduzione",
        "guided.phase.processing": "In corso · {name}",
        "guided.phase.result": "Sorgente ✓ · Trascrizione ✓ · Risultato",
        "guided.phase.result_translation": "Sorgente ✓ · Trascrizione ✓ · Traduzione ✓ · Risultato",
        "guided.phase.srt": "SRT esistente · Scegli un'operazione",
        "guided.phase.srt_result": "SRT esistente ✓ · Risultato",
        "guided.transcription_ready": "Trascrizione salvata. Scegli la lingua finale; la traduzione parte solo se lo chiedi.",
        "guided.captions.count": "{count} sottotitoli · {name}",
        "guided.original_ready": "La trascrizione nella lingua originale è pronta.",
        "guided.audio_cost": "Stima audio: {cost}",
        "guided.translation_cost": "Stima traduzione: {cost}",
        "guided.transcription.estimate": "Selezionati: {minutes:.1f} min · stima audio: {cost}",
        "guided.translation.estimate": "Traduzione: {groups} gruppi · circa {cost}{qualifier}. Stima, non limite massimo di spesa.",
        "guided.translation.pending": "Trascrizione pronta. Premi Avvia traduzione per creare l’SRT finale.",
        "guided.translation.calculating": "Calcolo la stima della traduzione…",
        "guided.resume.transcription": "Riprendi trascrizione",
        "guided.resume.translation": "Riprendi traduzione",
        "guided.result.ready": "SRT pronto · {name}",
        "guided.summary.download": "Download · {name}",
        "guided.summary.transcription": "Trascrizione · {name}{interval}",
        "guided.summary.translation": "Traduzione in {language} · {name}",
        "guided.summary.ready": "Sottotitoli in {language} · {name}{interval}",
        "guided.range.summary": " · intervallo {start}–{end}",
        "menu.tools": "Strumenti",
        "menu.settings": "Impostazioni",
        "menu.jobs": "Lavori",
        "menu.translate_srt": "Traduci SRT…",
        "menu.improve_srt": "Migliora sottotitoli…",
        "menu.readability": "Migliora leggibilità SRT…",
        "menu.api_key": "Configura chiave API…",
        "menu.interface_language": "Lingua dell’interfaccia",
        "menu.language.english": "Inglese",
        "menu.language.italian": "Italiano",
        "menu.recent_jobs": "Lavori recenti…",
        "menu.storage": "Spazio e file temporanei…",
        "main.no_video": "Nessun file multimediale selezionato",
        "main.choose_source": "Scegli un video o un file audio, oppure scarica un video da un link.",
        "main.choose_video": "Scegli file…",
        "main.from_link": "Da link…",
        "main.existing_srt": "Hai già i sottotitoli? Traduci un SRT senza caricare un video.",
        "main.source": "Sorgente",
        "main.video": "File multimediale",
        "main.copy_path": "Copia percorso",
        "main.audio_track": "Traccia audio",
        "main.spoken_language": "Lingua parlata",
        "main.final_subtitles": "Sottotitoli finali",
        "main.final_language": "Lingua finale",
        "main.range": "Intervallo",
        "main.start": "Inizio",
        "main.end": "Fine",
        "main.whole_video": "Tutto il file",
        "main.save_srt": "Salva SRT in",
        "main.choose": "Scegli…",
        "main.choose_destination": "Scegli una destinazione",
        "main.folder": "Cartella: {name}",
        "main.advanced_show": "Mostra opzioni avanzate",
        "main.advanced_hide": "Nascondi opzioni avanzate",
        "main.summary_option": "Crea anche un riassunto con temi e link (.txt)",
        "main.summary_help": "Tematiche, riassunto e link web · costo e avvio separati dopo l’SRT.",
        "main.translation_model": "Modello traduzione",
        "main.refresh_models": "Aggiorna modelli",
        "main.model_quality": "Qualità attesa: {quality} · valutata il {date} per {languages}.",
        "main.model_quality_unrated": "Qualità attesa: non valutata sui sottotitoli.",
        "main.model_unverified": "Nuovi modelli visibili all’account da verificare per prezzo e compatibilità: {models}.",
        "main.catalog_partial": "Catalogo modelli aggiornato solo in parte; restano in uso le ultime tariffe verificate.",
        "main.context": "Contesto e terminologia (facoltativo)",
        "main.range_hint": "Anche minuti decimali; usa ←/→ per regolare di un secondo.",
        "main.model_selected": "Modello selezionato per la traduzione: {model}.",
        "main.activity": "Attività",
        "main.result": "Risultato",
        "main.result_pending": "Il file comparirà qui al termine del lavoro.",
        "main.generate": "Genera sottotitoli",
        "main.generate_transcription": "Genera trascrizione",
        "main.start_translation": "Avvia traduzione",
        "main.resume": "Riprendi",
        "main.cancel": "Interrompi",
        "main.open_srt": "Apri SRT",
        "main.open_txt": "Apri TXT",
        "main.create_txt": "Crea TXT",
        "main.show_finder": "Mostra nel Finder",
        "main.view_issues": "Vedi problemi",
        "main.new_job": "Nuovo lavoro",
        "main.ready": "Pronto.",
        "main.video_required": "Disponibile dopo il caricamento di un video o file audio.",
        "main.estimate_video": "Seleziona un video o file audio per vedere la stima.",
        "main.select_media_to_start": "Scegli un video o file audio per iniziare.",
        "main.select_media_first": "Seleziona prima un video o file audio.",
        "main.reading_media": "Leggo le informazioni del file multimediale…",
        "main.media_ready": "Pronto. Controlla la traccia audio e avvia quando vuoi.",
        "main.path_copied": "Percorso del file multimediale copiato negli appunti.",
        "help.spoken.title": "Lingua parlata",
        "help.spoken.body": "È la lingua che viene pronunciata nell'audio. Automatico lascia che il servizio la rilevi; se il risultato è ambiguo potrai indicarla dopo la trascrizione.",
        "help.final.title": "Lingua finale",
        "help.final.body": "È la lingua del file SRT che riceverai. Se coincide con la lingua parlata, l’app usa direttamente la trascrizione.",
        "help.range.title": "Intervallo",
        "help.range.body": "Inserisci HH:MM:SS oppure minuti decimali, con virgola o punto. I timestamp finali restano riferiti al file multimediale originale.",
        "help.model.title": "Modello",
        "help.model.body": "Il modello si usa per traduzione e revisione contestuale. Modelli diversi hanno tariffe diverse; il prezzo non garantisce un risultato linguistico specifico.",
        "help.context.title": "Contesto",
        "help.context.body": "Aggiungi informazioni utili per tradurre, per esempio: “lezione di botanica; il termine X è il nome di una persona”. Non serve per forza un contesto.",
        "help.cost.title": "Stima e costo",
        "help.cost.body": "La stima audio viene mostrata prima dell'avvio. Se traduci, il costo viene stimato dopo aver ottenuto il testo. È un'indicazione, non un limite massimo di spesa.",
        "language.auto": "Automatico",
        "language.original": "Originale",
        "language.en": "Inglese",
        "language.it": "Italiano",
        "language.ja": "Giapponese",
        "language.fr": "Francese",
        "quality.economy": "economica",
        "quality.balanced": "equilibrata",
        "quality.advanced": "avanzata",
        "quality.unrated": "non valutata",
        "details.show": "Mostra dettagli",
        "details.hide": "Nascondi dettagli",
        "details.all": "Tutti gli eventi",
        "details.warnings": "Avvisi ed errori",
        "details.latest": "Vai agli ultimi eventi",
        "details.copy": "Copia diagnostica",
        "details.open_log": "Apri log",
        "dialog.download.title": "Scarica da un link",
        "dialog.download.heading": "Scarica un video",
        "dialog.download.public_link": "Link pubblico",
        "dialog.download.analyze": "Analizza link",
        "dialog.download.video": "Video da scaricare",
        "dialog.download.format": "Formato",
        "dialog.download.audio": "Traccia audio",
        "dialog.download.filename": "Nome del file",
        "dialog.download.extension": "L’estensione viene aggiunta automaticamente",
        "dialog.download.save": "Salvataggio",
        "dialog.download.folder": "Cartella",
        "dialog.download.download": "Scarica video",
        "dialog.download.another": "Scarica un altro video",
        "dialog.download.default_track": "Traccia predefinita del sito",
        "dialog.download.paste": "Incolla il link di un singolo video pubblico e analizzalo.",
        "dialog.download.ready": "Pronto.",
        "dialog.recent": "Lavori recenti",
        "dialog.storage": "Spazio e file temporanei",
        "dialog.refresh": "Aggiorna",
        "dialog.open_record": "Apri registro…",
        "dialog.operation": "Operazione",
        "dialog.source": "Sorgente",
        "dialog.status": "Stato",
        "dialog.progress": "Avanzamento",
        "dialog.cost": "Costo",
        "dialog.modified": "Modificato",
        "dialog.loading_jobs": "Carico i registri salvati…",
        "dialog.cleanup_selected": "Elimina temporanei…",
        "dialog.cleanup_all": "Elimina tutti i temporanei…",
        "dialog.close": "Chiudi",
        "dialog.translation": "Traduci i sottotitoli",
        "dialog.revision": "Migliora i sottotitoli",
        "dialog.media.choose": "Scegli un video o file audio",
        "dialog.from": "Da",
        "dialog.to": "A",
        "dialog.model": "Modello",
        "dialog.revision_type": "Tipo di revisione",
        "dialog.conservative": "Conservativa — mantiene tutte le parole",
        "dialog.linguistic": "Linguistica — può correggere piccole parti della frase",
        "dialog.actual_cost": "Costo effettivo: $0,0000 USD",
        "dialog.start_translation": "Avvia traduzione",
        "dialog.start_revision": "Avvia revisione",
        "dialog.details": "Dettagli…",
        "dialog.captions": "Sottotitoli: {count}",
        "filetype.media": "Video e audio",
        "filetype.video": "Video",
        "filetype.audio": "Audio",
        "filetype.all": "Tutti i file",
        "restart.title": "Riavvia SRT Compass",
        "restart.failed": "La lingua è stata salvata, ma non è stato possibile riavviare automaticamente l’app. Verrà usata alla prossima apertura di SRT Compass.\n\n{error}",
    },
}

# The executable loads the persisted/system locale before creating widgets.
# Italian here preserves compatibility for modules imported directly by older
# integrations and tests that do not run the application entry point.
_locale = "it"


def normalize_locale(value: str | None) -> str:
    code = (value or "").replace("-", "_").split("_", 1)[0].lower()
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


def detect_system_locale() -> str:
    """Return the desktop's primary UI language with a portable fallback."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                text=True,
                capture_output=True,
                check=False,
                timeout=2,
            )
            if result.returncode == 0:
                for token in result.stdout.replace("(", "").replace(")", "").split(","):
                    candidate = token.strip().strip('"')
                    if candidate:
                        return normalize_locale(candidate)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        return normalize_locale(system_locale.getlocale()[0])
    except (ValueError, TypeError):
        return DEFAULT_LOCALE


def load_locale(preferences_path: Path) -> str:
    try:
        data = json.loads(preferences_path.read_text(encoding="utf-8"))
        value = data.get("ui_locale")
        if value in SUPPORTED_LOCALES:
            return str(value)
    except (OSError, ValueError, TypeError):
        pass
    return detect_system_locale()


def save_locale(preferences_path: Path, locale_code: str) -> None:
    locale_code = normalize_locale(locale_code)
    data: dict[str, Any] = {}
    try:
        loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, ValueError, TypeError):
        pass
    data["ui_locale"] = locale_code
    preferences_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = preferences_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, preferences_path)


def set_locale(locale_code: str) -> None:
    global _locale
    _locale = normalize_locale(locale_code)


def get_locale() -> str:
    return _locale


def tr(message_id: str, **values: Any) -> str:
    template = CATALOGS.get(_locale, CATALOGS[DEFAULT_LOCALE]).get(message_id)
    if template is None:
        template = CATALOGS[DEFAULT_LOCALE].get(message_id, message_id)
    return template.format(**values) if values else template


def language_label(code: str) -> str:
    return tr(f"language.{code}")


def language_code(label: str, *, include_source: bool = True) -> str | None:
    codes = ("auto", "en", "it", "ja", "fr", "original") if include_source else ("en", "it", "ja", "original")
    for code in codes:
        if label == language_label(code):
            return code
    return None

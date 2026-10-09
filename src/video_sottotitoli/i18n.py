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
        "main.no_video": "No video selected",
        "main.choose_source": "Choose a video or download one from a link.",
        "main.choose_video": "Choose video…",
        "main.from_link": "From link…",
        "main.source": "Source",
        "main.video": "Video",
        "main.copy_path": "Copy path",
        "main.audio_track": "Audio track",
        "main.spoken_language": "Spoken language",
        "main.final_subtitles": "Final subtitles",
        "main.final_language": "Final language",
        "main.range": "Range",
        "main.start": "Start",
        "main.end": "End",
        "main.whole_video": "Whole video",
        "main.save_srt": "Save SRT to",
        "main.choose": "Choose…",
        "main.choose_destination": "Choose a destination",
        "main.folder": "Folder: {name}",
        "main.advanced_show": "Show advanced options",
        "main.advanced_hide": "Hide advanced options",
        "main.summary_option": "Also create a summary with topics and links (.txt)",
        "main.summary_help": "Topics, summary and web links · separate estimate and start after the SRT.",
        "main.translation_model": "Translation model",
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
        "main.video_required": "Available after a video is loaded.",
        "main.estimate_video": "Select a video to see the estimate.",
        "help.spoken.title": "Spoken language",
        "help.spoken.body": "The language spoken in the video. Automatic lets the service detect it; if the result is ambiguous, you can select it after transcription.",
        "help.final.title": "Final language",
        "help.final.body": "The language of the SRT you will receive. If it matches the spoken language, the app uses the transcription directly.",
        "help.range.title": "Range",
        "help.range.body": "Enter HH:MM:SS or decimal minutes, using a comma or period. Final timestamps remain relative to the original video.",
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
        "restart.title": "Restart SRT Compass",
        "restart.failed": "The language was saved but the app could not restart automatically. It will be used next time you open SRT Compass.\n\n{error}",
    },
    "it": {
        "app.name": "SRT Compass",
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
        "main.no_video": "Nessun video selezionato",
        "main.choose_source": "Scegli un video o scaricalo da un link.",
        "main.choose_video": "Scegli video…",
        "main.from_link": "Da link…",
        "main.source": "Sorgente",
        "main.video": "Video",
        "main.copy_path": "Copia percorso",
        "main.audio_track": "Traccia audio",
        "main.spoken_language": "Lingua parlata",
        "main.final_subtitles": "Sottotitoli finali",
        "main.final_language": "Lingua finale",
        "main.range": "Intervallo",
        "main.start": "Inizio",
        "main.end": "Fine",
        "main.whole_video": "Tutto il video",
        "main.save_srt": "Salva SRT in",
        "main.choose": "Scegli…",
        "main.choose_destination": "Scegli una destinazione",
        "main.folder": "Cartella: {name}",
        "main.advanced_show": "Mostra opzioni avanzate",
        "main.advanced_hide": "Nascondi opzioni avanzate",
        "main.summary_option": "Crea anche un riassunto con temi e link (.txt)",
        "main.summary_help": "Tematiche, riassunto e link web · costo e avvio separati dopo l’SRT.",
        "main.translation_model": "Modello traduzione",
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
        "main.video_required": "Disponibile dopo il caricamento del video.",
        "main.estimate_video": "Seleziona un video per vedere la stima.",
        "help.spoken.title": "Lingua parlata",
        "help.spoken.body": "È la lingua che viene pronunciata nel video. Automatico lascia che il servizio la rilevi; se il risultato è ambiguo potrai indicarla dopo la trascrizione.",
        "help.final.title": "Lingua finale",
        "help.final.body": "È la lingua del file SRT che riceverai. Se coincide con la lingua parlata, l’app usa direttamente la trascrizione.",
        "help.range.title": "Intervallo",
        "help.range.body": "Inserisci HH:MM:SS oppure minuti decimali, con virgola o punto. I timestamp finali restano riferiti al video originale.",
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

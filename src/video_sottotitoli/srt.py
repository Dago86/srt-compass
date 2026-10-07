from __future__ import annotations

import re
from pathlib import Path

from .models import Caption, Word

MAX_LINE_LENGTH = 42
MAX_LINES = 2
MAX_CAPTION_CHARS = MAX_LINE_LENGTH * MAX_LINES

MIN_CAPTION_DURATION = 1.0
MAX_CAPTION_DURATION = 6.0

# Velocità di lettura ideale indicativa.
TARGET_CPS = 17.0

# Minimo spazio tra due sottotitoli.
MIN_GAP = 0.05

# Una pausa di questa durata può chiudere una caption.
PAUSE_BREAK = 0.65


# Parole che è brutto lasciare alla fine della prima riga.
# Es:
#
#   I went to
#   the house
#
# meglio di:
#
#   I went to the
#   house
#
_WEAK_LINE_ENDS = {
    # English
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "and",
    "or",
    "but",
    "as",
    "if",
    "that",
    # Italiano, utile anche quando aggiungeremo la traduzione
    "il",
    "lo",
    "la",
    "i",
    "gli",
    "le",
    "un",
    "uno",
    "una",
    "di",
    "da",
    "con",
    "su",
    "per",
    "tra",
    "fra",
    "e",
    "o",
    "ma",
    "che",
    "se",
    "non",
}


_TIMESTAMP_RE = re.compile(
    r"(?P<h>\d{1,2}):"
    r"(?P<m>\d{2}):"
    r"(?P<s>\d{2})"
    r"[,.]"
    r"(?P<ms>\d{3})"
)

_TIMING_RE = re.compile(
    r"^\s*"
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
    r"(?:\s+.*)?$"
)


# ---------------------------------------------------------------------------
# WHISPER -> WORD
# ---------------------------------------------------------------------------


def _normalize_token(text: str) -> str:
    """
    Versione di una parola usata solo per confrontare
    il token Whisper con il testo punteggiato.
    """
    return re.sub(
        r"[^\w'’-]+",
        "",
        text,
        flags=re.UNICODE,
    ).casefold()


def _punctuated_tokens(response: dict) -> list[str]:
    """
    Recupera il testo dei segmenti Whisper,
    che contiene la punteggiatura.
    """
    tokens: list[str] = []

    for segment in response.get("segments") or []:
        text = str(segment.get("text", "")).strip()

        if text:
            tokens.extend(text.split())

    # Fallback: usa il testo completo.
    if not tokens:
        text = str(response.get("text", "")).strip()

        if text:
            tokens = text.split()

    return tokens


def words_from_response(response: dict, offset: float) -> list[Word]:
    """
    Usa i timestamp precisi di response["words"],
    ma recupera maiuscole e punteggiatura dai segmenti.
    """

    raw_words = response.get("words") or []
    punctuated = _punctuated_tokens(response)

    result: list[Word] = []
    token_index = 0

    for item in raw_words:
        try:
            raw_text = str(item["word"]).strip()
            start = float(item["start"]) + offset
            end = float(item["end"]) + offset

        except (KeyError, TypeError, ValueError):
            continue

        if not raw_text or end < start:
            continue

        display_text = raw_text
        wanted = _normalize_token(raw_text)

        # Cerca il corrispondente token nel testo
        # punteggiato di Whisper.
        for index in range(
            token_index,
            min(token_index + 6, len(punctuated)),
        ):
            candidate = punctuated[index]

            if _normalize_token(candidate) == wanted:
                prefix = ""

                # Eventuali simboli standalone prima della parola:
                # es. " Hello
                for before in punctuated[token_index:index]:
                    if not _normalize_token(before):
                        prefix += before

                display_text = prefix + candidate
                token_index = index + 1

                # Eventuale punteggiatura standalone subito dopo.
                while (
                    token_index < len(punctuated)
                    and not _normalize_token(punctuated[token_index])
                ):
                    display_text += punctuated[token_index]
                    token_index += 1

                break

        result.append(
            Word(
                text=display_text,
                start=start,
                end=end,
            )
        )

    return result


def detected_language(response: dict) -> str | None:
    """Normalizza la lingua restituita da Whisper, se supportata dall'app."""
    detected = str(response.get("language", "")).strip().lower()

    aliases = {
        "japanese": "ja",
        "english": "en",
        "italian": "it",
        "french": "fr",
        "ja": "ja",
        "en": "en",
        "it": "it",
        "fr": "fr",
    }

    return aliases.get(detected)


def _effective_language(response: dict, requested: str) -> str:
    """Restituisce un codice lingua coerente anche quando la GUI usa auto."""
    if requested and requested != "auto":
        return requested
    return detected_language(response) or "auto"


def captions_from_response(
    response: dict, offset: float, language: str = "auto"
) -> list[Caption]:
    """Converte Whisper senza inserire spazi artificiali nel giapponese."""
    language = _effective_language(response, language)
    words = words_from_response(response, offset)
    if language != "ja" and words:
        return compose_captions(words)
    captions: list[Caption] = []
    for segment in response.get("segments") or []:
        try:
            text = str(segment["text"]).strip()
            start = float(segment["start"]) + offset
            end = float(segment["end"]) + offset
        except (KeyError, TypeError, ValueError):
            continue
        if text and end >= start:
            captions.append(Caption(start, end, (text,)))
    if captions:
        return captions
    return compose_captions(words) if words else []

# ---------------------------------------------------------------------------
# TESTO
# ---------------------------------------------------------------------------


def _clean_text(text: str) -> str:
    """
    Normalizza gli spazi senza modificare realmente il contenuto.
    """

    text = text.replace("\ufeff", "").replace("\r", " ").replace("\n", " ")

    text = re.sub(r"\s+", " ", text).strip()

    # "hello ," -> "hello,"
    text = re.sub(
        r"\s+([,.;:!?])",
        r"\1",
        text,
    )

    return text


def join_caption_lines(lines: list[str]) -> str:
    """Join visual lines without introducing spaces inside Japanese text."""
    pieces = [line.strip() for line in lines if line.strip()]
    if not pieces:
        return ""
    text = pieces[0]
    for piece in pieces[1:]:
        previous = text[-1]
        following = piece[0]
        japanese_before = (
            "\u3040" <= previous <= "\u30ff"
            or "\u3400" <= previous <= "\u9fff"
            or previous in "。、，．！？「」『』"
        )
        japanese_after = (
            "\u3040" <= following <= "\u30ff"
            or "\u3400" <= following <= "\u9fff"
            or following in "。、，．！？「」『』"
        )
        text += ("" if japanese_before and japanese_after else " ") + piece
    return _clean_text(text)


# ---------------------------------------------------------------------------
# LINE BREAK
# ---------------------------------------------------------------------------


def _split_score(left: str, right: str) -> float:
    """
    Valuta quanto è bello un determinato punto di a-capo.

    Più basso = meglio.
    """

    if not left or not right:
        return 10_000.0

    # Cerchiamo innanzitutto due righe abbastanza equilibrate.
    score = abs(len(left) - len(right)) * 1.4

    # Evita righe ridicolmente corte.
    if len(left) < 12:
        score += (12 - len(left)) * 2

    if len(right) < 12:
        score += (12 - len(right)) * 2

    last_word = re.sub(
        r"[^\w'’-]+$",
        "",
        left.lower(),
    ).split(" ")[-1]

    first_word = re.sub(
        r"^[^\w'’-]+",
        "",
        right.lower(),
    ).split(" ")[0]

    # Penalizza:
    #
    #   I went to the
    #   house
    #
    # oppure:
    #
    #   Sono andato di
    #   là
    #
    if last_word in _WEAK_LINE_ENDS:
        score += 35

    # Non iniziare una riga con punteggiatura.
    if right[0] in ",.;:!?)]}":
        score += 100

    # Virgole e segni sintattici sono buoni punti
    # in cui andare a capo.
    if left.endswith((",", ";", ":")):
        score -= 8

    if left.endswith((".", "!", "?")):
        score -= 14

    # Piccola penalità per una congiunzione
    # all'inizio della seconda riga.
    if first_word in {
        "and",
        "or",
        "but",
        "e",
        "o",
        "ma",
    }:
        score += 5

    return score


def _wrap_two_lines(text: str) -> tuple[str, ...]:
    """
    Trasforma una caption in una o due righe
    cercando il punto di divisione migliore.
    """

    text = _clean_text(text)

    if not text:
        return ()

    if len(text) <= MAX_LINE_LENGTH:
        return (text,)

    spaces = [index for index, char in enumerate(text) if char == " "]

    candidates: list[tuple[float, str, str]] = []

    for split_at in spaces:
        left = text[:split_at].strip()
        right = text[split_at + 1 :].strip()

        if len(left) <= MAX_LINE_LENGTH and len(right) <= MAX_LINE_LENGTH:
            candidates.append(
                (
                    _split_score(left, right),
                    left,
                    right,
                )
            )

    if candidates:
        _, left, right = min(
            candidates,
            key=lambda item: item[0],
        )

        return (
            left,
            right,
        )

    # Qui il testo è troppo lungo perfino per due righe.
    # Verrà diviso in più caption dal livello superiore.
    return (text,)


# ---------------------------------------------------------------------------
# CREAZIONE CAPTION DA WORD TIMESTAMPS
# ---------------------------------------------------------------------------


def _text_len(words: list[Word]) -> int:
    return len(" ".join(word.text for word in words))


def _should_close(
    words: list[Word],
    candidate: Word,
) -> bool:

    if not words:
        return False

    start = words[0].start
    previous = words[-1]

    duration_with_candidate = candidate.end - start

    would_be = _text_len(words) + 1 + len(candidate.text)

    # Troppo testo.
    if would_be > MAX_CAPTION_CHARS:
        return True

    # Troppo tempo.
    if duration_with_candidate > MAX_CAPTION_DURATION:
        return True

    current_duration = max(
        0.01,
        previous.end - start,
    )

    pause = candidate.start - previous.end

    strong_punctuation = previous.text.endswith((".", "!", "?"))

    soft_punctuation = previous.text.endswith((",", ";", ":"))

    # Pausa naturale nel parlato.
    if pause >= PAUSE_BREAK and current_duration >= MIN_CAPTION_DURATION:
        return True

    # Fine frase.
    if strong_punctuation and current_duration >= MIN_CAPTION_DURATION:
        return True

    # Virgola ecc., ma soltanto se la caption
    # è già abbastanza corposa.
    return soft_punctuation and current_duration >= 2.0 and _text_len(words) >= 35


def _make_caption(
    words: list[Word],
) -> Caption:

    text = " ".join(word.text for word in words)

    return Caption(
        start=words[0].start,
        end=words[-1].end,
        lines=_wrap_two_lines(text),
    )


def _extend_for_readability(
    captions: list[Caption],
) -> list[Caption]:
    """
    Se c'è del silenzio tra una caption e la successiva,
    sfruttalo per lasciare il testo sullo schermo un po'
    più a lungo.

    Non modifica il momento in cui il testo compare:
    modifica soltanto, quando possibile, il momento
    in cui sparisce.
    """

    if not captions:
        return []

    result: list[Caption] = []

    for index, caption in enumerate(captions):
        text = " ".join(caption.lines)

        natural_end = caption.end

        desired_duration = min(
            MAX_CAPTION_DURATION,
            max(
                MIN_CAPTION_DURATION,
                len(text) / TARGET_CPS,
            ),
        )

        desired_end = caption.start + desired_duration

        if index + 1 < len(captions):
            next_start = captions[index + 1].start

            # Non invadere la caption successiva.
            end = min(
                max(
                    natural_end,
                    desired_end,
                ),
                next_start - MIN_GAP,
            )

            # Mai accorciare il parlato vero.
            end = max(
                natural_end,
                end,
            )

        else:
            # Ultima caption:
            # massimo mezzo secondo extra.
            end = min(
                max(
                    natural_end,
                    desired_end,
                ),
                natural_end + 0.5,
            )

        result.append(
            Caption(
                start=caption.start,
                end=max(
                    end,
                    caption.start + 0.01,
                ),
                lines=caption.lines,
            )
        )

    # Sicurezza finale anti-overlap.
    normalized: list[Caption] = []

    previous_end = 0.0

    for caption in result:
        start = max(
            caption.start,
            previous_end,
        )

        end = max(
            caption.end,
            start + 0.01,
        )

        normalized.append(
            Caption(
                start=start,
                end=end,
                lines=caption.lines,
            )
        )

        previous_end = end

    return normalized


def compose_captions(
    words: list[Word],
) -> list[Caption]:
    """
    Crea caption partendo dai timestamp parola-per-parola
    restituiti da Whisper.
    """

    captions: list[Caption] = []
    current: list[Word] = []

    for word in words:
        if _should_close(
            current,
            word,
        ):
            captions.append(_make_caption(current))

            current = []

        current.append(word)

    if current:
        captions.append(_make_caption(current))

    return _extend_for_readability(captions)


# ---------------------------------------------------------------------------
# PARSER SRT
# ---------------------------------------------------------------------------


def _parse_timestamp(
    value: str,
) -> float:

    match = _TIMESTAMP_RE.fullmatch(value.strip())

    if not match:
        raise ValueError(f"Timestamp SRT non valido: {value}")

    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000
    )


def parse_srt(
    text: str,
) -> list[Caption]:
    """
    Legge un SRT già esistente.

    Gli indici originali vengono ignorati:
    saranno rigenerati correttamente in output.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")

    if not normalized.strip():
        return []

    blocks = re.split(
        r"\n\s*\n",
        normalized.strip(),
    )

    captions: list[Caption] = []

    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]

        if not lines:
            continue

        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )

        if timing_index is None:
            continue

        match = _TIMING_RE.match(lines[timing_index])

        if not match:
            continue

        start = _parse_timestamp(match.group("start"))

        end = _parse_timestamp(match.group("end"))

        if end <= start:
            continue

        body = join_caption_lines(lines[timing_index + 1 :])

        if body:
            captions.append(
                Caption(
                    start=start,
                    end=end,
                    lines=(body,),
                )
            )

    return captions


# ---------------------------------------------------------------------------
# DIVISIONE DI UN SRT GIÀ ESISTENTE
# ---------------------------------------------------------------------------


def _semantic_chunks(
    text: str,
    max_chars: int = MAX_CAPTION_CHARS,
) -> list[str]:
    """
    Divide una caption troppo lunga.

    Prima cerca di sfruttare:
    . ! ? , ; :

    altrimenti taglia sulle parole.
    """

    text = _clean_text(text)

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    words = text.split()

    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join((*current, word))

        if len(candidate) <= max_chars:
            current.append(word)
            continue

        if current:
            best = None

            # Cerca un buon punto sintattico
            # nella seconda metà della caption.
            for i in range(
                max(1, len(current) // 2),
                len(current),
            ):
                left = " ".join(current[:i])

                if left.endswith(
                    (
                        ".",
                        "!",
                        "?",
                        ",",
                        ";",
                        ":",
                    )
                ):
                    best = i

            if best is not None:
                chunks.append(" ".join(current[:best]))

                current = current[best:]

                if len(" ".join((*current, word))) > max_chars and current:
                    chunks.append(" ".join(current))

                    current = []

            else:
                chunks.append(" ".join(current))

                current = []

        current.append(word)

    if current:
        chunks.append(" ".join(current))

    return [_clean_text(chunk) for chunk in chunks if _clean_text(chunk)]


def _split_existing_caption(
    caption: Caption,
) -> list[Caption]:
    """
    Se un SRT esterno contiene una caption enorme,
    la divide in più sottotitoli.

    Non abbiamo i timestamp delle singole parole,
    quindi il tempo viene distribuito in proporzione
    alla quantità di testo.
    """

    text = _clean_text(" ".join(caption.lines))

    chunks = _semantic_chunks(text)

    if len(chunks) <= 1:
        return [
            Caption(
                start=caption.start,
                end=caption.end,
                lines=_wrap_two_lines(text),
            )
        ]

    duration = caption.end - caption.start

    weights = [max(1, len(chunk)) for chunk in chunks]

    total_weight = sum(weights)

    result: list[Caption] = []

    cursor = caption.start
    used_weight = 0

    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        if index == len(chunks) - 1:
            end = caption.end

        else:
            used_weight += weight

            end = caption.start + duration * (used_weight / total_weight)

        end = max(
            end,
            cursor + 0.01,
        )

        result.append(
            Caption(
                start=cursor,
                end=end,
                lines=_wrap_two_lines(chunk),
            )
        )

        cursor = end

    return result


def format_captions(
    captions: list[Caption],
) -> list[Caption]:
    """
    Formatta caption provenienti da un SRT esterno.
    """
    from .readability import segment_captions

    return segment_captions(captions).captions


# ---------------------------------------------------------------------------
# INPUT SRT ESTERNO
# ---------------------------------------------------------------------------


def format_srt_text(
    text: str,
) -> str:
    """
    Esempio:

        formatted = format_srt_text(original_srt)
    """

    captions = parse_srt(text)
    captions = format_captions(captions)

    return render_srt(captions)


def format_srt_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """
    Formatta direttamente un file SRT.

    Esempio:

        format_srt_file("film.srt")

    produce:

        film_formatted.srt
    """

    source = Path(input_path)

    if output_path is None:
        destination = source.with_name(f"{source.stem}_formatted.srt")

    else:
        destination = Path(output_path)

    if destination.resolve() == source.resolve():
        raise ValueError("Il file di partenza non può essere sovrascritto.")
    from .readability import readability_warnings, segment_captions

    captions = parse_srt(source.read_text(encoding="utf-8-sig"))
    readable = segment_captions(captions)
    formatted = render_srt(readable.captions)
    warnings = readability_warnings(readable.captions)
    previous_report = source.with_name(f"{source.stem}.problemi.txt")
    report = destination.with_name(f"{destination.stem}.problemi.txt")
    split_or_shifted = {
        original: final for original, final in readable.id_map.items()
        if final != (original, original)
    }
    report_lines = [
        "Rapporto di formattazione SRT",
        "I tempi interni dei nuovi blocchi sono stimati localmente dal testo.",
        "Gli estremi temporali dei blocchi originali sono conservati.",
        "",
    ]
    for original, (first, last) in split_or_shifted.items():
        label = str(first) if first == last else f"{first}–{last}"
        report_lines.append(f"Originale {original} → finale {label}")
    report_lines.extend(["", *warnings, *readable.warnings])
    if previous_report.is_file():
        report_lines.extend([
            "", "Segnalazioni linguistiche del file originale (ID originali):", "",
            previous_report.read_text(encoding="utf-8-sig"),
        ])
    if destination.exists() or report.exists():
        raise FileExistsError("La destinazione o il rapporto esiste già. Scegli un altro nome.")
    with destination.open("x", encoding="utf-8") as result:
        result.write(formatted)
    try:
        with report.open("x", encoding="utf-8") as companion:
            companion.write("\n".join(report_lines).rstrip() + "\n")
    except OSError:
        destination.unlink(missing_ok=True)
        raise

    return destination


# ---------------------------------------------------------------------------
# OUTPUT SRT
# ---------------------------------------------------------------------------


def _timestamp(
    seconds: float,
) -> str:

    milliseconds = round(max(0, seconds) * 1000)

    hours, milliseconds = divmod(
        milliseconds,
        3_600_000,
    )

    minutes, milliseconds = divmod(
        milliseconds,
        60_000,
    )

    seconds, milliseconds = divmod(
        milliseconds,
        1_000,
    )

    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def render_srt(
    captions: list[Caption],
) -> str:

    blocks: list[str] = []

    for index, caption in enumerate(
        captions,
        start=1,
    ):
        blocks.append(
            "\n".join(
                (
                    str(index),
                    (f"{_timestamp(caption.start)} --> {_timestamp(caption.end)}"),
                    *caption.lines,
                )
            )
        )

    return "\n\n".join(blocks) + ("\n" if blocks else "")

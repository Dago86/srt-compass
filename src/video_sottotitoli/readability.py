"""Local, deterministic SRT segmentation; no audio or API calls are needed."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import Caption


@dataclass(frozen=True)
class ReadableResult:
    captions: list[Caption]
    id_map: dict[int, tuple[int, int]]
    warnings: list[str]


def _graphemes(text: str) -> list[str]:
    """Keep combining marks, variation selectors and joined emoji together."""
    result: list[str] = []
    for char in text:
        code = ord(char)
        if result and (
            unicodedata.combining(char)
            or 0xFE00 <= code <= 0xFE0F
            or 0x1F3FB <= code <= 0x1F3FF
            or (0x1F1E6 <= code <= 0x1F1FF and len(result[-1]) == 1
                and 0x1F1E6 <= ord(result[-1]) <= 0x1F1FF)
            or char == "\u200d"
            or result[-1].endswith("\u200d")
        ):
            result[-1] += char
        else:
            result.append(char)
    return result


def grapheme_count(text: str) -> int:
    return len(_graphemes(text))


def _is_japanese(text: str) -> bool:
    japanese = sum(
        "\u3040" <= char <= "\u30ff" or "\u3400" <= char <= "\u9fff"
        for char in text
    )
    letters = sum(char.isalpha() for char in text)
    return japanese > 0 and japanese >= letters * 0.3


def _split_lines(text: str, limit: int) -> tuple[list[str], bool]:
    remaining = re.sub(r"\s+", " ", text).strip()
    lines: list[str] = []
    split_word = False
    sentence_marks = ".!?。！？"
    clause_marks = ",;:、，；："
    while remaining:
        units = _graphemes(remaining)
        if len(units) <= limit:
            lines.append(remaining)
            break
        window = units[:limit]
        minimum = max(1, int(limit * 0.45))
        sentence = [i + 1 for i, unit in enumerate(window)
                    if i + 1 >= minimum and unit[-1] in sentence_marks]
        clauses = [i + 1 for i, unit in enumerate(window)
                   if i + 1 >= minimum and unit[-1] in clause_marks]
        spaces = [i for i, unit in enumerate(window) if unit == " " and i >= minimum]
        if sentence:
            cut = sentence[-1]
        elif clauses:
            cut = clauses[-1]
        elif spaces:
            cut = spaces[-1]
        else:
            cut = limit
            if len(units) > limit and units[limit][0] in "。、，．！？!?.,;:)]}」』】":
                cut -= 1
            if not _is_japanese("".join(window)):
                split_word = True
        lines.append("".join(units[:cut]).strip())
        remaining = "".join(units[cut:]).lstrip()
    return [line for line in lines if line], split_word


def segment_captions(captions: list[Caption], language: str = "auto") -> ReadableResult:
    """Split long cues while preserving each cue's outer timestamps and all text."""
    output: list[Caption] = []
    id_map: dict[int, tuple[int, int]] = {}
    warnings: list[str] = []
    for source_id, caption in enumerate(captions, 1):
        text = re.sub(r"\s+", " ", " ".join(caption.lines)).strip()
        limit = 21 if language == "ja" or _is_japanese(text) else 42
        lines, split_word = _split_lines(text, limit)
        chunks = [lines[index:index + 2] for index in range(0, len(lines), 2)]
        first_id = len(output) + 1
        start_ms = round(caption.start * 1000)
        end_ms = round(caption.end * 1000)
        if len(chunks) > 1 and end_ms - start_ms < len(chunks):
            warnings.append(
                f"Sottotitolo originale {source_id}: durata troppo breve per stimare "
                "i tempi di tutti i nuovi blocchi; testo mantenuto."
            )
            output.append(caption)
        elif chunks:
            weights = [max(1, sum(len(_graphemes(line.strip())) for line in chunk))
                       for chunk in chunks]
            total = sum(weights)
            used = 0
            cursor = start_ms
            for index, (chunk, weight) in enumerate(zip(chunks, weights)):
                used += weight
                remaining = len(chunks) - index - 1
                end = (
                    end_ms if not remaining else
                    min(end_ms - remaining,
                        max(cursor + 1, start_ms + round((end_ms - start_ms) * used / total)))
                )
                output.append(Caption(cursor / 1000, end / 1000, tuple(chunk)))
                cursor = end
            if len(chunks) > 1:
                warnings.append(
                    f"Sottotitolo originale {source_id}: suddiviso in {len(chunks)} "
                    "blocchi; tempi interni stimati dal testo."
                )
        else:
            output.append(caption)
        if split_word:
            warnings.append(
                f"Sottotitolo originale {source_id}: parola lunga divisa senza perdere caratteri."
            )
        id_map[source_id] = (first_id, len(output))
    return ReadableResult(output, id_map, warnings)


def readability_warnings(captions: list[Caption], language: str = "auto") -> list[str]:
    warnings: list[str] = []
    previous_end: float | None = None
    for index, caption in enumerate(captions, 1):
        text = " ".join(caption.lines)
        japanese = language == "ja" or _is_japanese(text)
        limit, cps = (21, 10.0) if japanese else (42, 20.0)
        duration = caption.end - caption.start
        if duration <= 0:
            warnings.append(f"Sottotitolo finale {index}: durata non valida.")
        elif grapheme_count(text) / duration > cps:
            warnings.append(
                f"Sottotitolo finale {index}: oltre {cps:g} caratteri al secondo."
            )
        if previous_end is not None and caption.start < previous_end:
            warnings.append(f"Sottotitolo finale {index}: sovrapposto al precedente.")
        if len(caption.lines) > 2 or any(
            grapheme_count(line) > limit for line in caption.lines
        ):
            warnings.append(
                f"Sottotitolo finale {index}: oltre {limit} caratteri per riga."
            )
        previous_end = caption.end
    return warnings

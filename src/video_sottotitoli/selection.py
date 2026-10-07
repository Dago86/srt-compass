from __future__ import annotations

import math
from typing import Any

from .config import CHUNK_SECONDS


class StartTimeError(ValueError):
    """L'intervallo richiesto non è valido per il video selezionato."""


def parse_time_value(value: str) -> float:
    """Converte HH:MM:SS oppure minuti decimali in secondi."""
    normalized = value.strip().replace(",", ".")
    if not normalized:
        raise StartTimeError("Inserisci un tempo.")

    if ":" in normalized:
        parts = normalized.split(":")
        if len(parts) != 3:
            raise StartTimeError("Usa il formato HH:MM:SS.")
        try:
            hours, minutes, seconds = (float(part) for part in parts)
        except ValueError as exc:
            raise StartTimeError("Il tempo deve contenere solo numeri.") from exc
        if not all(math.isfinite(item) for item in (hours, minutes, seconds)):
            raise StartTimeError("Il tempo deve essere finito.")
        if hours < 0 or minutes < 0 or seconds < 0:
            raise StartTimeError("Il tempo non può essere negativo.")
        if not hours.is_integer() or not minutes.is_integer():
            raise StartTimeError("Ore e minuti devono essere interi.")
        if minutes >= 60 or seconds >= 60:
            raise StartTimeError("Minuti e secondi devono essere inferiori a 60.")
        return hours * 3600 + minutes * 60 + seconds

    try:
        minutes = float(normalized)
    except ValueError as exc:
        raise StartTimeError(
            "Inserisci minuti decimali oppure un tempo HH:MM:SS."
        ) from exc
    if not math.isfinite(minutes):
        raise StartTimeError("Il tempo deve essere finito.")
    if minutes < 0:
        raise StartTimeError("Il tempo non può essere negativo.")
    return minutes * 60


def format_time_value(seconds: float) -> str:
    """Formatta un tempo al secondo più vicino per i campi dell'interfaccia."""
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def parse_time_range(
    start_value: str, end_value: str, duration_seconds: float
) -> tuple[float, float]:
    start_seconds = parse_time_value(start_value)
    end_seconds = parse_time_value(end_value)
    if duration_seconds < end_seconds <= math.ceil(duration_seconds):
        end_seconds = duration_seconds
    if start_seconds >= end_seconds:
        raise StartTimeError("L'inizio deve precedere la fine.")
    if end_seconds > duration_seconds:
        raise StartTimeError("La fine non può superare la durata del video.")
    return start_seconds, end_seconds


def parse_start_minutes(value: str, duration_seconds: float) -> float:
    """Converte minuti scritti con virgola o punto in secondi assoluti."""
    start_seconds = parse_time_value(value)
    if start_seconds >= duration_seconds:
        raise StartTimeError("Il minuto iniziale deve precedere la fine del video.")

    return start_seconds


def create_chunks(
    duration_seconds: float,
    start_at_seconds: float = 0.0,
    chunk_seconds: float = CHUNK_SECONDS,
    end_at_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Crea blocchi contigui con offset assoluti rispetto al video."""
    end_at_seconds = duration_seconds if end_at_seconds is None else end_at_seconds
    if not math.isfinite(start_at_seconds):
        raise StartTimeError("Il punto iniziale deve essere finito.")
    if not math.isfinite(end_at_seconds):
        raise StartTimeError("Il punto finale deve essere finito.")
    if start_at_seconds < 0 or start_at_seconds >= end_at_seconds:
        raise StartTimeError("L'inizio deve precedere la fine.")
    if end_at_seconds > duration_seconds:
        raise StartTimeError("Il punto finale supera la durata del video.")
    if chunk_seconds <= 0:
        raise ValueError("La durata del blocco deve essere positiva.")

    chunks: list[dict[str, Any]] = []
    start = start_at_seconds
    while start < end_at_seconds:
        chunk_duration = min(chunk_seconds, end_at_seconds - start)
        chunks.append({"start": start, "duration": chunk_duration, "status": "pending"})
        start += chunk_duration
    return chunks

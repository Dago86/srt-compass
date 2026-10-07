from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioTrack:
    stream_index: int
    ordinal: int
    language: str | None
    title: str | None
    codec: str | None

    @property
    def label(self) -> str:
        parts = [f"Traccia {self.ordinal + 1}"]
        if self.language:
            parts.append(self.language.upper())
        if self.title:
            parts.append(self.title)
        if self.codec:
            parts.append(self.codec)
        return " · ".join(parts)


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    audio_tracks: tuple[AudioTrack, ...]


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    lines: tuple[str, ...]

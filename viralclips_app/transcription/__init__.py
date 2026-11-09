"""Transcription provider architecture for VIRALCLIPS AI.

The V1 engine used Faster-Whisper directly, which requires the
``ctranslate2`` native extension. That extension is blocked by Windows
Smart App Control on some hosts, which made live transcription impossible
there. The V2.1 layer adds Groq Speech-to-Text as a first-class
transcription provider so the pipeline can run on any host.

Both providers implement the same ``TranscriptionProvider`` interface, so
the downstream intelligence layer cannot tell them apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TranscriptionSegment:
    """One timestamped segment of a transcript."""
    start: float
    end: float
    text: str


@dataclass
class TranscriptionWord:
    """One word with its timing."""
    word: str
    start: float
    end: float


@dataclass
class TranscriptionResult:
    """The output of a transcription run.

    This mirrors the dict that the V1 engine wrote to ``transcript.json``
    so the existing intelligence layer keeps working unchanged.
    """
    text: str
    language: str
    duration: float
    segments: list[TranscriptionSegment] = field(default_factory=list)
    words: list[TranscriptionWord] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    request_id: str | None = None
    raw: dict | None = None


class TranscriptionProvider(Protocol):
    """Common interface implemented by every transcription backend."""

    name: str
    model: str

    def transcribe(self, audio_path: str, *,
                   language: str | None = None,
                   word_timestamps: bool = True) -> TranscriptionResult:
        """Transcribe an audio file and return timestamped results."""
        ...

    def is_available(self) -> bool:
        """Whether this provider can run on this host."""
        ...
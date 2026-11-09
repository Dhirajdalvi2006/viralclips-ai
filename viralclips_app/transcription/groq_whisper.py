"""Groq Speech-to-Text provider.

Uses the official Groq audio transcriptions endpoint:
https://api.groq.com/openai/v1/audio/transcriptions

The endpoint is OpenAI-compatible, so the request shape mirrors the
OpenAI audio transcription API. Responses are requested in
``verbose_json`` so segments and (optionally) word timings come back.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from viralclips_app.transcription import (
    TranscriptionResult, TranscriptionSegment, TranscriptionWord)
from .audio import file_size_mb


GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Groq free tier: 25 MB per request. Developer tier: 100 MB.
DEFAULT_MAX_FILE_MB = 25.0
CHUNK_TARGET_MB = 15.0
OVERLAP_SECONDS = 5.0


class GroqTranscriptionError(Exception):
    """Raised when the Groq transcription API cannot be used."""


def _api_key() -> str:
    # Process environment first.
    key = (os.environ.get("GROQ_API_KEY")
           or os.environ.get("VIRALCLIPS_GROQ_API_KEY"))
    if key:
        return key.strip()
    # Local credential file / project .env.
    try:
        from providers import credentials
        key = credentials.get("GROQ_API_KEY", "")
        if key:
            return key.strip()
    except Exception:
        pass
    raise GroqTranscriptionError("No GROQ_API_KEY is configured.")


def _post_audio(audio_path: Path, model: str, api_key: str,
                language: str | None, word_timestamps: bool,
                timeout: int = 300) -> dict:
    """POST one audio file to the Groq transcription endpoint."""
    boundary = "----ViralClipsGroqBoundary9c4e7a12"
    with open(audio_path, "rb") as handle:
        payload = handle.read()

    filename = audio_path.name
    mime = "audio/flac" if audio_path.suffix.lower() == ".flac" else "audio/wav"

    parts = []
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + payload
        + b"\r\n")
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
        .encode("utf-8"))
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        f"verbose_json\r\n".encode("utf-8"))
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="temperature"\r\n\r\n0\r\n'
        .encode("utf-8"))
    granularities = ["segment"]
    if word_timestamps:
        granularities.append("word")
    granularity_fields = ""
    for g in granularities:
        granularity_fields += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="timestamp_granularities[]"\r\n\r\n'
            f"{g}\r\n")
    parts.append(granularity_fields.encode("utf-8"))
    if language:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="language"\r\n\r\n'
            f"{language}\r\n".encode("utf-8"))
    body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")

    request = urllib.request.Request(
        GROQ_TRANSCRIPTION_URL, data=body, method="POST")
    request.add_header("Content-Type",
                        f"multipart/form-data; boundary={boundary}")
    request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("User-Agent", "ViralClipsAI/2.1 (Groq transcription)")

    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                data = json.loads(raw)
                return data
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", "replace")[:400]
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                wait = 2 ** attempt
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
                time.sleep(min(wait, 30))
                last_error = GroqTranscriptionError(
                    f"rate limited (HTTP 429): {detail}")
                continue
            if exc.code in (401, 403):
                raise GroqTranscriptionError(
                    f"authentication failed (HTTP {exc.code}): {detail}")
            if exc.code == 413:
                raise GroqTranscriptionError(
                    f"audio too large (HTTP 413): {detail}")
            if 500 <= exc.code < 600:
                time.sleep(2 ** attempt)
                last_error = GroqTranscriptionError(
                    f"server error (HTTP {exc.code}): {detail}")
                continue
            raise GroqTranscriptionError(
                f"HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            time.sleep(2 ** attempt)
            last_error = GroqTranscriptionError(f"connection error: {exc}")
            continue
    raise last_error or GroqTranscriptionError("Groq transcription failed")


def _parse_response(data: dict, offset: float = 0.0) -> TranscriptionResult:
    """Convert a verbose_json response into a TranscriptionResult."""
    text = data.get("text", "") or ""
    language = data.get("language", "") or ""
    duration = float(data.get("duration") or 0.0)

    segments = []
    for seg in data.get("segments") or []:
        try:
            start = float(seg.get("start", 0.0)) + offset
            end = float(seg.get("end", 0.0)) + offset
        except (TypeError, ValueError):
            continue
        seg_text = (seg.get("text") or "").strip()
        if not seg_text:
            continue
        segments.append(TranscriptionSegment(start=start, end=end, text=seg_text))

    words = []
    for w in data.get("words") or []:
        try:
            word = str(w.get("word", "")).strip()
            if not word:
                continue
            start = float(w.get("start", 0.0)) + offset
            end = float(w.get("end", 0.0)) + offset
            words.append(TranscriptionWord(word=word, start=start, end=end))
        except (TypeError, ValueError):
            continue

    return TranscriptionResult(
        text=text.strip(),
        language=language,
        duration=duration,
        segments=segments,
        words=words,
        provider="groq",
        model=data.get("model", "") or "",
        request_id=data.get("request_id") or data.get("x_groq", {}).get(
            "id") if isinstance(data.get("x_groq"), dict) else None,
        raw=data,
    )


def _chunk_audio(audio_path: Path, target_mb: float = CHUNK_TARGET_MB,
                 overlap: float = OVERLAP_SECONDS) -> list[tuple[Path, float]]:
    """Split a large audio file into overlapping chunks.

    Returns a list of (chunk_path, start_offset_seconds) tuples. The
    caller is responsible for deleting the chunk files.
    """
    import json as _json
    import subprocess as _sp

    duration = None
    result = _sp.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(audio_path)],
        capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        try:
            duration = float(_json.loads(result.stdout)["format"]["duration"])
        except (ValueError, KeyError, TypeError):
            duration = None
    if not duration or duration <= 0:
        # Cannot chunk without a duration; transcribe as-is.
        return [(audio_path, 0.0)]

    size_mb = file_size_mb(audio_path)
    if size_mb <= target_mb:
        return [(audio_path, 0.0)]

    # Estimate bytes per second from the actual encoded file.
    bytes_per_second = audio_path.stat().st_size / duration
    target_bytes = target_mb * 1024 * 1024
    chunk_duration = max(30.0, target_bytes / bytes_per_second)
    overlap = min(overlap, chunk_duration / 4.0)

    chunks: list[tuple[Path, float]] = []
    start = 0.0
    index = 0
    while start < duration:
        end = min(duration, start + chunk_duration)
        chunk_path = audio_path.with_name(
            f"{audio_path.stem}_chunk{index:03d}{audio_path.suffix}")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{(end - start):.3f}",
            "-i", str(audio_path),
            "-c", "copy", str(chunk_path),
        ]
        result = _sp.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not chunk_path.is_file():
            raise GroqTranscriptionError(
                f"FFmpeg chunking failed: {result.stderr.strip()[:300]}")
        chunks.append((chunk_path, start))
        if end >= duration:
            break
        start = end - overlap
        index += 1
    return chunks


def _merge_results(results: list[tuple[TranscriptionResult, float]],
                   overlap: float = OVERLAP_SECONDS) -> TranscriptionResult:
    """Merge chunked transcription results into one transcript.

    Duplicate segments that fall inside the overlap region are dropped
    when their text matches a recent segment. Timestamps are preserved
    as absolute values.
    """
    if not results:
        return TranscriptionResult(text="", language="", duration=0.0,
                                  provider="groq", model="")

    merged_segments: list[TranscriptionSegment] = []
    merged_words: list[TranscriptionWord] = []
    seen_texts: list[str] = []
    language = results[0][0].language
    model = results[0][0].model
    total_duration = 0.0

    for result, offset in results:
        for seg in result.segments:
            # Drop a segment whose text is a near-duplicate of one we
            # already kept within the overlap window.
            duplicate = False
            for recent in seen_texts[-6:]:
                if _normalise(seg.text) == recent:
                    duplicate = True
                    break
            if duplicate:
                continue
            merged_segments.append(seg)
            seen_texts.append(_normalise(seg.text))
        for w in result.words:
            merged_words.append(w)
        total_duration = max(total_duration, result.duration + offset)

    merged_segments.sort(key=lambda s: (s.start, s.end))
    merged_words.sort(key=lambda w: (w.start, w.end))

    text = " ".join(s.text for s in merged_segments).strip()
    if not text:
        text = " ".join(r[0].text for r in results).strip()

    return TranscriptionResult(
        text=text,
        language=language,
        duration=total_duration,
        segments=merged_segments,
        words=merged_words,
        provider="groq",
        model=model,
    )


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


class GroqTranscriptionProvider:
    """Groq Speech-to-Text provider."""

    name = "groq"
    model: str

    def __init__(self, model: str = "whisper-large-v3-turbo",
                 max_file_mb: float = DEFAULT_MAX_FILE_MB,
                 language: str | None = None,
                 word_timestamps: bool = True):
        self.model = model
        self.max_file_mb = max_file_mb
        self.language = language
        self.word_timestamps = word_timestamps

    def is_available(self) -> bool:
        try:
            _api_key()
            return True
        except GroqTranscriptionError:
            return False

    def transcribe(self, audio_path: str, *,
                   language: str | None = None,
                   word_timestamps: bool = True) -> TranscriptionResult:
        lang = language if language is not None else self.language
        wt = word_timestamps if word_timestamps is not None else self.word_timestamps
        api_key = _api_key()

        audio = Path(audio_path)
        chunks = _chunk_audio(audio, target_mb=getattr(self, "_chunk_target_mb", 15.0),
                             overlap=OVERLAP_SECONDS)

        results: list[tuple[TranscriptionResult, float]] = []
        try:
            for chunk_path, offset in chunks:
                data = _post_audio(chunk_path, self.model, api_key, lang, wt)
                parsed = _parse_response(data, offset=offset)
                parsed.model = self.model
                results.append((parsed, offset))
        finally:
            # Clean up chunk files we created (never the original).
            for chunk_path, offset in chunks:
                if chunk_path != audio and chunk_path.is_file():
                    try:
                        chunk_path.unlink()
                    except OSError:
                        pass

        if len(results) == 1:
            result = results[0][0]
            result.model = self.model
            return result
        return _merge_results(results)


def transcribe_audio_file(audio_path: str, *,
                         model: str = "whisper-large-v3-turbo",
                         max_file_mb: float = 25.0,
                         chunk_target_mb: float = 15.0,
                         language: str | None = None,
                         word_timestamps: bool = True) -> TranscriptionResult:
    """Convenience entry point used by the worker and tests."""
    provider = GroqTranscriptionProvider(
        model=model, max_file_mb=max_file_mb, language=language,
        word_timestamps=word_timestamps)
    provider._chunk_target_mb = chunk_target_mb
    return provider.transcribe(audio_path, language=language,
                               word_timestamps=word_timestamps)

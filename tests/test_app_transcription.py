"""Tests for the Groq transcription provider.

These tests use mocked HTTP responses and do not consume real API
credits. They pin down the provider's contract: authentication, error
handling, timestamp parsing, chunking, merging and attribution.
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

from viralclips_app.transcription import (
    TranscriptionResult, TranscriptionSegment, TranscriptionWord)
from viralclips_app.transcription import groq_whisper as gw
from viralclips_app.transcription import audio


# --- helpers ---------------------------------------------------------------

def _verbose_response(text="hello world", language="en", duration=5.0,
                     segments=None, words=None, model="whisper-large-v3-turbo"):
    if segments is None:
        segments = [{"start": 0.0, "end": 2.5, "text": text}]
    if words is None:
        words = [{"word": w, "start": i * 0.5, "end": (i + 1) * 0.5}
                 for i, w in enumerate(text.split())]
    return {
        "text": text,
        "language": language,
        "duration": duration,
        "segments": segments,
        "words": words,
        "model": model,
    }


def _http_response(payload, status=200):
    raw = json.dumps(payload).encode("utf-8")
    response = mock.MagicMock()
    response.status = status
    response.read.return_value = raw
    response.__enter__ = mock.MagicMock(return_value=response)
    response.__exit__ = mock.MagicMock(return_value=False)
    return response


def _http_error(status, body="{}"):
    exc = urllib.error.HTTPError(
        url="https://api.groq.com/openai/v1/audio/transcriptions",
        code=status, msg="err", hdrs={}, fp=io.BytesIO(body.encode()))
    exc.read = lambda: body.encode()
    return exc


# --- API key resolution ----------------------------------------------------

def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-key-123")
    assert gw._api_key() == "env-key-123"


def test_api_key_missing_raises():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("VIRALCLIPS_GROQ_API_KEY", raising=False)
    # Ensure credentials module returns nothing.
    fake = mock.MagicMock()
    fake.get = lambda name, default="": ""
    monkeypatch.setattr("providers.credentials", fake, raising=False)
    with pytest.raises(gw.GroqTranscriptionError) as excinfo:
        gw._api_key()
    assert "configured" in str(excinfo.value).lower()
    monkeypatch.undo()


# --- successful transcription ---------------------------------------------

def test_successful_transcription_parses_segments_and_words(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"fake audio bytes")

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    payload = _verbose_response("hello world", language="en", duration=5.0)
    with mock.patch("urllib.request.urlopen", return_value=_http_response(payload)):
        result = gw.transcribe_audio_file(str(audio))

    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello world"
    assert result.language == "en"
    assert result.duration == 5.0
    assert result.provider == "groq"
    assert result.model == "whisper-large-v3-turbo"
    assert len(result.segments) == 1
    assert result.segments[0].text == "hello world"
    assert len(result.words) == 2
    assert result.words[0].word == "hello"


def test_transcription_attribution_is_groq(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    payload = _verbose_response("hi")
    with mock.patch("urllib.request.urlopen", return_value=_http_response(payload)):
        result = gw.transcribe_audio_file(str(audio), model="whisper-large-v3")
    assert result.provider == "groq"
    assert result.model == "whisper-large-v3"


# --- error handling ---------------------------------------------------------

def test_missing_api_key_raises_before_network(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("VIRALCLIPS_GROQ_API_KEY", raising=False)
    fake = mock.MagicMock()
    fake.get = lambda name, default="": ""
    monkeypatch.setattr("providers.credentials", fake, raising=False)
    with pytest.raises(gw.GroqTranscriptionError) as excinfo:
        gw.transcribe_audio_file(str(audio))
    assert "configured" in str(excinfo.value).lower()


def test_authentication_error_is_permanent(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "bad")
    with mock.patch("urllib.request.urlopen",
                    side_effect=_http_error(401, '{"error":{"message":"invalid key"}}')):
        with pytest.raises(gw.GroqTranscriptionError) as excinfo:
            gw.transcribe_audio_file(str(audio))
    assert "authentication" in str(excinfo.value).lower()


def test_forbidden_is_permanent(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with mock.patch("urllib.request.urlopen",
                    side_effect=_http_error(403, '{"error":{"message":"forbidden"}}')):
        with pytest.raises(gw.GroqTranscriptionError) as excinfo:
            gw.transcribe_audio_file(str(audio))
    assert "authentication" in str(excinfo.value).lower()


def test_file_too_large_raises_413(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with mock.patch("urllib.request.urlopen",
                    side_effect=_http_error(413, '{"error":{"message":"too big"}}')):
        with pytest.raises(gw.GroqTranscriptionError) as excinfo:
            gw.transcribe_audio_file(str(audio))
    assert "too large" in str(excinfo.value).lower()


def test_rate_limit_retries_then_succeeds(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    payload = _verbose_response("ok")

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, '{"error":{"message":"rate limited"}}')
        return _http_response(payload)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with mock.patch("time.sleep"):
            result = gw.transcribe_audio_file(str(audio))
    assert result.text == "ok"
    assert calls["n"] == 2


def test_server_error_retries(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    payload = _verbose_response("ok")

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(500, '{"error":{"message":"boom"}}')
        return _http_response(payload)

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with mock.patch("time.sleep"):
            result = gw.transcribe_audio_file(str(audio))
    assert result.text == "ok"


def test_invalid_json_raises(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")

    response = mock.MagicMock()
    response.status = 200
    response.read.return_value = b"not json at all"
    response.__enter__ = mock.MagicMock(return_value=response)
    response.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(gw.GroqTranscriptionError):
            gw.transcribe_audio_file(str(audio))


def test_empty_transcript_is_handled(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    payload = {"text": "", "language": "en", "duration": 2.0,
               "segments": [], "words": [], "model": "whisper-large-v3-turbo"}
    with mock.patch("urllib.request.urlopen",
                    return_value=_http_response(payload)):
        result = gw.transcribe_audio_file(str(audio))
    assert result.text == ""
    assert result.segments == []
    assert result.words == []
    assert result.language == "en"


def test_missing_segments_falls_back_to_text(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    payload = {"text": "hello world", "language": "en", "duration": 2.0,
               "model": "whisper-large-v3-turbo"}
    with mock.patch("urllib.request.urlopen",
                    return_value=_http_response(payload)):
        result = gw.transcribe_audio_file(str(audio))
    assert result.text == "hello world"
    assert result.segments == []


def test_missing_word_timestamps_is_handled(monkeypatch, tmp_path):
    audio = tmp_path / "a.flac"
    audio.write_bytes(b"x")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    payload = {"text": "hi", "language": "en", "duration": 1.0,
               "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}],
               "model": "whisper-large-v3-turbo"}
    with mock.patch("urllib.request.urlopen",
                    return_value=_http_response(payload)):
        result = gw.transcribe_audio_file(str(audio))
    assert len(result.segments) == 1
    assert result.words == []


# --- chunking and merging ---------------------------------------------------

def test_chunk_audio_does_not_split_small_files(tmp_path):
    audio = tmp_path / "small.flac"
    audio.write_bytes(b"x" * 1000)
    # monkeypatch probe_duration to return a short duration
    with mock.patch("viralclips_app.transcription.groq_whisper._chunk_audio",
                    wraps=gw._chunk_audio):
        pass
    # Directly test: a file whose size is below target returns one chunk.
    with mock.patch("viralclips_app.transcription.audio.file_size_mb",
                    return_value=1.0):
        chunks = gw._chunk_audio(audio, target_mb=15.0)
    assert len(chunks) == 1
    assert chunks[0][1] == 0.0


def test_merge_removes_duplicate_overlap_segments():
    seg = gw.TranscriptionSegment
    r1 = gw.TranscriptionResult(
        text="hello world", language="en", duration=10.0,
        segments=[seg(start=0.0, end=5.0, text="hello"),
                  seg(start=5.0, end=10.0, text="world")],
        words=[], provider="groq", model="m")
    r2 = gw.TranscriptionResult(
        text="world again", language="en", duration=10.0,
        segments=[seg(start=9.0, end=14.0, text="world"),  # duplicate
                  seg(start=14.0, end=19.0, text="again")],
        words=[], provider="groq", model="m")
    merged = gw._merge_results([(r1, 0.0), (r2, 9.0)])
    texts = [s.text for s in merged.segments]
    assert "again" in texts
    # The duplicate "world" from the overlap should be dropped.
    assert texts.count("world") == 1


def test_merge_preserves_chronological_order():
    seg = gw.TranscriptionSegment
    r1 = gw.TranscriptionResult(
        text="a", language="en", duration=5.0,
        segments=[seg(start=0.0, end=5.0, text="a")],
        words=[], provider="groq", model="m")
    r2 = gw.TranscriptionResult(
        text="b", language="en", duration=5.0,
        segments=[seg(start=5.0, end=10.0, text="b")],
        words=[], provider="groq", model="m")
    merged = gw._merge_results([(r1, 0.0), (r2, 5.0)])
    assert [s.text for s in merged.segments] == ["a", "b"]
    assert merged.segments[0].start == 0.0
    assert merged.segments[1].start == 5.0


def test_merge_applies_chunk_offset_to_timestamps():
    seg = gw.TranscriptionSegment
    r1 = gw.TranscriptionResult(
        text="x", language="en", duration=5.0,
        segments=[seg(start=0.0, end=5.0, text="x")],
        words=[], provider="groq", model="m")
    # Chunk starts at offset 10s; the segment's start is already absolute
    # because _parse_response adds the offset. Here we simulate a chunk
    # whose response was parsed with offset=10.
    r2 = gw.TranscriptionResult(
        text="y", language="en", duration=5.0,
        segments=[seg(start=10.0, end=15.0, text="y")],
        words=[], provider="groq", model="m")
    merged = gw._merge_results([(r1, 0.0), (r2, 10.0)])
    assert merged.segments[1].start == 10.0
    assert merged.segments[1].end == 15.0


# --- audio extraction -------------------------------------------------------

def test_extract_audio_missing_source_raises(tmp_path):
    with pytest.raises(RuntimeError):
        audio.extract_audio(str(tmp_path / "nope.mp4"), output_dir=tmp_path)


def test_file_size_mb(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"x" * 1024 * 1024)
    assert abs(audio.file_size_mb(p) - 1.0) < 0.001


def test_cleanup_removes_directory(tmp_path):
    d = tmp_path / "to_remove"
    d.mkdir()
    (d / "f.txt").write_text("x")
    audio.cleanup(d)
    assert not d.exists()


# --- provider availability --------------------------------------------------

def test_groq_provider_is_available_with_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    p = gw.GroqTranscriptionProvider(model="whisper-large-v3-turbo")
    assert p.is_available() is True


def test_groq_provider_is_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("VIRALCLIPS_GROQ_API_KEY", raising=False)
    fake = mock.MagicMock()
    fake.get = lambda name, default="": ""
    monkeypatch.setattr("providers.credentials", fake, raising=False)
    p = gw.GroqTranscriptionProvider(model="whisper-large-v3-turbo")
    assert p.is_available() is False


def test_groq_provider_name_and_model():
    p = gw.GroqTranscriptionProvider(model="whisper-large-v3")
    assert p.name == "groq"
    assert p.model == "whisper-large-v3"


def test_parse_response_preserves_top_level_request_id():
    parsed = gw._parse_response({
        "text": "hello",
        "duration": 1.0,
        "request_id": "req-123",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
    })
    assert parsed.request_id == "req-123"


def test_oversized_audio_with_unavailable_duration_fails_before_upload(
        tmp_path):
    audio_file = tmp_path / "large.flac"
    audio_file.write_bytes(b"x" * 1024)
    with mock.patch(
            "subprocess.run",
            return_value=mock.MagicMock(returncode=1, stdout="", stderr="ffprobe failed")):
        with mock.patch(
                "viralclips_app.transcription.groq_whisper.file_size_mb",
                return_value=30.0):
            with pytest.raises(gw.GroqTranscriptionError, match="ffprobe"):
                gw._chunk_audio(audio_file, target_mb=15.0)

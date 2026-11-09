"""Provider dispatch tests: Groq must be selected before local CTranslate2."""
from __future__ import annotations

import json

import download_and_transcribe as dt


def test_auto_prefers_groq_before_any_faster_whisper_import(monkeypatch, tmp_path):
    source = tmp_path / "authorized.mp4"
    source.write_bytes(b"video")
    expected = tmp_path / "transcript.json"

    monkeypatch.setenv("VIRALCLIPS_TRANSCRIPTION_PROVIDER", "auto")
    monkeypatch.setenv("VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED", "1")
    monkeypatch.setenv("VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED", "1")
    monkeypatch.setattr(
        "viralclips_app.transcription.groq_whisper._api_key",
        lambda: "test-key",
    )
    monkeypatch.setattr(
        dt, "_transcribe_with_groq",
        lambda *args, **kwargs: expected,
    )

    def forbidden_local(*args, **kwargs):
        raise AssertionError("Faster-Whisper/CTranslate2 must not be initialized")

    monkeypatch.setattr(dt, "_load_model", forbidden_local)
    monkeypatch.setattr(dt, "transcribe_chunked", forbidden_local)

    result = dt.transcribe(
        source, tmp_path, "tiny", "cpu", "int8",
        chunked=True, provider="auto",
    )
    assert result == expected


def test_auto_uses_local_when_groq_key_is_missing(monkeypatch, tmp_path):
    source = tmp_path / "authorized.mp4"
    source.write_bytes(b"video")
    monkeypatch.setenv("VIRALCLIPS_TRANSCRIPTION_PROVIDER", "auto")
    monkeypatch.setenv("VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED", "1")
    monkeypatch.setenv("VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED", "1")

    def missing_key():
        raise RuntimeError("No GROQ_API_KEY is configured.")

    monkeypatch.setattr(
        "viralclips_app.transcription.groq_whisper._api_key", missing_key
    )
    monkeypatch.setattr(dt, "_load_model", lambda *args: object())
    monkeypatch.setattr(
        dt, "_transcribe_media",
        lambda *args, **kwargs: (
            [{"start": 0.0, "end": 1.0, "text": "hello"}],
            [{"word": "hello", "start": 0.0, "end": 1.0}],
            "en", 1.0,
        ),
    )

    result = dt.transcribe(source, tmp_path, "tiny", "cpu", "int8")
    data = json.loads(result.read_text(encoding="utf-8"))
    assert data["transcription_provider"] == "faster_whisper"
    assert data["transcription_model"] == "tiny"


def test_explicit_groq_never_falls_through_to_local(monkeypatch, tmp_path):
    source = tmp_path / "authorized.mp4"
    source.write_bytes(b"video")
    expected = tmp_path / "transcript.json"
    monkeypatch.setenv("VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED", "1")
    monkeypatch.setattr(
        dt, "_transcribe_with_groq", lambda *args, **kwargs: expected
    )

    def forbidden_local(*args, **kwargs):
        raise AssertionError("Explicit Groq mode must not use local transcription")

    monkeypatch.setattr(dt, "_load_model", forbidden_local)
    monkeypatch.setattr(dt, "transcribe_chunked", forbidden_local)

    assert dt.transcribe(
        source, tmp_path, "tiny", "cpu", "int8",
        provider="groq", chunked=True,
    ) == expected


def test_disabled_groq_does_not_call_groq(monkeypatch, tmp_path):
    source = tmp_path / "authorized.mp4"
    source.write_bytes(b"video")
    monkeypatch.setenv("VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED", "0")
    monkeypatch.setenv("VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED", "1")
    monkeypatch.setattr(
        "viralclips_app.transcription.groq_whisper._api_key",
        lambda: "test-key",
    )

    def local_model(*args):
        return object()

    monkeypatch.setattr(dt, "_load_model", local_model)
    monkeypatch.setattr(
        dt, "_transcribe_media",
        lambda *args, **kwargs: ([], [], "en", 1.0),
    )
    monkeypatch.setattr(
        dt, "_transcribe_with_groq",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Groq is disabled")
        ),
    )

    result = dt.transcribe(source, tmp_path, "tiny", "cpu", "int8")
    data = json.loads(result.read_text(encoding="utf-8"))
    assert data["transcription_provider"] == "faster_whisper"

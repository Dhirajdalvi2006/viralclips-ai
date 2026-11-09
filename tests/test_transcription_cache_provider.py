from pathlib import Path

import projects


def _options():
    return {"whisper_model": "tiny", "device": "cpu"}


def test_transcript_cache_key_changes_when_provider_changes(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"same source")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("VIRALCLIPS_TRANSCRIPTION_PROVIDER", "groq")
    groq_key = projects._transcription_cache_key(
        source, _options(), False, "video", False, str(source))

    monkeypatch.setenv("VIRALCLIPS_TRANSCRIPTION_PROVIDER", "faster_whisper")
    local_key = projects._transcription_cache_key(
        source, _options(), False, "video", False, str(source))

    assert groq_key != local_key


def test_transcript_cache_key_changes_when_groq_model_changes(
        monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"same source")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("VIRALCLIPS_TRANSCRIPTION_PROVIDER", "groq")
    monkeypatch.setenv(
        "VIRALCLIPS_GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo")
    first = projects._transcription_cache_key(
        source, _options(), False, "video", False, str(source))
    monkeypatch.setenv(
        "VIRALCLIPS_GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")
    second = projects._transcription_cache_key(
        source, _options(), False, "video", False, str(source))
    assert first != second


def test_auto_provider_resolves_to_groq_when_key_exists(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("VIRALCLIPS_TRANSCRIPTION_PROVIDER", "auto")
    assert projects.dt.resolve_transcription_provider() == "groq"

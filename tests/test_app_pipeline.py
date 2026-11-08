"""Tests for the pipeline wrapper and the channel monitor.

The pipeline wrapper is the seam between the application and the
upstream Chopify engine. These tests verify that it builds valid
upstream options, that it reports AI usage honestly, and that the
monitor resolves channels and parses feeds without scraping.
"""
from __future__ import annotations

import datetime as dt

import pytest

from viralclips_app import monitor, pipeline


# --- option building --------------------------------------------------------

def test_build_options_from_a_plain_dict():
    options = pipeline.build_options({})
    assert options["aspect"] == "9:16"
    assert options["style"] == "default"
    assert options["layout"] == "single"
    assert options["min_len"] == 15
    assert options["max_len"] == 90


def test_build_options_uses_the_task_values():
    options = pipeline.build_options({
        "aspect_ratio": "16:9", "caption_style": "bold",
        "num_clips": 5, "min_clip_seconds": 20, "max_clip_seconds": 60,
        "whisper_model": "small", "min_score": 4.5})
    assert options["aspect"] == "16:9"
    assert options["style"] == "bold"
    assert options["max_clips"] == 5
    assert options["min_len"] == 20
    assert options["max_len"] == 60
    assert options["whisper_model"] == "small"
    assert options["min_score"] == 4.5


def test_build_options_falls_back_on_an_unknown_aspect():
    """An unknown aspect must not reach the renderer.

    The renderer only accepts the ratios in its own registry, so an
    unknown value has to be replaced with a supported one.
    """
    options = pipeline.build_options({"aspect_ratio": "42:7"})
    assert options["aspect"] == "9:16"
    assert options["aspect"] in pipeline.VALID_ASPECTS


def test_build_options_falls_back_on_an_unknown_caption_style():
    options = pipeline.build_options({"caption_style": "not-a-style"})
    assert options["style"] == "default"
    assert options["style"] in pipeline.VALID_STYLES


def test_every_valid_aspect_and_style_is_accepted():
    for aspect in pipeline.VALID_ASPECTS:
        assert pipeline.build_options({"aspect_ratio": aspect})["aspect"] \
            == aspect
    for style in pipeline.VALID_STYLES:
        assert pipeline.build_options({"caption_style": style})["style"] \
            == style


def test_build_options_accepts_a_model_object():
    class FakeTask:
        aspect_ratio = "1:1"
        caption_style = "clean"
        num_clips = 2
        min_clip_seconds = 30
        max_clip_seconds = 120
        whisper_model = "base"
        min_score = 1.0
        ai_model = "openai/gpt-oss-120b"

    options = pipeline.build_options(FakeTask())
    assert options["aspect"] == "1:1"
    assert options["style"] == "clean"
    assert options["max_clips"] == 2
    assert options["min_len"] == 30


def test_build_options_produces_options_upstream_accepts():
    """The result must pass upstream's own validation."""
    import projects

    options = pipeline.build_options({})
    projects.validate_options(options)


def test_build_options_sets_the_llm_only_when_a_provider_is_configured(
        monkeypatch):
    monkeypatch.setattr(pipeline.config, "DEFAULT_AI_PROVIDER", "groq")
    options = pipeline.build_options({})
    assert options["llm"] == pipeline.config.DEFAULT_AI_MODEL

    monkeypatch.setattr(pipeline.config, "DEFAULT_AI_PROVIDER", "none")
    options = pipeline.build_options({})
    assert "llm" not in options


def test_semantic_search_stays_off():
    """Groq publishes no embedding model, so semantic search is off."""
    options = pipeline.build_options({})
    assert options["search"] is None
    assert options["semantic"] is None
    assert options["embed_model"] is None


# --- AI resolution ----------------------------------------------------------

def test_resolve_ai_reports_a_missing_credential(monkeypatch):
    monkeypatch.setattr(pipeline.provider_adapter, "configured_provider",
                        lambda: None)
    model, error, provider = pipeline._resolve_ai(None, "groq")
    assert model is None
    assert error
    assert "credential" in error.lower()
    # No provider could be resolved, so none may be reported.
    assert provider is None


def test_resolve_ai_reports_no_provider(monkeypatch):
    monkeypatch.setattr(pipeline.config, "DEFAULT_AI_PROVIDER", "none")
    model, error, provider = pipeline._resolve_ai(None, None)
    assert model is None
    assert error
    assert provider is None


def test_resolve_ai_reports_the_provider_name(monkeypatch):
    """The provider name must come from the adapter, not the model id.

    ``openai/gpt-oss-120b`` is a Groq model; reporting it as the
    provider would be wrong.
    """
    monkeypatch.setattr(pipeline.provider_adapter, "configured_provider",
                        lambda: {"name": "groq", "base_url": "https://x",
                                 "api_key": "k",
                                 "chat_model_env": "VIRALCLIPS_GROQ_MODEL",
                                 "chat_model_default": "openai/gpt-oss-120b"})
    monkeypatch.setattr(pipeline.provider_adapter, "install", lambda: None)

    model, error, provider = pipeline._resolve_ai("openai/gpt-oss-120b", "groq")
    assert error is None
    assert provider == "groq"
    assert model == "openai/gpt-oss-120b"


# --- clip collection --------------------------------------------------------

def test_collect_clips_reads_the_real_segments(tmp_path):
    import json

    project = tmp_path / "proj"
    (project / "clips").mkdir(parents=True)
    (project / "segments.json").write_text(json.dumps([
        {"start": 0.0, "end": 10.0, "overall": 7.5, "hook": "big claim",
         "reason": "Strong hook"},
        {"start": 12.0, "end": 24.0, "overall": 5.0, "hook": "payoff",
         "reason": "Good payoff"},
    ]), encoding="utf-8")
    (project / "candidates.json").write_text(json.dumps({
        "candidates": [
            {"start": 0.0, "end": 10.0, "raw_score": 6.9,
             "llm_adjustment": 0.6, "llm_model": "openai/gpt-oss-120b"},
            {"start": 12.0, "end": 24.0, "raw_score": 5.2},
        ]}), encoding="utf-8")

    clips = pipeline._collect_clips(project, {"last_outputs": []})
    assert len(clips) == 2
    assert clips[0].score == 7.5
    assert clips[0].heuristic_score == 6.9
    assert clips[0].ai_adjustment == 0.6
    assert clips[0].ai_model == "openai/gpt-oss-120b"
    assert clips[0].title.startswith("Big claim")
    assert clips[1].ai_adjustment is None
    assert clips[1].ai_model is None


def test_collect_clips_survives_missing_artifacts(tmp_path):
    project = tmp_path / "empty"
    project.mkdir()
    clips = pipeline._collect_clips(project, {"last_outputs": []})
    assert clips == []


def test_collect_clips_ignores_malformed_json(tmp_path):
    project = tmp_path / "broken"
    project.mkdir()
    (project / "segments.json").write_text("{not json", encoding="utf-8")
    (project / "candidates.json").write_text("also not json", encoding="utf-8")
    clips = pipeline._collect_clips(project, {"last_outputs": []})
    assert clips == []


def test_transcript_extraction_selects_the_right_words(tmp_path):
    import json

    project = tmp_path / "proj"
    project.mkdir()
    (project / "transcript.json").write_text(json.dumps({
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 1.0, "end": 1.5},
            {"word": "later", "start": 30.0, "end": 30.5},
        ]}), encoding="utf-8")

    text = pipeline._transcript_for(project, 0.0, 5.0)
    assert "hello" in text
    assert "world" in text
    assert "later" not in text


# --- channel monitor --------------------------------------------------------

def test_extract_a_channel_id_from_a_channel_url():
    channel_id = "UCabcdefghijklmnopqrstuv"
    assert monitor.extract_channel_id(
        f"https://www.youtube.com/channel/{channel_id}") == channel_id


def test_extract_a_bare_channel_id():
    channel_id = "UCabcdefghijklmnopqrstuv"
    assert monitor.extract_channel_id(channel_id) == channel_id


def test_a_playlist_url_is_rejected():
    with pytest.raises(monitor.MonitorError) as info:
        monitor.extract_channel_id("https://www.youtube.com/playlist?list=X")
    assert "playlist" in str(info.value).lower()


def test_an_empty_channel_is_rejected():
    with pytest.raises(monitor.MonitorError):
        monitor.extract_channel_id("")


def test_an_unresolvable_handle_is_rejected(monkeypatch):
    monkeypatch.setattr(monitor, "api_key", lambda: "")
    with pytest.raises(monitor.MonitorError) as info:
        monitor.extract_channel_id("https://www.youtube.com/@somehandle")
    assert "channel id" in str(info.value).lower()


def test_next_check_time_is_in_the_future():
    when = monitor.next_check_time(30)
    now = dt.datetime.now(dt.timezone.utc)
    assert when > now
    delta = (when - now).total_seconds() / 60
    assert 25 < delta <= 31


def test_parse_published_handles_the_common_formats():
    assert monitor.parse_published("2026-11-01T10:00:00+00:00") is not None
    assert monitor.parse_published("2026-11-01T10:00:00Z") is not None
    assert monitor.parse_published("2026-11-01") is not None


def test_parse_published_of_nonsense_is_none():
    assert monitor.parse_published("not a date") is None
    assert monitor.parse_published(None) is None
    assert monitor.parse_published("") is None


def test_the_monitor_uses_the_official_rss_feed():
    """Discovery must use the official feed, not page scraping."""
    assert monitor.RSS_TEMPLATE == (
        "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")


def test_the_monitor_does_not_scrape_html():
    import inspect

    source = inspect.getsource(monitor)
    assert "BeautifulSoup" not in source
    assert "html.parser" not in source


def test_api_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "the-key")
    assert monitor.api_key() == "the-key"


def test_no_api_key_is_an_empty_string(monkeypatch):
    from providers import credentials

    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "get",
                        lambda name, default="": default)
    assert monitor.api_key() == ""

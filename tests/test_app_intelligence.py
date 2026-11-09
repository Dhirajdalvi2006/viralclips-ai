"""Regression tests for the V2 intelligence layer.

The V2 layer replaces "cut a fixed-length window" with context-aware
moment detection: the transcript is grouped into utterances, boundaries
are snapped onto sentence edges, and each candidate is scored on eight
named signals so the result is explainable and reproducible.

These tests pin down that behaviour, including the honest failure modes:
no provider means ``heuristic``, never a dressed-up AI result.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from viralclips_app import intelligence
from viralclips_app.intelligence import (
    Moment,
    Utterance,
    build_utterances,
    combine_signals,
    detect_moments,
    snap_to_utterance,
    text_for_range,
)


def words(pairs):
    """Build Whisper-style word dicts from (start, end, word) tuples."""
    return [{"start": s, "end": e, "word": w} for s, e, w in pairs]


def make_utterances(text, start=0.0, step=2.0, gap=0.2):
    """Build a simple set of utterances with a fixed cadence."""
    result = []
    for index, line in enumerate(text):
        begin = start + index * step
        result.append(Utterance(start=begin, end=begin + step - 0.2,
                                text=line, words=[]))
    return result


# --- transcript structure -----------------------------------------------------

def test_build_utterances_groups_contiguous_words():
    result = build_utterances(words([
        (0.0, 0.4, "hello"), (0.4, 0.8, "there"),
        (0.8, 1.2, "friend"),
    ]))
    assert len(result) == 1
    assert result[0].text == "hello there friend"
    assert result[0].start == 0.0
    assert result[0].end == 1.2


def test_build_utterances_splits_on_a_long_gap():
    result = build_utterances(words([
        (0.0, 0.4, "first"),
        (5.0, 5.4, "second"),
    ]))
    assert len(result) == 2
    assert result[0].text == "first"
    assert result[1].text == "second"


def test_build_utterances_ignores_malformed_words():
    result = build_utterances([
        {"start": 0.0, "end": 0.4, "word": "good"},
        {"start": "bad", "end": 1.0, "word": "broken"},
        {"start": 2.0, "end": 1.0, "word": "reversed"},
        "not a dict",
    ])
    assert len(result) == 1
    assert result[0].text == "good"


def test_build_utterances_sorts_out_of_order_words():
    result = build_utterances(words([
        (1.0, 1.4, "second"), (0.0, 0.4, "first"),
    ]))
    assert result[0].text == "first second"


def test_load_transcript_reads_a_project_directory(tmp_path: Path):
    payload = {"words": words([(0.0, 0.5, "hello"), (0.5, 1.0, "world")])}
    (tmp_path / "transcript.json").write_text(
        json.dumps(payload), encoding="utf-8")
    result = intelligence.load_transcript(tmp_path)
    assert len(result) == 1
    assert result[0].text == "hello world"


def test_load_transcript_returns_nothing_for_a_missing_file(tmp_path: Path):
    assert intelligence.load_transcript(tmp_path) == []


def test_load_transcript_returns_nothing_for_broken_json(tmp_path: Path):
    (tmp_path / "transcript.json").write_text("{not json", encoding="utf-8")
    assert intelligence.load_transcript(tmp_path) == []


def test_transcript_text_is_timestamped():
    result = intelligence.transcript_text(make_utterances(["hello", "world"]))
    assert "[0.0-1.8] U1: hello" in result
    assert "U2: world" in result


# --- boundary handling --------------------------------------------------------

def test_snap_to_utterance_moves_the_start_onto_an_utterance_edge():
    utterances = make_utterances(["one", "two", "three"], step=2.0)
    start, end = snap_to_utterance(utterances, 0.1, 5.9)
    assert start == 0.0
    assert end == pytest.approx(5.8)


def test_snap_to_utterance_keeps_a_boundary_that_is_too_far_away():
    utterances = make_utterances(["one", "two"], step=2.0)
    start, end = snap_to_utterance(utterances, 50.0, 52.0, tolerance=1.5)
    assert start == 50.0
    assert end == 52.0


def test_snap_to_utterance_handles_an_empty_transcript():
    assert snap_to_utterance([], 1.0, 2.0) == (1.0, 2.0)


def test_text_for_range_returns_only_the_covered_utterances():
    utterances = make_utterances(["alpha", "beta", "gamma"], step=2.0)
    text = text_for_range(utterances, 0.0, 2.5)
    assert "alpha" in text
    assert "beta" in text
    assert "gamma" not in text


# --- individual signals -------------------------------------------------------

def test_hook_score_is_higher_for_a_question():
    question = intelligence.hook_score("What is the secret to this trick?")
    flat = intelligence.hook_score("And then we moved the chair slightly left")
    assert question > flat


def test_hook_score_is_zero_for_empty_text():
    assert intelligence.hook_score("") == 0.0


def test_comedy_score_needs_more_than_a_single_keyword():
    """One marker word alone must not produce a comedy score on its own."""
    text = "haha"
    alone = intelligence.comedy_score(text, False, {})
    with_context = intelligence.comedy_score(
        "haha that is absolutely hilarious I cannot believe what you just did",
        True, {"mean_volume": -18.0, "max_volume": -6.0})
    assert with_context > alone
    assert 0.0 <= alone <= 100.0


def test_reaction_score_uses_audio_contrast():
    quiet = intelligence.reaction_score("wow", {"mean_volume": -30.0,
                                                "max_volume": -29.0})
    punchy = intelligence.reaction_score("wow", {"mean_volume": -30.0,
                                                 "max_volume": -5.0})
    assert punchy > quiet


def test_dialogue_quality_penalises_filler():
    dense = "the quick brown fox jumps over the lazy dog while the crowd watches"
    filler = "um so like you know i mean like basically um yeah i guess so"
    assert intelligence.dialogue_quality_score(dense, 0, 5.0) > \
        intelligence.dialogue_quality_score(filler, 0, 5.0)


def test_dialogue_quality_is_zero_for_empty_text():
    assert intelligence.dialogue_quality_score("", 0, 5.0) == 0.0


def test_clip_structure_rewards_a_long_enough_exchange():
    short = intelligence.clip_structure_score("yes no", 0, 2.0)
    long_text = ("why did nobody think of this sooner because we have been "
                 "doing it the wrong way for years")
    long_score = intelligence.clip_structure_score(long_text, 0, 12.0)
    assert long_score > short


def test_context_completeness_rewards_clean_boundaries():
    # One long utterance: a range that covers it whole starts and ends on
    # its edges, a range that cuts into its middle does not.
    utterances = [Utterance(start=0.0, end=10.0, text="one long turn",
                            words=[])]
    clean = intelligence.context_completeness_score(utterances, 0.0, 10.0)
    ragged = intelligence.context_completeness_score(utterances, 3.0, 7.0)
    assert clean > ragged


def test_context_completeness_is_zero_without_utterances():
    assert intelligence.context_completeness_score([], 0.0, 5.0) == 0.0


def test_energy_score_treats_silence_as_zero():
    assert intelligence.energy_score({"mean_volume": None,
                                      "max_volume": None}) == 0.0


def test_energy_score_rewards_loudness_and_contrast():
    flat = intelligence.energy_score({"mean_volume": -30.0, "max_volume": -29.0})
    punchy = intelligence.energy_score({"mean_volume": -18.0, "max_volume": -4.0})
    assert punchy > flat
    assert 0.0 <= flat <= 100.0


# --- combining ----------------------------------------------------------------

def test_combine_signals_returns_zero_when_there_are_no_signals():
    assert combine_signals({}) == 0.0


def test_combine_signals_is_a_weighted_average():
    signals = {name: 100.0 for name in intelligence.SIGNAL_WEIGHTS}
    assert combine_signals(signals) == 100.0
    signals = {name: 0.0 for name in intelligence.SIGNAL_WEIGHTS}
    assert combine_signals(signals) == 0.0


def test_combine_signals_ignores_unknown_names():
    signals = {name: 50.0 for name in intelligence.SIGNAL_WEIGHTS}
    signals["made_up_signal"] = 100.0
    assert combine_signals(signals) == 50.0


def test_combine_signals_clamps_out_of_range_values():
    signals = {name: 50.0 for name in intelligence.SIGNAL_WEIGHTS}
    signals["hook_strength"] = 500.0
    assert 0.0 <= combine_signals(signals) <= 100.0


def test_all_eight_signals_are_named():
    assert len(intelligence.SIGNAL_WEIGHTS) == 8
    assert set(intelligence.SIGNAL_WEIGHTS) == set(intelligence.SIGNAL_LABELS)


def test_every_signal_has_a_readable_label():
    for name, label in intelligence.SIGNAL_LABELS.items():
        assert label and label[0].isupper()
        assert "_" not in label


# --- repetition penalty -------------------------------------------------------

def test_repetition_penalty_penalises_a_near_duplicate():
    first = Moment(start=0.0, end=30.0, text="a")
    second = Moment(start=1.0, end=31.0, text="b")
    intelligence.repetition_penalty([first, second])
    assert first.signals["repetition_penalty"] == 100.0
    assert second.signals["repetition_penalty"] < 100.0


def test_repetition_penalty_leaves_distant_moments_alone():
    first = Moment(start=0.0, end=30.0, text="a")
    second = Moment(start=300.0, end=330.0, text="b")
    intelligence.repetition_penalty([first, second])
    assert second.signals["repetition_penalty"] == 100.0


# --- the detection entry point ------------------------------------------------

def test_detect_moments_on_an_empty_transcript_reports_an_error():
    result = detect_moments([])
    assert result.moments == []
    assert result.error
    assert result.used_ai is False


def test_detect_moments_falls_back_to_heuristics_without_a_provider(monkeypatch):
    """With no provider the result is labelled heuristic, not AI."""
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: None)

    utterances = make_utterances([
        "why did that actually work",
        "because the trick is that you never rush the ending",
        "and that is why it landed so well with everyone",
        "no way that is genuinely surprising",
        "tell me you did not just do that on purpose right now",
        "because that would honestly have been the final straw",
    ])
    result = detect_moments(utterances, source_path=None)

    assert result.moments
    assert result.used_ai is False
    assert result.error  # the honest reason the AI path did not run
    assert result.score_kind == "estimated"
    for moment in result.moments:
        assert moment.source == "heuristic"
        assert moment.explanation
        assert "no AI provider" in moment.explanation


def test_detect_moments_uses_the_provider_when_it_is_available(monkeypatch):
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: {
        "base_url": "https://example.invalid/v1", "api_key": "test"})
    monkeypatch.setattr(openai_compat, "chat", lambda **kwargs: json.dumps({
        "moments": [{
            "start": 0.0, "end": 20.0,
            "signals": {"hook_strength": 80, "comedy_potential": 70,
                        "reaction_intensity": 60,
                        "context_completeness": 90, "audio_energy": 55,
                        "dialogue_quality": 65, "clip_structure": 75},
            "explanation": "A complete exchange with a clear opening.",
            "category": "comedy", "title": "The reveal",
            "description": "Someone works out the trick.",
            "hashtags": ["shorts", "fyp"],
        }]
    }))

    utterances = make_utterances([
        "so here is the thing I was trying to explain",
        "you have to time it exactly like this",
        "and that is the whole secret right there",
    ])
    result = detect_moments(utterances, source_path=None)

    assert result.used_ai is True
    assert result.provider
    assert result.model
    assert result.moments
    moment = result.moments[0]
    assert moment.source == "ai"
    assert moment.category == "comedy"
    assert moment.title == "The reveal"
    assert moment.hashtags == ["shorts", "fyp"]
    assert moment.signals["hook_strength"] == 80.0
    assert 0.0 <= moment.score <= 100.0


def test_a_provider_error_degrades_to_heuristics(monkeypatch):
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: {
        "base_url": "https://example.invalid/v1", "api_key": "test"})

    def boom(**kwargs):
        raise RuntimeError("provider is unreachable")

    monkeypatch.setattr(openai_compat, "chat", boom)

    utterances = make_utterances([
        "why is nobody talking about this",
        "because we were all waiting for the right moment",
        "and it finally arrived this morning",
        "which honestly nobody in the room expected",
        "the whole thing landed completely differently",
        "from what any of us had planned for today",
    ])
    result = detect_moments(utterances, source_path=None)

    assert result.used_ai is False
    assert "provider is unreachable" in (result.error or "")
    assert result.moments  # the offline path still produced something


def test_provider_junk_does_not_crash_the_pipeline(monkeypatch):
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: {
        "base_url": "https://example.invalid/v1", "api_key": "test"})
    monkeypatch.setattr(openai_compat, "chat", lambda **kwargs: "not json at all")

    utterances = make_utterances([
        "honestly this whole thing was a complete surprise",
        "and nobody in the room expected the answer to be that simple",
    ])
    result = detect_moments(utterances, source_path=None)
    assert result.used_ai is False
    assert result.error


def test_ai_moments_are_snapped_to_utterance_edges(monkeypatch):
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: {
        "base_url": "https://example.invalid/v1", "api_key": "test"})
    monkeypatch.setattr(openai_compat, "chat", lambda **kwargs: json.dumps({
        "moments": [{"start": 0.4, "end": 19.6,
                     "signals": {"hook_strength": 50}}]
    }))

    utterances = make_utterances([
        "the first line of the exchange", "the second line of the exchange",
        "the third line of the exchange", "the fourth line of the exchange",
    ])
    result = detect_moments(utterances, source_path=None)
    assert result.moments
    moment = result.moments[0]
    # The start moves onto the nearest utterance edge; the end is left
    # alone because nothing is close enough to it.
    assert moment.start == 0.0
    assert moment.end == 19.6


def test_ai_moments_outside_the_allowed_length_are_dropped(monkeypatch):
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: {
        "base_url": "https://example.invalid/v1", "api_key": "test"})
    monkeypatch.setattr(openai_compat, "chat", lambda **kwargs: json.dumps({
        "moments": [
            {"start": 0.0, "end": 2.0, "signals": {"hook_strength": 90}},
            {"start": 0.0, "end": 600.0, "signals": {"hook_strength": 90}},
        ]
    }))
    utterances = make_utterances(["a b c", "d e f", "g h i"])
    result = detect_moments(utterances, source_path=None)
    assert result.used_ai is False
    assert result.moments == []


def test_ai_signal_values_are_clamped(monkeypatch):
    import providers.openai_compat as openai_compat
    monkeypatch.setattr(openai_compat, "resolve", lambda provider: {
        "base_url": "https://example.invalid/v1", "api_key": "test"})
    monkeypatch.setattr(openai_compat, "chat", lambda **kwargs: json.dumps({
        "moments": [{"start": 0.0, "end": 20.0, "signals": {
            "hook_strength": 900, "comedy_potential": -50,
            "reaction_intensity": "not a number",
            "context_completeness": 60, "audio_energy": 50,
            "dialogue_quality": 50, "clip_structure": 50}}]
    }))
    utterances = make_utterances([
        "here is a long enough exchange for the clip",
        "with more than a handful of words in it",
        "and a third line for good measure here",
    ])
    result = detect_moments(utterances, source_path=None)
    assert result.used_ai is True
    signals = result.moments[0].signals
    assert signals["hook_strength"] == 100.0
    assert signals["comedy_potential"] == 0.0
    for value in signals.values():
        assert 0.0 <= value <= 100.0


def test_the_score_kind_is_always_estimated():
    """There is no measured audience data, so the label must never lie."""
    assert intelligence.moment_to_payload(
        Moment(start=0, end=1, text="x"))["score_kind"] == "estimated"


def test_moment_to_payload_carries_the_full_breakdown():
    moment = Moment(start=1.0, end=5.0, text="hello",
                    signals={"hook_strength": 70.0}, score=70.0,
                    explanation="because", category="comedy", title="T",
                    description="D", hashtags=["shorts"], source="ai")
    payload = intelligence.moment_to_payload(moment)
    assert payload["signals"]["hook_strength"] == 70.0
    assert payload["signal_weights"] == dict(intelligence.SIGNAL_WEIGHTS)
    assert payload["signal_labels"] == dict(intelligence.SIGNAL_LABELS)
    assert payload["explanation"] == "because"
    assert payload["source"] == "ai"
    assert payload["duration"] == 4.0

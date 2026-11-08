"""AI scoring service.

Wraps the existing provider adapter so the rest of the application gets a
simple, honest interface:

    result = score_candidates(candidates, model=..., provider=...)
    result.used_ai          # True only when the model actually answered
    result.adjustments      # the parsed {index, adjustment, reason} list
    result.error            # why it fell back, if it did

The critical rule, from the brief: **never silently run heuristic-only
scoring while displaying an AI-success status.** `used_ai` is set from
evidence -- whether the provider returned usable adjustments -- not from
intent. Every clip row records which path produced its score.

Groq publishes no embedding model, so this service never assumes
embeddings are available and never enables semantic search on its own.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers import adapter, openai_compat  # noqa: E402

from . import config  # noqa: E402


@dataclass
class ScoreResult:
    """Outcome of one reranking attempt."""

    used_ai: bool = False
    adjustments: list = field(default_factory=list)
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    raw_content: str | None = None

    def adjustment_for(self, index: int) -> tuple[float, str] | None:
        """Return (adjustment, reason) for a candidate index, if any."""
        for entry in self.adjustments:
            if isinstance(entry, dict) and entry.get("index") == index:
                try:
                    value = float(entry.get("adjustment", 0.0))
                except (TypeError, ValueError):
                    return None
                return max(-1.0, min(1.0, value)), str(entry.get("reason", ""))
        return None


def provider_health() -> dict:
    """Return a key-free health report for the configured AI provider."""
    # The configured provider lives in config (VIRALCLIPS_AI_PROVIDER).
    # The runtime override VIRALCLIPS_LLM_PROVIDER is set by the worker
    # when it resolves a provider for a job; the API process does not
    # set it, so it must not be the only source here -- otherwise the
    # dashboard would report "not configured" even though the worker
    # is correctly using Groq.
    name = (os.environ.get("VIRALCLIPS_LLM_PROVIDER")
            or config.DEFAULT_AI_PROVIDER or "").strip().lower()
    fallback_name = (os.environ.get("VIRALCLIPS_LLM_FALLBACK")
                     or config.DEFAULT_AI_FALLBACK or "").strip().lower()

    report = {
        "provider": name or None,
        "fallback": fallback_name or None,
        "model": config.DEFAULT_AI_MODEL,
        "key_present": False,
        "chat_ok": False,
        "error": None,
        "embeddings_supported": False,
        "embedding_note": "Groq publishes no embedding model. Semantic "
                          "search stays optional and is disabled unless an "
                          "embedding provider is configured.",
    }

    if not name or name == "none":
        report["error"] = "No AI provider configured."
        return report

    try:
        provider = openai_compat.resolve(name)
    except openai_compat.ProviderError as exc:
        report["error"] = str(exc)
        return report

    if provider is None:
        report["error"] = f"No credential found for provider '{name}'."
        return report

    report["key_present"] = True
    report["provider"] = provider["name"]
    report["model"] = openai_compat.chat_model_for(provider)
    report["embeddings_supported"] = bool(
        openai_compat.embed_model_for(provider))

    try:
        content = openai_compat.chat(
            messages=[{"role": "user",
                       "content": "Reply with the single word: pong"}],
            model=report["model"], base_url=provider["base_url"],
            api_key=provider["api_key"], timeout=45, max_tokens=256)
        report["chat_ok"] = bool(content and content.strip())
        if not report["chat_ok"]:
            report["error"] = "Provider returned an empty response."
    except openai_compat.ProviderError as exc:
        report["error"] = str(exc)

    return report


def score_candidates(candidates: list, model: str | None = None,
                     provider: str | None = None,
                     timeout: int = 120) -> ScoreResult:
    """Rerank candidates with the configured AI provider.

    ``candidates`` is a list of dicts with at least ``start``, ``end`` and
    ``text``. Returns a ScoreResult whose ``used_ai`` is True **only** when
    the provider returned at least one valid adjustment.
    """
    result = ScoreResult()

    if not candidates:
        return result

    # Explicitly select the provider and model for this call. The
    # environment is set here rather than assumed, so the reranker always
    # has a provider to talk to.
    if provider:
        os.environ["VIRALCLIPS_LLM_PROVIDER"] = provider
    elif not os.environ.get("VIRALCLIPS_LLM_PROVIDER"):
        os.environ["VIRALCLIPS_LLM_PROVIDER"] = config.DEFAULT_AI_PROVIDER

    if model:
        os.environ["VIRALCLIPS_LLM_MODEL"] = model

    resolved = adapter.configured_provider()
    if resolved is None:
        result.error = "No AI provider configured."
        return result

    result.provider = resolved["name"]
    result.model = openai_compat.chat_model_for(resolved)

    # Build the upstream reranker prompt exactly as score_clips does, so
    # the provider returns the shape upstream already parses.
    import score_clips

    ranked = sorted(candidates, key=lambda item: (
        -float(item.get("overall", 0.0)),
        float(item.get("start", 0.0)),
        float(item.get("duration", 0.0))))[:50]
    sent = [{"index": i, "start": item.get("start"), "end": item.get("end"),
             "text": str(item.get("text", ""))[:400]}
            for i, item in enumerate(ranked)]

    messages = [
        {"role": "system", "content": score_clips.RERANK_SYSTEM},
        {"role": "user", "content": __import__("json").dumps(
            sent, ensure_ascii=False)},
    ]

    try:
        parsed = adapter.chat(result.model, messages, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - never break the pipeline
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    if not parsed:
        result.error = "Provider returned no usable adjustments."
        return result

    valid = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        adjustment = entry.get("adjustment")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if isinstance(adjustment, bool) or not isinstance(adjustment, (int, float)):
            continue
        valid.append(entry)

    if not valid:
        result.error = "Provider returned no valid adjustments."
        return result

    result.adjustments = valid
    result.used_ai = True
    return result


def apply_adjustments(candidates: list, result: ScoreResult) -> list:
    """Apply a ScoreResult's adjustments to a candidate list.

    Mirrors upstream's contract: ``overall`` is clamped to 0..10,
    timestamps never change, and the AI reason is appended to the
    existing heuristic reason.
    """
    if not result.used_ai:
        return candidates

    updated = [dict(item) for item in candidates]
    order = sorted(candidates, key=lambda item: (
        -float(item.get("overall", 0.0)),
        float(item.get("start", 0.0)),
        float(item.get("duration", 0.0))))[:50]

    for entry in result.adjustments:
        index = entry.get("index")
        if not isinstance(index, int) or not 0 <= index < len(order):
            continue
        try:
            adjustment = max(-1.0, min(1.0, float(entry.get("adjustment", 0.0))))
        except (TypeError, ValueError):
            continue
        target = order[index]
        for record in updated:
            if (round(float(record.get("start", 0.0)), 2)
                    == round(float(target.get("start", 0.0)), 2)
                    and round(float(record.get("end", 0.0)), 2)
                    == round(float(target.get("end", 0.0)), 2)):
                base = float(record.get("overall", 0.0))
                record["overall"] = round(max(0.0, min(10.0, base + adjustment)), 2)
                record["llm_adjustment"] = adjustment
                record["llm_model"] = result.model
                reason = str(entry.get("reason", ""))[:120]
                if reason and reason not in str(record.get("reason", "")):
                    base_reason = str(record.get("reason", ""))[:160]
                    record["reason"] = (base_reason + " | " + reason)[:160]
                break

    return updated

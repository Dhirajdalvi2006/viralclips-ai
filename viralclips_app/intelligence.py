"""V2 Intelligence -- context-aware moment detection and scoring.

V1 cut videos into fixed windows and reranked them. That optimises for
"a clip existed here" rather than "this moment is worth watching".

This module replaces the blind window with a **moment**: a span of the
source that carries a complete idea -- a question and its answer, a setup
and its punchline, a statement and the reaction to it. Moments are found
by reading the transcript as a conversation, and are then scored on eight
named signals whose components are stored alongside the result so the
score is explainable and reproducible.

Two rules shape everything here:

* **A keyword is never enough.** Comedy, for instance, is not "the word
  'haha' appeared". It needs the surrounding dialogue, the structure of
  the exchange, and the audio. The AI path asks for exactly that
  combination; the offline path says so plainly rather than pretending.
* **The score is an estimate, never a prediction.** Nothing here claims
  to know how many views a clip will get. There is no audience-retention
  data unless the user supplies authorised analytics, and the score is
  labelled ``estimated`` in the database, the API and the UI.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config

#: The eight signals, and how much each one contributes to the final
#: score. The weights are fixed, published and stored with every result
#: so a score can always be recomputed from its parts.
SIGNAL_WEIGHTS: dict[str, float] = {
    "hook_strength": 0.20,
    "comedy_potential": 0.18,
    "reaction_intensity": 0.14,
    "context_completeness": 0.16,
    "audio_energy": 0.10,
    "dialogue_quality": 0.12,
    "clip_structure": 0.07,
    "repetition_penalty": 0.03,
}

SIGNAL_LABELS = {
    "hook_strength": "Hook strength",
    "comedy_potential": "Comedy potential",
    "reaction_intensity": "Reaction intensity",
    "context_completeness": "Context completeness",
    "audio_energy": "Audio energy",
    "dialogue_quality": "Dialogue quality",
    "clip_structure": "Clip structure",
    "repetition_penalty": "Repetition penalty",
}

#: Words that mark a reaction or a laugh in the transcript. They are only
#: ever used together with structural and audio evidence -- never alone.
REACTION_MARKERS = (
    "haha", "hahaha", "lol", "rofl", "lmao", "😂", "🤣", "😆", "😅",
    "wow", "oh my god", "omg", "no way", "yay", "clap", "applause",
    "what", "sheryaar", "saboot",
)

#: Openers that suggest a strong hook.
HOOK_MARKERS = (
    "what", "why", "how", "when", "who", "listen", "look", "wait",
    "actually", "honestly", "nobody", "everyone", "imagine", "guess",
    "here's", "heres", "let me", "tell you", "believe it",
)

QUESTION_WORDS = ("what", "why", "how", "who", "when", "where", "which",
                  "can you", "could you", "do you", "did you", "have you")

FILLER_WORDS = ("um", "uh", "erm", "ah", "hmm", "like", "basically",
                "literally", "you know")


class IntelligenceError(RuntimeError):
    """The intelligence layer could not produce a usable result."""


@dataclass
class Utterance:
    """One continuous stretch of speech."""

    start: float
    end: float
    text: str
    words: list = field(default_factory=list)


@dataclass
class Moment:
    """A context-aware candidate moment with its full scoring breakdown."""

    start: float
    end: float
    text: str
    signals: dict = field(default_factory=dict)
    score: float = 0.0
    explanation: str = ""
    category: str = "general"
    title: str = ""
    description: str = ""
    hashtags: list = field(default_factory=list)
    source: str = "heuristic"      # "ai" or "heuristic"

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)


@dataclass
class IntelligenceResult:
    """The outcome of one intelligence analysis."""

    moments: list = field(default_factory=list)
    used_ai: bool = False
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    score_kind: str = "estimated"


# --- transcript structure -----------------------------------------------------

def build_utterances(words: list, max_gap: float = 0.75) -> list[Utterance]:
    """Group Whisper word timings into utterance-level stretches.

    A gap longer than ``max_gap`` seconds starts a new utterance, which
    is how a conversation turn or a pause between speakers is detected.
    """
    cleaned: list[dict] = []
    for word in words or []:
        if not isinstance(word, dict):
            continue
        try:
            start = float(word.get("start", 0.0))
            end = float(word.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if end < start:
            continue
        cleaned.append({"start": start, "end": end,
                        "word": str(word.get("word", "")).strip()})
    cleaned.sort(key=lambda item: item["start"])

    utterances: list[Utterance] = []
    current: list[dict] = []
    for word in cleaned:
        if current:
            gap = word["start"] - current[-1]["end"]
            if gap > max_gap:
                utterances.append(_make_utterance(current))
                current = []
        current.append(word)
    if current:
        utterances.append(_make_utterance(current))
    return utterances


def _make_utterance(words: list) -> Utterance:
    text = " ".join(str(w["word"]) for w in words).strip()
    return Utterance(start=words[0]["start"], end=words[-1]["end"],
                     text=text, words=words)


def transcript_text(utterances: list[Utterance], limit: int = 1200) -> str:
    """Render the transcript as a timestamped conversation."""
    lines = []
    for index, utterance in enumerate(utterances[:limit]):
        lines.append(f"[{utterance.start:.1f}-{utterance.end:.1f}] "
                     f"U{index + 1}: {utterance.text}")
    return "\n".join(lines)


def load_transcript(project_path: Path) -> list[Utterance]:
    """Load the utterances from a project's transcript.json."""
    path = Path(project_path) / "transcript.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return build_utterances(data.get("words") or [])


# --- boundary handling --------------------------------------------------------

def snap_to_utterance(utterances: list[Utterance], start: float, end: float,
                      tolerance: float = 1.5) -> tuple[float, float]:
    """Move a boundary onto the nearest utterance edge.

    A clip must never begin in the middle of a sentence or end before a
    punchline has landed. The boundary is moved to the closest utterance
    start (for the opening) or end (for the closing) within ``tolerance``
    seconds; if nothing is close enough the original boundary is kept.
    """
    if not utterances:
        return start, end

    best_start = None
    best_start_delta = tolerance
    for utterance in utterances:
        delta = abs(utterance.start - start)
        if delta < best_start_delta:
            best_start_delta = delta
            best_start = utterance.start
    if best_start is not None:
        start = best_start

    best_end = None
    best_end_delta = tolerance
    for utterance in utterances:
        delta = abs(utterance.end - end)
        if delta < best_end_delta:
            best_end_delta = delta
            best_end = utterance.end
    if best_end is not None:
        end = best_end

    if end <= start:
        return start, end
    return start, end


def text_for_range(utterances: list[Utterance], start: float,
                   end: float) -> str:
    """Return the transcript text inside a time range."""
    pieces = [u.text for u in utterances
              if u.end >= start and u.start <= end and u.text]
    return " ".join(pieces).strip()


# --- audio energy -------------------------------------------------------------

def audio_energy(path: Path, start: float, end: float,
                 timeout: int = 60) -> dict:
    """Measure loudness of a range with FFmpeg's volumedetect filter.

    Returns ``mean_volume`` and ``max_volume`` in decibels, or ``None``
    values when the range has no measurable audio. This is a real audio
    measurement, used as a supporting signal -- never on its own.
    """
    import shutil
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    duration = max(0.5, end - start)
    command = [
        ffmpeg, "-hide_banner", "-nostats", "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {"mean_volume": None, "max_volume": None}

    output = (result.stderr or "") + (result.stdout or "")
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", output)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", output)

    def _num(match):
        if not match:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    return {"mean_volume": _num(mean), "max_volume": _num(peak)}


def energy_score(measurement: dict) -> float:
    """Map a loudness measurement onto a 0-100 energy score.

    -50 dB is treated as silence and 0 dB as the ceiling. The score
    rewards a healthy signal but also rewards *contrast* between the
    mean and the peak, because a flat, uniformly loud passage is less
    interesting than one with a sudden spike.
    """
    mean = measurement.get("mean_volume")
    peak = measurement.get("max_volume")
    if mean is None or peak is None:
        return 0.0
    loudness = max(0.0, min(100.0, (float(mean) + 50.0) / 50.0 * 100.0))
    contrast = max(0.0, min(1.0, (float(peak) - float(mean)) / 20.0))
    return round(min(100.0, loudness * 0.75 + contrast * 25.0), 2)


# --- offline signals ----------------------------------------------------------

def _words_of(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w'’-]+", text.lower()) if w]


def context_completeness_score(utterances: list[Utterance], start: float,
                               end: float) -> float:
    """How complete the moment is as a self-contained idea."""
    if not utterances:
        return 0.0
    inside = [u for u in utterances if u.end >= start and u.start <= end]
    if not inside:
        return 0.0
    covered = sum(u.end - u.start for u in inside)
    span = max(0.001, end - start)
    coverage = min(1.0, covered / span)

    starts_clean = any(abs(u.start - start) < 1.0 for u in inside)
    ends_clean = any(abs(u.end - end) < 1.0 for u in inside)
    completeness = coverage * (0.5 + 0.25 * starts_clean + 0.25 * ends_clean)
    return round(min(100.0, completeness * 100.0), 2)


def dialogue_quality_score(text: str, start: float, end: float) -> float:
    """Is there anything worth hearing in this span?"""
    words = _words_of(text)
    if not words:
        return 0.0
    duration = max(1.0, end - start)
    rate = len(words) / duration

    # A good short-form pace is roughly 2 to 4.5 words per second.
    if rate < 1.2:
        rate_score = 25.0
    elif rate < 2.0:
        rate_score = 60.0
    elif rate <= 4.5:
        rate_score = 100.0
    elif rate <= 6.0:
        rate_score = 70.0
    else:
        rate_score = 40.0

    unique_ratio = len(set(words)) / len(words)
    lexical = min(100.0, unique_ratio * 140.0)

    fillers = sum(1 for w in words if w in FILLER_WORDS)
    filler_ratio = fillers / len(words)
    penalty = min(35.0, filler_ratio * 220.0)

    return round(max(0.0, min(100.0, rate_score * 0.6 + lexical * 0.4
                               - penalty)), 2)


def clip_structure_score(text: str, start: float, end: float) -> float:
    """Does the clip have an opening, a body and an ending?"""
    words = _words_of(text)
    if not words:
        return 0.0
    score = 40.0
    opening = " ".join(words[:8])
    closing = " ".join(words[-8:])

    if any(opening.startswith(q) or q in opening.split()[:4]
           for q in QUESTION_WORDS):
        score += 15.0
    if any(marker in opening for marker in HOOK_MARKERS):
        score += 12.0
    if closing.endswith(("?", "!", ".")) or len(closing.split()) > 3:
        score += 10.0
    if len(words) >= 25:
        score += 10.0
    if len(words) < 12:
        score -= 20.0
    return round(max(0.0, min(100.0, score)), 2)


def hook_score(text: str) -> float:
    """Offline estimate of how strong the opening is."""
    words = _words_of(text)
    if not words:
        return 0.0
    opening = " ".join(words[:10])
    score = 30.0
    if any(opening.startswith(q) for q in QUESTION_WORDS):
        score += 25.0
    if any(marker in opening for marker in HOOK_MARKERS):
        score += 20.0
    if "!" in text[:120]:
        score += 8.0
    if any(word in ("i", "we", "you") for word in words[:4]):
        score += 6.0
    return round(max(0.0, min(100.0, score)), 2)


def comedy_score(text: str, has_reaction: bool, audio: dict) -> float:
    """Offline comedy estimate.

    A single keyword never decides this. The marker count is capped hard
    and combined with the audio contrast, because a joke that lands is
    audible, and with the length of the exchange, because a punchline
    needs a setup.
    """
    lowered = text.lower()
    markers = sum(1 for marker in REACTION_MARKERS if marker in lowered)
    words = _words_of(text)

    score = 25.0
    score += min(25.0, markers * 9.0)
    if has_reaction:
        score += 15.0
    if len(words) >= 30:
        score += 10.0
    mean = (audio or {}).get("mean_volume")
    peak = (audio or {}).get("max_volume")
    if mean is not None and peak is not None and (peak - mean) >= 6.0:
        score += 12.0
    if markers == 0:
        score -= 10.0
    return round(max(0.0, min(100.0, score)), 2)


def reaction_score(text: str, audio: dict) -> float:
    """Offline estimate of how strong the reaction is."""
    lowered = text.lower()
    markers = sum(1 for marker in REACTION_MARKERS if marker in lowered)
    score = 20.0 + min(45.0, markers * 12.0)
    mean = (audio or {}).get("mean_volume")
    peak = (audio or {}).get("max_volume")
    if mean is not None and peak is not None:
        contrast = peak - mean
        score += min(30.0, max(0.0, (contrast - 3.0) * 4.0))
    return round(max(0.0, min(100.0, score)), 2)


# --- scoring ------------------------------------------------------------------

def combine_signals(signals: dict) -> float:
    """Combine the named signals into a single 0-100 score."""
    total = 0.0
    weight_sum = 0.0
    for name, weight in SIGNAL_WEIGHTS.items():
        value = signals.get(name)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        total += max(0.0, min(100.0, value)) * weight
        weight_sum += weight
    if weight_sum <= 0:
        return 0.0
    return round(total / weight_sum, 2)


def repetition_penalty(moments: list[Moment]) -> None:
    """Apply a repetition penalty across the moments, in place.

    Two moments that cover substantially the same source range are
    near-duplicates. The later one is penalised, because showing the
    same moment twice in one video is not interesting.
    """
    for index, moment in enumerate(moments):
        penalty = 0.0
        for other in moments[:index]:
            overlap = _overlap(moment, other)
            if overlap > 0.55:
                penalty = max(penalty, (overlap - 0.55) * 180.0)
        moment.signals["repetition_penalty"] = round(
            max(0.0, 100.0 - min(100.0, penalty)), 2)


def _overlap(a: Moment, b: Moment) -> float:
    """Fraction of the shorter moment that is covered by the other."""
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    if end <= start:
        return 0.0
    shorter = min(a.end - a.start, b.end - b.start)
    if shorter <= 0:
        return 0.0
    return (end - start) / shorter


# --- the AI path --------------------------------------------------------------

ANALYSIS_SYSTEM = """You are a short-form video editor. You are given a \
timestamped transcript of a video and you must find the moments that \
would make the best vertical short-form clips.

Judge a moment on all eight of these signals, each from 0 to 100:

hook_strength -- how good the first seconds are as an opening.
comedy_potential -- humour and punchline quality.
reaction_intensity -- strength of reactions from anyone on screen.
context_completeness -- whether the moment makes sense on its own.
audio_energy -- laughter, excitement, emphasis in the audio.
dialogue_quality -- whether what is said is actually interesting.
clip_structure -- a beginning, a middle and an ending.

Rules:
- A single keyword never makes a moment funny. Combine the words with
  the surrounding dialogue and the structure of the exchange.
- A moment must be self-contained. Do not start a clip in the middle of
  a sentence, before a joke reaches its punchline, before a question is
  answered, or before a reaction finishes.
- Prefer a complete exchange over an isolated line.
- Judge only from the transcript. Do not invent events that are not in it.

Reply with JSON only, in exactly this shape:

{"moments": [{"start": 0.0, "end": 12.5, "signals": {"hook_strength": 70,
"comedy_potential": 40, "reaction_intensity": 30, "context_completeness":
85, "audio_energy": 50, "dialogue_quality": 60, "clip_structure": 55},
"explanation": "One sentence on why this moment was chosen.",
"category": "comedy", "title": "A short title", "description": "A one or
two sentence description", "hashtags": ["shorts", "fyp"]}]}

Use the timestamps exactly as they appear in the transcript. Every moment
must last between 12 and 90 seconds. Return between 1 and 8 moments."""


def _extract_json(content: str) -> dict | None:
    """Pull a JSON object out of a model response."""
    if not content:
        return None
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start:end + 1]
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalise_signals(raw: dict, fallback: dict) -> dict:
    """Keep only the eight known signals, each clamped to 0-100."""
    signals = {}
    for name in SIGNAL_WEIGHTS:
        if name == "repetition_penalty":
            continue
        value = raw.get(name) if isinstance(raw, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = fallback.get(name)
        try:
            signals[name] = round(max(0.0, min(100.0, float(value))), 2)
        except (TypeError, ValueError):
            signals[name] = 0.0
    return signals


def detect_moments(utterances: list[Utterance], source_path: Path | None = None,
                   count: int = 3, min_seconds: int = 15, max_seconds: int = 90,
                   provider: str | None = None, model: str | None = None,
                   timeout: int = 180) -> IntelligenceResult:
    """Find context-aware moments and score them.

    Uses the AI provider when one is configured. When it is not, the
    offline signals are used instead and the result is marked
    ``heuristic`` so the UI can say so.
    """
    result = IntelligenceResult()
    if not utterances:
        result.error = "The transcript is empty, so no moment could be found."
        return result

    provider_name = provider or config.DEFAULT_AI_PROVIDER
    model_name = model or config.DEFAULT_AI_MODEL

    ai_moments: list[Moment] = []
    error = None
    try:
        from providers import openai_compat
        resolved = openai_compat.resolve(provider_name)
        if resolved is None:
            error = (f"No credential found for provider '{provider_name}'.")
        else:
            content = openai_compat.chat(
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM},
                    {"role": "user", "content": (
                        "Transcript:\n" + transcript_text(utterances))},
                ],
                model=model_name,
                base_url=resolved["base_url"],
                api_key=resolved["api_key"],
                timeout=timeout,
                max_tokens=4096,
            )
            parsed = _extract_json(content)
            if not parsed:
                error = "The provider did not return usable JSON."
            else:
                ai_moments = _moments_from_ai(parsed, utterances, min_seconds,
                                              max_seconds)
                if not ai_moments:
                    error = "The provider returned no usable moments."
    except Exception as exc:  # noqa: BLE001 - never break the pipeline
        error = f"{type(exc).__name__}: {exc}"

    if ai_moments:
        result.moments = ai_moments
        result.used_ai = True
        result.provider = provider_name
        result.model = model_name
    else:
        result.error = error
        result.moments = _moments_offline(utterances, source_path, count,
                                          min_seconds, max_seconds)

    for moment in result.moments:
        if source_path is not None and "audio_energy" not in moment.signals:
            measurement = audio_energy(source_path, moment.start, moment.end)
            moment.signals["audio_energy"] = energy_score(measurement)
        moment.signals.setdefault("repetition_penalty", 100.0)

    repetition_penalty(result.moments)
    for moment in result.moments:
        moment.score = combine_signals(moment.signals)
    result.moments.sort(key=lambda m: (-m.score, m.start))
    return result


def _moments_from_ai(parsed: dict, utterances: list[Utterance],
                     min_seconds: int, max_seconds: int) -> list[Moment]:
    """Turn the model's JSON into validated moments."""
    raw_moments = parsed.get("moments")
    if not isinstance(raw_moments, list):
        return []
    moments: list[Moment] = []
    for entry in raw_moments:
        if not isinstance(entry, dict):
            continue
        try:
            start = float(entry.get("start"))
            end = float(entry.get("end"))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        if duration < min_seconds * 0.6 or duration > max_seconds * 1.6:
            continue

        start, end = snap_to_utterance(utterances, start, end)
        if end - start < 1.0:
            continue

        text = text_for_range(utterances, start, end)
        fallback = _offline_signals(utterances, start, end, text, None)
        signals = _normalise_signals(entry.get("signals") or {}, fallback)

        hashtags = entry.get("hashtags")
        if not isinstance(hashtags, list):
            hashtags = []
        hashtags = [str(tag).strip().lstrip("#") for tag in hashtags
                    if str(tag).strip()][:10]

        moments.append(Moment(
            start=round(start, 2),
            end=round(end, 2),
            text=text,
            signals=signals,
            explanation=str(entry.get("explanation", "")).strip()[:600],
            category=str(entry.get("category", "general")).strip()[:32]
            or "general",
            title=str(entry.get("title", "")).strip()[:400],
            description=str(entry.get("description", "")).strip()[:1200],
            hashtags=hashtags,
            source="ai",
        ))
    return moments


def _offline_signals(utterances: list[Utterance], start: float, end: float,
                     text: str, audio: dict | None) -> dict:
    """The offline signal set, used to fill gaps in the AI's answer."""
    audio = audio or {}
    measurement = audio or {"mean_volume": None, "max_volume": None}
    lowered = text.lower()
    has_reaction = any(marker in lowered for marker in REACTION_MARKERS)
    return {
        "hook_strength": hook_score(text),
        "comedy_potential": comedy_score(text, has_reaction, measurement),
        "reaction_intensity": reaction_score(text, measurement),
        "context_completeness": context_completeness_score(utterances, start,
                                                           end),
        "audio_energy": energy_score(measurement),
        "dialogue_quality": dialogue_quality_score(text, start, end),
        "clip_structure": clip_structure_score(text, start, end),
    }


def _moments_offline(utterances: list[Utterance], source_path: Path | None,
                     count: int, min_seconds: int,
                     max_seconds: int) -> list[Moment]:
    """Offline moment detection.

    Without a provider the layer still finds coherent stretches: it
    groups utterances into complete exchanges, scores them with the
    offline signals, and returns the best ones. The result is labelled
    ``heuristic`` -- it is not dressed up as an AI result.
    """
    if not utterances:
        return []

    spans: list[tuple[float, float]] = []
    current_start = utterances[0].start
    current_end = utterances[0].end
    for utterance in utterances[1:]:
        if utterance.end - current_start <= max_seconds:
            current_end = utterance.end
            continue
        spans.append((current_start, current_end))
        current_start = utterance.start
        current_end = utterance.end
    spans.append((current_start, current_end))

    moments: list[Moment] = []
    for start, end in spans:
        if end - start < min(min_seconds, 10):
            continue
        text = text_for_range(utterances, start, end)
        if not text:
            continue
        measurement = (audio_energy(source_path, start, end)
                       if source_path is not None else {})
        signals = _offline_signals(utterances, start, end, text, measurement)
        moments.append(Moment(
            start=round(start, 2),
            end=round(end, 2),
            text=text,
            signals=signals,
            explanation=(
                "Offline analysis: this stretch contains a complete exchange "
                "and was selected on structural and audio signals alone, "
                "because no AI provider was available for this run."),
            category="general",
            source="heuristic",
        ))

    moments.sort(key=lambda m: -combine_signals(m.signals))
    return moments[:max(1, count)]


def analyse_project(project_path: Path, source_path: Path | None = None,
                    count: int = 3, min_seconds: int = 15,
                    max_seconds: int = 90, provider: str | None = None,
                    model: str | None = None) -> IntelligenceResult:
    """Analyse a processed project and return ranked moments."""
    utterances = load_transcript(project_path)
    return detect_moments(utterances, source_path=source_path, count=count,
                          min_seconds=min_seconds, max_seconds=max_seconds,
                          provider=provider, model=model)


def moment_to_payload(moment: Moment) -> dict:
    """Serialise a moment for the API."""
    return {
        "start": moment.start,
        "end": moment.end,
        "duration": moment.duration,
        "text": moment.text,
        "signals": dict(moment.signals),
        "signal_weights": dict(SIGNAL_WEIGHTS),
        "signal_labels": dict(SIGNAL_LABELS),
        "score": moment.score,
        "score_kind": "estimated",
        "explanation": moment.explanation,
        "category": moment.category,
        "title": moment.title,
        "description": moment.description,
        "hashtags": list(moment.hashtags),
        "source": moment.source,
    }

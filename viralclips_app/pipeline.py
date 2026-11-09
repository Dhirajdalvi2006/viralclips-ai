"""Video processing pipeline service.

This is a thin, honest wrapper over the upstream Chopify engine. It does
not reimplement any of the processing -- it calls ``projects.run_project``
and then reads the real artifacts the engine produced.

The one thing this module adds on top of upstream is **explicit AI
reranking**. Upstream's reranker only fires when the ``llm`` option is
set, and it only succeeds when the provider returns usable JSON. This
module therefore:

- always passes ``llm=<model>`` when an AI model is configured,
- installs the provider adapter so upstream's Ollama seam is redirected to
  Groq,
- checks the resulting ``selection.json`` ``mode`` field, which upstream
  sets to ``"ollama"`` (its name for "the LLM reranked this") only when
  the reranker actually returned adjustments,
- and records that fact, so a clip row can never claim an AI score that
  the model did not produce.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from . import config  # noqa: E402

config.ensure_dirs()

# Import the upstream engine.
import projects  # noqa: E402
import render_clips  # noqa: E402
import score_clips  # noqa: E402

from providers import adapter as provider_adapter  # noqa: E402

#: The aspect ratios and caption styles the upstream renderer accepts.
#: These are read from upstream's own registries rather than hardcoded,
#: so a new upstream style is picked up automatically.
VALID_ASPECTS = tuple(render_clips.ASPECTS)
VALID_STYLES = tuple(render_clips.CAPTION_STYLES)


@dataclass
class ClipResult:
    """One rendered clip, described by real engine output."""

    index: int
    start: float
    end: float
    duration: float
    score: float
    heuristic_score: float | None
    ai_adjustment: float | None
    ai_model: str | None
    reason: str
    hook: str
    title: str
    description: str
    hashtags: list = field(default_factory=list)
    file_path: str | None = None
    poster_path: str | None = None
    srt_path: str | None = None
    meta_path: str | None = None
    transcript: str = ""
    # --- V2 intelligence ---
    #: The individual signal scores behind the overall score.
    signals: dict = field(default_factory=dict)
    #: "estimated" for every intelligence score. There is no measured
    #: value without authorised audience analytics, and none is invented.
    score_kind: str = "estimated"
    #: Why this moment was selected.
    explanation: str = ""
    #: "ai" or "heuristic" -- where the intelligence came from.
    intelligence_source: str | None = None
    suggested_title: str | None = None
    suggested_description: str | None = None
    suggested_hashtags: str | None = None


@dataclass
class ProcessResult:
    """Outcome of one processing run."""

    project_id: str
    project_path: str
    status: str
    #: The provider that served the AI reranking ("groq", "openrouter").
    #: None means the run fell back to deterministic heuristic scoring.
    ai_provider: str | None = None
    #: The model the provider used, e.g. "openai/gpt-oss-120b".
    ai_model: str | None = None
    #: The upstream scoring mode. Upstream calls the LLM path "ollama"
    #: regardless of which provider actually served it, so this field is
    #: kept for diagnostics and is never shown as the provider name.
    upstream_mode: str = "heuristic"
    #: True only when the provider actually returned adjustments.
    ai_used: bool = False
    ai_error: str | None = None
    clips: list = field(default_factory=list)
    render_errors: list = field(default_factory=list)
    error: str | None = None
    stats: dict = field(default_factory=dict)

    # --- V2 intelligence -------------------------------------------------
    #: True only when the intelligence layer reached the AI provider.
    intelligence_used: bool = False
    #: "ai" or "heuristic" -- where the moment analysis came from.
    intelligence_source: str | None = None
    intelligence_provider: str | None = None
    intelligence_model: str | None = None
    #: Why the intelligence layer did not produce an AI result, if it did
    #: not. The run still succeeds; the clips are simply not
    #: AI-analysed, and the UI says so.
    intelligence_error: str | None = None


def build_options(task_like) -> dict:
    """Build upstream options from a task record or dict.

    ``llm`` is set only when an AI model is available, because upstream
    treats a set ``llm`` as "the reranker is on".
    """
    get = task_like.get if isinstance(task_like, dict) else (
        lambda key, default=None: getattr(task_like, key, default))

    aspect = get("aspect_ratio", "9:16")
    if aspect not in VALID_ASPECTS:
        aspect = "9:16"

    style = get("caption_style", "default")
    if style not in VALID_STYLES:
        style = "default"

    options = {
        "aspect": aspect,
        "style": style,
        "tighten": False,
        "loudnorm": True,
        "whisper_model": get("whisper_model", config.DEFAULT_WHISPER_MODEL),
        "device": "cpu",
        "min_len": int(get("min_clip_seconds", 15)),
        "max_len": int(get("max_clip_seconds", 90)),
        "max_clips": int(get("num_clips", 3)) or None,
        "min_score": float(get("min_score", 0.0)),
        "preferred_len": None,
        # Semantic search stays off: Groq publishes no embedding model.
        "search": None,
        "semantic": None,
        "embed_model": None,
        "brand": None,
        "layout": "single",
        "centers": [0.25, 0.75],
        "caption": None,
    }
    # NOTE: the V2 intelligence layer is deliberately *not* an entry in
    # this dict. Upstream validates the option keys and rejects anything
    # it does not recognise, so the intelligence switch is a separate
    # argument to ``process()`` instead.

    model = get("ai_model", None) or config.DEFAULT_AI_MODEL
    provider = config.DEFAULT_AI_PROVIDER
    if provider and provider != "none":
        options["llm"] = model
    return options


def _resolve_ai(model: str | None, provider: str | None):
    """Point the environment at the requested provider/model.

    Returns (active_model, error, provider_name). The environment is
    set so upstream's adapter picks it up at call time.

    ``provider_name`` is the provider that will actually serve the
    request -- "groq", "openrouter", and so on. It is not the model
    name: ``openai/gpt-oss-120b`` is a Groq model, not a provider.
    """
    provider = provider or config.DEFAULT_AI_PROVIDER
    model = model or config.DEFAULT_AI_MODEL

    if not provider or provider == "none":
        return None, "No AI provider configured.", None

    os.environ["VIRALCLIPS_LLM_PROVIDER"] = provider
    if config.DEFAULT_AI_FALLBACK:
        os.environ["VIRALCLIPS_LLM_FALLBACK"] = config.DEFAULT_AI_FALLBACK
    else:
        os.environ.pop("VIRALCLIPS_LLM_FALLBACK", None)

    resolved = provider_adapter.configured_provider()
    if resolved is None:
        return None, (f"No credential found for provider '{provider}'. "
                      "Add it to the local credential file."), None

    provider_adapter.install()

    from providers import openai_compat
    active = openai_compat.chat_model_for(resolved)
    explicit = os.environ.get(resolved["chat_model_env"], "").strip()
    if explicit:
        active = explicit
    elif model and ":" not in model:
        active = model
    return active, None, resolved.get("name") or provider


def _transcript_for(project_path: Path, start: float, end: float) -> str:
    """Extract the transcript text for a clip's time range."""
    path = project_path / "transcript.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    words = data.get("words") or []
    pieces = []
    for word in words:
        try:
            mid = (float(word.get("start", 0)) + float(word.get("end", 0))) / 2
        except (TypeError, ValueError):
            continue
        if start - 0.5 <= mid <= end + 0.5:
            pieces.append(str(word.get("word", "")).strip())
    return " ".join(pieces).strip()


def _collect_clips(project_path: Path, state: dict) -> list:
    """Read the rendered clips and segments the engine produced."""
    clips: list[ClipResult] = []
    segments_path = project_path / "segments.json"
    segments = []
    if segments_path.is_file():
        try:
            segments = json.loads(segments_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            segments = []
    if not isinstance(segments, list):
        segments = []

    candidates = []
    cand_path = project_path / "candidates.json"
    if cand_path.is_file():
        try:
            envelope = json.loads(cand_path.read_text(encoding="utf-8-sig"))
            candidates = envelope.get("candidates", []) or []
        except (OSError, ValueError):
            candidates = []

    # Map (start,end) -> candidate record, so we can recover the AI
    # adjustment and the pre-AI heuristic score.
    by_window = {}
    for cand in candidates:
        try:
            key = (round(float(cand.get("start", 0)), 2),
                   round(float(cand.get("end", 0)), 2))
        except (TypeError, ValueError):
            continue
        by_window[key] = cand

    outputs = state.get("last_outputs") or []
    rendered = []
    for output in outputs:
        path = Path(output)
        if not path.is_file():
            continue
        rendered.append(path)
    rendered.sort()

    for index, segment in enumerate(segments):
        try:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
            score = float(segment.get("overall", 0.0))
        except (TypeError, ValueError):
            continue

        key = (round(start, 2), round(end, 2))
        cand = by_window.get(key, {})
        adjustment = cand.get("llm_adjustment")
        ai_model = cand.get("llm_model")
        raw = cand.get("raw_score")

        hook = str(segment.get("hook", "") or "").strip()
        title = (hook.capitalize() + " #shorts") if hook else "Untitled clip"
        description = ""
        hashtags = []
        file_path = poster = srt = meta = None

        if index < len(rendered):
            mp4 = rendered[index]
            file_path = str(mp4)
            poster_candidate = mp4.with_suffix(".png")
            srt_candidate = mp4.with_suffix(".srt")
            meta_candidate = mp4.with_suffix(".meta.json")
            if poster_candidate.is_file():
                poster = str(poster_candidate)
            if srt_candidate.is_file():
                srt = str(srt_candidate)
            if meta_candidate.is_file():
                meta = str(meta_candidate)
                try:
                    meta_data = json.loads(
                        meta_candidate.read_text(encoding="utf-8-sig"))
                    title = meta_data.get("title") or title
                    description = meta_data.get("description") or ""
                    hashtags = meta_data.get("hashtags") or []
                except (OSError, ValueError):
                    pass

        clips.append(ClipResult(
            index=index,
            start=start,
            end=end,
            duration=round(end - start, 2),
            score=score,
            heuristic_score=float(raw) if isinstance(raw, (int, float)) else None,
            ai_adjustment=float(adjustment) if isinstance(adjustment, (int, float))
            else None,
            ai_model=str(ai_model) if ai_model else None,
            reason=str(segment.get("reason", ""))[:400],
            hook=hook,
            title=title,
            description=description,
            hashtags=list(hashtags),
            file_path=file_path,
            poster_path=poster,
            srt_path=srt,
            meta_path=meta,
            transcript=_transcript_for(project_path, start, end),
        ))

    return clips


def _overlap_seconds(a_start: float, a_end: float,
                     b_start: float, b_end: float) -> float:
    """Seconds covered by both ranges."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _analyse_moments(project_path: Path, source_path: Path | None,
                      options: dict, ai_model: str | None,
                      ai_provider: str | None):
    """Run the V2 intelligence layer over a project's transcript."""
    from . import intelligence

    utterances = intelligence.load_transcript(project_path)
    if not utterances:
        return None
    return intelligence.detect_moments(
        utterances,
        source_path=source_path,
        count=int(options.get("max_clips", 3)) or 3,
        min_seconds=int(options.get("min_len", 15)),
        max_seconds=int(options.get("max_len", 90)),
        provider=ai_provider,
        model=ai_model,
    )


def _render_moment(moment, source_path: Path, project_path: Path,
                   out_dir: Path, options: dict) -> Path | None:
    """Render one intelligent moment with the preserved Chopify engine."""
    transcript_path = project_path / "transcript.json"
    try:
        output = rerender(source_path, moment.start, moment.end, options,
                          out_dir, transcript_path)
    except Exception:  # noqa: BLE001 - a failed render must not lose the run
        return None
    return Path(output) if Path(output).is_file() else None


def _apply_intelligence(clips: list, result, project_path: Path,
                        source_path: Path | None, options: dict,
                        project_id: str) -> list:
    """Fold the intelligence layer into the rendered clips.

    Two things happen:

    1. Every existing clip that overlaps an intelligent moment inherits
       that moment's signals, score and explanation. The clip's own
       score is replaced by the multi-signal score, which is why the
       dashboard can show *why* a clip was chosen.
    2. A clip whose boundaries sit well away from the intelligent
       moment's boundaries is **re-rendered** at the moment's
       boundaries, because a cut in the middle of a sentence is exactly
       what the intelligence layer exists to prevent.

    A moment that the engine did not cover at all is rendered as a
    genuinely new clip, using the same rendering engine.
    """
    from . import intelligence

    if not result.moments:
        return clips

    out_dir = config.CLIP_DIR / f"project-{project_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    max_clips = int(options.get("max_clips", 3)) or len(clips) or 3

    # --- 1. attach intelligence to the clips that already exist ------
    for clip in clips:
        best = None
        best_overlap = 0.0
        for moment in result.moments:
            overlap = _overlap_seconds(clip.start, clip.end,
                                       moment.start, moment.end)
            if overlap > best_overlap:
                best_overlap = overlap
                best = moment
        if best is None or best_overlap < 0.5 * max(clip.duration, 0.001):
            continue

        clip.signals = dict(best.signals)
        clip.score = best.score
        clip.score_kind = "estimated"
        clip.explanation = best.explanation or clip.reason
        clip.intelligence_source = best.source
        clip.suggested_title = best.title or None
        clip.suggested_description = best.description or None
        clip.suggested_hashtags = (
            " ".join("#" + tag for tag in best.hashtags) or None)

        # --- 2. re-cut the clip at the intelligent boundaries ---------
        drift = (abs(best.start - clip.start) + abs(best.end - clip.end))
        if drift > 1.5 and source_path is not None:
            output = _render_moment(best, source_path, project_path, out_dir,
                                    options)
            if output is not None:
                clip.start = round(best.start, 2)
                clip.end = round(best.end, 2)
                clip.duration = round(best.end - best.start, 2)
                clip.file_path = str(output)
                poster = output.with_suffix(".png")
                if poster.is_file():
                    clip.poster_path = str(poster)
                srt = output.with_suffix(".srt")
                if srt.is_file():
                    clip.srt_path = str(srt)
                meta = output.with_suffix(".meta.json")
                if meta.is_file():
                    clip.meta_path = str(meta)

    # --- 3. render moments the engine did not cover at all -----------
    for moment in result.moments:
        if len(clips) >= max_clips:
            break
        covered = any(
            _overlap_seconds(clip.start, clip.end, moment.start, moment.end)
            >= 0.5 * moment.duration for clip in clips)
        if covered:
            continue
        if source_path is None:
            continue
        output = _render_moment(moment, source_path, project_path, out_dir,
                                options)
        if output is None:
            continue
        poster = output.with_suffix(".png")
        srt = output.with_suffix(".srt")
        meta = output.with_suffix(".meta.json")
        clips.append(ClipResult(
            index=len(clips),
            start=round(moment.start, 2),
            end=round(moment.end, 2),
            duration=round(moment.end - moment.start, 2),
            score=moment.score,
            heuristic_score=None,
            ai_adjustment=None,
            ai_model=None,
            reason=moment.explanation or "Selected by the intelligence layer.",
            hook=(moment.title or "").lower()[:60],
            title=moment.title or "Untitled moment",
            description=moment.description or "",
            hashtags=list(moment.hashtags),
            file_path=str(output),
            poster_path=str(poster) if poster.is_file() else None,
            srt_path=str(srt) if srt.is_file() else None,
            meta_path=str(meta) if meta.is_file() else None,
            transcript=moment.text,
            signals=dict(moment.signals),
            score_kind="estimated",
            explanation=moment.explanation,
            intelligence_source=moment.source,
            suggested_title=moment.title or None,
            suggested_description=moment.description or None,
            suggested_hashtags=(" ".join("#" + tag for tag in moment.hashtags)
                                or None),
        ))

    clips.sort(key=lambda clip: (-clip.score, clip.start))
    for index, clip in enumerate(clips):
        clip.index = index
    return clips


def process(source: str, options: dict, ai_model: str | None = None,
            ai_provider: str | None = None, progress=None,
            intelligence_enabled: bool = True) -> ProcessResult:
    """Run the full pipeline over a source video.

    ``source`` is a local file path or an authorized URL.
    ``options`` is an upstream options dict (see ``build_options``).
    ``intelligence_enabled`` turns the V2 intelligence layer on or off.
    It is an argument rather than an option because upstream validates
    the option keys and rejects anything it does not recognise.
    """
    project_root = config.PROJECT_DIR
    project_root.mkdir(parents=True, exist_ok=True)

    state = projects.create_project(project_root, source, options)
    project_id = state["id"]
    path = projects.project_path(project_root, project_id)

    active_model = None
    active_provider = None
    ai_error = None
    if options.get("llm"):
        active_model, ai_error, active_provider = _resolve_ai(
            ai_model, ai_provider)
        if ai_error:
            # Fall back to deterministic scoring rather than failing the
            # whole run. The caller is told the AI did not participate.
            options = {**options, "llm": None}

    def _progress(stage: str):
        if progress:
            try:
                progress(stage)
            except Exception:  # noqa: BLE001
                pass

    try:
        final = projects.run_project(path, action="all", progress=_progress)
    except Exception as exc:  # noqa: BLE001
        return ProcessResult(
            project_id=project_id,
            project_path=str(path),
            status="failed",
            ai_provider=active_provider,
            ai_model=active_model,
            ai_error=ai_error,
            error=str(exc),
        )

    stats = {}
    selection_path = path / "selection.json"
    if selection_path.is_file():
        try:
            stats = json.loads(selection_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            stats = {}

    upstream_mode = str(stats.get("mode", "heuristic"))
    # Upstream reports "ollama" for any LLM-reranked selection, because
    # its only built-in backend was Ollama. The real provider is the one
    # the adapter resolved, not the upstream mode string.
    ai_used = upstream_mode not in ("heuristic", "", None)

    clips = _collect_clips(path, final)

    # --- V2 intelligence -----------------------------------------------
    intelligence_result = None
    intelligence_error = None
    if intelligence_enabled:
        source_path = None
        try:
            project_state = projects.read_project(path)
            candidate = Path(project_state.get("source", ""))
            if candidate.is_file():
                source_path = candidate
        except (OSError, ValueError, KeyError):
            source_path = None

        try:
            intelligence_result = _analyse_moments(
                path, source_path, options, active_model, active_provider)
        except Exception as exc:  # noqa: BLE001 - never lose the run
            intelligence_error = f"{type(exc).__name__}: {exc}"

        if intelligence_result is not None:
            if intelligence_result.error:
                intelligence_error = intelligence_result.error
            clips = _apply_intelligence(clips, intelligence_result, path,
                                        source_path, options, project_id)

    return ProcessResult(
        project_id=project_id,
        project_path=str(path),
        status=str(final.get("status", "complete")),
        ai_provider=active_provider if ai_used else None,
        ai_model=active_model if ai_used else None,
        upstream_mode=upstream_mode,
        ai_used=ai_used,
        ai_error=ai_error if not ai_used else None,
        clips=clips,
        render_errors=final.get("render_errors") or [],
        stats=stats,
        intelligence_used=bool(intelligence_result and intelligence_result.used_ai),
        intelligence_source=(intelligence_result.moments[0].source
                             if intelligence_result and intelligence_result.moments
                             else None),
        intelligence_provider=(intelligence_result.provider
                               if intelligence_result else None),
        intelligence_model=(intelligence_result.model
                           if intelligence_result else None),
        intelligence_error=intelligence_error,
    )


def rerender(source: str, start: float, end: float, options: dict,
             out_dir: Path, transcript_path: Path | None = None) -> Path:
    """Re-render a single clip with new settings.

    Uses upstream's render path directly so the output is identical in
    quality to the original pipeline. ``transcript_path`` points at the
    original project's transcript.json, which holds the word timings the
    caption renderer needs.
    """
    import render_clips

    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source video is missing: {source_path}")
    width, height = render_clips.ffprobe_dims(source_path)

    words = []
    if transcript_path and Path(transcript_path).is_file():
        try:
            words = json.loads(
                Path(transcript_path).read_text(encoding="utf-8-sig")).get("words", [])
        except (OSError, ValueError):
            words = []

    segment = {"start": start, "end": end, "hook": "clip", "overall": 5.0,
               "duration": round(end - start, 2), "rank": 1}
    output = render_clips.render(
        segment, words, source_path, width, height, out_dir,
        options.get("aspect", "9:16"), out_dir=out_dir,
        style=options.get("style", "default"),
        do_tighten=options.get("tighten", False),
        loudnorm=options.get("loudnorm", True), preview=False,
        brand=None, layout=options.get("layout", "single"),
        centers=options.get("centers", [0.25, 0.75]), caption=None)
    return Path(output)


def probe(path: str) -> dict:
    """Probe a media file for duration and dimensions."""
    import ingest
    meta = ingest.probe_source(str(path))
    meta.pop("formats", None)
    return meta

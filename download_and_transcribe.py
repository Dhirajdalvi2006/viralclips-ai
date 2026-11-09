"""
Stage 1 of the viral-clip pipeline.

Downloads a YouTube video at highest quality with yt-dlp, then transcribes it
locally with faster-whisper (word-level timestamps). Writes work/transcript.json.

No external/paid APIs. CPU-friendly (int8). Usage:
    python download_and_transcribe.py <youtube_url> --model small
"""
import sys
import json
import argparse
import os
import subprocess
import tempfile
import shutil
from urllib.parse import urlparse
from pathlib import Path

TRANSCRIPT_VERSION = 2
CHUNK_SECONDS = 1800
OVERLAP_SECONDS = 30


def run(cmd):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def resolve_source(source, workdir):
    """Keep local files in place; only network URLs go through yt-dlp."""
    path = Path(source).expanduser()
    if path.is_file():
        if path.suffix.lower() not in {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}:
            raise ValueError("Use a video file: MP4, MKV, WebM, MOV, M4V or AVI.")
        return path.resolve()
    if urlparse(source).scheme not in {"http", "https"}:
        raise ValueError(f"Video file does not exist or URL is invalid: {source}")
    return download(source, Path(workdir))


def download(url, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    # A fresh directory prevents a changed URL from reusing an old source.mp4.
    with tempfile.TemporaryDirectory(prefix="download-", dir=workdir) as temp:
        video = _download(url, Path(temp))
        destination = workdir / video.name
        shutil.move(str(video), str(destination))
        return destination.resolve()


def _download(url, workdir):
    out_tmpl = workdir / "source.%(ext)s"
    # Highest quality: best video + best audio, merged to mp4 (needs ffmpeg on PATH).
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo*+bestaudio/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", str(out_tmpl),
        url,
    ]
    run(cmd)
    vids = [p for p in sorted(workdir.glob("source.*"))
            if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".m4v")]
    if not vids:
        raise SystemExit("Download failed: no video file produced.")
    return vids[0].resolve()


def resolve_transcription_provider(provider=None):
    """Resolve the provider once, before any local native dependency loads."""
    provider = (provider or os.environ.get(
        "VIRALCLIPS_TRANSCRIPTION_PROVIDER", "auto")).strip().lower()
    if provider in {"local", "faster-whisper", "faster_whisper"}:
        provider = "faster_whisper"
    if provider not in {"auto", "groq", "faster_whisper"}:
        raise ValueError(
            "Transcription provider must be auto, groq or faster_whisper.")

    groq_enabled = os.environ.get(
        "VIRALCLIPS_GROQ_TRANSCRIPTION_ENABLED", "1") != "0"
    local_enabled = os.environ.get(
        "VIRALCLIPS_LOCAL_TRANSCRIPTION_ENABLED", "1") != "0"

    if provider == "groq" and not groq_enabled:
        raise RuntimeError("Groq transcription is disabled by configuration.")
    if provider == "faster_whisper" and not local_enabled:
        raise RuntimeError("Local Faster-Whisper transcription is disabled.")

    if provider == "auto":
        if groq_enabled:
            try:
                from viralclips_app.transcription.groq_whisper import _api_key
                _api_key()
                return "groq"
            except Exception as exc:
                print(
                    "Groq transcription is not configured "
                    f"({type(exc).__name__}); checking local provider.",
                    flush=True)
        if not local_enabled:
            raise RuntimeError(
                "No transcription provider is available: Groq is not "
                "configured and local transcription is disabled.")
        return "faster_whisper"
    return provider


def transcribe(video, workdir, model_size, device, compute_type, duration=None,
               chunked=False, source=None, media_kind="video",
               render_from_sections=False, identity=None, progress=None,
               resume=True, provider=None):
    """Transcribe with an explicitly selected backend.

    Auto mode prefers Groq when a credential is configured, avoiding an
    unnecessary CTranslate2 import on hosts where Windows policy blocks it.
    If Groq is not configured, auto uses Faster-Whisper. Explicit provider
    selections never silently change providers.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    selected_provider = resolve_transcription_provider(provider)
    use_groq = selected_provider == "groq"

    if use_groq:
        return _transcribe_with_groq(
            video, workdir, duration=duration, source=source,
            media_kind=media_kind, render_from_sections=render_from_sections,
            identity=identity, progress=progress)
    if chunked:
        try:
            return transcribe_chunked(
                video, workdir, model_size, device, compute_type, duration,
                source=source, media_kind=media_kind,
                render_from_sections=render_from_sections, identity=identity,
                progress=progress, resume=resume)
        except Exception as exc:
            if selected_provider == "faster_whisper" and (provider is None or provider == "auto"):
                raise RuntimeError(
                    "Auto selected local Faster-Whisper because no Groq "
                    "credential was available, but local transcription "
                    "failed. Configure GROQ_API_KEY and select the groq "
                    "provider to avoid the local CTranslate2 dependency. "
                    f"Underlying error: {type(exc).__name__}: {exc}") from exc
            raise

    try:
        model = _load_model(model_size, device, compute_type)
        seg_list, words, language, info_duration = _transcribe_media(model, video)
    except Exception as exc:
        if selected_provider == "faster_whisper" and (provider is None or provider == "auto"):
            raise RuntimeError(
                "Auto selected local Faster-Whisper because no Groq "
                "credential was available, but local transcription failed. "
                "Configure GROQ_API_KEY and select the groq provider to avoid "
                "the local CTranslate2 dependency. "
                f"Underlying error: {type(exc).__name__}: {exc}") from exc
        raise

    total = float(duration) if duration is not None else float(info_duration)
    transcript = {
        "video": str(video),
        "language": language,
        "duration": total,
        "model": model_size,
        "segments": seg_list,
        "words": words,
        "transcript_version": TRANSCRIPT_VERSION,
        "chunked": False,
        "chunks": 0,
        "media_kind": media_kind,
        "render_from_sections": bool(render_from_sections),
        "source": str(source or video),
        "source_duration": total,
        "source_identity": str(identity or ""),
        "transcription_provider": "faster_whisper",
        "transcription_model": model_size,
    }
    out = workdir / "transcript.json"
    _atomic_json(out, transcript)
    print(f"Wrote {out}  ({len(words)} words, {len(seg_list)} segments)",
          flush=True)
    return out


def _atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(temp, path)


def _load_model(model_size, device, compute_type):
    from faster_whisper import WhisperModel
    print(f"Loading faster-whisper model={model_size} device={device} "
          f"compute={compute_type} (first run downloads the model)...", flush=True)
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def _transcribe_media(model, media, offset=0.0):
    segments, info = model.transcribe(
        str(media), word_timestamps=True, vad_filter=True)
    language = getattr(info, "language", "")
    print(f"Detected language: {language} "
          f"(p={getattr(info, 'language_probability', 0.0):.2f}), "
          f"audio {getattr(info, 'duration', 0.0):.1f}s", flush=True)
    seg_list, words = [], []
    for seg in segments:
        start = float(seg.start) + offset
        end = float(seg.end) + offset
        seg_list.append({"start": start, "end": end, "text": seg.text})
        for w in (seg.words or []):
            words.append({
                "word": w.word,
                "start": float(w.start) + offset,
                "end": float(w.end) + offset,
            })
        print(f"[{start:7.2f} -> {end:7.2f}] {seg.text}", flush=True)
    info_duration = float(getattr(info, "duration", 0.0) or 0.0)
    return seg_list, words, language, info_duration


def _probe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def _extract_chunk(source, start, end, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-ss", f"{float(start):.3f}", "-t", f"{float(end) - float(start):.3f}",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(path)], check=True)
    return path


def _part_matches(part, index, start, end, identity):
    if not isinstance(part, dict):
        return False
    if part.get("version") != TRANSCRIPT_VERSION:
        return False
    if part.get("index") != index:
        return False
    if str(part.get("identity") or "") != str(identity or ""):
        return False
    try:
        if abs(float(part.get("start")) - float(start)) > 1e-3:
            return False
        if abs(float(part.get("end")) - float(end)) > 1e-3:
            return False
    except (TypeError, ValueError):
        return False
    words = part.get("words") or []
    starts = [float(word.get("start", 0.0)) for word in words]
    return all(a <= b for a, b in zip(starts, starts[1:]))


def _read_part(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def merge_transcript_parts(parts, duration, overlap=OVERLAP_SECONDS):
    """Merge overlapping chunk transcripts into one global timeline."""
    ordered = sorted(parts, key=lambda part: int(part.get("index", 0)))
    last = len(ordered) - 1
    merged_words, merged_segments = [], []
    language = ""
    for position, part in enumerate(ordered):
        start = float(part.get("start") or 0.0)
        end = float(part.get("end") or 0.0)
        lower = start + float(overlap) / 2.0 if position > 0 else float("-inf")
        upper = end - float(overlap) / 2.0 if position < last else float("inf")
        merged_words.extend(
            word for word in (part.get("words") or [])
            if lower <= _midpoint(word) < upper)
        merged_segments.extend(
            seg for seg in (part.get("segments") or [])
            if lower <= _midpoint(seg) < upper)
        language = language or str(part.get("language") or "")

    words = _dedupe(sorted(merged_words, key=_start), "word")
    segments = _dedupe(sorted(merged_segments, key=_start), "text")
    return {"words": words, "segments": segments, "language": language,
            "chunks": len(ordered), "duration": float(duration)}


def _midpoint(item):
    return (float(item.get("start", 0.0)) + float(item.get("end", 0.0))) / 2.0


def _start(item):
    return float(item.get("start", 0.0))


def _dedupe(items, key):
    seen = set()
    out = []
    for item in items:
        marker = (round(_start(item), 3), str(item.get(key) or ""))
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def transcribe_chunked(video, workdir, model_size, device, compute_type,
                       duration=None, source=None, media_kind="video",
                       render_from_sections=False, identity=None,
                       progress=None, resume=True):
    """Transcribe a long source in 30-minute parts with overlap."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    source_path = Path(video)
    total = float(duration) if duration is not None else _probe_duration(source_path)
    if total <= 0:
        raise ValueError("Cannot transcribe an empty source.")
    identity = str(identity or "")

    bounds = []
    index = 0
    while index * CHUNK_SECONDS < total:
        start = index * CHUNK_SECONDS
        owned_end = min(total, start + CHUNK_SECONDS)
        end = min(total, owned_end + OVERLAP_SECONDS)
        bounds.append((index, float(start), float(end)))
        index += 1

    model = None
    parts = []
    part_dir = workdir / "audio_parts"
    part_dir.mkdir(parents=True, exist_ok=True)
    for done, (index, start, end) in enumerate(bounds, 1):
        part_path = workdir / (f"transcript.part{index:03d}.json")
        part = _read_part(part_path) if resume else None
        if not _part_matches(part, index, start, end, identity):
            if model is None:
                model = _load_model(model_size, device, compute_type)
            wav = part_dir / f"part{index:03d}.wav"
            _extract_chunk(source_path, start, end, wav)
            seg_list, words, language, _ = _transcribe_media(
                model, wav, offset=start)
            part = {
                "version": TRANSCRIPT_VERSION,
                "index": index,
                "start": start,
                "end": end,
                "identity": identity,
                "language": language,
                "segments": seg_list,
                "words": words,
            }
            _atomic_json(part_path, part)
            try:
                wav.unlink()
            except OSError:
                pass
        parts.append(part)
        if progress:
            progress(done, len(bounds))

    merged = merge_transcript_parts(parts, total, overlap=OVERLAP_SECONDS)
    transcript = {
        "video": str(video),
        "language": merged["language"],
        "duration": total,
        "model": model_size,
        "segments": merged["segments"],
        "words": merged["words"],
        "transcript_version": TRANSCRIPT_VERSION,
        "chunked": True,
        "chunks": merged["chunks"],
        "media_kind": media_kind,
        "render_from_sections": bool(render_from_sections),
        "source": str(source or video),
        "source_duration": total,
        "source_identity": identity,
        "transcription_provider": "faster_whisper",
        "transcription_model": model_size,
    }
    out = workdir / "transcript.json"
    _atomic_json(out, transcript)
    print(f"Wrote {out}  ({len(transcript['words'])} words, "
          f"{len(transcript['segments'])} segments, {merged['chunks']} chunks)",
          flush=True)
    return out


def write_media_transcript(video, workdir, duration, source=None,
                           media_kind="video", render_from_sections=True,
                           identity=None, language=""):
    """Write an empty transcript for a silent source scored from media alone."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    total = float(duration or 0.0)
    transcript = {
        "video": str(video),
        "language": language,
        "duration": total,
        "model": None,
        "segments": [],
        "words": [],
        "transcript_version": TRANSCRIPT_VERSION,
        "chunked": False,
        "chunks": 0,
        "media_kind": media_kind,
        "render_from_sections": bool(render_from_sections),
        "source": str(source or video),
        "source_duration": total,
        "source_identity": str(identity or ""),
    }
    out = workdir / "transcript.json"
    _atomic_json(out, transcript)
    print(f"Wrote {out}  (media-only source, no speech)", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--workdir", default="work")
    ap.add_argument("--model", default="medium",
                    help="faster-whisper model: tiny/base/small/medium/large-v3")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute-type", default="int8")
    args = ap.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    video = resolve_source(args.url, workdir)
    print("Downloaded:", video, flush=True)
    transcribe(video, workdir, args.model, args.device, args.compute_type)
    print("STAGE 1 COMPLETE", flush=True)



def _transcribe_with_groq(video, workdir, duration=None, source=None,
                          media_kind="video", render_from_sections=False,
                          identity=None, progress=None):
    """Transcribe using Groq Speech-to-Text and write transcript.json."""
    from viralclips_app.transcription.groq_whisper import (
        transcribe_audio_file)
    from viralclips_app.transcription.audio import extract_audio, cleanup
    from pathlib import Path

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if progress:
        try:
            progress("transcribe")
        except Exception:
            pass

    audio_dir = workdir / "_groq_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    try:
        audio_path = extract_audio(video, output_dir=audio_dir)
        print(f"Extracted audio: {audio_path} "
              f"({audio_path.stat().st_size} bytes)", flush=True)

        from viralclips_app import config as _config
        model = _config.DEFAULT_GROQ_TRANSCRIPTION_MODEL
        result = transcribe_audio_file(
            str(audio_path),
            model=model,
            max_file_mb=_config.GROQ_TRANSCRIPTION_MAX_FILE_MB,
            chunk_target_mb=_config.GROQ_TRANSCRIPTION_CHUNK_TARGET_MB)
        total = (float(duration) if duration is not None
                 else float(result.duration or 0.0))
        if total <= 0:
            total = result.duration

        seg_list = [{"start": s.start, "end": s.end, "text": s.text}
                    for s in result.segments]
        words = [{"word": w.word, "start": w.start, "end": w.end}
                 for w in result.words]

        transcript = {
            "video": str(video),
            "language": result.language or "",
            "duration": total,
            "model": result.model or "whisper-large-v3-turbo",
            "segments": seg_list,
            "words": words,
            "transcript_version": TRANSCRIPT_VERSION,
            "chunked": False,
            "chunks": 0,
            "media_kind": media_kind,
            "render_from_sections": bool(render_from_sections),
            "source": str(source or video),
            "source_duration": total,
            "source_identity": str(identity or ""),
            "transcription_provider": "groq",
            "transcription_model": result.model or "whisper-large-v3-turbo",
        }
        out = workdir / "transcript.json"
        _atomic_json(out, transcript)
        print(f"Wrote {out}  ({len(words)} words, {len(seg_list)} segments) "
              f"via Groq {result.model}", flush=True)
        return out
    finally:
        cleanup(audio_dir)


if __name__ == "__main__":
    main()

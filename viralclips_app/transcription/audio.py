"""Audio preprocessing helpers.

The original video is never modified. FFmpeg extracts a mono 16 kHz
FLAC (or WAV) stream into a job-specific temporary directory, which is
cleaned up after the run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def extract_audio(video_path: str | Path, output_dir: str | Path | None = None,
                  sample_rate: int = 16000, channels: int = 1,
                  codec: str = "flac") -> Path:
    """Extract an audio stream from a video using FFmpeg.

    Returns the path to the extracted audio file. Raises RuntimeError
    when FFmpeg fails or when the source has no audio track.
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        raise RuntimeError(f"Source video not found: {video_path}")

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="viralclips_audio_")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".flac" if codec == "flac" else ".wav"
    audio_path = output_dir / f"audio{suffix}"

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-vn",
        "-ar", str(sample_rate),
        "-ac", str(channels),
    ]
    if codec == "flac":
        command += ["-c:a", "flac"]
    else:
        command += ["-c:a", "pcm_s16le"]
    command.append(str(audio_path))

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not audio_path.is_file():
        raise RuntimeError(
            f"FFmpeg audio extraction failed: {result.stderr.strip()[:500]}")

    if audio_path.stat().st_size == 0:
        raise RuntimeError("The extracted audio file is empty -- the source "
                           "may have no audio track.")

    return audio_path


def file_size_mb(path: str | Path) -> float:
    return Path(path).stat().st_size / (1024 * 1024)


def cleanup(directory: str | Path) -> None:
    """Remove a temporary directory and its contents."""
    try:
        shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        pass


def probe_duration(path: str | Path) -> float | None:
    """Return a media file's duration in seconds via ffprobe."""
    import json as _json
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    try:
        return float(_json.loads(result.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None

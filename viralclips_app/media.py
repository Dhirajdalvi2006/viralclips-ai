"""Media serving for clip playback.

Two jobs:

**Byte-range streaming.** Starlette's ``FileResponse`` sets an
``Accept-Ranges`` header but does not implement the range protocol, so a
browser cannot seek inside a clip -- it has to download the whole file
before it can jump. This module implements the protocol properly: a
``Range`` header produces ``206 Partial Content`` with a correct
``Content-Range``, an unsatisfiable range produces ``416``, and the body
is streamed in chunks so a large clip is never held in memory.

**Poster generation.** Every rendered clip gets a real poster frame
extracted with FFmpeg. If extraction fails the caller falls back rather
than showing a generic placeholder.
"""
from __future__ import annotations

import mimetypes
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

#: 1 MiB. Large enough that syscall overhead is irrelevant, small enough
#: that a 100 MB clip never lands in memory at once.
CHUNK_SIZE = 1024 * 1024

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


class MediaError(RuntimeError):
    """The requested media could not be served."""


class RangeNotSatisfiable(MediaError):
    """The requested byte range falls outside the file."""


@dataclass
class MediaFile:
    """A resolved, verified media file ready to be streamed."""

    path: Path
    media_type: str
    size: int


def allowed_roots() -> list[Path]:
    """The directories this application is allowed to serve media from.

    Everything the application renders lives under the data directory, so
    the confinement is deliberately broad but absolute: a resolved path
    must sit inside one of these roots, or it is refused.
    """
    roots = [config.DATA_DIR]
    for extra in (config.CLIP_DIR, config.VIDEO_DIR, config.PROJECT_DIR,
                  config.THUMBNAIL_DIR, config.EXPORT_DIR):
        if extra not in roots:
            roots.append(extra)
    return roots


def resolve_media_path(raw: str | None) -> Path:
    """Resolve a stored media path and confirm it is safe to serve.

    Raises ``MediaError`` when the path is missing, is not a file, or
    escapes the application's own storage. Symlinks are resolved before
    the check, so a link pointing outside the data directory is refused
    too.
    """
    if not raw:
        raise MediaError("No media path is recorded for this item.")
    try:
        path = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise MediaError("The media path could not be resolved.") from exc

    if not path.is_file():
        raise MediaError("The media file is missing.")

    roots = [root.resolve() for root in allowed_roots()]
    for root in roots:
        try:
            path.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise MediaError("The media path is outside the application's "
                         "storage directory.")
    return path


def media_type_for(path: Path) -> str:
    """Return the MIME type for a media file."""
    suffix = path.suffix.lower()
    if suffix in VIDEO_MIME_TYPES:
        return VIDEO_MIME_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a ``Range`` header into an inclusive ``(start, end)`` pair.

    Returns ``None`` when there is no usable range, which means "send the
    whole file". Raises ``RangeNotSatisfiable`` when the range cannot be
    served.
    """
    if not header:
        return None
    text = header.strip()
    if not text.lower().startswith("bytes="):
        return None
    match = RANGE_RE.match(text)
    if not match:
        # A multi-range request is legal but rare. Serving the whole
        # file is a valid response to a multi-range request.
        if "," in text:
            return None
        # A syntactically broken range is not something to guess at.
        raise RangeNotSatisfiable("Malformed range.")

    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "" and raw_end == "":
        return None

    if raw_start == "":
        # Suffix range: the last N bytes.
        try:
            suffix_length = int(raw_end)
        except ValueError as exc:
            raise RangeNotSatisfiable("Malformed range.") from exc
        if suffix_length <= 0:
            raise RangeNotSatisfiable("Malformed range.")
        start = max(0, size - suffix_length)
        end = size - 1
    else:
        try:
            start = int(raw_start)
        except ValueError as exc:
            raise RangeNotSatisfiable("Malformed range.") from exc
        if raw_end == "":
            end = size - 1
        else:
            try:
                end = int(raw_end)
            except ValueError as exc:
                raise RangeNotSatisfiable("Malformed range.") from exc
        if end > size - 1:
            end = size - 1

    if start >= size or start > end or start < 0:
        raise RangeNotSatisfiable(
            f"The range {text} is outside the {size} byte file.")
    return start, end


def iter_file(path: Path, start: int = 0, end: int | None = None,
              chunk_size: int = CHUNK_SIZE):
    """Yield the bytes of a file in chunks, starting at ``start``."""
    remaining = (end - start + 1) if end is not None else None
    with path.open("rb") as handle:
        if start:
            handle.seek(start)
        while True:
            if remaining is not None:
                if remaining <= 0:
                    break
                size = min(chunk_size, remaining)
            else:
                size = chunk_size
            chunk = handle.read(size)
            if not chunk:
                break
            if remaining is not None:
                remaining -= len(chunk)
            yield chunk


# --- poster generation --------------------------------------------------------

def ffmpeg_path() -> str:
    """Return the ffmpeg executable to use."""
    import shutil
    return shutil.which("ffmpeg") or "ffmpeg"


def extract_poster(video_path: Path, poster_path: Path,
                   duration_seconds: float | None = None,
                   timeout: int = 60) -> Path | None:
    """Extract a representative frame from a clip and save it as a PNG.

    The frame is taken a little way into the clip rather than at zero,
    because the first frame of a rendered clip is often a fade-in or a
    black frame, which makes a poor poster. Returns the poster path on
    success and ``None`` on failure -- the caller decides what to show
    instead, and never shows a generic placeholder for a clip that does
    have a frame to extract.
    """
    video_path = Path(video_path)
    poster_path = Path(poster_path)
    # An existing, non-empty poster is a real extracted frame and is
    # reused as-is. It does not need the source video to still be there.
    if poster_path.is_file() and poster_path.stat().st_size > 0:
        return poster_path
    if not video_path.is_file():
        return None

    try:
        duration = float(duration_seconds) if duration_seconds else 0.0
    except (TypeError, ValueError):
        duration = 0.0

    if duration <= 0:
        duration = probe_duration(video_path) or 0.0

    # 12% into the clip, but never before half a second and never in the
    # last tenth, which is usually the fade-out.
    offset = 0.5
    if duration > 1.0:
        offset = min(max(duration * 0.12, 0.5), max(duration - 0.3, 0.5))

    poster_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{offset:.3f}", "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", str(poster_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not poster_path.is_file():
        return None
    if poster_path.stat().st_size == 0:
        return None
    return poster_path


def probe_duration(path: Path) -> float | None:
    """Return a media file's duration in seconds, via ffprobe."""
    import shutil
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    command = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return None

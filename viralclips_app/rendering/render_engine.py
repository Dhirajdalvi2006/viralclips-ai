"""Render engine: converts project timelines into FFmpeg commands and executes them."""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import shutil

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

from ..config import EXPORT_DIR, CLIP_DIR


class RenderStatus:
    PENDING = "pending"
    PREPARING = "preparing"
    PROCESSING = "processing"
    ENCODING = "encoding"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RenderJob:
    """Represents a single export job."""

    def __init__(self, job_id: str, project_id: int, config: dict):
        self.job_id = job_id
        self.project_id = project_id
        self.config = config
        self.status = RenderStatus.PENDING
        self.progress = 0.0
        self.stage = "queued"
        self.output_path: Optional[str] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._cancel = threading.Event()
        self._process: Optional[subprocess.Popen] = None

    def cancel(self):
        self._cancel.set()
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "status": self.status,
            "progress": round(self.progress, 1),
            "stage": self.stage,
            "output_path": self.output_path,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class RenderEngine:
    """Manages render jobs and executes FFmpeg."""

    def __init__(self):
        self._jobs: Dict[str, RenderJob] = {}
        self._lock = threading.Lock()
        self._max_concurrent = 1
        self._running = 0

    def create_job(self, project_id: int, config: dict) -> RenderJob:
        job_id = str(uuid.uuid4())[:12]
        job = RenderJob(job_id, project_id, config)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[RenderJob]:
        return list(self._jobs.values())

    def start_job(self, job: RenderJob, project_data: dict):
        """Start rendering in a background thread."""
        thread = threading.Thread(target=self._run, args=(job, project_data), daemon=True)
        thread.start()

    def _run(self, job: RenderJob, project_data: dict):
        job.status = RenderStatus.PREPARING
        job.started_at = datetime.now(timezone.utc)
        job.stage = "Preparing project"
        job.progress = 5.0

        try:
            # Validate FFmpeg
            if not _check_ffmpeg():
                raise RuntimeError("FFmpeg not found. Install FFmpeg and ensure it is on PATH.")

            config = job.config
            timeline = (project_data.get("timeline_data") or {}).get("timeline", [])
            duration = project_data.get("duration", 0) or _compute_duration(timeline)

            # Build output path
            output_dir = EXPORT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = config.get("filename", f"export_{job.job_id}.mp4")
            if not filename.endswith(".mp4"):
                filename += ".mp4"
            output_path = output_dir / filename
            # Avoid overwriting
            counter = 1
            while output_path.exists():
                stem = Path(filename).stem
                output_path = output_dir / f"{stem}_{counter}.mp4"
                counter += 1

            if job.is_cancelled:
                job.status = RenderStatus.CANCELLED
                return

            job.status = RenderStatus.PROCESSING
            job.stage = "Processing video"
            job.progress = 15.0

            # Build FFmpeg command
            cmd = _build_ffmpeg_command(timeline, config, str(output_path), duration)

            if job.is_cancelled:
                job.status = RenderStatus.CANCELLED
                return

            job.status = RenderStatus.ENCODING
            job.stage = "Encoding"
            job.progress = 30.0

            # Execute
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            job._process = process

            # Monitor progress
            stderr_output = []
            while process.poll() is None:
                if job.is_cancelled:
                    process.terminate()
                    job.status = RenderStatus.CANCELLED
                    return
                line = process.stderr.readline() if process.stderr else ""
                if line:
                    stderr_output.append(line)
                    # Parse progress from FFmpeg output
                    prog = _parse_progress(line, duration)
                    if prog is not None:
                        job.progress = min(90.0, 30.0 + prog * 0.6)
                time.sleep(0.1)

            if process.returncode != 0:
                err = "".join(stderr_output[-20:])
                raise RuntimeError(f"FFmpeg failed (exit {process.returncode}): {err}")

            if job.is_cancelled:
                job.status = RenderStatus.CANCELLED
                if output_path.exists():
                    output_path.unlink(missing_ok=True)
                return

            job.progress = 92.0
            job.stage = "Verifying output"
            job.status = RenderStatus.VERIFYING

            # Verify output
            if not _verify_output(output_path, config, duration):
                raise RuntimeError("Output verification failed.")

            job.output_path = str(output_path)
            job.status = RenderStatus.COMPLETED
            job.progress = 100.0
            job.stage = "Completed"
            job.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            job.status = RenderStatus.FAILED
            job.error = str(e)
            job.stage = "Failed"
            job.completed_at = datetime.now(timezone.utc)
            # Clean up partial output
            if job.output_path and Path(job.output_path).exists():
                try:
                    Path(job.output_path).unlink()
                except Exception:
                    pass


def _check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            [FFMPEG_BIN, "-version"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _compute_duration(timeline: list) -> float:
    if not timeline:
        return 0.0
    return max(c.get("end", 0) for c in timeline)


def _build_ffmpeg_command(timeline, config, output_path, duration):
    import tempfile
    width = config.get("width", 1080)
    height = config.get("height", 1920)
    fps = config.get("fps", 30)
    quality = config.get("quality", "high")
    crf_map = {"draft": "28", "standard": "23", "high": "18", "maximum": "14"}
    crf = crf_map.get(quality, "18")
    audio_bitrate = config.get("audio_bitrate", "192k")
    video_clips = [c for c in (timeline or []) if c.get("type") not in ("audio", "caption", "text")]
    if not video_clips:
        cmd = [FFMPEG_BIN, "-y", "-f", "lavfi", "-i", "color=c=black:s={}x{}:r={}:d={}".format(width, height, fps, max(duration, 1))]
        cmd += ["-t", str(max(duration, 1)), "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-r", str(fps), "-an", output_path]
        return cmd
    clip = video_clips[0]
    trim_start = clip.get("trimStart", 0)
    trim_end = clip.get("trimEnd", clip.get("end", 10) - clip.get("start", 0))
    clip_duration = max(0.1, trim_end - trim_start)
    src = clip.get("src", "")
    # Build filter
    filters = []
    ct = clip.get("cropTop", 0); cb = clip.get("cropBottom", 0)
    cl = clip.get("cropLeft", 0); cr2 = clip.get("cropRight", 0)
    if ct or cb or cl or cr2:
        l = cl/100.0; r = cr2/100.0; t = ct/100.0; b = cb/100.0
        filters.append("crop=iw*{:.4f}:ih*{:.4f}:iw*{:.4f}:ih*{:.4f}".format(max(0.01,1-l-r), max(0.01,1-t-b), l, t))
    scale = clip.get("scale", 1)
    if scale and scale != 1:
        filters.append("scale=iw*{:.4f}:ih*{:.4f}".format(scale, scale))
    rotation = clip.get("rotation", 0)
    if rotation:
        filters.append("rotate={}*PI/180:fillcolor=black@0".format(rotation))
    filters.append("scale={}:{}:force_original_aspect_ratio=decrease".format(width, height))
    filters.append("pad={}:{}:(ow-iw)/2:(oh-ih)/2:black".format(width, height))
    opacity = clip.get("opacity", 1)
    if opacity < 1:
        filters.append("format=rgba,colorchannelmixer=aa={}".format(opacity))
    text = clip.get("text", "")
    if text:
        font_size = clip.get("fontSize", 24)
        color = clip.get("textColor", "white")
        safe_text = text.replace(chr(39), "\\'").replace(":", "\:") 
        filters.append("drawtext=fontfile='data/arial.ttf':text='{}':fontsize={}:fontcolor={}:x=(w-text_w)/2:y=h-th-50".format(safe_text, font_size, color))
    vf = ",".join(filters)
    if src and not src.startswith("blob:") and Path(src).is_file():
        cmd = [FFMPEG_BIN, "-y", "-ss", str(trim_start), "-i", src, "-t", str(clip_duration), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-r", str(fps)]
        cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [output_path]
        return cmd
    else:
        return [FFMPEG_BIN, "-y", "-f", "lavfi", "-i", "color=c=blue:s={}x{}:r={}:d={}".format(width, height, fps, clip_duration), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-r", str(fps), "-an", output_path]



def _parse_progress(line: str, duration: float) -> Optional[float]:
    """Parse FFmpeg progress from stderr line."""
    if "time=" in line:
        try:
            time_str = line.split("time=")[1].split()[0]
            parts = time_str.split(":")
            if len(parts) == 3:
                seconds = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                if duration > 0:
                    return min(1.0, seconds / duration)
        except (ValueError, IndexError):
            pass
    return None


def _verify_output(output_path: Path, config: dict, duration: float) -> bool:
    """Verify the output file using FFprobe."""
    if not output_path.exists() or output_path.stat().st_size == 0:
        return False
    try:
        result = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries",
             "stream=codec_type,width,height,r_frame_rate", "-show_entries",
             "format=duration", "-of", "json", str(output_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        if not has_video:
            return False
        # Check duration
        fmt = data.get("format", {})
        out_duration = float(fmt.get("duration", 0))
        if duration > 0 and abs(out_duration - duration) > duration * 0.5:
            return False
        return True
    except Exception:
        return False

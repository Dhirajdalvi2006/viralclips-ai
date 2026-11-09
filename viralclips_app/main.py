"""FastAPI application: REST API plus the served frontend.

Every statistic the dashboard shows is computed from the database. There
are no hardcoded counters anywhere in this file.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
from pathlib import Path

from fastapi import (Depends, FastAPI, File, Form, HTTPException, Query,
                     Request, UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import (ai, config, intelligence, jobs, media, monitor, pipeline,
               publishing, security, storage)
from .db import get_db, init_db, session_scope
from .models import (Account, ApprovalEvent, Channel, Clip, Episode,
                     Job, Publication, Setting, Task, Video)
from .schemas import (BatchApproval, ChannelCreate, ChannelUpdate,
                      ClipUpdate, EpisodeUpdate, PublishRequest,
                      SettingsUpdate, TaskCreate, TaskUpdate)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="VIRALCLIPS AI",
    description=("Local autonomous video clipping platform. Groq-powered "
                 "clip scoring, 1080x1920 rendering, review, and "
                 "YouTube/Instagram publishing."),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://{config.API_HOST}:{config.API_PORT}"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request,
                                    exc: RequestValidationError):
    """Turn FastAPI's validation errors into a readable message.

    The default response is a list of nested objects. For a file upload
    the useful information is simple -- which field was wrong -- so the
    handler states that in one sentence. A request that fails
    validation never reaches a route body, so no job is created and no
    file is written.
    """
    fields = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", [])
                    if part not in ("body", "query", "path")]
        fields.append(location[-1] if location else "request")
    unique = sorted(set(fields))
    if unique:
        detail = ("The request is missing or has an invalid "
                  + ", ".join(unique) + ".")
    else:
        detail = "The request could not be understood."
    return JSONResponse(status_code=422, content={"detail": detail})


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    init_db()
    _ensure_default_settings()


def _ensure_default_settings() -> None:
    """Seed the settings row with the documented defaults."""
    with session_scope() as session:
        row = session.query(Setting).filter(Setting.key == "app").one_or_none()
        if row is None:
            session.add(Setting(key="app", value={
                "output_directory": str(config.CLIP_DIR),
                "export_directory": str(config.EXPORT_DIR),
                "resolution": "1080x1920",
                "caption_style": "default",
                "default_clip_duration": 45,
                "processing_concurrency": config.DEFAULT_CONCURRENCY,
                "monitor_interval_minutes": config.DEFAULT_MONITOR_INTERVAL_MINUTES,
                "auto_process_new_episodes": False,
                "require_approval": True,
                "retry_policy": {"max_attempts": config.MAX_JOB_ATTEMPTS},
                "cleanup_policy": {"keep_days": 30, "auto": False},
            }))


# --- helpers ---------------------------------------------------------------

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _settings(session) -> dict:
    row = session.query(Setting).filter(Setting.key == "app").one_or_none()
    return dict(row.value) if row and row.value else {}


def _save_settings(session, values: dict) -> dict:
    row = session.query(Setting).filter(Setting.key == "app").one_or_none()
    if row is None:
        row = Setting(key="app", value=values)
        session.add(row)
    else:
        row.value = values
    session.flush()
    return values


def _file_digest(path: Path) -> str:
    """Return the SHA-256 of a file, read in chunks."""
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: Names Windows refuses to use for a file, with or without an
#: extension. "CON" is reserved on Windows no matter what follows it.
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

#: Characters that carry meaning to a shell. A filename never needs one.
_SHELL_METACHARACTERS = set('&|;<>()$`\\"\'!*?[]{}~^#%')

#: Words that name a destructive or information-disclosing shell command.
#: Removing the metacharacters is not enough on its own: a name such as
#: ``rm -rf home`` contains no metacharacter, yet it still reads as a
#: command. Any word in a filename that matches one of these is dropped
#: as a whole word, so ``charm.mp4`` and ``Terminal.mp4`` are untouched
#: while ``rm -rf home.mp4`` is not.
#:
#: The list deliberately excludes ordinary English words that happen to
#: be command names -- ``cat``, ``find``, ``set``, ``net``, ``type``,
#: ``head``, ``tail`` and so on -- because a video file called
#: ``cat video.mp4`` is far more likely than an attack that relies on
#: the word surviving. The application never invokes a shell anyway:
#: every subprocess call passes an argument list, never a command
#: string.
_SHELL_COMMAND_WORDS = frozenset({
    "rm", "rmdir", "del", "erase", "format", "mkfs",
    "shutdown", "reboot", "halt", "poweroff",
    "chmod", "chown", "chgrp", "sudo",
    "curl", "wget", "ssh", "scp", "sftp", "ftp", "nc", "ncat", "netcat",
    "eval", "exec",
    "regedit", "cmd", "powershell", "pwsh", "wscript", "cscript",
    "certutil", "bitsadmin", "mshta", "rundll32", "regsvr32", "schtasks",
    "taskkill", "tasklist", "netsh", "whoami", "hostname", "ipconfig",
    "systeminfo", "nslookup", "tracert", "netstat", "arp",
    "mkfifo", "mknod", "chroot", "unshare",
})

#: The longest a Windows path component may be.
_MAX_NAME_LENGTH = 120


def _safe_filename(filename: str | None, default: str = "upload.mp4") -> str:
    """Turn an uploaded filename into a safe filesystem component.

    The uploaded name is untrusted input. It is never used as a path:
    this function returns a **single path component** that cannot
    escape its directory, cannot be interpreted by a shell, and cannot
    be confused with a reserved device name.

    The rules, in order:

    1. A missing or empty name becomes the default.
    2. Null bytes and control characters are removed. A null byte
       truncates the name inside the Windows API, so it must never
       survive.
    3. The name is split on path separators, and only the last
       component is kept. ``../../evil.mp4`` therefore becomes
       ``evil.mp4`` rather than a traversal.
    4. Any remaining ``..`` or ``.`` sequences are removed, so no
       traversal can survive in a name that had no separator.
    5. Shell metacharacters are removed.
    6. The extension is preserved separately, so a name like
       ``evil.mp4`` keeps its ``.mp4`` even if the stem is emptied.
    7. A Windows reserved device name is replaced.
    8. The result is length-limited.
    """
    if not filename:
        return default

    # 2. Null bytes and control characters. A null byte truncates the
    # name inside the Windows API, so it must never survive. Other
    # control characters are stripped because they have no place in a
    # media file name and can confuse shells and logs.
    cleaned = "".join(
        ch for ch in filename
        if ch != "\x00" and ord(ch) >= 32 and ord(ch) != 127
    )

    # 3. Keep only the final path component. This is the primary
    # defence: whatever preceded the last separator is discarded
    # entirely rather than merely escaped.
    for separator in ("/", "\\"):
        cleaned = cleaned.split(separator)[-1]

    # 4. Remove any remaining traversal dots.
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "")

    # Split off the extension before stripping the rest, so the
    # extension survives even if the stem becomes empty.
    stem, dot, extension = cleaned.rpartition(".")
    if not dot:
        stem, extension = cleaned, ""
    extension = extension.lower()

    # 5. Strip shell metacharacters and anything else unsafe from the
    # stem. Letters, digits, spaces, dots, dashes and underscores are
    # enough for a media file, and Unicode letters are kept so a name
    # like "vidéo.mp4" survives intact.
    safe_stem = "".join(
        ch for ch in stem
        if ch not in _SHELL_METACHARACTERS and ch not in "\r\n\t"
        and ord(ch) >= 32
    )
    safe_stem = safe_stem.strip(". ")
    if not safe_stem:
        safe_stem = "upload"

    # 5b. Drop whole words that name a shell command, together with
    # the flag that follows it. The metacharacters are already gone,
    # but a name like ``rm -rf home`` contains none of them and still
    # reads as a command. Matching is on whole words only, so
    # ``charm.mp4`` and ``Terminal.mp4`` are left alone.
    if safe_stem:
        words = safe_stem.split(" ")
        kept: list[str] = []
        skip_flag = False
        for word in words:
            if skip_flag:
                skip_flag = False
                if word.startswith("-") and word[1:].isalpha():
                    continue
            if word.strip("._-").lower() in _SHELL_COMMAND_WORDS:
                skip_flag = True
                continue
            kept.append(word)
        safe_stem = " ".join(kept)

    # 7. Windows reserved device names.
    if safe_stem.lower() in _WINDOWS_RESERVED:
        safe_stem = f"_{safe_stem}"

    # 8. Length limit. The extension is counted separately so a long
    # stem cannot push the whole name past the limit.
    safe_stem = safe_stem[:_MAX_NAME_LENGTH].strip(". ") or "upload"

    if extension:
        return f"{safe_stem}.{extension[:12]}"
    return safe_stem


def _gcd(a: int, b: int) -> int:
    """Greatest common divisor, used to reduce a resolution to a ratio."""
    while b:
        a, b = b, a % b
    return a or 1


def _clip_dict(clip: Clip) -> dict:
    """Serialise a clip for the API."""
    # The source video is read through the relationship so the library can
    # show which video a clip came from without a second query per clip.
    video = clip.video
    resolution = None
    aspect_ratio = None
    if video is not None and video.width and video.height:
        resolution = f"{video.width}x{video.height}"
        divisor = _gcd(video.width, video.height)
        aspect_ratio = f"{video.width // divisor}:{video.height // divisor}"
    return {
        "id": clip.id,
        "video_id": clip.video_id,
        "source_video_title": video.title if video is not None else None,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "task_id": clip.task_id,
        "job_id": clip.job_id,
        "index": clip.index,
        "start_seconds": clip.start_seconds,
        "end_seconds": clip.end_seconds,
        "duration_seconds": clip.duration_seconds,
        "score": clip.score,
        "heuristic_score": clip.heuristic_score,
        "ai_adjustment": clip.ai_adjustment,
        "ai_model": clip.ai_model,
        "ai_provider": clip.ai_provider,
        "ai_scored": bool(clip.ai_adjustment is not None),
        "reason": clip.reason,
        "category": clip.category,
        "transcript": clip.transcript,
        "title": clip.title,
        "description": clip.description,
        "hashtags": clip.hashtags,
        "caption_style": clip.caption_style,
        # --- V2 intelligence ---
        "signals": dict(clip.signals or {}),
        "signal_weights": dict(intelligence.SIGNAL_WEIGHTS),
        "signal_labels": dict(intelligence.SIGNAL_LABELS),
        "score_kind": clip.score_kind or "estimated",
        "explanation": clip.explanation,
        "intelligence_source": clip.intelligence_source,
        "suggested_title": clip.suggested_title,
        "suggested_description": clip.suggested_description,
        "suggested_hashtags": clip.suggested_hashtags,
        "file_path": clip.file_path,
        "poster_path": clip.poster_path,
        "srt_path": clip.srt_path,
        "approval_status": clip.approval_status,
        "publish_status": clip.publish_status,
        "published_at": clip.published_at,
        "published_platform": clip.published_platform,
        "published_video_id": clip.published_video_id,
        "publish_error": clip.publish_error,
        "created_at": clip.created_at,
    }


def _job_dict(job: Job, include_clips: bool = False) -> dict:
    clip_rows = list(job.clips or [])
    data = {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "task_id": job.task_id,
        "video_id": job.video_id,
        "source": job.source,
        "progress_stage": job.progress_stage,
        "progress_done": job.progress_done,
        "progress_total": job.progress_total,
        "progress_detail": job.progress_detail,
        "attempts": job.attempts,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_seconds": job.duration_seconds,
        "created_at": job.created_at,
        "clip_count": len(clip_rows),
        "approved_count": sum(1 for c in clip_rows
                              if c.approval_status == "approved"),
        "rejected_count": sum(1 for c in clip_rows
                              if c.approval_status == "rejected"),
        "pending_count": sum(1 for c in clip_rows
                             if c.approval_status == "pending"),
    }
    if include_clips:
        data["clips"] = [_clip_dict(clip) for clip in clip_rows]
    return data


def _task_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "category": task.category,
        "source_type": task.source_type,
        "source_url": task.source_url,
        "channel_id": task.channel_id,
        "num_clips": task.num_clips,
        "min_clip_seconds": task.min_clip_seconds,
        "max_clip_seconds": task.max_clip_seconds,
        "aspect_ratio": task.aspect_ratio,
        "resolution": task.resolution,
        "caption_style": task.caption_style,
        "language": task.language,
        "min_score": task.min_score,
        "whisper_model": task.whisper_model,
        "ai_model": task.ai_model,
        "monitor_enabled": task.monitor_enabled,
        "monitor_interval_minutes": task.monitor_interval_minutes,
        "auto_process_new_episodes": task.auto_process_new_episodes,
        "require_approval": task.require_approval,
        "auto_publish": task.auto_publish,
        "rights_confirmed": task.rights_confirmed,
        "rights_note": task.rights_note,
        "enabled": task.enabled,
        "created_at": task.created_at,
    }


def _channel_dict(channel: Channel, episode_count: int = 0,
                  processed_count: int = 0) -> dict:
    return {
        "id": channel.id,
        "name": channel.name,
        "channel_id": channel.channel_id,
        "channel_url": channel.channel_url,
        "handle": channel.handle,
        "description": channel.description,
        "thumbnail_url": channel.thumbnail_url,
        "monitoring": channel.monitoring,
        "paused": channel.paused,
        "check_interval_minutes": channel.check_interval_minutes,
        "last_checked_at": channel.last_checked_at,
        "next_check_at": channel.next_check_at,
        "last_error": channel.last_error,
        "last_error_at": channel.last_error_at,
        "episodes": episode_count,
        "processed": processed_count,
        "created_at": channel.created_at,
    }


# --- system ----------------------------------------------------------------

@app.get("/api/health")
def health():
    """Liveness and readiness report."""
    heartbeat = jobs.read_heartbeat()
    worker_alive = False
    if heartbeat:
        try:
            updated = dt.datetime.fromisoformat(heartbeat["updated_at"])
            age = (_now() - updated).total_seconds()
            worker_alive = age < (config.WORKER_POLL_INTERVAL * 6 + 30)
        except (KeyError, ValueError):
            worker_alive = False

    disk = shutil.disk_usage(str(config.DATA_DIR))
    return {
        "status": "ok",
        "app": "VIRALCLIPS AI",
        "version": "1.0.0",
        "time": _now().isoformat(),
        "worker": {
            "alive": worker_alive,
            "state": (heartbeat or {}).get("state"),
            "current_job": (heartbeat or {}).get("current_job"),
            "updated_at": (heartbeat or {}).get("updated_at"),
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "free_gb": round(disk.free / 1024 ** 3, 2),
            "enough_for_jobs": disk.free >= config.MIN_FREE_DISK_BYTES,
        },
        "publishing_enabled": config.PUBLISHING_ENABLED,
    }


@app.get("/api/bootstrap")
def bootstrap():
    """Everything the frontend needs on first load.

    The API token is returned here because this endpoint is only reachable
    from loopback and the token is required for mutations.
    """
    with session_scope() as session:
        return {
            "token": security.api_token(),
            "config": config.describe(),
            "settings": _settings(session),
            "jobs": jobs.counts(),
            "worker": jobs.read_heartbeat(),
        }


@app.get("/api/overview")
def overview():
    """Dashboard statistics, all computed from real rows."""
    with session_scope() as session:
        total_channels = session.query(func.count(Channel.id)).scalar() or 0
        active_channels = session.query(func.count(Channel.id)).filter(
            Channel.monitoring.is_(True), Channel.paused.is_(False)).scalar() or 0
        episodes = session.query(func.count(Episode.id)).scalar() or 0
        episodes_processed = session.query(func.count(Episode.id)).filter(
            Episode.processed_at.isnot(None)).scalar() or 0
        videos = session.query(func.count(Video.id)).scalar() or 0
        clips_total = session.query(func.count(Clip.id)).scalar() or 0
        clips_pending = session.query(func.count(Clip.id)).filter(
            Clip.approval_status == "pending").scalar() or 0
        clips_approved = session.query(func.count(Clip.id)).filter(
            Clip.approval_status == "approved").scalar() or 0
        clips_rejected = session.query(func.count(Clip.id)).filter(
            Clip.approval_status == "rejected").scalar() or 0
        clips_published = session.query(func.count(Clip.id)).filter(
            Clip.publish_status == "published").scalar() or 0
        publish_failed = session.query(func.count(Clip.id)).filter(
            Clip.publish_status == "failed").scalar() or 0

        avg_score = session.query(func.avg(Clip.score)).scalar()
        ai_scored = session.query(func.count(Clip.id)).filter(
            Clip.ai_adjustment.isnot(None)).scalar() or 0

        completed = session.query(func.count(Job.id)).filter(
            Job.status == "completed").scalar() or 0
        failed_jobs = session.query(func.count(Job.id)).filter(
            Job.status == "failed").scalar() or 0
        avg_duration = session.query(func.avg(Job.duration_seconds)).filter(
            Job.status == "completed").scalar()

        recent_jobs = session.execute(
            select(Job).order_by(Job.created_at.desc()).limit(8)).scalars().all()
        upcoming = session.execute(
            select(Episode).where(Episode.processed_at.is_(None))
            .order_by(Episode.detected_at.desc()).limit(8)).scalars().all()
        recent_clips = session.execute(
            select(Clip).order_by(Clip.created_at.desc()).limit(8)).scalars().all()

        categories = session.execute(
            select(Clip.category, func.count()).group_by(Clip.category)).all()

        # Which provider actually reranked each clip. This is the
        # attribution the dashboard shows, so it comes from the stored
        # provider name rather than from the upstream mode string.
        # A clip that was scored before provider attribution existed has
        # an adjustment but no provider, so it is reported as
        # "not recorded" rather than as a null key or as heuristic.
        ai_by_provider: dict[str, int] = {}
        for provider, count in session.execute(
                select(Clip.ai_provider, func.count())
                .where(Clip.ai_adjustment.isnot(None))
                .group_by(Clip.ai_provider)).all():
            ai_by_provider[provider or "not recorded"] = count
        ai_by_model: dict[str, int] = {}
        for model, count in session.execute(
                select(Clip.ai_model, func.count())
                .where(Clip.ai_adjustment.isnot(None))
                .group_by(Clip.ai_model)).all():
            ai_by_model[model or "not recorded"] = count

        accounts = {
            name: publishing.account_state(session, name)
            for name in ("youtube", "instagram")
        }

        return {
            "totals": {
                "channels": total_channels,
                "active_channels": active_channels,
                "episodes_monitored": episodes,
                "episodes_processed": episodes_processed,
                "videos_processed": videos,
                "clips_generated": clips_total,
                "clips_awaiting_approval": clips_pending,
                "clips_approved": clips_approved,
                "clips_rejected": clips_rejected,
                "clips_published": clips_published,
                "publish_failures": publish_failed,
                "ai_scored_clips": ai_scored,
                "ai_by_provider": ai_by_provider,
                "ai_by_model": ai_by_model,
                "jobs_completed": completed,
                "jobs_failed": failed_jobs,
                "average_ai_score": round(float(avg_score), 2) if avg_score else None,
                "average_processing_seconds": (
                    round(float(avg_duration), 1) if avg_duration else None),
            },
            "jobs": jobs.counts(),
            "recent_jobs": [_job_dict(job) for job in recent_jobs],
            "upcoming_episodes": [{
                "id": episode.id,
                "video_id": episode.video_id,
                "title": episode.title,
                "url": episode.url,
                "detected_at": episode.detected_at,
                "published_at": episode.published_at,
                "processed": episode.processed_at is not None,
            } for episode in upcoming],
            "recent_clips": [_clip_dict(clip) for clip in recent_clips],
            "clip_categories": {name: count for name, count in categories},
            "ai_health": ai.provider_health(),
            "accounts": accounts,
            "worker": jobs.read_heartbeat(),
        }


@app.get("/api/analytics")
def analytics():
    """Real metrics only. No synthesised views or engagement figures."""
    with session_scope() as session:
        clips_total = session.query(func.count(Clip.id)).scalar() or 0
        published = session.query(func.count(Clip.id)).filter(
            Clip.publish_status == "published").scalar() or 0
        failed_uploads = session.query(func.count(Clip.id)).filter(
            Clip.publish_status == "failed").scalar() or 0

        by_platform = dict(session.execute(
            select(Clip.published_platform, func.count())
            .filter(Clip.published_platform.isnot(None))
            .group_by(Clip.published_platform)).all())

        by_category = dict(session.execute(
            select(Clip.category, func.count()).group_by(Clip.category)).all())

        avg_score = session.query(func.avg(Clip.score)).scalar()
        avg_duration = session.query(func.avg(Clip.duration_seconds)).scalar()

        durations = session.execute(
            select(Job.duration_seconds).filter(
                Job.status == "completed",
                Job.duration_seconds.isnot(None))).scalars().all()
        durations = [float(d) for d in durations]

        # Views are only available through an authorized API. The YouTube
        # Data API would need per-clip tracking, which is reported as
        # unavailable rather than invented.
        metrics_available = {
            "views": False,
            "engagement": False,
            "note": ("View and engagement figures are only available through "
                     "an authorized YouTube Analytics or Instagram Insights "
                     "connection. No such connection is configured, so these "
                     "are not reported."),
        }

        return {
            "clips_generated": clips_total,
            "clips_published": published,
            "failed_uploads": failed_uploads,
            "published_by_platform": by_platform,
            "clips_by_category": by_category,
            "average_ai_score": round(float(avg_score), 2) if avg_score else None,
            "average_clip_seconds": (round(float(avg_duration), 1)
                                     if avg_duration else None),
            "processing_time": {
                "count": len(durations),
                "average_seconds": (round(sum(durations) / len(durations), 1)
                                    if durations else None),
                "total_seconds": round(sum(durations), 1) if durations else None,
                "min_seconds": round(min(durations), 1) if durations else None,
                "max_seconds": round(max(durations), 1) if durations else None,
            },
            "metrics_available": metrics_available,
        }


# --- AI configuration -------------------------------------------------------

@app.get("/api/ai/status")
def ai_status():
    """Provider health and current model."""
    from providers import adapter
    health = ai.provider_health()
    health["adapter"] = adapter.status()
    health["default_model"] = config.DEFAULT_AI_MODEL
    health["default_provider"] = config.DEFAULT_AI_PROVIDER
    health["semantic_search_enabled"] = False
    health["semantic_note"] = (
        "Groq publishes no embedding model, so semantic search stays off. "
        "Keyword search remains available in the upstream engine.")
    return health


@app.post("/api/ai/test")
def ai_test(_: None = Depends(security.require_token)):
    """Run one real provider request and report the outcome."""
    return ai.provider_health()


@app.post("/api/ai/config")
def ai_config(payload: dict, _: None = Depends(security.require_token)):
    """Save the AI provider selection.

    Only non-secret configuration is stored. The API key itself stays in
    the local credential file.
    """
    with session_scope() as session:
        row = session.query(Setting).filter(Setting.key == "ai").one_or_none()
        values = dict(row.value) if row and row.value else {}
        for key in ("provider", "model", "fallback_provider", "enabled"):
            if key in payload:
                values[key] = payload[key]
        if row is None:
            session.add(Setting(key="ai", value=values))
        else:
            row.value = values
        session.flush()
        return {"saved": True, "ai": values,
                "note": ("The API key is read from the local credential file "
                         "and is never returned by this API.")}


# --- tasks ------------------------------------------------------------------

@app.get("/api/tasks")
def list_tasks():
    with session_scope() as session:
        tasks = session.execute(
            select(Task).order_by(Task.created_at.desc())).scalars().all()
        return {"tasks": [_task_dict(task) for task in tasks]}


@app.post("/api/tasks")
def create_task(payload: TaskCreate, _: None = Depends(security.require_token)):
    """Create a task configuration."""
    if payload.source_type != "upload" and not payload.source_url:
        raise HTTPException(
            status_code=400,
            detail="A source URL is required for this source type.")
    if payload.source_type in ("youtube_channel", "youtube_playlist") \
            and not payload.rights_confirmed:
        raise HTTPException(
            status_code=400,
            detail=("Automated ingestion of a remote channel requires an "
                    "explicit rights confirmation. Confirm that you hold the "
                    "rights to download and republish this content."))
    if payload.min_clip_seconds > payload.max_clip_seconds:
        raise HTTPException(
            status_code=400,
            detail="Minimum clip duration cannot exceed the maximum.")

    data = payload.model_dump()
    with session_scope() as session:
        task = Task(**data)
        session.add(task)
        session.flush()
        return {"task": _task_dict(task)}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return {"task": _task_dict(task)}


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate,
                _: None = Depends(security.require_token)):
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(task, key, value)
        session.flush()
        return {"task": _task_dict(task)}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, _: None = Depends(security.require_token)):
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        session.delete(task)
        return {"deleted": True}


@app.post("/api/tasks/{task_id}/run")
def run_task(task_id: int, _: None = Depends(security.require_token)):
    """Queue a task for processing."""
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        source = task.source_url
        if not source:
            raise HTTPException(
                status_code=400,
                detail="This task has no source. Attach a video file or a URL.")
        options = pipeline.build_options(task)
        job_id = jobs.enqueue("process", source=source, options=options,
                              task_id=task.id)
        return {"job_id": job_id, "status": "queued"}


# --- uploads ----------------------------------------------------------------

@app.post("/api/videos/upload")
async def upload_video(
    file: UploadFile = File(...),
    task_id: int | None = Form(default=None),
    _: None = Depends(security.require_token),
):
    """Accept a local video upload and queue it for processing."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use MP4, MKV, WebM, MOV, M4V or AVI.")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = _safe_filename(file.filename)
    target = config.VIDEO_DIR / f"{stamp}-{safe}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)

    size = target.stat().st_size
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # Validate that the file is actually a readable video before it is
    # queued. Without this a corrupt or truncated upload is accepted,
    # a job is created, and the failure only surfaces minutes later as
    # an opaque ffprobe error in the queue. Rejecting it here gives an
    # immediate, actionable message.
    try:
        probe = pipeline.probe(str(target))
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=(f"That file could not be read as a video ({exc}). "
                    "The upload may be truncated or corrupt.")) from exc

    duration = probe.get("duration")
    if duration is not None and float(duration) <= 0:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="That video has no readable duration. It may be corrupt.")

    # Duplicate guard: the same file submitted twice would produce the
    # same clips twice. The hash is of the content, not the name, so a
    # renamed copy is caught too.
    digest = _file_digest(target)

    options = None
    if task_id:
        with session_scope() as session:
            task = session.get(Task, task_id)
            if task is not None:
                options = pipeline.build_options(task)
    if options is None:
        options = pipeline.build_options({})

    with session_scope() as session:
        existing = session.query(Video).filter(
            Video.content_hash == digest).one_or_none()
        if existing is not None:
            target.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail=("This exact file has already been uploaded "
                        f"(video {existing.id}). Its clips are already in "
                        "the library."))

        video = Video(title=safe, source=str(target), source_type="upload",
                      size_bytes=size, content_hash=digest)
        session.add(video)
        session.flush()
        job_id = jobs.enqueue("process", source=str(target), options=options,
                              task_id=task_id, video_id=video.id)
        return {"video_id": video.id, "job_id": job_id, "status": "queued",
                "filename": safe, "size_bytes": size}


# --- channels ----------------------------------------------------------------

@app.get("/api/channels")
def list_channels():
    with session_scope() as session:
        channels = session.execute(
            select(Channel).order_by(Channel.created_at.desc())).scalars().all()
        result = []
        for channel in channels:
            episodes = session.query(func.count(Episode.id)).filter(
                Episode.channel_id == channel.id).scalar() or 0
            processed = session.query(func.count(Episode.id)).filter(
                Episode.channel_id == channel.id,
                Episode.processed_at.isnot(None)).scalar() or 0
            result.append(_channel_dict(channel, episodes, processed))
        return {"channels": result}


@app.post("/api/channels")
def create_channel(payload: ChannelCreate,
                   _: None = Depends(security.require_token)):
    """Add a channel to monitor.

    The channel's identity is resolved and then validated against
    YouTube's own RSS feed, so a channel is never reported as connected
    unless YouTube actually confirms it. The name YouTube reports is
    preferred over the caller's label, because the dashboard must show
    the real channel name.
    """
    try:
        identity = monitor.resolve_channel_identity(payload.url)
    except monitor.MonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    channel_id = identity["channel_id"]

    with session_scope() as session:
        existing = session.query(Channel).filter(
            Channel.channel_id == channel_id).one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="That channel is already being monitored.")

        channel = Channel(
            name=identity.get("name") or payload.name or channel_id,
            channel_id=channel_id,
            channel_url=payload.url,
            handle=identity.get("handle") or None,
            description=identity.get("description", ""),
            thumbnail_url=identity.get("thumbnail_url"),
            check_interval_minutes=payload.check_interval_minutes,
            monitoring=True,
            paused=False,
            next_check_at=monitor.next_check_time(payload.check_interval_minutes),
        )
        session.add(channel)
        session.flush()
        return {"channel": _channel_dict(channel),
                "resolved_via": identity.get("resolved_via"),
                "validated": identity.get("validated"),
                "recent_count": identity.get("recent_count")}


@app.patch("/api/channels/{channel_id}")
def update_channel(channel_id: int, payload: ChannelUpdate,
                   _: None = Depends(security.require_token)):
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found.")
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(channel, key, value)
        if "check_interval_minutes" in data or "paused" in data:
            if channel.paused:
                channel.next_check_at = None
            else:
                channel.next_check_at = monitor.next_check_time(
                    channel.check_interval_minutes)
        session.flush()
        return {"channel": _channel_dict(channel)}


@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: int, _: None = Depends(security.require_token)):
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found.")
        session.delete(channel)
        return {"deleted": True}


@app.post("/api/channels/{channel_id}/check")
def check_channel(channel_id: int, _: None = Depends(security.require_token)):
    """Check a channel now for new episodes."""
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found.")
        channel_id_value = channel.channel_id
        interval = channel.check_interval_minutes

    try:
        uploads = monitor.fetch_recent_uploads(channel_id_value)
    except monitor.MonitorError as exc:
        with session_scope() as session:
            channel = session.get(Channel, channel_id)
            if channel is not None:
                channel.last_error = str(exc)
                channel.last_error_at = _now()
                channel.next_check_at = monitor.next_check_time(interval)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    added = 0
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        for upload in uploads:
            video_id = upload.get("video_id")
            if not video_id:
                continue
            # Duplicate guard: a video id already known is never added again.
            existing = session.query(Episode).filter(
                Episode.video_id == video_id).one_or_none()
            if existing is not None:
                # The episode is already known, so it is never re-added and
                # never re-processed. Any metadata that the feed now
                # supplies but that was missing when it was first recorded
                # (a thumbnail, for instance) is filled in, because that is
                # discovery metadata and not a processing decision.
                #
                # Nothing about the authorisation state is touched here.
                # A monitoring re-check must never silently grant or
                # revoke permission to process a video.
                if upload.get("thumbnail_url") and not existing.thumbnail_url:
                    existing.thumbnail_url = upload["thumbnail_url"]
                if upload.get("title") and not existing.title:
                    existing.title = upload["title"]
                if upload.get("url") and not existing.url:
                    existing.url = upload["url"]
                continue
            session.add(Episode(
                channel_id=channel_id,
                video_id=video_id,
                title=upload.get("title", ""),
                url=upload.get("url")
                or f"https://www.youtube.com/watch?v={video_id}",
                published_at=monitor.parse_published(upload.get("published_at")),
                thumbnail_url=upload.get("thumbnail_url") or None,
            ))
            added += 1
        if channel is not None:
            channel.last_checked_at = _now()
            channel.last_error = None
            channel.last_error_at = None
            channel.next_check_at = monitor.next_check_time(interval)
            session.flush()

    return {"checked": True, "new_episodes": added,
            "uploads_seen": len(uploads)}


@app.get("/api/episodes")
def list_episodes(channel_id: int | None = Query(default=None),
                  limit: int = Query(default=100, ge=1, le=500)):
    with session_scope() as session:
        query = select(Episode).order_by(Episode.detected_at.desc())
        if channel_id is not None:
            query = query.where(Episode.channel_id == channel_id)
        episodes = session.execute(query.limit(limit)).scalars().all()
        return {"episodes": [{
            "id": episode.id,
            "channel_id": episode.channel_id,
            "video_id": episode.video_id,
            "title": episode.title,
            "url": episode.url,
            "published_at": episode.published_at,
            "detected_at": episode.detected_at,
            "processed_at": episode.processed_at,
            "source_file": episode.source_file,
            # Detection is not permission. An episode that has not been
            # authorised is shown as awaiting an authorised source and is
            # never downloaded automatically.
            "authorization_state": episode.authorization_state
            or "awaiting_authorization",
            "authorization_note": episode.authorization_note or "",
            "thumbnail_url": episode.thumbnail_url,
            "duration_seconds": episode.duration_seconds,
        } for episode in episodes]}


@app.patch("/api/episodes/{episode_id}")
def update_episode(episode_id: int, payload: EpisodeUpdate,
                   _: None = Depends(security.require_token)):
    """Record the authorisation decision for a detected upload.

    Only an authorised episode may be turned into a processing job. The
    decision and the reason are stored, so the distinction between
    "detected" and "allowed to process" is auditable.
    """
    with session_scope() as session:
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="Episode not found.")
        episode.authorization_state = payload.authorization_state
        episode.authorization_note = payload.note or ""
        session.flush()
        return {"episode": {
            "id": episode.id,
            "video_id": episode.video_id,
            "title": episode.title,
            "authorization_state": episode.authorization_state,
            "authorization_note": episode.authorization_note or "",
        }}


# --- library (videos) ---------------------------------------------------------

@app.get("/api/videos")
def list_videos():
    with session_scope() as session:
        videos = session.execute(
            select(Video).order_by(Video.created_at.desc())).scalars().all()
        return {"videos": [{
            "id": video.id,
            "title": video.title,
            "source_type": video.source_type,
            "source": video.source,
            "duration_seconds": video.duration_seconds,
            "width": video.width,
            "height": video.height,
            "size_bytes": video.size_bytes,
            "project_id": video.project_id,
            "created_at": video.created_at,
        } for video in videos]}


# --- queue -------------------------------------------------------------------

@app.get("/api/jobs")
def list_jobs(status: str | None = Query(default=None), limit: int = 50):
    with session_scope() as session:
        query = select(Job).order_by(Job.created_at.desc()).limit(limit)
        if status:
            query = query.where(Job.status == status)
        job_rows = session.execute(query).scalars().all()
        return {"jobs": [_job_dict(job) for job in job_rows],
                "counts": jobs.counts()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    """Return one job, including the clips it produced.

    The clips are included so a finished job can show what it actually
    generated, with a working preview for each one.
    """
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        data = _job_dict(job, include_clips=True)
        video = session.get(Video, job.video_id) if job.video_id else None
        data["video"] = {
            "id": video.id,
            "title": video.title,
            "source": video.source,
            "source_type": video.source_type,
            "duration_seconds": video.duration_seconds,
            "width": video.width,
            "height": video.height,
            "size_bytes": video.size_bytes,
        } if video is not None else None
        return data


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int, _: None = Depends(security.require_token)):
    ok = jobs.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"cancelled": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int, _: None = Depends(security.require_token)):
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        if job.status == "running":
            raise HTTPException(
                status_code=409, detail="This job is already running.")
        job.status = "queued"
        job.error = None
        job.started_at = None
        job.finished_at = None
        session.flush()
        return {"requeued": True}


# --- clips ---------------------------------------------------------------------

@app.get("/api/clips")
def list_clips(approval: str | None = Query(default=None),
               publish_status: str | None = Query(default=None),
               task_id: int | None = Query(default=None),
               job_id: int | None = Query(default=None),
               search: str | None = Query(default=None, max_length=200),
               sort: str = Query(default="newest"),
               limit: int = Query(default=200, ge=1, le=1000)):
    """List the clip library, with the filters and sorts the UI offers.

    ``sort`` accepts: ``newest`` (the default, and the V1 behaviour),
    ``oldest``, ``score``, ``longest`` and ``shortest``.
    """
    orderings = {
        "newest": Clip.created_at.desc(),
        "oldest": Clip.created_at.asc(),
        "score": Clip.score.desc(),
        "longest": Clip.duration_seconds.desc(),
        "shortest": Clip.duration_seconds.asc(),
    }
    if sort not in orderings:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sort '{sort}'. Use one of: "
                   + ", ".join(sorted(orderings)))

    with session_scope() as session:
        query = select(Clip)
        if approval:
            query = query.where(Clip.approval_status == approval)
        if publish_status:
            query = query.where(Clip.publish_status == publish_status)
        if task_id is not None:
            query = query.where(Clip.task_id == task_id)
        if job_id is not None:
            query = query.where(Clip.job_id == job_id)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                (Clip.title.ilike(pattern))
                | (Clip.transcript.ilike(pattern))
                | (Clip.category.ilike(pattern)))
        query = query.order_by(orderings[sort])
        clips = session.execute(query.limit(limit)).scalars().all()
        return {"clips": [_clip_dict(clip) for clip in clips],
                "sort": sort,
                "count": len(clips)}


@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: int):
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(status_code=404, detail="Clip not found.")
        history = session.query(ApprovalEvent).filter(
            ApprovalEvent.clip_id == clip_id).order_by(
            ApprovalEvent.created_at.desc()).all()
        publications = session.query(Publication).filter(
            Publication.clip_id == clip_id).order_by(
            Publication.created_at.desc()).all()
        return {
            "clip": _clip_dict(clip),
            "approval_history": [{
                "id": event.id,
                "action": event.action,
                "actor": event.actor,
                "note": event.note,
                "created_at": event.created_at,
            } for event in history],
            "publications": [{
                "id": publication.id,
                "platform": publication.platform,
                "status": publication.status,
                "external_id": publication.external_id,
                "error": publication.error,
                "created_at": publication.created_at,
            } for publication in publications],
        }


@app.patch("/api/clips/{clip_id}")
def update_clip(clip_id: int, payload: ClipUpdate,
                _: None = Depends(security.require_token)):
    """Edit a clip's metadata, approval state, or re-render it."""
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(status_code=404, detail="Clip not found.")

        data = payload.model_dump(exclude_unset=True)
        rerender = data.pop("rerender", False)
        status = data.pop("approval_status", None)

        for key, value in data.items():
            if value is not None:
                setattr(clip, key, value)

        if status is not None and status != clip.approval_status:
            clip.approval_status = status
            if status == "approved":
                clip.approved_at = _now()
                clip.rejected_at = None
            elif status == "rejected":
                clip.rejected_at = _now()
                clip.approved_at = None
            session.add(ApprovalEvent(clip_id=clip.id, action=status,
                                      actor="local-user"))

        if rerender:
            if not clip.file_path:
                raise HTTPException(
                    status_code=400, detail="This clip has no rendered file.")
            video = session.get(Video, clip.video_id) if clip.video_id else None
            if video is None or not video.source:
                raise HTTPException(
                    status_code=400,
                    detail="The original source for this clip is unavailable, "
                           "so it cannot be re-rendered.")
            # The word timings live in the original project's transcript.
            transcript_path = None
            if video.project_id:
                candidate = (config.PROJECT_DIR / video.project_id
                             / "transcript.json")
                if candidate.is_file():
                    transcript_path = candidate
            out_dir = config.CLIP_DIR / f"clip-{clip.id}"
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                output = pipeline.rerender(
                    video.source,
                    clip.start_seconds, clip.end_seconds,
                    {"aspect": "9:16", "style": clip.caption_style,
                     "loudnorm": True}, out_dir, transcript_path)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=500,
                    detail=f"Re-render failed: {exc}") from exc
            clip.file_path = str(output)
            poster = output.with_suffix(".png")
            if poster.is_file():
                clip.poster_path = str(poster)
            srt = output.with_suffix(".srt")
            if srt.is_file():
                clip.srt_path = str(srt)

        session.flush()
        return {"clip": _clip_dict(clip)}


@app.post("/api/clips/batch")
def batch_clip_action(payload: BatchApproval,
                      _: None = Depends(security.require_token)):
    """Approve or reject several clips at once."""
    # The request uses the verbs "approve"/"reject"; the stored status
    # uses "approved"/"rejected". Writing the verb straight into the
    # column would leave the clip in a state that publishing -- which
    # requires approval_status == "approved" -- would never accept.
    status = "approved" if payload.action == "approve" else "rejected"

    updated = []
    with session_scope() as session:
        for clip_id in payload.clip_ids:
            clip = session.get(Clip, clip_id)
            if clip is None:
                continue
            clip.approval_status = status
            if status == "approved":
                clip.approved_at = _now()
                clip.rejected_at = None
            else:
                clip.rejected_at = _now()
                clip.approved_at = None
            session.add(ApprovalEvent(clip_id=clip.id, action=payload.action,
                                      actor="local-user"))
            updated.append(clip_id)
        session.flush()
    return {"updated": updated, "count": len(updated), "action": payload.action}


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: int):
    """Download the rendered clip file."""
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None or not clip.file_path:
            raise HTTPException(status_code=404, detail="Clip file not found.")
        path = Path(clip.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Clip file is missing.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/clips/{clip_id}/srt")
def download_srt(clip_id: int):
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None or not clip.srt_path:
            raise HTTPException(status_code=404, detail="Subtitles not found.")
        path = Path(clip.srt_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Subtitles are missing.")
    return PlainTextResponse(path.read_text(encoding="utf-8"),
                             media_type="text/plain")


# --- publishing ---------------------------------------------------------------

@app.get("/api/accounts")
def list_accounts():
    """Connection state for every publishing platform."""
    with session_scope() as session:
        return {"accounts": {
            name: publishing.account_state(session, name)
            for name in ("youtube", "instagram")
        }}


@app.get("/api/accounts/youtube/connect")
def youtube_connect_link():
    """Return the Google OAuth consent URL."""
    import secrets as _secrets
    state = _secrets.token_urlsafe(24)
    try:
        url = publishing.youtube_authorize_url(state)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"url": url}


@app.get("/api/accounts/youtube/callback")
def youtube_callback(code: str = Query(...), state: str | None = Query(default=None)):
    """OAuth redirect target for YouTube."""
    try:
        with session_scope() as session:
            state_data = publishing.youtube_connect(session, code, state)
    except publishing.PublishError as exc:
        return HTMLResponse(
            f"<h1>YouTube connection failed</h1><p>{exc}</p>"
            "<p><a href='/accounts'>Back to the app</a></p>",
            status_code=400)
    return RedirectResponse("/accounts?connected=youtube")


@app.get("/api/accounts/instagram/connect")
def instagram_connect_link():
    import secrets as _secrets
    state = _secrets.token_urlsafe(24)
    try:
        url = publishing.instagram_authorize_url(state)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"url": url}


@app.get("/api/accounts/instagram/callback")
def instagram_callback(code: str = Query(...),
                       state: str | None = Query(default=None)):
    try:
        with session_scope() as session:
            publishing.instagram_connect(session, code)
    except publishing.PublishError as exc:
        return HTMLResponse(
            f"<h1>Instagram connection failed</h1><p>{exc}</p>"
            "<p><a href='/accounts'>Back to the app</a></p>",
            status_code=400)
    return RedirectResponse("/accounts?connected=instagram")


@app.post("/api/accounts/{platform}/disconnect")
def disconnect_account(platform: str, _: None = Depends(security.require_token)):
    if platform not in ("youtube", "instagram"):
        raise HTTPException(status_code=400, detail="Unknown platform.")
    with session_scope() as session:
        account = session.query(Account).filter(
            Account.platform == platform).one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail="Not connected.")
        account.access_token = None
        account.refresh_token = None
        account.token_expiry = None
        account.connected = False
        session.flush()
        return {"disconnected": True, "platform": platform}


@app.post("/api/publish")
def publish_clips(payload: PublishRequest,
                  _: None = Depends(security.require_token)):
    """Publish approved clips to a platform.

    Only approved clips are published. Anything else is reported as
    skipped rather than silently ignored.
    """
    results = []
    with session_scope() as session:
        for clip_id in payload.clip_ids:
            clip = session.get(Clip, clip_id)
            if clip is None:
                results.append({"clip_id": clip_id, "status": "missing"})
                continue
            if clip.approval_status != "approved":
                results.append({
                    "clip_id": clip_id, "status": "skipped",
                    "detail": "Only approved clips can be published.",
                })
                continue
            if clip.publish_status == "published" \
                    and clip.published_platform == payload.platform:
                results.append({"clip_id": clip_id, "status": "already_published",
                                "video_id": clip.published_video_id})
                continue

            publication = Publication(
                clip_id=clip.id, platform=payload.platform, status="pending")
            session.add(publication)
            session.flush()

            try:
                if payload.platform == "youtube":
                    outcome = publishing.youtube_publish(
                        session, clip, title=payload.title,
                        description=payload.description,
                        privacy_status=payload.privacy_status,
                        tags=[t.strip() for t in (clip.hashtags or "").split()
                              if t.strip()])
                else:
                    outcome = publishing.instagram_publish(
                        session, clip, caption=payload.description,
                        title=payload.title)
            except publishing.PublishError as exc:
                publication.status = "failed"
                publication.error = str(exc)
                clip.publish_status = "failed"
                clip.publish_error = str(exc)
                results.append({"clip_id": clip_id, "status": "failed",
                                "error": str(exc)})
                continue

            publication.status = "published"
            publication.external_id = outcome.get("video_id", "")
            publication.privacy_status = payload.privacy_status
            clip.publish_status = "published"
            clip.published_at = _now()
            clip.published_platform = payload.platform
            clip.published_video_id = outcome.get("video_id", "")
            clip.publish_error = None
            results.append({"clip_id": clip_id, "status": "published",
                            **outcome})
        session.flush()

    return {"results": results}


@app.get("/api/publishing/calendar")
def publishing_calendar():
    """Published clips grouped by day, from real rows."""
    with session_scope() as session:
        clips = session.execute(
            select(Clip).filter(Clip.publish_status == "published")
            .order_by(Clip.published_at.desc())).scalars().all()
        grouped: dict = {}
        for clip in clips:
            when = clip.published_at or clip.created_at
            key = when.strftime("%Y-%m-%d")
            grouped.setdefault(key, []).append({
                "clip_id": clip.id,
                "title": clip.title,
                "platform": clip.published_platform,
                "published_at": clip.published_at,
                "external_id": clip.published_video_id,
            })
        return {"calendar": grouped, "total": len(clips)}


# --- storage: backup, restore, cleanup ---------------------------------------

@app.get("/api/storage")
def storage_report():
    """Disk usage per managed directory plus volume free space."""
    return storage.disk_report()


@app.get("/api/storage/backups")
def list_backups():
    """Available database backups, newest first."""
    return {"backups": storage.list_backups()}


@app.post("/api/storage/backup")
def create_backup(_: None = Depends(security.require_token)):
    """Take a consistent snapshot of the database."""
    try:
        return storage.backup_database()
    except storage.StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/storage/restore")
def restore_backup(payload: dict,
                   _: None = Depends(security.require_token)):
    """Restore the database from a backup file.

    The current database is backed up first, so this is reversible.
    """
    path = str(payload.get("path") or "")
    if not path:
        raise HTTPException(status_code=400,
                            detail="A backup path is required.")
    try:
        return storage.restore_database(path)
    except storage.StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/storage/cleanup")
def cleanup_storage(payload: dict,
                    _: None = Depends(security.require_token)):
    """Remove old media. Defaults to a dry run that deletes nothing."""
    keep_days = payload.get("keep_days", 30)
    try:
        keep_days = int(keep_days)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400,
                            detail="keep_days must be a number.") from exc
    dry_run = bool(payload.get("dry_run", True))
    include_published = bool(payload.get("include_published", False))
    try:
        result = storage.cleanup(keep_days=keep_days, dry_run=dry_run,
                                 include_published=include_published)
    except storage.StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["logs"] = storage.trim_logs(keep_days=keep_days)
    return result


# --- settings -------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    with session_scope() as session:
        ai_row = session.query(Setting).filter(Setting.key == "ai").one_or_none()
        disk = shutil.disk_usage(str(config.DATA_DIR))
        return {
            "app": _settings(session),
            "ai": dict(ai_row.value) if ai_row and ai_row.value else {},
            "disk": {
                "total": disk.total, "used": disk.used, "free": disk.free,
                "free_gb": round(disk.free / 1024 ** 3, 2),
            },
            "directories": {
                "data": str(config.DATA_DIR),
                "videos": str(config.VIDEO_DIR),
                "clips": str(config.CLIP_DIR),
                "exports": str(config.EXPORT_DIR),
                "logs": str(config.LOG_DIR),
            },
            "publishing_enabled": config.PUBLISHING_ENABLED,
        }


@app.patch("/api/settings")
def update_settings(payload: SettingsUpdate,
                    _: None = Depends(security.require_token)):
    with session_scope() as session:
        current = _settings(session)
        current.update(payload.settings)
        saved = _save_settings(session, current)
        session.flush()
        return {"settings": saved}


@app.get("/api/logs")
def read_logs(lines: int = Query(default=200, ge=1, le=2000)):
    """Read the application log tail. Credentials are never written there."""
    log_file = config.LOG_DIR / "app.log"
    if not log_file.is_file():
        return {"lines": []}
    text = log_file.read_text(encoding="utf-8", errors="replace")
    return {"lines": text.splitlines()[-lines:]}


# --- media serving ---------------------------------------------------------------

@app.get("/media/clip/{clip_id}")
def serve_clip(clip_id: int, request: Request):
    """Serve a rendered clip for preview playback.

    This implements the HTTP byte-range protocol properly. Starlette's
    ``FileResponse`` sets an ``Accept-Ranges`` header but ignores the
    ``Range`` header, which means a browser cannot seek inside a clip --
    it has to download the whole file first. With real range support the
    player can jump straight to a timestamp.

    The body is streamed in chunks, so a large clip is never held in
    memory in full.
    """
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None or not clip.file_path:
            raise HTTPException(status_code=404, detail="Clip not found.")
        raw_path = clip.file_path

    try:
        path = media.resolve_media_path(raw_path)
    except media.MediaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type = media.media_type_for(path)
    size = path.stat().st_size
    range_header = request.headers.get("range")

    try:
        window = media.parse_range(range_header, size)
    except media.RangeNotSatisfiable as exc:
        return Response(
            status_code=416,
            content=str(exc),
            media_type="text/plain",
            headers={"Content-Range": f"bytes */{size}",
                     "Accept-Ranges": "bytes"},
        )

    if window is None:
        return StreamingResponse(
            media.iter_file(path),
            media_type=media_type,
            headers={"Accept-Ranges": "bytes",
                     "Content-Length": str(size),
                     "Cache-Control": "no-cache"},
        )

    start, end = window
    return StreamingResponse(
        media.iter_file(path, start, end),
        status_code=206,
        media_type=media_type,
        headers={"Accept-Ranges": "bytes",
                 "Content-Range": f"bytes {start}-{end}/{size}",
                 "Content-Length": str(end - start + 1),
                 "Cache-Control": "no-cache"},
    )


@app.get("/media/clip/{clip_id}/poster")
def serve_poster(clip_id: int):
    """Serve the clip's poster, generating it from the clip if needed.

    A real frame is extracted with FFmpeg and cached beside the clip, so
    the library shows the actual video rather than a generic
    placeholder. If extraction genuinely fails the request is a 404 and
    the UI draws its own fallback.
    """
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(status_code=404, detail="Clip not found.")
        poster_path = clip.poster_path
        clip_path = clip.file_path
        duration = clip.duration_seconds

    if poster_path:
        try:
            path = media.resolve_media_path(poster_path)
        except media.MediaError:
            path = None
        if path is not None and path.is_file():
            return FileResponse(path, media_type="image/png",
                                headers={"Cache-Control": "no-cache"})

    if clip_path:
        try:
            video = media.resolve_media_path(clip_path)
        except media.MediaError:
            video = None
        if video is not None:
            target = video.with_suffix(".png")
            generated = media.extract_poster(video, target, duration)
            if generated is not None:
                with session_scope() as session:
                    clip = session.get(Clip, clip_id)
                    if clip is not None:
                        clip.poster_path = str(generated)
                return FileResponse(generated, media_type="image/png",
                                    headers={"Cache-Control": "no-cache"})

    raise HTTPException(status_code=404, detail="Poster not found.")


@app.post("/api/clips/{clip_id}/poster")
def regenerate_poster(clip_id: int,
                      _: None = Depends(security.require_token)):
    """Regenerate a clip's poster frame from the rendered video."""
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is None:
            raise HTTPException(status_code=404, detail="Clip not found.")
        clip_path = clip.file_path
        duration = clip.duration_seconds
    if not clip_path:
        raise HTTPException(status_code=400,
                            detail="This clip has no rendered video.")
    try:
        video = media.resolve_media_path(clip_path)
    except media.MediaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    generated = media.extract_poster(video, video.with_suffix(".png"), duration)
    if generated is None:
        raise HTTPException(
            status_code=500,
            detail="A poster frame could not be extracted from this clip.")
    with session_scope() as session:
        clip = session.get(Clip, clip_id)
        if clip is not None:
            clip.poster_path = str(generated)
        session.flush()
        return {"poster_path": str(generated)}


# --- live updates ------------------------------------------------------------------

@app.get("/api/events")
async def events(request: Request):
    """Server-Sent Events stream of job status changes."""
    async def generator():
        last = None
        while True:
            if await request.is_disconnected():
                break
            counts_now = jobs.counts()
            if counts_now != last:
                last = counts_now
                payload = json.dumps({"jobs": counts_now,
                                      "time": _now().isoformat()})
                yield f"data: {payload}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --- frontend ---------------------------------------------------------------------

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        return HTMLResponse("<h1>VIRALCLIPS AI</h1><p>Frontend missing.</p>",
                             status_code=500)
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/{page}", response_class=HTMLResponse)
def spa(page: str):
    """Serve the single-page app for any client-side route."""
    if page.startswith(("api/", "media/", "static/", "docs", "redoc")):
        raise HTTPException(status_code=404, detail="Not found.")
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))

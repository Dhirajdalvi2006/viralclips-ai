"""Standalone background worker.

This runs as its own OS process, separate from the API. That separation is
the point: closing the browser tab must not stop processing, and neither
must restarting the API. The two processes share only the SQLite
database, so the queue survives either of them restarting.

Run it with::

    .venv\\Scripts\\python.exe worker.py

The worker:

- claims queued jobs one at a time (concurrency is configurable),
- records live progress on every job row,
- retries a failed job up to the configured attempt limit,
- honours cancellation requests,
- checks free disk space before starting,
- writes a heartbeat file so the API can report worker health,
- shuts down gracefully on Ctrl+C or SIGTERM.
"""
from __future__ import annotations

import argparse
import atexit
import datetime as dt
import json
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from viralclips_app import config, jobs, pipeline  # noqa: E402
from viralclips_app.db import init_db, session_scope  # noqa: E402
from viralclips_app.models import Clip, Episode, Job, Video  # noqa: E402

LOGGER = logging.getLogger("viralclips.worker")

_STOP = False

#: The worker records its own PID so stop.bat can stop exactly this
#: process without touching unrelated Python or Node processes.
PID_FILE = config.DATA_DIR / "worker.pid"


def _write_pid() -> None:
    config.ensure_dirs()
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _remove_pid() -> None:
    try:
        if PID_FILE.is_file() and PID_FILE.read_text(
                encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def _handle_signal(signum, _frame):
    """Ask the worker loop to stop after the current job."""
    global _STOP
    _STOP = True
    LOGGER.info("Signal %s received. Shutting down after the current job.",
                signum)


def setup_logging() -> None:
    """Send logs to both the console and the application log file."""
    config.ensure_dirs()
    log_file = config.LOG_DIR / "app.log"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def free_disk_bytes() -> int:
    """Free bytes on the volume holding the data directory."""
    return shutil.disk_usage(str(config.DATA_DIR)).free


def disk_gate_message() -> str | None:
    """Return a message when there is not enough free disk to work.

    Kept separate from the worker loop so the gate can be exercised
    directly. Returns ``None`` when there is enough space.
    """
    free = free_disk_bytes()
    if free >= config.MIN_FREE_DISK_BYTES:
        return None
    return (f"Not enough free disk space "
            f"({free / 1024 ** 3:.1f} GB free, "
            f"{config.MIN_FREE_DISK_BYTES / 1024 ** 3:.1f} GB "
            f"required).")


def run_process_job(job: dict) -> None:
    """Process one video job and store the resulting clips."""
    job_id = job["id"]
    source = job["source"]
    options = job.get("options") or {}

    jobs.update_progress(job_id, "starting", detail=source)
    LOGGER.info("Job %s: processing %s", job_id, source)

    def progress(stage: str):
        jobs.update_progress(job_id, stage, detail=stage)

    result = pipeline.process(source, options, progress=progress)

    if result.status == "failed":
        raise RuntimeError(result.error or "Processing failed.")

    # Persist the video record and the clips.
    with session_scope() as session:
        video = None
        if job.get("video_id"):
            video = session.get(Video, job["video_id"])
        if video is None:
            video = Video(
                title=Path(source).name,
                source=source,
                source_type="upload" if Path(source).is_file() else "remote",
                project_id=result.project_id,
            )
            session.add(video)
            session.flush()

        video.project_id = result.project_id
        video.source_type = video.source_type or "upload"

        # Fill in the real media properties. The dashboard shows these,
        # so they have to come from the file rather than being guessed.
        if video.duration_seconds is None or video.width is None:
            try:
                meta = pipeline.probe(source)
                video.duration_seconds = meta.get("duration")
                video.width = meta.get("width")
                video.height = meta.get("height")
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Could not probe %s: %s", source, exc)

        for clip_result in result.clips:
            clip = Clip(
                video_id=video.id,
                task_id=job.get("task_id"),
                job_id=job_id,
                index=clip_result.index,
                start_seconds=clip_result.start,
                end_seconds=clip_result.end,
                duration_seconds=clip_result.duration,
                score=clip_result.score,
                heuristic_score=clip_result.heuristic_score,
                ai_adjustment=clip_result.ai_adjustment,
                ai_model=clip_result.ai_model,
                ai_provider=(result.ai_provider if result.ai_used else None),
                reason=clip_result.reason,
                transcript=clip_result.transcript,
                title=clip_result.title,
                description=clip_result.description,
                hashtags=" ".join(clip_result.hashtags),
                caption_style=options.get("style", "default"),
                # --- V2 intelligence ---
                signals=dict(clip_result.signals or {}),
                score_kind=clip_result.score_kind or "estimated",
                explanation=clip_result.explanation or "",
                intelligence_source=clip_result.intelligence_source,
                suggested_title=clip_result.suggested_title,
                suggested_description=clip_result.suggested_description,
                suggested_hashtags=clip_result.suggested_hashtags,
                file_path=clip_result.file_path,
                poster_path=clip_result.poster_path,
                srt_path=clip_result.srt_path,
                meta_path=clip_result.meta_path,
                approval_status="pending",
                publish_status="not_published",
            )
            session.add(clip)
        session.flush()

        # Mark the episode as processed so it is never queued twice.
        if job.get("episode_id"):
            episode = session.get(Episode, job["episode_id"])
            if episode is not None:
                episode.processed_at = dt.datetime.now(dt.timezone.utc)
                episode.source_file = source

    if result.ai_used:
        LOGGER.info(
            "Job %s: complete. %s clip(s). AI reranked by %s (%s).",
            job_id, len(result.clips), result.ai_provider, result.ai_model)
    else:
        reason = result.ai_error or "the provider did not respond"
        LOGGER.info(
            "Job %s: complete. %s clip(s). Heuristic scoring only -- no AI "
            "reranking (%s).", job_id, len(result.clips), reason)

    # The intelligence layer is reported separately from the upstream
    # reranker, because they are different things: the reranker adjusts
    # scores, the intelligence layer chooses the moments.
    if result.intelligence_used:
        LOGGER.info(
            "Job %s: intelligence analysis by %s (%s).",
            job_id, result.intelligence_provider, result.intelligence_model)
    elif result.intelligence_error:
        LOGGER.info(
            "Job %s: intelligence analysis fell back to offline signals (%s).",
            job_id, result.intelligence_error)

    jobs.update_progress(job_id, "complete",
                         done=len(result.clips), total=len(result.clips))


def run_publish_job(job: dict) -> None:
    """Publish an approved clip."""
    from viralclips_app import publishing
    from viralclips_app.models import Clip as ClipModel

    job_id = job["id"]
    options = job.get("options") or {}
    platform = options.get("platform", "youtube")
    clip_id = job.get("clip_id")

    jobs.update_progress(job_id, "publishing", detail=platform)
    with session_scope() as session:
        clip = session.get(ClipModel, clip_id) if clip_id else None
        if clip is None:
            raise RuntimeError("The clip for this publish job no longer exists.")
        if clip.approval_status != "approved":
            raise RuntimeError("Only approved clips can be published.")
        if platform == "youtube":
            outcome = publishing.youtube_publish(session, clip)
        else:
            outcome = publishing.instagram_publish(session, clip)
        clip.publish_status = "published"
        clip.published_at = dt.datetime.now(dt.timezone.utc)
        clip.published_platform = platform
        clip.published_video_id = outcome.get("video_id", "")
        clip.publish_error = None
        session.flush()

    LOGGER.info("Job %s: published to %s.", job_id, platform)
    jobs.update_progress(job_id, "complete")


def run_channel_check_job(job: dict) -> None:
    """Check a monitored channel for new episodes."""
    from viralclips_app import monitor
    from viralclips_app.models import Channel

    job_id = job["id"]
    channel_db_id = job.get("clip_id") or (job.get("options") or {}).get(
        "channel_db_id")
    if not channel_db_id:
        raise RuntimeError("No channel was named for this check.")

    jobs.update_progress(job_id, "checking", detail=str(channel_db_id))
    with session_scope() as session:
        channel = session.get(Channel, channel_db_id)
        if channel is None:
            raise RuntimeError("The channel no longer exists.")
        external_id = channel.channel_id
        interval = channel.check_interval_minutes

    uploads = monitor.fetch_recent_uploads(external_id)

    added = 0
    with session_scope() as session:
        channel = session.get(Channel, channel_db_id)
        for upload in uploads:
            video_id = upload.get("video_id")
            if not video_id:
                continue
            existing = session.query(Episode).filter(
                Episode.video_id == video_id).one_or_none()
            if existing is not None:
                continue
            session.add(Episode(
                channel_id=channel_db_id,
                video_id=video_id,
                title=upload.get("title", ""),
                url=f"https://www.youtube.com/watch?v={video_id}",
                published_at=monitor.parse_published(upload.get("published_at")),
            ))
            added += 1
        if channel is not None:
            channel.last_checked_at = dt.datetime.now(dt.timezone.utc)
            channel.last_error = None
            channel.next_check_at = monitor.next_check_time(interval)
            session.flush()

    LOGGER.info("Job %s: channel check found %s new episode(s).",
                job_id, added)
    jobs.update_progress(job_id, "complete", done=added, total=added)


HANDLERS = {
    "process": run_process_job,
    "publish": run_publish_job,
    "channel_check": run_channel_check_job,
}


def schedule_due_channel_checks() -> None:
    """Queue a check job for every channel whose next check is due."""
    from viralclips_app.models import Channel

    with session_scope() as session:
        now = dt.datetime.now(dt.timezone.utc)
        due = session.execute(
            select(Channel).where(
                Channel.monitoring.is_(True),
                Channel.paused.is_(False),
                (Channel.next_check_at.is_(None))
                | (Channel.next_check_at <= now),
            )).scalars().all()

        pending = session.query(Job).filter(
            Job.kind == "channel_check",
            Job.status.in_(("queued", "running"))).all()
        pending_channels = {
            str((job.options or {}).get("channel_db_id")) for job in pending}

        for channel in due:
            # Duplicate-job prevention: skip if a check is already queued.
            if str(channel.id) in pending_channels:
                continue
            jobs.enqueue("channel_check", source=channel.channel_id,
                         options={"channel_db_id": channel.id})
            channel.next_check_at = monitor_next(channel.check_interval_minutes)
            LOGGER.info("Scheduled a channel check for %s", channel.name)


def monitor_next(interval_minutes: int) -> dt.datetime:
    """Return the next check time for a channel."""
    from viralclips_app import monitor
    return monitor.next_check_time(interval_minutes)


def recover_stale_jobs() -> None:
    """Requeue jobs that were running when the worker stopped.

    This is the startup recovery the brief asks for: a job left in
    ``running`` by a crash is put back on the queue rather than being
    stranded forever.
    """
    with session_scope() as session:
        stale = session.query(Job).filter(Job.status == "running").all()
        for job in stale:
            job.status = "queued"
            job.started_at = None
            job.error = "Requeued after the worker restarted."
            LOGGER.info("Recovered job %s from a previous run.", job.id)


def main() -> int:
    parser = argparse.ArgumentParser(description="VIRALCLIPS AI worker")
    parser.add_argument("--once", action="store_true",
                        help="Process a single job then exit.")
    parser.add_argument("--poll-interval", type=float,
                        default=config.WORKER_POLL_INTERVAL)
    args = parser.parse_args()

    setup_logging()
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (AttributeError, ValueError):
        pass

    config.ensure_dirs()
    init_db()
    _write_pid()
    atexit.register(_remove_pid)
    recover_stale_jobs()

    LOGGER.info("Worker started (pid %s). Poll interval %.1fs.",
                os.getpid(), args.poll_interval)
    jobs.write_heartbeat("idle")

    while not _STOP:
        try:
            schedule_due_channel_checks()
            job = jobs.claim_next()
            if job is None:
                jobs.write_heartbeat("idle")
                time.sleep(args.poll_interval)
                continue

            jobs.write_heartbeat("busy", current_job=job["id"],
                                 detail=job.get("source", ""))
            handler = HANDLERS.get(job["kind"])
            if handler is None:
                jobs.fail(job["id"], f"Unknown job kind: {job['kind']}",
                          retry=False)
                continue

            message = disk_gate_message()
            if message:
                LOGGER.warning("Job %s deferred: %s", job["id"], message)
                jobs.fail(job["id"], message, retry=False)
                continue

            try:
                handler(job)
                jobs.complete(job["id"])
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Job %s failed: %s", job["id"], exc)
                status = jobs.fail(job["id"], str(exc))
                LOGGER.info("Job %s moved to status %s.", job["id"], status)

            jobs.write_heartbeat("idle")
            if args.once:
                break
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Worker loop error: %s", exc)
            time.sleep(max(args.poll_interval, 5))

    LOGGER.info("Worker stopped.")
    jobs.write_heartbeat("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Job queue helpers.

The queue lives in the SQLite database, so it survives an API restart, a
worker restart, and a closed browser tab. The API process enqueues; the
separate worker process claims and runs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
from pathlib import Path

from sqlalchemy import select

from . import config
from .db import session_scope
from .models import Job

#: Set by the worker process so the API can report worker health.
WORKER_HEARTBEAT_FILE = config.DATA_DIR / "worker_heartbeat.json"


def enqueue(kind: str, source: str = "", options: dict | None = None, *,
            task_id: int | None = None, video_id: int | None = None,
            episode_id: int | None = None, clip_id: int | None = None,
            max_attempts: int | None = None) -> int:
    """Add a job to the queue. Returns the job id."""
    with session_scope() as session:
        job = Job(
            kind=kind,
            status="queued",
            source=source,
            options=options or {},
            task_id=task_id,
            video_id=video_id,
            episode_id=episode_id,
            clip_id=clip_id,
            max_attempts=max_attempts if max_attempts is not None
            else config.MAX_JOB_ATTEMPTS,
        )
        session.add(job)
        session.flush()
        return job.id


def claim_next() -> dict | None:
    """Claim the next queued job, atomically.

    Returns a plain dict describing the job, or None when the queue is
    empty. The claim is written inside a transaction so two workers can
    never take the same job.
    """
    with session_scope() as session:
        job = session.execute(
            select(Job).where(Job.status == "queued")
            .order_by(Job.created_at).limit(1)).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.started_at = dt.datetime.now(dt.timezone.utc)
        job.attempts += 1
        session.flush()
        return {
            "id": job.id,
            "kind": job.kind,
            "source": job.source,
            "options": job.options or {},
            "task_id": job.task_id,
            "video_id": job.video_id,
            "episode_id": job.episode_id,
            "clip_id": job.clip_id,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
        }


def update_progress(job_id: int, stage: str, done: int = 0, total: int = 0,
                    detail: str = "") -> None:
    """Record progress on a running job."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.progress_stage = stage
        job.progress_done = done
        job.progress_total = total
        job.progress_detail = detail[:500]


def complete(job_id: int, result: dict | None = None) -> None:
    """Mark a job finished successfully."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "completed"
        job.finished_at = dt.datetime.now(dt.timezone.utc)
        job.error = None
        if job.started_at:
            started = job.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=dt.timezone.utc)
            job.duration_seconds = (
                dt.datetime.now(dt.timezone.utc) - started).total_seconds()


def fail(job_id: int, error: str, retry: bool = True) -> str:
    """Mark a job failed, optionally requeueing it for a retry.

    Returns the resulting status.
    """
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return "missing"
        job.error = error[:2000]
        job.finished_at = dt.datetime.now(dt.timezone.utc)
        if retry and job.attempts < job.max_attempts:
            job.status = "queued"
            job.started_at = None
            job.finished_at = None
            job.error = f"Attempt {job.attempts} failed: {error[:1000]}"
            return "queued"
        job.status = "failed"
        return "failed"


def cancel(job_id: int) -> bool:
    """Request cancellation of a job.

    A queued job is cancelled immediately. A running job is flagged so the
    worker stops it at the next checkpoint.
    """
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return False
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = dt.datetime.now(dt.timezone.utc)
        return True


def is_cancelled(job_id: int) -> bool:
    """True when cancellation was requested for a job."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        return bool(job and job.cancel_requested)


def counts() -> dict:
    """Return a count of jobs by status."""
    from sqlalchemy import func
    with session_scope() as session:
        rows = session.execute(
            select(Job.status, func.count()).group_by(Job.status)).all()
    result = {status: 0 for status in
              ("queued", "running", "completed", "failed", "cancelled")}
    for status, count in rows:
        result[status] = count
    return result


# --- worker heartbeat -----------------------------------------------------

def write_heartbeat(state: str, current_job: int | None = None,
                    detail: str = "") -> None:
    """Record that a worker is alive and what it is doing."""
    payload = {
        "state": state,
        "current_job": current_job,
        "detail": detail[:400],
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    try:
        WORKER_HEARTBEAT_FILE.write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def read_heartbeat() -> dict | None:
    """Return the worker heartbeat, or None when no worker has run."""
    if not WORKER_HEARTBEAT_FILE.is_file():
        return None
    try:
        return json.loads(WORKER_HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

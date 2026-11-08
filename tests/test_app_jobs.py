"""Tests for the job queue and the worker lifecycle.

The queue is the mechanism that makes background processing survive a
closed browser tab, an API restart, and a worker restart. These tests
exercise it directly.
"""
from __future__ import annotations

import datetime as dt

from viralclips_app import jobs
from viralclips_app.db import session_scope
from viralclips_app.models import Job


def test_enqueue_creates_a_queued_job():
    job_id = jobs.enqueue("process", source="C:/tmp/a.mp4",
                          options={"aspect": "9:16"})
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job is not None
        assert job.kind == "process"
        assert job.status == "queued"
        assert job.source == "C:/tmp/a.mp4"
        assert job.options["aspect"] == "9:16"
        assert job.attempts == 0


def test_claim_next_takes_the_oldest_job():
    first = jobs.enqueue("process", source="first")
    second = jobs.enqueue("process", source="second")
    claimed = jobs.claim_next()
    assert claimed is not None
    assert claimed["id"] == first
    assert claimed["source"] == "first"
    assert claimed["attempts"] == 1
    with session_scope() as active:
        assert active.get(Job, second).status == "queued"


def test_claim_next_returns_none_on_an_empty_queue():
    assert jobs.claim_next() is None


def test_a_claimed_job_cannot_be_claimed_again():
    jobs.enqueue("process", source="only")
    first = jobs.claim_next()
    second = jobs.claim_next()
    assert first is not None
    assert second is None


def test_claim_marks_the_job_running_and_stamps_the_start():
    job_id = jobs.enqueue("process", source="x")
    jobs.claim_next()
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "running"
        assert job.started_at is not None


def test_complete_records_the_duration():
    job_id = jobs.enqueue("process", source="x")
    jobs.claim_next()
    jobs.complete(job_id)
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "completed"
        assert job.finished_at is not None
        assert job.duration_seconds is not None
        assert job.duration_seconds >= 0
        assert job.error is None


def test_fail_requeues_until_the_attempt_limit():
    job_id = jobs.enqueue("process", source="x", max_attempts=2)
    jobs.claim_next()
    status = jobs.fail(job_id, "first failure")
    assert status == "queued"
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "queued"
        assert job.attempts == 1
        assert "first failure" in job.error

    jobs.claim_next()
    status = jobs.fail(job_id, "second failure")
    assert status == "failed"
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "failed"
        assert job.attempts == 2


def test_fail_without_retry_parks_the_job():
    job_id = jobs.enqueue("process", source="x")
    jobs.claim_next()
    status = jobs.fail(job_id, "permanent", retry=False)
    assert status == "failed"
    with session_scope() as active:
        assert active.get(Job, job_id).status == "failed"


def test_cancel_marks_a_queued_job_cancelled_immediately():
    job_id = jobs.enqueue("process", source="x")
    assert jobs.cancel(job_id) is True
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "cancelled"
        assert job.cancel_requested is True


def test_cancel_flags_a_running_job_without_changing_status():
    job_id = jobs.enqueue("process", source="x")
    jobs.claim_next()
    assert jobs.cancel(job_id) is True
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "running"
        assert job.cancel_requested is True
    assert jobs.is_cancelled(job_id) is True


def test_cancel_on_a_missing_job_returns_false():
    assert jobs.cancel(999999) is False


def test_update_progress_is_recorded():
    job_id = jobs.enqueue("process", source="x")
    jobs.update_progress(job_id, "transcribing", done=1, total=3,
                         detail="working")
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.progress_stage == "transcribing"
        assert job.progress_done == 1
        assert job.progress_total == 3
        assert job.progress_detail == "working"


def test_update_progress_on_a_missing_job_is_a_no_op():
    jobs.update_progress(999999, "stage")


def test_counts_reports_every_status():
    jobs.enqueue("process", source="a")
    jobs.enqueue("process", source="b")
    jobs.enqueue("process", source="c")
    jobs.claim_next()
    counts = jobs.counts()
    assert counts["queued"] == 2
    assert counts["running"] == 1
    assert counts["completed"] == 0
    assert set(counts) == {"queued", "running", "completed", "failed",
                           "cancelled"}


def test_heartbeat_round_trip():
    jobs.write_heartbeat("busy", current_job=7, detail="working")
    heartbeat = jobs.read_heartbeat()
    assert heartbeat is not None
    assert heartbeat["state"] == "busy"
    assert heartbeat["current_job"] == 7
    assert heartbeat["detail"] == "working"
    assert "pid" in heartbeat
    assert "updated_at" in heartbeat


def test_heartbeat_on_a_missing_file_returns_none():
    import viralclips_app.jobs as module

    original = module.WORKER_HEARTBEAT_FILE
    module.WORKER_HEARTBEAT_FILE = original.with_name("no-such-heartbeat.json")
    try:
        assert module.read_heartbeat() is None
    finally:
        module.WORKER_HEARTBEAT_FILE = original


def test_recover_stale_jobs_requeues_running_work():
    """A job left running by a crash must not be stranded."""
    import worker

    job_id = jobs.enqueue("process", source="x")
    jobs.claim_next()
    with session_scope() as active:
        assert active.get(Job, job_id).status == "running"

    worker.recover_stale_jobs()

    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "queued"
        assert job.started_at is None
        assert "restart" in (job.error or "").lower()


def test_worker_handlers_cover_every_job_kind():
    import worker

    assert set(worker.HANDLERS) == {"process", "publish", "channel_check"}


def test_worker_pid_file_is_removed_on_exit():
    import worker

    worker._write_pid()
    assert worker.PID_FILE.is_file()
    worker._remove_pid()
    assert not worker.PID_FILE.exists()


def test_free_disk_bytes_is_positive():
    import worker

    assert worker.free_disk_bytes() > 0


def test_duplicate_channel_checks_are_not_scheduled_twice():
    """The scheduler must not queue a second check for one channel."""
    import worker
    from viralclips_app.models import Channel

    with session_scope() as active:
        channel = Channel(name="c", channel_id="UC1", channel_url="u",
                          monitoring=True, paused=False,
                          next_check_at=dt.datetime.now(dt.timezone.utc)
                          - dt.timedelta(minutes=1))
        active.add(channel)
        active.flush()
        channel_id = channel.id

    worker.schedule_due_channel_checks()
    worker.schedule_due_channel_checks()

    with session_scope() as active:
        checks = active.query(Job).filter(Job.kind == "channel_check").all()
        assert len(checks) == 1
        assert checks[0].options["channel_db_id"] == channel_id


def test_paused_channels_are_not_checked():
    import worker
    from viralclips_app.models import Channel

    with session_scope() as active:
        active.add(Channel(name="c", channel_id="UC2", channel_url="u",
                            monitoring=True, paused=True,
                            next_check_at=dt.datetime.now(dt.timezone.utc)
                            - dt.timedelta(minutes=1)))
    worker.schedule_due_channel_checks()
    with session_scope() as active:
        assert active.query(Job).filter(Job.kind == "channel_check").count() == 0

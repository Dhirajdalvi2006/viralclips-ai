"""Tests for the application database layer.

Covers the models, the reentrant session scope, and the WAL/journal
settings that let the API and the worker share one SQLite file.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import inspect, select

from viralclips_app import config
from viralclips_app.db import engine, session_scope
from viralclips_app.models import (Account, Channel, Clip, Episode, Job,
                                   Task, Video)


def test_expected_tables_exist():
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    for expected in ("tasks", "channels", "episodes", "videos", "clips",
                     "jobs", "publications", "accounts", "approval_events",
                     "settings"):
        assert expected in names, f"missing table {expected}"


def test_wal_and_pragmas_are_enabled():
    with engine.connect() as connection:
        mode = connection.exec_driver_sql(
            "PRAGMA journal_mode").scalar()
        foreign_keys = connection.exec_driver_sql(
            "PRAGMA foreign_keys").scalar()
    assert str(mode).lower() == "wal"
    assert foreign_keys == 1


def test_session_scope_commits_on_success():
    with session_scope() as active:
        active.add(Task(name="committed", source_type="upload"))
    with session_scope() as active:
        assert active.query(Task).filter_by(name="committed").count() == 1


def test_session_scope_rolls_back_on_error():
    with pytest.raises(ValueError):
        with session_scope() as active:
            active.add(Task(name="rolled back", source_type="upload"))
            raise ValueError("boom")
    with session_scope() as active:
        assert active.query(Task).filter_by(name="rolled back").count() == 0


def test_session_scope_is_reentrant():
    """A nested scope must not open a second connection.

    SQLite permits one writer. A nested scope that opened its own
    connection would deadlock against the outer transaction's write
    lock, so the nested scope has to share the outer session.
    """
    with session_scope() as outer:
        outer.add(Task(name="outer", source_type="upload"))
        outer.flush()
        with session_scope() as inner:
            assert inner is outer
            inner.add(Task(name="inner", source_type="upload"))
            inner.flush()
        # The inner write is visible before the outer commit.
        assert outer.query(Task).filter_by(name="inner").count() == 1
    with session_scope() as active:
        assert active.query(Task).filter_by(name="outer").count() == 1
        assert active.query(Task).filter_by(name="inner").count() == 1


def test_nested_failure_marks_the_outer_scope_failed():
    """An error in a nested scope must roll back the whole transaction.

    The nested scope cannot commit on its own, so it has to record
    that the transaction is doomed and let the outermost scope roll
    everything back.
    """
    with session_scope() as outer:
        outer.add(Task(name="outer keeps", source_type="upload"))
        outer.flush()
        with pytest.raises(ValueError):
            with session_scope() as inner:
                inner.add(Task(name="inner keeps", source_type="upload"))
                inner.flush()
                raise ValueError("nested failure")

    with session_scope() as active:
        # The outer scope saw the nested failure, so it rolled back too.
        assert active.query(Task).filter_by(name="outer keeps").count() == 0
        assert active.query(Task).filter_by(name="inner keeps").count() == 0


def test_task_defaults():
    with session_scope() as active:
        task = Task(name="defaults", source_type="upload")
        active.add(task)
        active.flush()
        assert task.aspect_ratio == "9:16"
        assert task.caption_style == "default"
        assert task.num_clips == 3
        assert task.require_approval is True
        assert task.auto_publish is False
        assert task.rights_confirmed is False
        assert task.created_at is not None


def test_clip_relationships_resolve():
    with session_scope() as active:
        task = Task(name="rel", source_type="upload")
        active.add(task)
        active.flush()
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        job = Job(kind="process", status="queued", source="C:/tmp/v.mp4")
        active.add(job)
        active.flush()
        clip = Clip(video_id=video.id, task_id=task.id, job_id=job.id,
                    index=0, start_seconds=0.0, end_seconds=5.0,
                    duration_seconds=5.0, score=5.0)
        active.add(clip)
        active.flush()
        assert clip.video.title == "v"
        assert clip.task.name == "rel"
        assert clip.job.kind == "process"


def test_video_content_hash_is_indexed():
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("videos")}
    assert "content_hash" in columns
    indexes = {tuple(ix["column_names"]) for ix in
               inspector.get_indexes("videos")}
    assert ("content_hash",) in indexes


def test_job_defaults_and_json_column():
    with session_scope() as active:
        job = Job(kind="process", status="queued", source="x",
                  options={"aspect": "9:16"})
        active.add(job)
        active.flush()
        assert job.attempts == 0
        assert job.max_attempts == config.MAX_JOB_ATTEMPTS
        assert job.options["aspect"] == "9:16"
        assert job.cancel_requested is False


def test_channel_and_episode_relationship():
    with session_scope() as active:
        channel = Channel(name="c", channel_id="UC123", channel_url="u")
        active.add(channel)
        active.flush()
        episode = Episode(channel_id=channel.id, video_id="vid1",
                          title="ep", url="https://y/watch?v=vid1")
        active.add(episode)
        active.flush()
        assert episode.channel.channel_id == "UC123"
        assert episode.processed_at is None


def test_account_stores_tokens_in_dedicated_columns():
    """The account row holds tokens in dedicated columns only.

    The API layer is responsible for never returning them; that
    contract is checked in the API tests.
    """
    with session_scope() as active:
        account = Account(platform="youtube", external_id="me",
                          display_name="Test",
                          access_token="secret-token-value",
                          refresh_token="secret-refresh-value")
        active.add(account)
        active.flush()
        assert account.access_token == "secret-token-value"
        assert account.connected is False
        assert account.platform == "youtube"


def test_clip_score_defaults_are_numeric():
    with session_scope() as active:
        video = Video(title="v2", source="C:/tmp/v2.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=1.0,
                    end_seconds=2.0, duration_seconds=1.0, score=7.5)
        active.add(clip)
        active.flush()
        assert clip.score == 7.5
        assert clip.approval_status == "pending"
        assert clip.publish_status == "not_published"


def test_timestamp_mixin_sets_both_timestamps():
    with session_scope() as active:
        task = Task(name="ts", source_type="upload")
        active.add(task)
        active.flush()
        assert isinstance(task.created_at, dt.datetime)
        assert isinstance(task.updated_at, dt.datetime)


def test_query_by_status_returns_only_matching_rows():
    with session_scope() as active:
        active.add(Job(kind="process", status="queued", source="a"))
        active.add(Job(kind="process", status="failed", source="b"))
        active.flush()
    with session_scope() as active:
        queued = active.execute(
            select(Job).where(Job.status == "queued")).scalars().all()
        assert len(queued) == 1
        assert queued[0].source == "a"

"""Database models.

Every number the dashboard shows comes from one of these tables. There is
no hardcoded or synthesised metric anywhere in the application.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# --- sources and tasks ----------------------------------------------------

class Task(Base, TimestampMixin):
    """A reusable processing task configuration."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="general")

    # Source configuration
    source_type: Mapped[str] = mapped_column(String(32), default="upload")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)

    # Processing settings
    num_clips: Mapped[int] = mapped_column(Integer, default=3)
    min_clip_seconds: Mapped[int] = mapped_column(Integer, default=15)
    max_clip_seconds: Mapped[int] = mapped_column(Integer, default=90)
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="9:16")
    resolution: Mapped[str] = mapped_column(String(16), default="1080x1920")
    caption_style: Mapped[str] = mapped_column(String(64), default="default")
    language: Mapped[str] = mapped_column(String(16), default="en")
    min_score: Mapped[float] = mapped_column(Float, default=0.0)
    whisper_model: Mapped[str] = mapped_column(String(32), default="tiny")
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Automation settings
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    monitor_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    auto_process_new_episodes: Mapped[bool] = mapped_column(Boolean,
                                                              default=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)

    # Rights attestation. The brief is explicit that a public channel URL
    # is not permission to download and republish, so remote channel
    # ingestion requires the user to confirm they hold the rights.
    rights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_note: Mapped[str] = mapped_column(Text, default="")

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    clips: Mapped[list["Clip"]] = relationship(back_populates="task")
    jobs: Mapped[list["Job"]] = relationship(back_populates="task")


class Channel(Base, TimestampMixin):
    """A monitored YouTube channel."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(120), nullable=False,
                                            unique=True)
    channel_url: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    monitoring: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)

    #: The channel's public handle, e.g. "@indiasgotlatentofficial".
    #: Kept for display only -- the id is the identity.
    handle: Mapped[str | None] = mapped_column(String(160), nullable=True)

    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    next_check_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)

    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("channel_id", name="uq_channel_id"),)


class Episode(Base, TimestampMixin):
    """A video detected on a monitored channel."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    video_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(400), default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False)

    # Set when the episode has been turned into a processing job. This is
    # the duplicate guard: an episode already processed is never queued
    # again.
    processed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Whether this upload may be processed. Detection is not permission:
    #: a public channel gives no right to download, edit or republish.
    #: "awaiting_authorization" | "authorized" | "not_authorized"
    authorization_state: Mapped[str] = mapped_column(
        String(32), default="awaiting_authorization")
    authorization_note: Mapped[str] = mapped_column(Text, default="")

    channel: Mapped[Channel] = relationship(back_populates="episodes")

    __table_args__ = (UniqueConstraint("video_id", name="uq_episode_video_id"),)


class Video(Base, TimestampMixin):
    """An ingested source video."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(400), default="")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="upload")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: SHA-256 of the uploaded file. Used to refuse a duplicate upload of
    #: the same content, which would otherwise produce duplicate clips.
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True)
    episode_id: Mapped[int | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)

    clips: Mapped[list["Clip"]] = relationship(back_populates="video")


class Clip(Base, TimestampMixin):
    """A rendered vertical clip produced by the pipeline."""

    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    index: Mapped[int] = mapped_column(Integer, default=0)
    start_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    end_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    score: Mapped[float] = mapped_column(Float, default=0.0)
    heuristic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_adjustment: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: The provider that produced the score ("groq", "openrouter", ...).
    #: Null means the clip was scored heuristically without an AI.
    ai_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    ai_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    category: Mapped[str] = mapped_column(String(64), default="general")
    transcript: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")
    caption_style: Mapped[str] = mapped_column(String(64), default="default")

    # --- V2 intelligence -------------------------------------------------
    #: The individual signal scores behind the overall score, e.g.
    #: {"hook_strength": 71.0, "comedy_potential": 44.0, ...}. Storing
    #: the components is what makes the score explainable: the result
    #: can be recomputed from them, and the UI can show why a clip won.
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    #: "estimated" for every intelligence score. There is no "measured"
    #: value unless the user supplies authorised analytics, and this
    #: application never invents one.
    score_kind: Mapped[str] = mapped_column(String(32), default="estimated")
    #: Why this moment was selected, in one or two sentences.
    explanation: Mapped[str] = mapped_column(Text, default="")
    #: Where the intelligence came from: "ai" or "heuristic". Null means
    #: the clip predates the V2 layer.
    intelligence_source: Mapped[str | None] = mapped_column(String(32),
                                                            nullable=True)
    #: Suggestions from the intelligence layer. These are kept separate
    #: from title/description/hashtags so a reviewer's own wording is
    #: never overwritten by a later analysis.
    suggested_title: Mapped[str | None] = mapped_column(String(400),
                                                        nullable=True)
    suggested_description: Mapped[str | None] = mapped_column(Text,
                                                              nullable=True)
    suggested_hashtags: Mapped[str | None] = mapped_column(Text,
                                                            nullable=True)

    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    srt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "pending" | "approved" | "rejected"
    approval_status: Mapped[str] = mapped_column(String(32), default="pending")
    approved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    rejected_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)

    # "not_published" | "queued" | "published" | "failed"
    publish_status: Mapped[str] = mapped_column(String(32),
                                                 default="not_published")
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    published_platform: Mapped[str | None] = mapped_column(String(32),
                                                            nullable=True)
    published_video_id: Mapped[str | None] = mapped_column(String(200),
                                                            nullable=True)
    publish_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    video: Mapped[Video | None] = relationship(back_populates="clips")
    task: Mapped[Task | None] = relationship(back_populates="clips")
    # Clips and jobs reference each other in both directions (clip.job_id
    # and job.clip_id), so the join condition has to be explicit.
    job: Mapped["Job | None"] = relationship(
        back_populates="clips",
        foreign_keys=[job_id])


class ApprovalEvent(Base, TimestampMixin):
    """Audit trail of every approval decision."""

    __tablename__ = "approval_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clip_id: Mapped[int] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), default="local-user")
    note: Mapped[str] = mapped_column(Text, default="")


class Job(Base, TimestampMixin):
    """A unit of work for the background worker."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="process")
    status: Mapped[str] = mapped_column(String(32), default="queued")

    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    episode_id: Mapped[int | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)
    clip_id: Mapped[int | None] = mapped_column(
        ForeignKey("clips.id", ondelete="SET NULL"), nullable=True)

    source: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    progress_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_detail: Mapped[str] = mapped_column(Text, default="")

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    task: Mapped[Task | None] = relationship(back_populates="jobs")
    clips: Mapped[list[Clip]] = relationship(
        back_populates="job",
        foreign_keys="Clip.job_id")


class Account(Base, TimestampMixin):
    """A connected social account (YouTube or Instagram).

    Tokens are stored here and never leave the backend.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False,
                                           unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    external_id: Mapped[str] = mapped_column(String(200), default="")
    channel_title: Mapped[str] = mapped_column(String(200), default="")
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expiry: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base, TimestampMixin):
    """Key/value application settings."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class Publication(Base, TimestampMixin):
    """A record of one publish attempt."""

    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clip_id: Mapped[int] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    privacy_status: Mapped[str] = mapped_column(String(32), default="public")

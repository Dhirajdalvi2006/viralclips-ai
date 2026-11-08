"""Pydantic request and response models for the API."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator


# --- tasks -----------------------------------------------------------------

class TaskBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = "general"

    source_type: str = "upload"
    source_url: str | None = None
    channel_id: int | None = None

    num_clips: int = Field(default=3, ge=1, le=50)
    min_clip_seconds: int = Field(default=15, ge=5, le=600)
    max_clip_seconds: int = Field(default=90, ge=10, le=1800)
    aspect_ratio: str = "9:16"
    resolution: str = "1080x1920"
    caption_style: str = "default"
    language: str = "en"
    min_score: float = Field(default=0.0, ge=0.0, le=10.0)
    whisper_model: str = "tiny"
    ai_model: str | None = None

    monitor_enabled: bool = False
    monitor_interval_minutes: int = Field(default=60, ge=1, le=1440)
    auto_process_new_episodes: bool = False
    require_approval: bool = True
    auto_publish: bool = False

    rights_confirmed: bool = False
    rights_note: str = ""

    enabled: bool = True

    @field_validator("aspect_ratio")
    @classmethod
    def _check_aspect(cls, value: str) -> str:
        if value not in ("9:16", "16:9", "1:1"):
            raise ValueError("Aspect ratio must be 9:16, 16:9 or 1:1.")
        return value

    @field_validator("source_type")
    @classmethod
    def _check_source(cls, value: str) -> str:
        allowed = {"upload", "youtube_video", "youtube_channel", "youtube_playlist"}
        if value not in allowed:
            raise ValueError(f"Source type must be one of {sorted(allowed)}.")
        return value

    @field_validator("min_clip_seconds", "max_clip_seconds")
    @classmethod
    def _positive(cls, value: int) -> int:
        return value


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    channel_id: int | None = None
    num_clips: int | None = Field(default=None, ge=1, le=50)
    min_clip_seconds: int | None = Field(default=None, ge=5, le=600)
    max_clip_seconds: int | None = Field(default=None, ge=10, le=1800)
    aspect_ratio: str | None = None
    resolution: str | None = None
    caption_style: str | None = None
    language: str | None = None
    min_score: float | None = Field(default=None, ge=0.0, le=10.0)
    whisper_model: str | None = None
    ai_model: str | None = None
    monitor_enabled: bool | None = None
    monitor_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    auto_process_new_episodes: bool | None = None
    require_approval: bool | None = None
    auto_publish: bool | None = None
    rights_confirmed: bool | None = None
    rights_note: str | None = None
    enabled: bool | None = None


# --- channels ---------------------------------------------------------------

class ChannelCreate(BaseModel):
    url: str = Field(min_length=3, max_length=1000)
    name: str | None = None
    check_interval_minutes: int = Field(default=60, ge=1, le=1440)


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    monitoring: bool | None = None
    paused: bool | None = None
    check_interval_minutes: int | None = Field(default=None, ge=1, le=1440)


# --- clips ------------------------------------------------------------------

class ClipUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=400)
    description: str | None = None
    hashtags: str | None = None
    caption_style: str | None = None
    approval_status: str | None = None
    category: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    rerender: bool = False

    @field_validator("approval_status")
    @classmethod
    def _check_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in ("pending", "approved", "rejected"):
            raise ValueError("Approval status must be pending, approved or rejected.")
        return value


class BatchApproval(BaseModel):
    clip_ids: list[int] = Field(min_length=1)
    action: str = "approve"

    @field_validator("action")
    @classmethod
    def _check_action(cls, value: str) -> str:
        if value not in ("approve", "reject"):
            raise ValueError("Action must be approve or reject.")
        return value


class PublishRequest(BaseModel):
    platform: str
    clip_ids: list[int] = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    privacy_status: str = "public"

    @field_validator("platform")
    @classmethod
    def _check_platform(cls, value: str) -> str:
        if value not in ("youtube", "instagram"):
            raise ValueError("Platform must be youtube or instagram.")
        return value


# --- settings ---------------------------------------------------------------

class SettingsUpdate(BaseModel):
    settings: dict[str, Any]


class AIConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    fallback_provider: str | None = None
    enabled: bool | None = None


# --- output -----------------------------------------------------------------

class ClipOut(BaseModel):
    id: int
    video_id: int | None = None
    task_id: int | None = None
    job_id: int | None = None
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    score: float
    heuristic_score: float | None = None
    ai_adjustment: float | None = None
    ai_model: str | None = None
    reason: str
    category: str
    transcript: str
    title: str
    description: str
    hashtags: str
    caption_style: str
    file_path: str | None = None
    poster_path: str | None = None
    srt_path: str | None = None
    approval_status: str
    publish_status: str
    published_at: dt.datetime | None = None
    published_platform: str | None = None
    published_video_id: str | None = None
    publish_error: str | None = None
    created_at: dt.datetime

    model_config = {"from_attributes": True}

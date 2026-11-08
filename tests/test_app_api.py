"""Tests for the HTTP API.

These cover the routes, the local token guard, the error handling, and
the rule that every number the dashboard returns comes from the
database rather than from a hardcoded value.
"""
from __future__ import annotations

import json

from viralclips_app.db import session_scope
from viralclips_app.models import Channel, Clip, Episode, Job, Task, Video


# --- health and bootstrap --------------------------------------------------

def test_health_is_public_and_reports_worker_state(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "worker" in body
    assert "disk" in body


def test_bootstrap_returns_the_token_and_config(client):
    body = client.get("/api/bootstrap").json()
    assert body["token"]
    assert body["config"]["api_port"]
    assert body["settings"]


def test_bootstrap_never_leaks_a_credential(client):
    raw = client.get("/api/bootstrap").text
    for marker in ("gsk_", "sk-", "client_secret", "access_token"):
        assert marker not in raw


# --- the token guard --------------------------------------------------------

def test_a_mutation_without_the_token_is_rejected(anon_client):
    response = anon_client.post("/api/tasks", json={"name": "x"})
    assert response.status_code == 403


def test_a_mutation_with_a_wrong_token_is_rejected(client):
    response = client.post("/api/tasks", json={"name": "x"},
                           headers={"X-ViralClips-Token": "wrong"})
    assert response.status_code == 403


def test_reads_do_not_require_the_token(anon_client):
    assert anon_client.get("/api/health").status_code == 200
    assert anon_client.get("/api/overview").status_code == 200
    assert anon_client.get("/api/clips").status_code == 200
    assert anon_client.get("/api/jobs").status_code == 200


# --- tasks ------------------------------------------------------------------

def test_create_and_list_a_task(client):
    response = client.post("/api/tasks", json={
        "name": "My Task", "source_type": "upload", "num_clips": 2,
        "min_clip_seconds": 10, "max_clip_seconds": 40,
    })
    assert response.status_code == 200
    task_id = response.json()["task"]["id"]

    body = client.get("/api/tasks").json()
    assert any(t["id"] == task_id for t in body["tasks"])
    assert body["tasks"][0]["name"] == "My Task"


def test_get_one_task(client):
    task_id = client.post("/api/tasks", json={
        "name": "Single", "source_type": "upload"}).json()["task"]["id"]
    response = client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["task"]["id"] == task_id


def test_get_a_missing_task_is_404(client):
    assert client.get("/api/tasks/999999").status_code == 404


def test_update_a_task(client):
    task_id = client.post("/api/tasks", json={
        "name": "Before", "source_type": "upload"}).json()["task"]["id"]
    response = client.patch(f"/api/tasks/{task_id}",
                            json={"name": "After", "num_clips": 5})
    assert response.status_code == 200
    body = client.get(f"/api/tasks/{task_id}").json()
    assert body["task"]["name"] == "After"
    assert body["task"]["num_clips"] == 5


def test_delete_a_task(client):
    task_id = client.post("/api/tasks", json={
        "name": "Doomed", "source_type": "upload"}).json()["task"]["id"]
    assert client.delete(f"/api/tasks/{task_id}").status_code == 200
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_running_a_task_without_a_source_is_rejected(client):
    task_id = client.post("/api/tasks", json={
        "name": "No Source", "source_type": "upload"}).json()["task"]["id"]
    response = client.post(f"/api/tasks/{task_id}/run")
    assert response.status_code == 400


# --- uploads ----------------------------------------------------------------

def test_upload_rejects_an_unsupported_extension(client):
    response = client.post("/api/videos/upload",
                           files={"file": ("notes.txt", b"hello",
                                           "text/plain")})
    assert response.status_code == 400


def test_upload_rejects_an_empty_file(client):
    response = client.post("/api/videos/upload",
                           files={"file": ("empty.mp4", b"", "video/mp4")})
    assert response.status_code == 400


def test_upload_creates_a_video_and_a_queued_job(client, real_video_bytes):
    response = client.post("/api/videos/upload",
                           files={"file": ("clip.mp4", real_video_bytes,
                                           "video/mp4")})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["video_id"]
    assert body["job_id"]

    with session_scope() as active:
        video = active.get(Video, body["video_id"])
        assert video is not None
        assert video.content_hash
        job = active.get(Job, body["job_id"])
        assert job.status == "queued"
        assert job.kind == "process"


def test_a_duplicate_upload_is_refused(client, real_video_bytes):
    first = client.post("/api/videos/upload",
                        files={"file": ("one.mp4", real_video_bytes,
                                        "video/mp4")})
    assert first.status_code == 200
    second = client.post("/api/videos/upload",
                         files={"file": ("two.mp4", real_video_bytes,
                                         "video/mp4")})
    assert second.status_code == 409
    assert "already" in second.json()["detail"].lower()


# --- jobs -------------------------------------------------------------------

def test_list_jobs_includes_counts(client):
    body = client.get("/api/jobs").json()
    assert "jobs" in body
    assert "counts" in body
    assert body["counts"]["queued"] == 0


def test_get_one_job(client):
    with session_scope() as active:
        job = Job(kind="process", status="queued", source="x")
        active.add(job)
        active.flush()
        job_id = job.id
    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_a_missing_job_is_404(client):
    assert client.get("/api/jobs/999999").status_code == 404


def test_cancel_a_queued_job(client):
    with session_scope() as active:
        job = Job(kind="process", status="queued", source="x")
        active.add(job)
        active.flush()
        job_id = job.id
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    with session_scope() as active:
        assert active.get(Job, job_id).status == "cancelled"


def test_cancel_a_missing_job_is_404(client):
    assert client.post("/api/jobs/999999/cancel").status_code == 404


def test_retry_a_failed_job(client):
    with session_scope() as active:
        job = Job(kind="process", status="failed", source="x", error="boom")
        active.add(job)
        active.flush()
        job_id = job.id
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 200
    with session_scope() as active:
        job = active.get(Job, job_id)
        assert job.status == "queued"
        assert job.error is None


def test_retry_a_running_job_is_rejected(client):
    with session_scope() as active:
        job = Job(kind="process", status="running", source="x")
        active.add(job)
        active.flush()
        job_id = job.id
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


# --- clips ------------------------------------------------------------------

def _make_clip(approval="pending", publish="not_published", ai_model=None,
               ai_provider=None, ai_adjustment=None):
    with session_scope() as active:
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=0.0,
                    end_seconds=10.0, duration_seconds=10.0, score=6.5,
                    approval_status=approval, publish_status=publish,
                    ai_model=ai_model, ai_provider=ai_provider,
                    ai_adjustment=ai_adjustment,
                    title="A clip")
        active.add(clip)
        active.flush()
        return clip.id


def test_list_clips(client):
    clip_id = _make_clip()
    body = client.get("/api/clips").json()
    assert any(c["id"] == clip_id for c in body["clips"])
    assert body["clips"][0]["score"] == 6.5


def test_filter_clips_by_approval(client):
    _make_clip(approval="approved")
    _make_clip(approval="pending")
    body = client.get("/api/clips?approval=approved").json()
    assert len(body["clips"]) == 1
    assert body["clips"][0]["approval_status"] == "approved"


def test_get_one_clip(client):
    clip_id = _make_clip()
    response = client.get(f"/api/clips/{clip_id}")
    assert response.status_code == 200
    assert response.json()["clip"]["id"] == clip_id


def test_get_a_missing_clip_is_404(client):
    assert client.get("/api/clips/999999").status_code == 404


def test_a_corrupt_upload_is_rejected_immediately(client, tmp_path):
    """A file that is not a readable video must be refused at upload.

    Without this check a corrupt file is accepted, a job is created, and
    the failure only surfaces later as an opaque ffprobe error in the
    queue instead of an immediate message to the person uploading.
    """
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a video file" * 400)
    response = client.post(
        "/api/videos/upload",
        files={"file": ("corrupt.mp4", corrupt.read_bytes(), "video/mp4")})
    assert response.status_code == 400
    assert "video" in response.json()["detail"].lower()


def test_a_valid_upload_is_accepted_and_queued(client, real_video_bytes):
    """A real, readable video is accepted and queued for processing."""
    response = client.post(
        "/api/videos/upload",
        files={"file": ("tiny.mp4", real_video_bytes, "video/mp4")})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"]


# --- AI provider attribution -----------------------------------------------

def test_a_clip_reports_its_ai_provider_separately_from_the_model(client):
    """Provider and model are different things and must not be merged.

    ``openai/gpt-oss-120b`` is a model that Groq serves. Reporting the
    model id as the provider name is the bug this test guards against.
    """
    clip_id = _make_clip(ai_model="openai/gpt-oss-120b", ai_provider="groq",
                         ai_adjustment=0.6)
    clip = client.get(f"/api/clips/{clip_id}").json()["clip"]
    assert clip["ai_provider"] == "groq"
    assert clip["ai_model"] == "openai/gpt-oss-120b"
    assert clip["ai_scored"] is True


def test_a_heuristically_scored_clip_reports_no_provider(client):
    """A clip scored without an AI must not claim a provider."""
    clip_id = _make_clip(ai_model=None, ai_provider=None, ai_adjustment=None)
    clip = client.get(f"/api/clips/{clip_id}").json()["clip"]
    assert clip["ai_provider"] is None
    assert clip["ai_scored"] is False


def test_the_overview_attributes_clips_to_their_provider(client):
    _make_clip(ai_model="openai/gpt-oss-120b", ai_provider="groq",
               ai_adjustment=0.6)
    _make_clip(ai_model="openai/gpt-oss-120b", ai_provider="groq",
               ai_adjustment=-0.2)
    totals = client.get("/api/overview").json()["totals"]
    assert totals["ai_scored_clips"] == 2
    assert totals["ai_by_provider"] == {"groq": 2}
    assert totals["ai_by_model"] == {"openai/gpt-oss-120b": 2}


def test_the_overview_does_not_count_heuristic_clips_as_ai_scored(client):
    _make_clip(ai_model=None, ai_provider=None, ai_adjustment=None)
    totals = client.get("/api/overview").json()["totals"]
    assert totals["ai_scored_clips"] == 0
    assert totals["ai_by_provider"] == {}


def test_the_ai_status_endpoint_reports_the_configured_provider(client):
    """The dashboard must name the provider, not the model.

    The isolated test environment has no credential file, so the
    adapter reports no active primary. The configured provider name
    must still be "groq" -- never the model id.
    """
    body = client.get("/api/ai/status").json()
    assert body["provider"] == "groq"
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["default_provider"] == "groq"
    # Without a credential the adapter has no active primary, but the
    # configured provider is still named.
    assert body["adapter"]["primary"] is None
    assert body["key_present"] is False


def test_approve_a_clip(client):
    clip_id = _make_clip()
    response = client.patch(f"/api/clips/{clip_id}",
                            json={"approval_status": "approved"})
    assert response.status_code == 200
    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        assert clip.approval_status == "approved"
        assert clip.approved_at is not None


def test_reject_a_clip(client):
    clip_id = _make_clip()
    response = client.patch(f"/api/clips/{clip_id}",
                            json={"approval_status": "rejected"})
    assert response.status_code == 200
    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        assert clip.approval_status == "rejected"
        assert clip.rejected_at is not None


def test_an_invalid_approval_status_is_rejected(client):
    clip_id = _make_clip()
    response = client.patch(f"/api/clips/{clip_id}",
                            json={"approval_status": "maybe"})
    assert response.status_code == 422


def test_batch_approval(client):
    first = _make_clip()
    second = _make_clip()
    response = client.post("/api/clips/batch", json={
        "clip_ids": [first, second], "action": "approve"})
    assert response.status_code == 200
    with session_scope() as active:
        assert active.get(Clip, first).approval_status == "approved"
        assert active.get(Clip, second).approval_status == "approved"


def test_batch_rejection(client):
    clip_id = _make_clip()
    response = client.post("/api/clips/batch", json={
        "clip_ids": [clip_id], "action": "reject"})
    assert response.status_code == 200
    with session_scope() as active:
        assert active.get(Clip, clip_id).approval_status == "rejected"


def test_batch_with_an_invalid_action_is_rejected(client):
    clip_id = _make_clip()
    response = client.post("/api/clips/batch", json={
        "clip_ids": [clip_id], "action": "explode"})
    assert response.status_code == 422


def test_media_route_returns_404_for_a_missing_clip(client):
    assert client.get("/media/clip/999999").status_code == 404


def test_media_route_serves_an_existing_clip(client, tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not really a video")
    with session_scope() as active:
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=0.0,
                    end_seconds=1.0, duration_seconds=1.0, score=1.0,
                    file_path=str(media))
        active.add(clip)
        active.flush()
        clip_id = clip.id
    response = client.get(f"/media/clip/{clip_id}")
    assert response.status_code == 200
    assert response.content == b"not really a video"


# --- channels ---------------------------------------------------------------

#: A syntactically valid YouTube channel id. The monitor resolves
#: ``/channel/UC...`` URLs without needing a Data API key.
CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
CHANNEL_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}"


def test_create_a_channel(client):
    response = client.post("/api/channels", json={
        "url": CHANNEL_URL,
        "name": "Some Creator", "check_interval_minutes": 30})
    assert response.status_code == 200
    body = response.json()
    assert body["channel"]["check_interval_minutes"] == 30
    assert body["channel"]["monitoring"] is True
    assert body["channel"]["channel_id"] == CHANNEL_ID


def test_adding_the_same_channel_twice_is_rejected(client):
    payload = {"url": CHANNEL_URL}
    assert client.post("/api/channels", json=payload).status_code == 200
    assert client.post("/api/channels", json=payload).status_code == 409


def test_an_invalid_channel_url_is_rejected(client):
    response = client.post("/api/channels", json={"url": "not a url"})
    assert response.status_code == 400


def test_a_playlist_url_is_rejected(client):
    response = client.post("/api/channels", json={
        "url": "https://www.youtube.com/playlist?list=PL123"})
    assert response.status_code == 400
    assert "playlist" in response.json()["detail"].lower()


def test_pause_and_resume_a_channel(client):
    channel_id = client.post("/api/channels", json={
        "url": CHANNEL_URL}).json()["channel"]["id"]

    response = client.patch(f"/api/channels/{channel_id}",
                            json={"paused": True})
    assert response.status_code == 200
    with session_scope() as active:
        assert active.get(Channel, channel_id).paused is True

    client.patch(f"/api/channels/{channel_id}", json={"paused": False})
    with session_scope() as active:
        assert active.get(Channel, channel_id).paused is False


def test_delete_a_channel(client):
    channel_id = client.post("/api/channels", json={
        "url": CHANNEL_URL}).json()["channel"]["id"]
    assert client.delete(f"/api/channels/{channel_id}").status_code == 200
    assert client.get("/api/channels").json()["channels"] == []


def test_checking_a_channel_records_new_episodes(client, monkeypatch):
    """A channel check records newly discovered episodes.

    The feed is stubbed so the test does not depend on the network.
    """
    from viralclips_app import monitor

    uploads = [
        {"video_id": "vid001", "title": "Episode One",
         "published_at": "2026-11-01T10:00:00+00:00"},
        {"video_id": "vid002", "title": "Episode Two",
         "published_at": "2026-11-02T10:00:00+00:00"},
    ]
    monkeypatch.setattr(monitor, "fetch_recent_uploads",
                        lambda channel_id: list(uploads))

    channel_id = client.post("/api/channels", json={
        "url": CHANNEL_URL}).json()["channel"]["id"]
    response = client.post(f"/api/channels/{channel_id}/check")
    assert response.status_code == 200
    assert response.json()["new_episodes"] == 2
    assert response.json()["uploads_seen"] == 2

    with session_scope() as active:
        episodes = active.query(Episode).all()
        assert len(episodes) == 2
        assert {e.video_id for e in episodes} == {"vid001", "vid002"}


def test_a_second_check_does_not_duplicate_episodes(client, monkeypatch):
    """The duplicate guard must survive repeated checks."""
    from viralclips_app import monitor

    uploads = [{"video_id": "vid001", "title": "Episode One",
                "published_at": "2026-11-01T10:00:00+00:00"}]
    monkeypatch.setattr(monitor, "fetch_recent_uploads",
                        lambda channel_id: list(uploads))

    channel_id = client.post("/api/channels", json={
        "url": CHANNEL_URL}).json()["channel"]["id"]
    client.post(f"/api/channels/{channel_id}/check")
    second = client.post(f"/api/channels/{channel_id}/check")
    assert second.json()["new_episodes"] == 0

    with session_scope() as active:
        assert active.query(Episode).count() == 1


def test_a_channel_check_updates_the_schedule(client, monkeypatch):
    from viralclips_app import monitor

    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda channel_id: [])
    channel_id = client.post("/api/channels", json={
        "url": CHANNEL_URL}).json()["channel"]["id"]
    client.post(f"/api/channels/{channel_id}/check")
    with session_scope() as active:
        channel = active.get(Channel, channel_id)
        assert channel.last_checked_at is not None
        assert channel.next_check_at is not None
        assert channel.last_error is None


def test_a_failing_channel_check_records_the_error(client, monkeypatch):
    from viralclips_app import monitor

    def boom(channel_id):
        raise monitor.MonitorError("feed unavailable")

    monkeypatch.setattr(monitor, "fetch_recent_uploads", boom)
    channel_id = client.post("/api/channels", json={
        "url": CHANNEL_URL}).json()["channel"]["id"]
    response = client.post(f"/api/channels/{channel_id}/check")
    assert response.status_code == 502
    with session_scope() as active:
        channel = active.get(Channel, channel_id)
        assert "feed unavailable" in channel.last_error


# --- overview and analytics -------------------------------------------------

def test_overview_counts_come_from_the_database(client):
    clip_id = _make_clip()
    task_id = client.post("/api/tasks", json={
        "name": "Counted", "source_type": "upload"}).json()["task"]["id"]
    body = client.get("/api/overview").json()
    assert body["totals"]["clips_generated"] == 1
    assert body["totals"]["clips_awaiting_approval"] == 1
    assert body["totals"]["clips_approved"] == 0
    assert isinstance(body["jobs"], dict)
    assert body["totals"]["clips_generated"] == len(
        client.get("/api/clips").json()["clips"])


def test_analytics_returns_real_aggregates(client):
    _make_clip()
    body = client.get("/api/analytics").json()
    assert body["clips_generated"] == 1
    assert body["clips_published"] == 0
    assert body["average_ai_score"] == 6.5
    assert body["metrics_available"]["views"] is False
    assert body["metrics_available"]["note"]


def test_analytics_reports_unavailable_metrics_honestly(client):
    """Views must never be invented when no analytics API is connected."""
    body = client.get("/api/analytics").json()
    assert body["metrics_available"]["engagement"] is False
    assert "views" not in body or body.get("views") in (None, 0, [])


def test_empty_database_gives_zeroed_metrics(client):
    body = client.get("/api/overview").json()
    assert body["totals"]["clips_generated"] == 0
    assert body["totals"]["videos_processed"] == 0
    assert body["jobs"]["queued"] == 0


# --- accounts and settings --------------------------------------------------

def test_accounts_report_a_real_connection_state(client):
    body = client.get("/api/accounts").json()
    assert "accounts" in body
    for account in body["accounts"]:
        assert "access_token" not in account
        assert "refresh_token" not in account


def test_settings_can_be_read_and_updated(client):
    original = client.get("/api/settings").json()
    assert "app" in original
    assert "disk" in original
    assert "directories" in original
    response = client.patch("/api/settings", json={
        "settings": {"output_directory": "D:/clips"}})
    assert response.status_code == 200
    assert client.get("/api/settings").json()["app"]["output_directory"] \
        == "D:/clips"


def test_logs_endpoint_returns_lines(client):
    body = client.get("/api/logs").json()
    assert "lines" in body or "logs" in body


# --- publishing guards ------------------------------------------------------

def test_publishing_an_unapproved_clip_is_skipped(client):
    """An unapproved clip must never reach the platform."""
    clip_id = _make_clip(approval="pending")
    response = client.post("/api/publish", json={
        "clip_ids": [clip_id], "platform": "youtube"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "skipped"
    assert "approved" in result["detail"].lower()
    with session_scope() as active:
        assert active.get(Clip, clip_id).publish_status == "not_published"


def test_publishing_without_a_connection_reports_a_failure(client):
    """With no OAuth account connected, publishing fails honestly."""
    clip_id = _make_clip(approval="approved")
    response = client.post("/api/publish", json={
        "clip_ids": [clip_id], "platform": "youtube"})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["error"]
    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        assert clip.publish_status == "failed"
        assert clip.publish_error


def test_publishing_a_missing_clip_is_reported_as_missing(client):
    response = client.post("/api/publish", json={
        "clip_ids": [999999], "platform": "youtube"})
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "missing"


def test_an_invalid_platform_is_rejected(client):
    clip_id = _make_clip(approval="approved")
    response = client.post("/api/publish", json={
        "clip_ids": [clip_id], "platform": "tiktok"})
    assert response.status_code == 422


# --- static frontend --------------------------------------------------------

def test_the_frontend_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "VIRALCLIPS" in response.text.upper()


def test_the_static_assets_are_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_openapi_schema_is_generated(client):
    schema = client.get("/openapi.json").json()
    assert "/api/health" in schema["paths"]
    assert "/api/tasks" in schema["paths"]
    assert "/api/clips" in schema["paths"]

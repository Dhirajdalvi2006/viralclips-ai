"""Tests for the security helpers and the publishing guards.

The rules under test:

  * every mutating request needs the local token,
  * a cross-origin mutation is refused,
  * OAuth tokens never leave the backend,
  * publishing requires an approved clip AND a live connection,
  * a platform that is not configured reports "awaiting credentials"
    instead of pretending to work.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi import HTTPException

from viralclips_app import publishing, security
from viralclips_app.db import session_scope
from viralclips_app.models import Account, Clip, Video


# --- the local token -------------------------------------------------------

def test_the_token_is_not_empty_and_is_long_enough():
    token = security.api_token()
    assert token
    assert len(token) >= 32


def test_the_token_is_not_in_the_url():
    """The token travels in a header, never in the query string."""
    from viralclips_app.main import app

    for route in app.routes:
        for parameter in getattr(route, "dependant", None).query_params \
                if getattr(route, "dependant", None) else []:
            assert parameter.name != "token"


def test_the_wrong_token_is_refused():
    from starlette.requests import Request

    scope = {"type": "http", "headers": [(b"x-viralclips-token", b"nope")],
             "method": "POST", "path": "/api/tasks", "query_string": b"",
             "server": ("127.0.0.1", 8799), "scheme": "http",
             "client": ("127.0.0.1", 1234), "root_path": ""}
    request = Request(scope)
    with pytest.raises(HTTPException) as info:
        security.require_token(request)
    assert info.value.status_code == 403


def test_the_right_token_is_accepted():
    from starlette.requests import Request

    token = security.api_token().encode()
    scope = {"type": "http", "headers": [(b"x-viralclips-token", token)],
             "method": "POST", "path": "/api/tasks", "query_string": b"",
             "server": ("127.0.0.1", 8799), "scheme": "http",
             "client": ("127.0.0.1", 1234), "root_path": ""}
    security.require_token(Request(scope))


def test_a_request_without_the_token_is_refused():
    from starlette.requests import Request

    scope = {"type": "http", "headers": [], "method": "POST",
             "path": "/api/tasks", "query_string": b"",
             "server": ("127.0.0.1", 8799), "scheme": "http",
             "client": ("127.0.0.1", 1234), "root_path": ""}
    with pytest.raises(HTTPException) as info:
        security.require_token(Request(scope))
    assert info.value.status_code == 403


# --- cross-origin ----------------------------------------------------------

def test_a_foreign_origin_is_refused():
    from starlette.requests import Request

    scope = {"type": "http",
             "headers": [(b"origin", b"https://evil.example.com")],
             "method": "POST", "path": "/api/tasks", "query_string": b"",
             "server": ("127.0.0.1", 8799), "scheme": "http",
             "client": ("127.0.0.1", 1234), "root_path": ""}
    with pytest.raises(HTTPException) as info:
        security.check_origin(Request(scope))
    assert info.value.status_code == 403


def test_our_own_origin_is_accepted():
    from starlette.requests import Request

    scope = {"type": "http", "headers": [(b"origin", b"http://127.0.0.1:8799")],
             "method": "POST", "path": "/api/tasks", "query_string": b"",
             "server": ("127.0.0.1", 8799), "scheme": "http",
             "client": ("127.0.0.1", 1234), "root_path": ""}
    security.check_origin(Request(scope))


def test_a_request_without_an_origin_is_accepted():
    from starlette.requests import Request

    scope = {"type": "http", "headers": [], "method": "POST",
             "path": "/api/tasks", "query_string": b"",
             "server": ("127.0.0.1", 8799), "scheme": "http",
             "client": ("127.0.0.1", 1234), "root_path": ""}
    security.check_origin(Request(scope))


# --- token masking ---------------------------------------------------------

def test_mask_token_never_shows_the_whole_token():
    masked = security.mask_token("abcdefghijklmnopqrstuvwxyz")
    assert masked.startswith("...")
    assert masked.endswith("wxyz")
    assert "abcdefgh" not in masked


def test_mask_token_of_nothing_is_empty():
    assert security.mask_token("") == ""
    assert security.mask_token(None) == ""


def test_mask_token_of_a_short_token_is_not_the_token():
    masked = security.mask_token("abc")
    assert masked == "set"


# --- token expiry ----------------------------------------------------------

def test_a_missing_expiry_counts_as_expired():
    assert security.token_expired(None) is True


def test_a_past_expiry_is_expired():
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    assert security.token_expired(past) is True


def test_a_future_expiry_is_valid():
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    assert security.token_expired(future) is False


def test_a_naive_expiry_is_treated_as_utc():
    naive = dt.datetime.utcnow() + dt.timedelta(hours=1)
    assert security.token_expired(naive) is False


# --- OAuth configuration ---------------------------------------------------

def test_oauth_status_never_exposes_the_secret(monkeypatch):
    monkeypatch.setattr(security, "oauth_client_id", lambda p: "the-id")
    monkeypatch.setattr(security, "oauth_client_secret", lambda p: "the-secret")
    status = security.oauth_status("youtube")
    assert status["client_id_present"] is True
    assert status["client_secret_present"] is True
    assert "the-secret" not in str(status)


def test_oauth_status_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(security, "oauth_client_id", lambda p: "")
    monkeypatch.setattr(security, "oauth_client_secret", lambda p: "")
    status = security.oauth_status("instagram")
    assert status["configured"] is False
    assert status["client_id_present"] is False


def test_oauth_status_includes_the_redirect_uri(monkeypatch):
    monkeypatch.setattr(security, "oauth_client_id", lambda p: "")
    monkeypatch.setattr(security, "oauth_client_secret", lambda p: "")
    status = security.oauth_status("youtube")
    assert "127.0.0.1" in status["redirect_uri"]
    assert "/api/accounts/youtube/callback" in status["redirect_uri"]


# --- publishing guards -----------------------------------------------------

def test_publishing_requires_an_approved_clip():
    with session_scope() as active:
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=0.0,
                    end_seconds=1.0, duration_seconds=1.0, score=1.0,
                    approval_status="pending")
        active.add(clip)
        active.flush()
        clip_id = clip.id

    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        with pytest.raises(publishing.PublishError) as info:
            publishing._require_approval(clip)
    assert "approved" in str(info.value).lower()


def test_publishing_requires_a_rendered_file():
    with session_scope() as active:
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=0.0,
                    end_seconds=1.0, duration_seconds=1.0, score=1.0,
                    approval_status="approved", file_path=None)
        active.add(clip)
        active.flush()
        clip_id = clip.id

    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        with pytest.raises(publishing.PublishError) as info:
            publishing._require_file(clip.file_path)
    assert "file" in str(info.value).lower()


def test_publishing_requires_a_file_that_exists(tmp_path):
    with pytest.raises(publishing.PublishError) as info:
        publishing._require_file(str(tmp_path / "missing.mp4"))
    assert "missing" in str(info.value).lower()


def test_an_unconfigured_platform_reports_awaiting_credentials(monkeypatch):
    monkeypatch.setattr(security, "oauth_status", lambda platform: {
        "configured": False, "client_id_present": False,
        "client_secret_present": False, "redirect_uri": "http://x",
        "scopes": []})
    with session_scope() as active:
        state = publishing.account_state(active, "youtube")
    assert state["status"] == "awaiting_credentials"
    assert state["connected"] is False


def test_a_configured_but_unconnected_platform_reports_awaiting_authorization(
        monkeypatch):
    monkeypatch.setattr(security, "oauth_status", lambda platform: {
        "configured": True, "client_id_present": True,
        "client_secret_present": True, "redirect_uri": "http://x",
        "scopes": []})
    with session_scope() as active:
        state = publishing.account_state(active, "instagram")
    assert state["status"] == "awaiting_authorization"
    assert state["connected"] is False


def test_account_state_never_includes_a_token():
    with session_scope() as active:
        state = publishing.account_state(active, "youtube")
    assert "access_token" not in state
    assert "refresh_token" not in state
    assert "client_secret" not in state


def test_a_connected_account_reports_connected():
    with session_scope() as active:
        active.add(Account(
            platform="youtube", external_id="me", display_name="Me",
            access_token="secret", connected=True,
            token_expiry=dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(hours=1)))
    with session_scope() as active:
        state = publishing.account_state(active, "youtube")
    assert state["connected"] is True
    assert state["status"] == "connected"
    # The token value must not appear anywhere in the state.
    assert "secret" not in str(state).replace("client_secret_present", "") \
        .replace("secret_present", "")


def test_youtube_publish_refuses_when_not_connected():
    with session_scope() as active:
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=0.0,
                    end_seconds=1.0, duration_seconds=1.0, score=1.0,
                    approval_status="approved", file_path="C:/tmp/v.mp4")
        active.add(clip)
        active.flush()
        clip_id = clip.id

    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        with pytest.raises(publishing.PublishError):
            publishing.youtube_publish(active, clip)


def test_instagram_publish_refuses_when_not_connected():
    with session_scope() as active:
        video = Video(title="v", source="C:/tmp/v.mp4")
        active.add(video)
        active.flush()
        clip = Clip(video_id=video.id, index=0, start_seconds=0.0,
                    end_seconds=1.0, duration_seconds=1.0, score=1.0,
                    approval_status="approved", file_path="C:/tmp/v.mp4")
        active.add(clip)
        active.flush()
        clip_id = clip.id

    with session_scope() as active:
        clip = active.get(Clip, clip_id)
        with pytest.raises(publishing.PublishError):
            publishing.instagram_publish(active, clip)


def test_the_accounts_api_never_returns_a_token(client):
    body = client.get("/api/accounts").json()
    for account in body.get("accounts", []):
        assert "access_token" not in account
        assert "refresh_token" not in account
        assert "client_secret" not in account


def test_a_connected_account_is_stored_not_exposed():
    with session_scope() as active:
        active.add(Account(platform="youtube", external_id="me",
                           display_name="Me",
                           access_token="super-secret-token"))
    from viralclips_app.db import session_scope as scope

    with scope() as active:
        stored = active.query(Account).filter_by(platform="youtube").one()
        assert stored.access_token == "super-secret-token"
        assert stored.connected is False

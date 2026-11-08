"""Publishing services for YouTube Shorts and Instagram Reels.

Design rules, taken directly from the brief:

- **No invented connections.** An account shows as connected only when a
  real OAuth exchange produced a usable token.
- **Publishing stays disabled until the user approves.** A clip must be in
  the ``approved`` state before any publish call is made, and the master
  switch in ``config.PUBLISHING_ENABLED`` must be on.
- **No browser automation, no password collection.** OAuth only.
- **Tokens never reach the frontend.** The API returns connection *state*,
  never a token.

YouTube uses the official Google OAuth flow and the YouTube Data API v3
resumable upload endpoint. Instagram uses the official Meta OAuth flow and
the Instagram Graph API content-publish endpoint. Both need credentials
the user supplies; until then the integration reports
``awaiting_credentials`` rather than pretending to work.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
import time
from pathlib import Path

import httpx

from . import config, security

# --- shared helpers -------------------------------------------------------

class PublishError(RuntimeError):
    """A publishing attempt failed."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _require_approval(clip) -> None:
    """Raise unless the clip has been approved."""
    if getattr(clip, "approval_status", None) != "approved":
        raise PublishError(
            "Only approved clips can be published. "
            f"Current state: {getattr(clip, 'approval_status', 'unknown')}.")


def _require_enabled() -> None:
    if not config.PUBLISHING_ENABLED:
        raise PublishError(
            "Publishing is disabled. Enable it in Settings before publishing.")


def _require_file(path: str | None) -> Path:
    if not path:
        raise PublishError("This clip has no rendered file.")
    file_path = Path(path)
    if not file_path.is_file():
        raise PublishError(f"The clip file is missing: {file_path.name}")
    return file_path


def _state(session, platform: str):
    """Return the Account row for a platform, creating it if needed."""
    from .models import Account
    account = session.query(Account).filter(Account.platform == platform).one_or_none()
    if account is None:
        account = Account(platform=platform)
        session.add(account)
        session.flush()
    return account


def account_state(session, platform: str) -> dict:
    """Return a key-free connection state for a platform."""
    from .models import Account
    account = session.query(Account).filter(Account.platform == platform).one_or_none()
    oauth = security.oauth_status(platform)

    if account is None or not account.connected or not account.access_token:
        return {
            "platform": platform,
            "connected": False,
            "status": "awaiting_credentials" if not oauth["configured"]
            else "awaiting_authorization",
            "message": ("Add the OAuth client credentials to your local "
                        "credential file." if not oauth["configured"]
                        else "Authorize the account to publish."),
            "display_name": "",
            "channel_title": "",
            "external_id": "",
            "thumbnail_url": None,
            "scopes": [],
            "client_id_present": oauth["client_id_present"],
            "client_secret_present": oauth["client_secret_present"],
            "redirect_uri": oauth["redirect_uri"],
            "last_verified_at": None,
            "last_error": account.last_error if account else None,
        }

    expired = security.token_expired(account.token_expiry)
    return {
        "platform": platform,
        "connected": True,
        "status": "connected",
        "message": "Connected and authorized.",
        "display_name": account.display_name,
        "channel_title": account.channel_title,
        "external_id": account.external_id,
        "thumbnail_url": account.thumbnail_url,
        "scopes": list(account.scopes or []),
        "client_id_present": True,
        "client_secret_present": True,
        "redirect_uri": oauth["redirect_uri"],
        "token_expired": expired,
        "last_verified_at": account.last_verified_at,
        "last_error": account.last_error,
    }


# --- YouTube ---------------------------------------------------------------

YT_TOKEN_URL = "https://oauth2.googleapis.com/token"
YT_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
YT_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YT_ME_URL = "https://www.googleapis.com/youtube/v3/channels"


def youtube_authorize_url(state: str) -> str:
    """Build the Google OAuth consent URL."""
    client_id = security.oauth_client_id("youtube")
    if not client_id:
        raise PublishError("YouTube OAuth client id is not configured.")
    params = {
        "client_id": client_id,
        "redirect_uri": config.oauth_redirect_uri("youtube"),
        "response_type": "code",
        "scope": " ".join(config.OAUTH_SCOPES["youtube"]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    query = "&".join(f"{key}={httpx.QueryParams({key: value})[key]}"
                     for key, value in params.items())
    return f"{YT_AUTH_URL}?{query}"


def _token_exchange(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for tokens."""
    client_id = security.oauth_client_id("youtube")
    client_secret = security.oauth_client_secret("youtube")
    if not client_id or not client_secret:
        raise PublishError("YouTube OAuth client credentials are not configured.")
    try:
        response = httpx.post(YT_TOKEN_URL, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=30)
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not reach Google: {exc}") from exc
    if response.status_code != 200:
        detail = response.json() if response.headers.get(
            "content-type", "").startswith("application/json") else response.text
        raise PublishError(
            f"Google rejected the token exchange ({response.status_code}). {detail}")
    return response.json()


def youtube_connect(session, code: str, state: str | None = None) -> dict:
    """Complete the YouTube OAuth exchange and store the account."""
    redirect_uri = config.oauth_redirect_uri("youtube")
    payload = _token_exchange(code, redirect_uri)
    access_token = payload.get("access_token")
    if not access_token:
        raise PublishError("Google did not return an access token.")

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        channels = httpx.get(YT_ME_URL, headers=headers, params={
            "part": "snippet", "mine": "true"}, timeout=30).json()
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not verify the YouTube channel: {exc}") from exc

    items = channels.get("items") or []
    if not items:
        raise PublishError(
            "The account authorized but has no YouTube channel. "
            "A channel is required to publish Shorts.")
    snippet = items[0].get("snippet", {})

    expires_in = int(payload.get("expires_in", 3600))
    account = _state(session, "youtube")
    account.access_token = access_token
    account.refresh_token = payload.get("refresh_token") or account.refresh_token
    account.token_expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        seconds=expires_in)
    account.external_id = items[0].get("id", "")
    account.channel_title = snippet.get("title", "")
    account.display_name = snippet.get("title", "")
    account.thumbnail_url = (
        (snippet.get("thumbnails") or {}).get("default", {}) or {}).get("url")
    account.scopes = list(config.OAUTH_SCOPES["youtube"])
    account.connected = True
    account.last_verified_at = dt.datetime.now(dt.timezone.utc)
    account.last_error = None
    session.flush()
    return account_state(session, "youtube")


def youtube_refresh(session) -> bool:
    """Refresh the YouTube access token if it has expired."""
    from .models import Account
    account = session.query(Account).filter(Account.platform == "youtube").one_or_none()
    if account is None or not account.refresh_token:
        return False
    if not security.token_expired(account.token_expiry):
        return True
    client_id = security.oauth_client_id("youtube")
    client_secret = security.oauth_client_secret("youtube")
    if not client_id or not client_secret:
        return False
    try:
        response = httpx.post(YT_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": account.refresh_token,
            "grant_type": "refresh_token",
        }, timeout=30)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        account.last_error = "Token refresh failed."
        return False
    payload = response.json()
    account.access_token = payload.get("access_token", account.access_token)
    account.token_expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        seconds=int(payload.get("expires_in", 3600)))
    session.flush()
    return True


def youtube_publish(session, clip, title: str | None = None,
                    description: str | None = None,
                    privacy_status: str = "public",
                    tags: list | None = None) -> dict:
    """Upload an approved clip to YouTube as a Short.

    Uses the official resumable upload endpoint. Returns a dict with the
    video id and a watch URL.
    """
    _require_enabled()
    _require_approval(clip)
    file_path = _require_file(clip.file_path)

    if not youtube_refresh(session):
        raise PublishError("The YouTube connection is not usable. Reconnect it.")

    from .models import Account
    account = session.query(Account).filter(
        Account.platform == "youtube").one_or_none()
    if account is None or not account.access_token:
        raise PublishError("YouTube is not connected.")

    final_title = (title or clip.title or "Untitled clip").strip()
    final_description = (description if description is not None
                         else clip.description or "").strip()
    tag_list = tags if tags is not None else (
        [t.strip() for t in (clip.hashtags or "").split() if t.strip()])
    body = {
        "snippet": {
            "title": final_title[:100],
            "description": final_description[:5000],
            "tags": [t.lstrip("#") for t in tag_list][:30],
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    headers = {
        "Authorization": f"Bearer {account.access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
    }

    try:
        # 1. start the resumable upload
        start = httpx.post(
            YT_UPLOAD_URL,
            headers=headers,
            params={"uploadType": "resumable", "part": "snippet,status"},
            content=json.dumps(body).encode("utf-8"),
            timeout=60)
        if start.status_code not in (200, 201):
            detail = _safe_detail(start)
            raise PublishError(
                f"YouTube rejected the upload ({start.status_code}). {detail}",
                start.status_code)
        location = start.headers.get("Location")
        if not location:
            raise PublishError("YouTube did not return an upload location.")

        # 2. upload the file bytes
        size = file_path.stat().st_size
        with httpx.Client(timeout=300) as client:
            uploaded = client.put(
                location, headers={"Content-Length": str(size)},
                content=file_path.read_bytes())
        if uploaded.status_code not in (200, 201):
            detail = _safe_detail(uploaded)
            raise PublishError(
                f"YouTube rejected the file upload ({uploaded.status_code}). "
                f"{detail}", uploaded.status_code)
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not reach YouTube: {exc}") from exc

    payload = {}
    try:
        payload = uploaded.json()
    except ValueError:
        pass
    video_id = payload.get("id", "")
    return {
        "platform": "youtube",
        "video_id": video_id,
        "url": f"https://www.youtube.com/shorts/{video_id}" if video_id else "",
        "title": final_title,
    }


# --- Instagram -------------------------------------------------------------

IG_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
IG_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
IG_GRAPH = "https://graph.facebook.com/v21.0"


def instagram_authorize_url(state: str) -> str:
    """Build the Meta OAuth consent URL."""
    client_id = security.oauth_client_id("instagram")
    if not client_id:
        raise PublishError("Instagram OAuth client id is not configured.")
    params = {
        "client_id": client_id,
        "redirect_uri": config.oauth_redirect_uri("instagram"),
        "response_type": "code",
        "scope": ",".join(config.OAUTH_SCOPES["instagram"]),
        "state": state,
    }
    query = "&".join(f"{key}={httpx.QueryParams({key: value})[key]}"
                     for key, value in params.items())
    return f"{IG_AUTH_URL}?{query}"


def instagram_connect(session, code: str) -> dict:
    """Complete the Meta OAuth exchange and verify account eligibility."""
    client_id = security.oauth_client_id("instagram")
    client_secret = security.oauth_client_secret("instagram")
    if not client_id or not client_secret:
        raise PublishError("Instagram OAuth client credentials are not configured.")
    redirect_uri = config.oauth_redirect_uri("instagram")

    try:
        response = httpx.get(IG_TOKEN_URL, params={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=30)
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not reach Meta: {exc}") from exc
    if response.status_code != 200:
        raise PublishError(
            f"Meta rejected the token exchange ({response.status_code}). "
            f"{_safe_detail(response)}")
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise PublishError("Meta did not return an access token.")

    # Find the Facebook Page and the Instagram professional account.
    try:
        pages = httpx.get(f"{IG_GRAPH}/me/accounts", headers={
            "Authorization": f"Bearer {access_token}"}, timeout=30).json()
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not verify the Facebook Page: {exc}") from exc

    page_items = pages.get("data") or []
    if not page_items:
        raise PublishError(
            "No Facebook Page is linked to this account. Instagram Reels "
            "publishing requires a Page.")
    page = page_items[0]

    ig_id = ""
    ig_name = ""
    try:
        ig = httpx.get(f"{IG_GRAPH}/{page['id']}", params={
            "fields": "instagram_business_account{id,username,name,profile_picture_url}",
            "access_token": access_token}, timeout=30).json()
        account_data = ig.get("instagram_business_account") or {}
        ig_id = account_data.get("id", "")
        ig_name = account_data.get("username") or account_data.get("name", "")
    except httpx.HTTPError:
        ig_id = ""

    if not ig_id:
        raise PublishError(
            "The linked Page has no Instagram professional account "
            "(Business or Creator). Reels publishing requires one.")

    account = _state(session, "instagram")
    account.access_token = access_token
    account.refresh_token = payload.get("refresh_token") or account.refresh_token
    account.token_expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
        seconds=int(payload.get("expires_in", 5184000)))
    account.external_id = ig_id
    account.channel_title = page.get("name", "")
    account.display_name = ig_name or page.get("name", "")
    account.scopes = list(config.OAUTH_SCOPES["instagram"])
    account.connected = True
    account.last_verified_at = dt.datetime.now(dt.timezone.utc)
    account.last_error = None
    account.extra = {"page_id": page.get("id", ""),
                     "page_name": page.get("name", "")}
    session.flush()
    return account_state(session, "instagram")


def instagram_publish(session, clip, caption: str | None = None,
                      title: str | None = None) -> dict:
    """Publish an approved clip as an Instagram Reel."""
    _require_enabled()
    _require_approval(clip)
    file_path = _require_file(clip.file_path)

    from .models import Account
    account = session.query(Account).filter(
        Account.platform == "instagram").one_or_none()
    if account is None or not account.access_token:
        raise PublishError("Instagram is not connected.")
    ig_id = account.external_id
    if not ig_id:
        raise PublishError(
            "The connected Instagram account id is unknown. Reconnect it.")

    final_caption = caption if caption is not None else (
        (title or clip.title or "") + "\n\n" + (clip.description or "")).strip()

    # Step 1: create the media container. The Graph API requires a public
    # URL for the video bytes, so the file is served by this application.
    container_url = f"{IG_GRAPH}/{ig_id}/media"
    create_params = {
        "media_type": "REELS",
        "video_url": _public_media_url(clip),
        "caption": final_caption[:2200],
        "access_token": account.access_token,
    }
    try:
        create = httpx.post(container_url, data=create_params, timeout=120)
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not reach Meta: {exc}") from exc
    if create.status_code != 200:
        raise PublishError(
            f"Meta rejected the Reel container ({create.status_code}). "
            f"{_safe_detail(create)}", create.status_code)
    creation = create.json()
    container_id = creation.get("id")
    if not container_id:
        raise PublishError("Meta did not return a media container id.")
    if creation.get("error"):
        raise PublishError(f"Meta rejected the Reel: {creation['error']}")

    # Step 2: publish the container.
    try:
        publish = httpx.post(f"{IG_GRAPH}/{ig_id}/media_publish", data={
            "creation_id": container_id,
            "access_token": account.access_token,
        }, timeout=120)
    except httpx.HTTPError as exc:
        raise PublishError(f"Could not reach Meta: {exc}") from exc
    if publish.status_code != 200:
        raise PublishError(
            f"Meta rejected the publish ({publish.status_code}). "
            f"{_safe_detail(publish)}", publish.status_code)
    result = publish.json()
    if result.get("error"):
        raise PublishError(f"Meta rejected the publish: {result['error']}")

    return {
        "platform": "instagram",
        "video_id": result.get("id", ""),
        "url": f"https://www.instagram.com/reel/{result.get('id', '')}",
        "title": title or clip.title or "",
    }


def _public_media_url(clip) -> str:
    """Build the URL Meta fetches the video from.

    Meta requires a publicly reachable HTTPS URL. On a loopback-only
    installation this is not satisfiable, so the caller must be told
    rather than left with a silent failure.
    """
    base = getattr(config, "PUBLIC_MEDIA_BASE_URL", "")
    if not base:
        raise PublishError(
            "Instagram Reels publishing needs a publicly reachable media "
            "URL. Set VIRALCLIPS_PUBLIC_MEDIA_URL to an HTTPS host that "
            "serves this application's media endpoint, then reconnect "
            "Instagram.")
    return f"{base.rstrip('/')}/media/clip/{clip.id}"


def _safe_detail(response) -> str:
    """Extract a short, non-secret error detail from a response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message", error))[:300]
        return json.dumps(payload)[:300]
    return str(payload)[:300]

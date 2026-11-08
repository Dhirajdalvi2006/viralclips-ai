"""Security helpers: local API token and OAuth credential handling.

Two separate concerns live here:

1. **Local API token** — a random secret minted at startup. Every mutating
   request must carry it. This stops a stray page on the machine (or a
   browser extension) from driving the application.

2. **OAuth credentials** — provider client secrets and account tokens. The
   provider API key comes from the existing credential loader; OAuth
   client secrets come from the same file. Tokens live in the database and
   are never returned to the frontend.
"""
from __future__ import annotations

import datetime as dt
import os
import secrets

from fastapi import HTTPException, Request

from . import config

#: The in-process API token. Generated once per API process.
_API_TOKEN = os.environ.get(config.LOCAL_API_TOKEN_ENV) or secrets.token_urlsafe(32)


def api_token() -> str:
    """Return the current local API token."""
    return _API_TOKEN


def require_token(request: Request) -> None:
    """FastAPI dependency enforcing the local API token on mutations.

    Applied to POST/PUT/PATCH/DELETE routes. The token travels in a
    header, never in the URL, so it stays out of logs and history.

    The origin is checked as well. The application is loopback-only, so
    a request carrying a foreign ``Origin`` header is a page on another
    site trying to drive it, and is refused even if it somehow has the
    token.
    """
    supplied = request.headers.get("X-ViralClips-Token", "")
    if not secrets.compare_digest(supplied, _API_TOKEN):
        raise HTTPException(
            status_code=403,
            detail="Request rejected. Reload the application and retry.")
    check_origin(request)


def check_origin(request: Request) -> None:
    """Reject cross-origin mutating requests.

    The app is loopback-only, so any request carrying a foreign Origin
    header is not ours.
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return
    expected = f"http://{request.url.hostname}:{request.url.port}"
    if origin.rstrip("/") != expected:
        raise HTTPException(status_code=403, detail="Cross-origin request rejected.")


# --- OAuth credential access ---------------------------------------------

def oauth_client_id(platform: str) -> str:
    """Return the OAuth client id for a platform, or '' if not configured."""
    from providers import credentials
    name = ("YOUTUBE_CLIENT_ID" if platform == "youtube"
            else "INSTAGRAM_CLIENT_ID")
    return (credentials.get(name, "") or "").strip()


def oauth_client_secret(platform: str) -> str:
    """Return the OAuth client secret for a platform, or '' if not set."""
    from providers import credentials
    name = ("YOUTUBE_CLIENT_SECRET" if platform == "youtube"
            else "INSTAGRAM_CLIENT_SECRET")
    return (credentials.get(name, "") or "").strip()


def oauth_configured(platform: str) -> bool:
    """True when both client id and secret are available."""
    return bool(oauth_client_id(platform) and oauth_client_secret(platform))


def oauth_status(platform: str) -> dict:
    """Return a key-free description of OAuth readiness for a platform.

    Never includes the secret, only whether one is present.
    """
    configured = oauth_configured(platform)
    return {
        "platform": platform,
        "client_id_present": bool(oauth_client_id(platform)),
        "client_secret_present": bool(oauth_client_secret(platform)),
        "configured": configured,
        "redirect_uri": config.oauth_redirect_uri(platform),
        "scopes": config.OAUTH_SCOPES.get(platform, []),
    }


def mask_token(token: str | None) -> str:
    """Return a safe display form of a token: last 4 characters only."""
    if not token:
        return ""
    return f"...{token[-4:]}" if len(token) > 8 else "set"


def token_expired(expiry: dt.datetime | None) -> bool:
    """True when a token expiry is in the past (or missing)."""
    if expiry is None:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=dt.timezone.utc)
    return expiry <= dt.datetime.now(dt.timezone.utc)

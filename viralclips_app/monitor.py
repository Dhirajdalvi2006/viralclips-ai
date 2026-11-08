"""Channel monitoring service.

Uses the **official YouTube Data API v3** where possible, and falls back
to the public RSS feed (also official, published by YouTube) for channel
*detection*. Neither is page scraping.

Detection needs only a channel id, which the RSS feed provides directly.
Listing a channel's uploads with full metadata needs an API key, so that
path is used only when a key is configured.

Rights note: detecting that a video exists is not the same as being
licensed to download and republish it. This module only *detects*; the
ingestion decision belongs to the task, which requires an explicit rights
attestation before any automated remote download.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET

import httpx

from . import config

RSS_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
API_CHANNELS = "https://www.googleapis.com/youtube/v3/channels"
API_SEARCH = "https://www.googleapis.com/youtube/v3/search"

NS = {"atom": "http://www.w3.org/2005/Atom",
      "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


class MonitorError(RuntimeError):
    """A channel lookup or feed read failed."""


def api_key() -> str:
    """Return the configured YouTube Data API key, or ''."""
    from providers import credentials
    return (credentials.get("YOUTUBE_API_KEY", "") or "").strip()


def extract_channel_id(url_or_id: str) -> str:
    """Extract a channel id from a URL, handle, or bare id.

    Handles:
      - https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx
      - https://www.youtube.com/@handle
      - https://www.youtube.com/c/name
      - https://www.youtube.com/user/name
      - https://www.youtube.com/playlist?list=...
    """
    if not url_or_id or not isinstance(url_or_id, str):
        raise MonitorError("Enter a YouTube channel URL or id.")
    text = url_or_id.strip()
    if CHANNEL_ID_RE.match(text):
        return text

    match = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", text)
    if match:
        return match.group(1)

    if "list=" in text:
        raise MonitorError(
            "A playlist URL does not identify a channel. Add the channel "
            "URL instead.")

    key = api_key()
    if key:
        resolved = _lookup_channel_id(text, key)
        if resolved:
            return resolved

    raise MonitorError(
        "Could not determine the channel id from that URL. Use the channel's "
        "'.../channel/UC...' URL, or configure a YouTube Data API key so "
        "handles and custom URLs can be resolved.")


def _lookup_channel_id(url: str, key: str) -> str | None:
    """Resolve a handle or custom URL to a channel id using the Data API."""
    for params in ({"forHandle": url.lstrip("@").split("/")[0]},
                   {"forUsername": url.rstrip("/").split("/")[-1]}):
        try:
            response = httpx.get(API_CHANNELS, params={
                **params, "part": "id,snippet", "key": key}, timeout=30)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            continue
        items = response.json().get("items") or []
        if items:
            return items[0].get("id")
    return None


def fetch_channel_info(channel_id: str, key: str | None = None) -> dict:
    """Fetch a channel's title, description and thumbnail."""
    key = key or api_key()
    if not key:
        return {"channel_id": channel_id, "name": "", "description": "",
                "thumbnail_url": None, "via_api": False}
    try:
        response = httpx.get(API_CHANNELS, params={
            "part": "snippet", "id": channel_id, "key": key}, timeout=30)
    except httpx.HTTPError as exc:
        raise MonitorError(f"Could not reach the YouTube Data API: {exc}") from exc
    if response.status_code != 200:
        raise MonitorError(
            f"The YouTube Data API returned {response.status_code}. "
            "Check the API key.")
    items = response.json().get("items") or []
    if not items:
        raise MonitorError("That channel id was not found on YouTube.")
    snippet = items[0].get("snippet", {})
    return {
        "channel_id": channel_id,
        "name": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "thumbnail_url": (
            (snippet.get("thumbnails") or {}).get("default", {}) or {}).get("url"),
        "via_api": True,
    }


def fetch_recent_uploads(channel_id: str, key: str | None = None,
                         limit: int = 15) -> list:
    """List a channel's most recent uploads.

    Uses the official RSS feed, which needs no API key. When an API key is
    configured, the Data API is preferred because it exposes exact
    publication times.
    """
    key = key or api_key()
    if key:
        try:
            response = httpx.get(API_SEARCH, params={
                "part": "snippet", "channelId": channel_id, "type": "video",
                "order": "date", "maxResults": min(limit, 50), "key": key},
                timeout=30)
            if response.status_code == 200:
                items = response.json().get("items") or []
                uploads = []
                for item in items:
                    snippet = item.get("snippet", {})
                    uploads.append({
                        "video_id": (item.get("id") or {}).get("videoId", ""),
                        "title": snippet.get("title", ""),
                        "published_at": snippet.get("publishedAt"),
                        "thumbnail_url": (
                            (snippet.get("thumbnails") or {}).get("medium", {})
                            or {}).get("url"),
                        "description": snippet.get("description", ""),
                    })
                if uploads:
                    return uploads
        except httpx.HTTPError:
            pass  # fall through to RSS

    return fetch_recent_uploads_rss(channel_id, limit)


def fetch_recent_uploads_rss(channel_id: str, limit: int = 15) -> list:
    """List a channel's most recent uploads using the official RSS feed."""
    url = RSS_TEMPLATE.format(channel_id=channel_id)
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise MonitorError(f"Could not reach the YouTube feed: {exc}") from exc
    if response.status_code != 200:
        raise MonitorError(
            f"The YouTube feed returned {response.status_code} for that "
            "channel id.")
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise MonitorError(f"The YouTube feed was not valid XML: {exc}") from exc

    entries = []
    for entry in root.findall("atom:entry", NS)[:limit]:
        video_id = ""
        for link in entry.findall("atom:link", NS):
            if link.get("rel") == "alternate":
                match = re.search(r"v=([\w-]{6,})", link.get("href", ""))
                if match:
                    video_id = match.group(1)
                    break
        if not video_id:
            video_id = entry.findtext("yt:videoId", "", NS)
        published = entry.findtext("atom:published", "", NS)
        entries.append({
            "video_id": video_id,
            "title": entry.findtext("atom:title", "", NS),
            "published_at": published,
            "thumbnail_url": "",
            "description": "",
        })
    return entries


def parse_published(value) -> dt.datetime | None:
    """Parse an RFC3339 timestamp into an aware datetime."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def next_check_time(interval_minutes: int, now: dt.datetime | None = None
                    ) -> dt.datetime:
    """Return when a channel should next be checked."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return now + dt.timedelta(minutes=max(1, int(interval_minutes)))

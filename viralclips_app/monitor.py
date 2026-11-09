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
CHANNEL_PAGE = "https://www.youtube.com/{path}"

NS = {"atom": "http://www.w3.org/2005/Atom",
      "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")

#: The channel id YouTube's own page declares for itself. This is read
#: from the channel's public page -- the same identifier the page's own
#: canonical link points at -- and is used only to turn a "@handle" into
#: the UC id that the official RSS feed needs. No video content, no
#: private data and no access control is involved.
PAGE_CHANNEL_ID_PATTERNS = (
    re.compile(r'"externalId":"(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'"channelId":"(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'itemprop="identifier"\s+content="(UC[A-Za-z0-9_-]{22})"'),
    re.compile(r'channel/(UC[A-Za-z0-9_-]{22})'),
)

PAGE_TITLE_PATTERNS = (
    re.compile(r'<meta property="og:title" content="([^"]{1,200})"'),
    re.compile(r'<meta itemprop="name" content="([^"]{1,200})"'),
    re.compile(r'"name":"([^"\\]{1,200})"'),
)


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


def _page_path(url_or_id: str) -> str | None:
    """Return the YouTube path for a handle or custom channel URL."""
    text = (url_or_id or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        return text
    if text.startswith("http://") or text.startswith("https://"):
        without_scheme = re.sub(r"^https?://(www\.)?youtube\.com", "",
                                 text, flags=re.I)
        without_scheme = without_scheme.split("?")[0].split("#")[0]
        parts = [p for p in without_scheme.split("/") if p]
        if not parts:
            return None
        if parts[0].startswith("@"):
            # "/@handle" is a single segment.
            return parts[0]
        if parts[0] in ("c", "user"):
            if len(parts) < 2:
                return None
            return parts[0] + "/" + parts[1]
        if parts[0] == "channel":
            return None           # already an id, no lookup needed
        return None
    if text.startswith(("c/", "user/")):
        return text
    return None


def _lookup_channel_page(url_or_id: str) -> dict | None:
    """Read a channel's public page for the identity it declares itself.

    The page states its own channel id (in its canonical link and in its
    structured metadata). Turning a handle into the UC id that the
    official RSS feed needs therefore does not require a Data API key.

    This reads public page metadata only. It does not bypass an access
    control, and it does not read video content.
    """
    path = _page_path(url_or_id)
    if not path:
        return None
    url = CHANNEL_PAGE.format(path=path)
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True,
                             headers={"Accept-Language": "en-US,en"})
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    text = response.text

    channel_id = None
    for pattern in PAGE_CHANNEL_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            channel_id = match.group(1)
            break
    if not channel_id:
        return None

    name = ""
    for pattern in PAGE_TITLE_PATTERNS:
        match = pattern.search(text)
        if match:
            name = _clean_page_title(match.group(1))
            if name:
                break

    handle = ""
    if path.startswith("@"):
        handle = path.split("/")[0]
    else:
        match = re.search(r'itemprop="alternate"[^>]*content="([^"]+)"', text)
        if match and "@" in match.group(1):
            handle = "@" + match.group(1).lstrip("@").split("/")[0]

    return {"channel_id": channel_id, "name": name, "handle": handle}


def _clean_page_title(raw: str) -> str:
    """Turn an HTML-escaped page title into plain text."""
    import html
    text = html.unescape(raw).strip()
    if text.endswith(" - YouTube"):
        text = text[: -len(" - YouTube")].strip()
    return text


def validate_channel(channel_id: str) -> dict:
    """Confirm that a channel id is real, using the official RSS feed.

    The feed is the authority on "does this channel exist and does it
    publish": a valid id returns entries, an invalid one does not.
    """
    if not CHANNEL_ID_RE.match(channel_id or ""):
        raise MonitorError("That is not a valid channel id.")
    try:
        entries = fetch_recent_uploads_rss(channel_id, limit=3)
    except MonitorError as exc:
        raise MonitorError(
            f"That channel could not be validated: {exc}") from exc
    if not entries:
        raise MonitorError(
            "YouTube returned no uploads for that channel id, so it could "
            "not be confirmed.")
    return {"channel_id": channel_id, "validated": True,
            "recent_count": len(entries)}


def resolve_channel_identity(url_or_id: str) -> dict:
    """Resolve a channel URL, handle or id into a verified identity.

    Tries, in order:

    1. the id, when the input already contains one;
    2. the official YouTube Data API, when a key is configured;
    3. the channel's own public page, which declares its id.

    The result is then validated against the official RSS feed, so a
    channel is never reported as connected unless YouTube actually
    confirms it.
    """
    text = (url_or_id or "").strip()
    if not text:
        raise MonitorError("Enter a YouTube channel URL or id.")

    channel_id = None
    name = ""
    handle = ""
    resolved_via = None
    original_error = None

    try:
        channel_id = extract_channel_id(text)
        resolved_via = "url"
    except MonitorError as exc:
        # Keep the original reason. A playlist URL must still be told
        # that it is a playlist, even though the page lookup below also
        # fails for it.
        original_error = str(exc)
        channel_id = None

    if channel_id is None:
        key = api_key()
        if key:
            looked_up = _lookup_channel_id(text, key)
            if looked_up:
                channel_id = looked_up
                resolved_via = "data_api"

    if channel_id is None:
        page = _lookup_channel_page(text)
        if page:
            channel_id = page["channel_id"]
            name = page.get("name") or ""
            handle = page.get("handle") or ""
            resolved_via = "channel_page"

    if channel_id is None:
        raise MonitorError(
            original_error or
            "Could not determine the channel id from that URL. Use the "
            "channel's '.../channel/UC...' URL, or configure a YouTube Data "
            "API key so handles and custom URLs can be resolved.")

    info = fetch_channel_info(channel_id)
    if info.get("name"):
        name = info["name"]
    if not handle and text.startswith("@"):
        handle = text.split("/")[0]

    validated = validate_channel(channel_id)

    return {
        "channel_id": channel_id,
        "name": name,
        "handle": handle,
        "thumbnail_url": info.get("thumbnail_url"),
        "description": info.get("description", ""),
        "resolved_via": resolved_via,
        "validated": validated["validated"],
        "recent_count": validated["recent_count"],
    }


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
        url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("rel") == "alternate":
                url = link.get("href", "")
                match = re.search(r"v=([\w-]{6,})", url)
                if match:
                    video_id = match.group(1)
                    break
        if not video_id:
            video_id = entry.findtext("yt:videoId", "", NS)
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        published = entry.findtext("atom:published", "", NS)

        # YouTube nests the media details inside a ``media:group`` element
        # rather than directly under the entry, so the group is searched
        # first and the entry itself second.
        group = entry.find("media:group", NS)
        scopes = [scope for scope in (group, entry) if scope is not None]

        # The thumbnail is the channel's own published image for that
        # upload, so it can be recorded without downloading the video.
        thumbnail = ""
        for scope in scopes:
            for thumb in scope.findall("media:thumbnail", NS):
                candidate = thumb.get("url", "")
                if candidate:
                    thumbnail = candidate
                    break
            if thumbnail:
                break

        description = ""
        for scope in scopes:
            description = scope.findtext("media:description", "", NS)
            if description:
                break

        entries.append({
            "video_id": video_id,
            "title": entry.findtext("atom:title", "", NS),
            "published_at": published,
            "thumbnail_url": thumbnail,
            "url": url,
            "description": description,
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

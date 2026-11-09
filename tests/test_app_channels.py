"""Regression tests for the V2 channel monitoring layer.

Two rules matter here.

**A channel is never reported as connected unless it was actually
verified.** Identity is resolved through YouTube's own public page and
then validated against the official RSS feed. A channel id is never
invented.

**Public discovery is not processing authorization.** A detected upload
from a monitored channel is metadata only. It becomes an episode that
can be processed only after the user records an explicit decision.
"""
from __future__ import annotations

import httpx
import pytest

from viralclips_app import monitor


# --- channel id extraction ----------------------------------------------------

def test_extract_channel_id_from_a_channel_url():
    assert monitor.extract_channel_id(
        "https://www.youtube.com/channel/UCBR8-60-B28hp2BmDPdntcQ"
    ) == "UCBR8-60-B28hp2BmDPdntcQ"


def test_extract_channel_id_from_a_bare_id():
    assert monitor.extract_channel_id("UCBR8-60-B28hp2BmDPdntcQ") == \
        "UCBR8-60-B28hp2BmDPdntcQ"


def test_extract_channel_id_rejects_a_video_url():
    with pytest.raises(monitor.MonitorError):
        monitor.extract_channel_id("https://www.youtube.com/watch?v=abc123")


def test_extract_channel_id_rejects_a_playlist_url():
    with pytest.raises(monitor.MonitorError) as excinfo:
        monitor.extract_channel_id(
            "https://www.youtube.com/playlist?list=PL1234567890")
    assert "playlist" in str(excinfo.value).lower()


def test_extract_channel_id_rejects_a_handle_without_a_lookup():
    with pytest.raises(monitor.MonitorError):
        monitor.extract_channel_id("@indiasgotlatentofficial")


def test_extract_channel_id_rejects_an_empty_value():
    with pytest.raises(monitor.MonitorError):
        monitor.extract_channel_id("")


# --- public page path handling ------------------------------------------------

def test_page_path_for_a_bare_handle():
    assert monitor._page_path("@SamayRainaOfficial") == "@SamayRainaOfficial"


def test_page_path_for_a_handle_url():
    assert monitor._page_path(
        "https://www.youtube.com/@SamayRainaOfficial") == "@SamayRainaOfficial"


def test_page_path_for_a_handle_url_with_a_trailing_slash():
    assert monitor._page_path(
        "https://www.youtube.com/@SamayRainaOfficial/") == "@SamayRainaOfficial"


def test_page_path_for_a_handle_url_with_a_query_string():
    assert monitor._page_path(
        "https://www.youtube.com/@SamayRainaOfficial?sub_confirmation=1"
    ) == "@SamayRainaOfficial"


def test_page_path_for_a_custom_url():
    assert monitor._page_path("https://www.youtube.com/c/SomeChannel") == \
        "c/SomeChannel"


def test_page_path_for_a_user_url():
    assert monitor._page_path("https://www.youtube.com/user/SomeUser") == \
        "user/SomeUser"


def test_page_path_for_a_channel_url_is_none():
    # A channel URL already contains the id, so no page lookup is needed.
    assert monitor._page_path(
        "https://www.youtube.com/channel/UCBR8-60-B28hp2BmDPdntcQ") is None


def test_page_path_for_a_video_url_is_none():
    assert monitor._page_path(
        "https://www.youtube.com/watch?v=abc") is None


def test_page_path_for_an_empty_value_is_none():
    assert monitor._page_path("") is None
    assert monitor._page_path(None) is None


def test_page_title_cleaning_removes_the_youtube_suffix():
    assert monitor._clean_page_title("Samay Raina - YouTube") == "Samay Raina"


def test_page_title_cleaning_unescapes_html():
    assert monitor._clean_page_title(
        "India&#39;s Got Latent Clips - YouTube") == "India's Got Latent Clips"


# --- channel id validation ----------------------------------------------------

def test_a_malformed_channel_id_is_rejected():
    with pytest.raises(monitor.MonitorError):
        monitor.validate_channel("not-a-channel-id")


def test_an_empty_channel_id_is_rejected():
    with pytest.raises(monitor.MonitorError):
        monitor.validate_channel("")


# --- identity resolution ------------------------------------------------------

def test_resolve_channel_identity_uses_the_official_page(monkeypatch):
    """A handle is resolved through the channel's own public page."""
    page = """
    <html><head>
    <link rel="canonical" href="https://www.youtube.com/channel/UCBR8-60-B28hp2BmDPdntcQ">
    <meta itemprop="channelId" content="UCBR8-60-B28hp2BmDPdntcQ">
    <meta property="og:title" content="India's Got Latent Clips">
    </head><body></body></html>
    """
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return httpx.Response(200, text=page)

    monkeypatch.setattr(monitor.httpx, "get", fake_get)
    monkeypatch.setattr(monitor, "fetch_channel_info",
                        lambda channel_id, key=None: {
                            "channel_id": channel_id, "name": "",
                            "description": "", "thumbnail_url": None,
                            "via_api": False})
    monkeypatch.setattr(monitor, "validate_channel",
                        lambda channel_id: {"channel_id": channel_id,
                                            "validated": True,
                                            "recent_count": 15})

    identity = monitor.resolve_channel_identity("@indiasgotlatentofficial")
    assert identity["channel_id"] == "UCBR8-60-B28hp2BmDPdntcQ"
    assert identity["name"] == "India's Got Latent Clips"
    assert identity["handle"] == "@indiasgotlatentofficial"
    assert identity["resolved_via"] == "channel_page"
    assert identity["validated"] is True
    assert identity["recent_count"] == 15
    assert any("@indiasgotlatentofficial" in url for url in requested)


def test_resolve_channel_identity_reports_failure_honestly(monkeypatch):
    """A handle that cannot be resolved must raise, not be invented."""
    monkeypatch.setattr(monitor.httpx, "get",
                        lambda url, **kwargs: httpx.Response(404, text=""))
    with pytest.raises(monitor.MonitorError):
        monitor.resolve_channel_identity("@doesnotexistatall999")


def test_resolve_channel_identity_rejects_an_empty_input():
    with pytest.raises(monitor.MonitorError):
        monitor.resolve_channel_identity("")


def test_resolve_channel_identity_validates_the_resolved_id(monkeypatch):
    """A resolved id that the RSS feed rejects must not be reported as
    connected."""
    monkeypatch.setattr(monitor, "extract_channel_id",
                        lambda text: "UCBR8-60-B28hp2BmDPdntcQ")
    monkeypatch.setattr(monitor, "fetch_channel_info",
                        lambda channel_id, key=None: {
                            "channel_id": channel_id, "name": "Test",
                            "description": "", "thumbnail_url": None,
                            "via_api": False})

    def failing_validate(channel_id):
        raise monitor.MonitorError("YouTube returned no uploads.")

    monkeypatch.setattr(monitor, "validate_channel", failing_validate)
    with pytest.raises(monitor.MonitorError) as excinfo:
        monitor.resolve_channel_identity("https://www.youtube.com/@someone")
    assert "no uploads" in str(excinfo.value).lower()


def test_resolve_channel_identity_keeps_the_original_error_for_playlists(
        monkeypatch):
    """A playlist URL must still be reported as a playlist."""
    monkeypatch.setattr(monitor.httpx, "get",
                        lambda url, **kwargs: httpx.Response(404, text=""))
    with pytest.raises(monitor.MonitorError) as excinfo:
        monitor.resolve_channel_identity(
            "https://www.youtube.com/playlist?list=PL1234567890")
    assert "playlist" in str(excinfo.value).lower()


# --- RSS parsing --------------------------------------------------------------

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Channel Title</title>
  <entry>
    <id>yt:video:VIDEOID001</id>
    <yt:videoId>VIDEOID001</yt:videoId>
    <title>First upload title</title>
    <published>2026-10-01T10:00:00+00:00</published>
    <updated>2026-10-01T12:00:00+00:00</updated>
    <link rel="alternate" href="https://www.youtube.com/watch?v=VIDEOID001"/>
    <media:group>
      <media:title>First upload title</media:title>
      <media:content url="https://www.youtube.com/v/VIDEOID001?version=3"
                     type="application/x-shockwave-flash" width="640" height="390"/>
      <media:thumbnail url="https://i4.ytimg.com/vi/VIDEOID001/hqdefault.jpg"
                      width="480" height="360"/>
      <media:description>The description of the first upload.</media:description>
      <media:community>
        <media:starRating count="613" average="5.00" min="1" max="5"/>
        <media:statistics views="93736"/>
      </media:community>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:VIDEOID002</id>
    <yt:videoId>VIDEOID002</yt:videoId>
    <title>Second upload title</title>
    <published>2026-09-28T08:30:00+00:00</published>
    <updated>2026-09-28T08:30:00+00:00</updated>
    <link rel="alternate" href="https://www.youtube.com/watch?v=VIDEOID002"/>
    <media:group>
      <media:title>Second upload title</media:title>
      <media:thumbnail url="https://i4.ytimg.com/vi/VIDEOID002/hqdefault.jpg"
                      width="480" height="360"/>
      <media:description>The description of the second upload.</media:description>
    </media:group>
  </entry>
</feed>"""


def test_rss_entries_are_parsed(monkeypatch):
    monkeypatch.setattr(monitor.httpx, "get",
                        lambda url, **kwargs: httpx.Response(200, text=RSS))
    entries = monitor.fetch_recent_uploads_rss("UCBR8-60-B28hp2BmDPdntcQ")
    assert len(entries) == 2
    assert entries[0]["video_id"] == "VIDEOID001"
    assert entries[0]["title"] == "First upload title"
    assert entries[0]["url"] == "https://www.youtube.com/watch?v=VIDEOID001"
    # The thumbnail lives inside media:group, not directly under the entry.
    assert entries[0]["thumbnail_url"] == \
        "https://i4.ytimg.com/vi/VIDEOID001/hqdefault.jpg"
    assert entries[0]["description"] == "The description of the first upload."
    assert entries[0]["published_at"]

def test_rss_limit_is_respected(monkeypatch):
    monkeypatch.setattr(monitor.httpx, "get",
                        lambda url, **kwargs: httpx.Response(200, text=RSS))
    entries = monitor.fetch_recent_uploads_rss("UCBR8-60-B28hp2BmDPdntcQ",
                                                limit=1)
    assert len(entries) == 1


def test_rss_for_a_channel_with_no_uploads_returns_nothing(monkeypatch):
    empty = ('<?xml version="1.0" encoding="UTF-8"?><feed '
             'xmlns="http://www.w3.org/2005/Atom"><title>Empty</title></feed>')
    monkeypatch.setattr(monitor.httpx, "get",
                        lambda url, **kwargs: httpx.Response(200, text=empty))
    assert monitor.fetch_recent_uploads_rss("UCBR8-60-B28hp2BmDPdntcQ") == []


def test_an_rss_http_error_is_reported(monkeypatch):
    monkeypatch.setattr(monitor.httpx, "get",
                        lambda url, **kwargs: httpx.Response(500, text=""))
    with pytest.raises(monitor.MonitorError):
        monitor.fetch_recent_uploads_rss("UCBR8-60-B28hp2BmDPdntcQ")


# --- the API routes -----------------------------------------------------------

def _stub_resolution(monkeypatch, channel_id="UCBR8-60-B28hp2BmDPdntcQ",
                     name="India's Got Latent Clips"):
    monkeypatch.setattr(monitor, "resolve_channel_identity", lambda url: {
        "channel_id": channel_id, "name": name,
        "handle": "@indiasgotlatentofficial",
        "thumbnail_url": None, "description": "",
        "resolved_via": "channel_page", "validated": True,
        "recent_count": 15})


def test_adding_a_channel_stores_the_verified_identity(client, monkeypatch):
    _stub_resolution(monkeypatch)
    response = client.post("/api/channels",
                           json={"name": "India's Got Latent Official",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"})
    assert response.status_code == 200
    body = response.json()
    # The name YouTube reports wins over the label the user typed.
    assert body["channel"]["name"] == "India's Got Latent Clips"
    assert body["channel"]["channel_id"] == "UCBR8-60-B28hp2BmDPdntcQ"
    assert body["channel"]["handle"] == "@indiasgotlatentofficial"
    assert body["validated"] is True
    assert body["resolved_via"] == "channel_page"


def test_adding_a_channel_that_cannot_be_verified_fails(client, monkeypatch):
    def failing(url):
        raise monitor.MonitorError("Could not determine the channel id.")
    monkeypatch.setattr(monitor, "resolve_channel_identity", failing)
    response = client.post("/api/channels",
                           json={"name": "Fake",
                                 "url": "https://www.youtube.com/@nope12345"})
    assert response.status_code == 400
    assert "channel id" in response.json()["detail"].lower()


def test_adding_the_same_channel_twice_is_refused(client, monkeypatch):
    _stub_resolution(monkeypatch)
    payload = {"name": "X", "url": "https://www.youtube.com/@indiasgotlatentofficial"}
    assert client.post("/api/channels", json=payload).status_code == 200
    second = client.post("/api/channels", json=payload)
    assert second.status_code == 409
    assert "already" in second.json()["detail"].lower()


def test_a_detected_upload_starts_as_awaiting_authorization(client, monkeypatch):
    """Public discovery is not permission to process."""
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()

    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda channel_id: [
        {"video_id": "VIDEOID001", "title": "First upload title",
         "published_at": "2026-10-01T10:00:00+00:00",
         "thumbnail_url": "https://i.ytimg.com/vi/VIDEOID001/hqdefault.jpg",
         "url": "https://www.youtube.com/watch?v=VIDEOID001"},
    ])
    check = client.post(f"/api/channels/{created['channel']['id']}/check")
    assert check.status_code == 200
    assert check.json()["new_episodes"] == 1

    episodes = client.get("/api/episodes").json()["episodes"]
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["video_id"] == "VIDEOID001"
    assert episode["title"] == "First upload title"
    assert episode["thumbnail_url"]
    # Not yet authorised for processing.
    assert episode["authorization_state"] == "awaiting_authorization"
    assert episode["processed_at"] is None


def test_checking_twice_does_not_duplicate_an_episode(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda channel_id: [
        {"video_id": "VIDEOID001", "title": "First upload title",
         "published_at": "2026-10-01T10:00:00+00:00",
         "thumbnail_url": None,
         "url": "https://www.youtube.com/watch?v=VIDEOID001"},
    ])
    client.post(f"/api/channels/{created['channel']['id']}/check")
    second = client.post(f"/api/channels/{created['channel']['id']}/check")
    assert second.json()["new_episodes"] == 0
    assert len(client.get("/api/episodes").json()["episodes"]) == 1


def test_a_monitoring_error_is_recorded_and_reported(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()

    def failing(channel_id):
        raise monitor.MonitorError("The RSS feed could not be reached.")
    monkeypatch.setattr(monitor, "fetch_recent_uploads", failing)

    response = client.post(f"/api/channels/{created['channel']['id']}/check")
    assert response.status_code == 502
    assert "RSS" in response.json()["detail"]

    channels = client.get("/api/channels").json()["channels"]
    assert channels[0]["last_error"]
    assert "RSS" in channels[0]["last_error"]


def test_an_episode_can_be_marked_authorized(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda channel_id: [
        {"video_id": "VIDEOID001", "title": "T", "published_at": None,
         "thumbnail_url": None, "url": "u"},
    ])
    client.post(f"/api/channels/{created['channel']['id']}/check")
    episode = client.get("/api/episodes").json()["episodes"][0]

    response = client.patch(f"/api/episodes/{episode['id']}", json={
        "authorization_state": "authorized",
        "note": "I own this video.",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["episode"]["authorization_state"] == "authorized"
    assert body["episode"]["authorization_note"] == "I own this video."


def test_an_episode_can_be_marked_not_authorized(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda channel_id: [
        {"video_id": "VIDEOID001", "title": "T", "published_at": None,
         "thumbnail_url": None, "url": "u"},
    ])
    client.post(f"/api/channels/{created['channel']['id']}/check")
    episode = client.get("/api/episodes").json()["episodes"][0]

    response = client.patch(f"/api/episodes/{episode['id']}", json={
        "authorization_state": "not_authorized",
        "note": "This is someone else's content.",
    })
    assert response.status_code == 200
    assert response.json()["episode"]["authorization_state"] == \
        "not_authorized"


def test_an_unknown_authorization_state_is_refused(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda channel_id: [
        {"video_id": "VIDEOID001", "title": "T", "published_at": None,
         "thumbnail_url": None, "url": "u"},
    ])
    client.post(f"/api/channels/{created['channel']['id']}/check")
    episode = client.get("/api/episodes").json()["episodes"][0]

    response = client.patch(f"/api/episodes/{episode['id']}", json={
        "authorization_state": "totally_made_up"})
    assert response.status_code == 422


# --- metadata backfill --------------------------------------------------------

def test_a_recheck_backfills_a_missing_thumbnail(client, monkeypatch):
    """An episode recorded before thumbnails were parsed keeps its
    identity and gains the thumbnail."""
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    channel_id = created["channel"]["id"]

    # First detection, with no thumbnail available.
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A title",
         "published_at": "2026-10-01T10:00:00+00:00",
         "thumbnail_url": None,
         "url": "https://www.youtube.com/watch?v=VIDEOID001"},
    ])
    client.post(f"/api/channels/{channel_id}/check")
    before = client.get("/api/episodes").json()["episodes"][0]
    assert before["thumbnail_url"] is None
    original_id = before["id"]

    # Second detection, with the thumbnail now available.
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A title",
         "published_at": "2026-10-01T10:00:00+00:00",
         "thumbnail_url": "https://i4.ytimg.com/vi/VIDEOID001/hqdefault.jpg",
         "url": "https://www.youtube.com/watch?v=VIDEOID001"},
    ])
    result = client.post(f"/api/channels/{channel_id}/check")
    assert result.json()["new_episodes"] == 0

    after = client.get("/api/episodes").json()["episodes"][0]
    # The same row, enriched -- not a replacement.
    assert after["id"] == original_id
    assert after["thumbnail_url"] == \
        "https://i4.ytimg.com/vi/VIDEOID001/hqdefault.jpg"


def test_a_source_url_is_always_recorded(client, monkeypatch):
    """The feed supplies the URL for most entries, but the video id is
    enough to build one when it does not."""
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    channel_id = created["channel"]["id"]

    # The feed supplies the URL.
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A title", "published_at": None,
         "thumbnail_url": None,
         "url": "https://www.youtube.com/shorts/VIDEOID001"},
    ])
    client.post(f"/api/channels/{channel_id}/check")
    first = client.get("/api/episodes").json()["episodes"][0]
    assert first["url"] == "https://www.youtube.com/shorts/VIDEOID001"

    # The feed supplies nothing, so the video id is used to build one.
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID002", "title": "Another title",
         "published_at": None, "thumbnail_url": None, "url": ""},
    ])
    client.post(f"/api/channels/{channel_id}/check")
    episodes = client.get("/api/episodes").json()["episodes"]
    built = [e for e in episodes if e["video_id"] == "VIDEOID002"][0]
    assert built["url"] == "https://www.youtube.com/watch?v=VIDEOID002"


def test_a_recheck_never_overwrites_an_existing_thumbnail(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    channel_id = created["channel"]["id"]

    original = "https://i4.ytimg.com/vi/VIDEOID001/hqdefault.jpg"
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A title", "published_at": None,
         "thumbnail_url": original, "url": "u"},
    ])
    client.post(f"/api/channels/{channel_id}/check")

    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A different title",
         "published_at": None, "thumbnail_url": "https://example.test/other.jpg",
         "url": "u2"},
    ])
    client.post(f"/api/channels/{channel_id}/check")

    after = client.get("/api/episodes").json()["episodes"][0]
    assert after["thumbnail_url"] == original
    assert after["title"] == "A title"


def test_a_recheck_never_changes_the_authorization_state(client, monkeypatch):
    """Monitoring must never grant or revoke processing permission."""
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    channel_id = created["channel"]["id"]

    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A title", "published_at": None,
         "thumbnail_url": "https://i4.ytimg.com/vi/VIDEOID001/hqdefault.jpg",
         "url": "u"},
    ])
    client.post(f"/api/channels/{channel_id}/check")
    episode = client.get("/api/episodes").json()["episodes"][0]
    client.patch(f"/api/episodes/{episode['id']}", json={
        "authorization_state": "authorized", "note": "I own this."})

    # Re-check with new metadata.
    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": "VIDEOID001", "title": "A title", "published_at": None,
         "thumbnail_url": None, "url": "u"},
    ])
    client.post(f"/api/channels/{channel_id}/check")

    after = client.get("/api/episodes").json()["episodes"][0]
    assert after["authorization_state"] == "authorized"
    assert after["authorization_note"] == "I own this."


def test_repeated_checks_never_accumulate_episodes(client, monkeypatch):
    _stub_resolution(monkeypatch)
    created = client.post("/api/channels",
                           json={"name": "X",
                                 "url": "https://www.youtube.com/@indiasgotlatentofficial"}).json()
    channel_id = created["channel"]["id"]

    monkeypatch.setattr(monitor, "fetch_recent_uploads", lambda cid: [
        {"video_id": f"VIDEOID{index:03d}", "title": f"Upload {index}",
         "published_at": None,
         "thumbnail_url": f"https://i4.ytimg.com/vi/VIDEOID{index:03d}/hqdefault.jpg",
         "url": f"https://www.youtube.com/watch?v=VIDEOID{index:03d}"}
        for index in range(5)
    ])
    first = client.post(f"/api/channels/{channel_id}/check")
    assert first.json()["new_episodes"] == 5

    for _ in range(3):
        again = client.post(f"/api/channels/{channel_id}/check")
        assert again.json()["new_episodes"] == 0
        assert again.json()["uploads_seen"] == 5

    episodes = client.get("/api/episodes").json()["episodes"]
    assert len(episodes) == 5
    video_ids = [e["video_id"] for e in episodes]
    assert len(video_ids) == len(set(video_ids))

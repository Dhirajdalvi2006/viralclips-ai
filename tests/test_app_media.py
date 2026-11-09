"""Regression tests for the V2 media layer.

The V1 dashboard advertised ``Accept-Ranges`` but never implemented the
range protocol, so the player could not seek inside a clip. These tests
lock in real byte-range behaviour, poster generation, and the refusal to
serve files that live outside the application's own storage.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from viralclips_app import config, media


# --- range parsing ----------------------------------------------------------

def test_no_range_header_means_the_whole_file():
    assert media.parse_range(None, 1000) is None
    assert media.parse_range("", 1000) is None


def test_plain_range_is_inclusive():
    assert media.parse_range("bytes=0-499", 1000) == (0, 499)
    assert media.parse_range("bytes=500-999", 1000) == (500, 999)


def test_open_ended_range_runs_to_the_end_of_the_file():
    assert media.parse_range("bytes=100-", 1000) == (100, 999)


def test_suffix_range_returns_the_tail():
    assert media.parse_range("bytes=-200", 1000) == (800, 999)


def test_suffix_range_larger_than_the_file_returns_everything():
    assert media.parse_range("bytes=-5000", 1000) == (0, 999)


def test_range_end_beyond_the_file_is_clamped():
    assert media.parse_range("bytes=900-99999", 1000) == (900, 999)


def test_start_beyond_the_file_is_not_satisfiable():
    with pytest.raises(media.RangeNotSatisfiable):
        media.parse_range("bytes=1000-1200", 1000)


def test_inverted_range_is_not_satisfiable():
    with pytest.raises(media.RangeNotSatisfiable):
        media.parse_range("bytes=800-200", 1000)


def test_malformed_range_is_not_satisfiable():
    with pytest.raises(media.RangeNotSatisfiable):
        media.parse_range("bytes=abc-def", 1000)


def test_zero_length_suffix_is_not_satisfiable():
    with pytest.raises(media.RangeNotSatisfiable):
        media.parse_range("bytes=-0", 1000)


def test_non_byte_unit_is_ignored_rather_than_rejected():
    # A unit this server does not understand is answered with the whole
    # file rather than an error, which is what the HTTP spec allows.
    assert media.parse_range("items=0-10", 1000) is None


def test_multi_range_request_falls_back_to_the_whole_file():
    assert media.parse_range("bytes=0-10,20-30", 1000) is None


# --- streaming --------------------------------------------------------------

def test_iter_file_yields_the_whole_file(tmp_path: Path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"abcdefghij")
    assert b"".join(media.iter_file(target)) == b"abcdefghij"


def test_iter_file_honours_a_start_offset(tmp_path: Path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"abcdefghij")
    assert b"".join(media.iter_file(target, 3, 6)) == b"defg"


def test_iter_file_streams_in_chunks(tmp_path: Path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"x" * 2500)
    chunks = list(media.iter_file(target, chunk_size=1000))
    assert len(chunks) == 3
    assert sum(len(chunk) for chunk in chunks) == 2500


# --- path confinement -------------------------------------------------------

def test_resolve_media_path_accepts_a_file_inside_storage(tmp_path: Path,
                                                          monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    target = root / "clip.mp4"
    target.write_bytes(b"video")
    monkeypatch.setattr(media, "allowed_roots", lambda: [root])
    assert media.resolve_media_path(str(target)) == target.resolve()


def test_resolve_media_path_refuses_a_file_outside_storage(tmp_path: Path,
                                                           monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("classified", encoding="utf-8")
    monkeypatch.setattr(media, "allowed_roots", lambda: [root])
    with pytest.raises(media.MediaError):
        media.resolve_media_path(str(outside))


def test_resolve_media_path_refuses_a_traversal(tmp_path: Path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"video")
    monkeypatch.setattr(media, "allowed_roots", lambda: [root])
    with pytest.raises(media.MediaError):
        media.resolve_media_path(str(root / ".." / "secret.txt"))


def test_resolve_media_path_refuses_a_missing_file(tmp_path: Path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(media, "allowed_roots", lambda: [root])
    with pytest.raises(media.MediaError):
        media.resolve_media_path(str(root / "nope.mp4"))


def test_resolve_media_path_refuses_an_empty_path():
    with pytest.raises(media.MediaError):
        media.resolve_media_path(None)
    with pytest.raises(media.MediaError):
        media.resolve_media_path("")


def test_media_type_for_known_video_extensions(tmp_path: Path):
    assert media.media_type_for(Path("a.mp4")) == "video/mp4"
    assert media.media_type_for(Path("a.mov")) == "video/quicktime"
    assert media.media_type_for(Path("a.webm")) == "video/webm"
    assert media.media_type_for(Path("a.png")) == "image/png"


def test_media_type_falls_back_to_octet_stream(tmp_path: Path):
    assert media.media_type_for(Path("a.unknown")) == "application/octet-stream"


# --- poster generation ------------------------------------------------------

def _has_ffmpeg() -> bool:
    from shutil import which
    return bool(which("ffmpeg"))


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg is not installed")
def test_extract_poster_writes_a_real_frame(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, capture_output=True,
    )
    poster = tmp_path / "clip.png"
    result = media.extract_poster(video, poster)
    assert result is not None
    assert poster.is_file()
    assert poster.stat().st_size > 0
    # A PNG always starts with this signature.
    assert poster.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg is not installed")
def test_extract_poster_returns_none_for_a_missing_video(tmp_path: Path):
    assert media.extract_poster(tmp_path / "nope.mp4",
                                 tmp_path / "out.png") is None


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg is not installed")
def test_extract_poster_reuses_an_existing_poster(tmp_path: Path):
    poster = tmp_path / "clip.png"
    poster.write_bytes(b"\x89PNG\r\n\x1a\n already here")
    # No video exists, so extraction cannot run; the cached file is kept.
    assert media.extract_poster(tmp_path / "nope.mp4", poster) == poster
    assert poster.read_bytes().endswith(b"already here")


def test_probe_duration_returns_none_for_a_missing_file(tmp_path: Path):
    assert media.probe_duration(tmp_path / "nope.mp4") is None


# --- the HTTP route ---------------------------------------------------------

def _clip_fixture(tmp_path: Path, monkeypatch):
    """Create a clip row backed by a real file inside application storage."""
    from viralclips_app import db
    from viralclips_app.models import Clip

    clip_dir = config.CLIP_DIR
    clip_dir.mkdir(parents=True, exist_ok=True)
    video = clip_dir / "range_test_clip.mp4"
    video.write_bytes(b"0123456789" * 100)

    with db.session_scope() as session:
        clip = Clip(video_id=None, task_id=None, job_id=None, index=0,
                    start_seconds=0.0, end_seconds=10.0, duration_seconds=10.0,
                    score=50.0, file_path=str(video))
        session.add(clip)
        session.flush()
        clip_id = clip.id
    return clip_id, video


@pytest.fixture()
def range_client(tmp_path: Path, monkeypatch):
    """A test client with a real clip whose file lives in storage."""
    from fastapi.testclient import TestClient
    from viralclips_app.main import app

    clip_id, video = _clip_fixture(tmp_path, monkeypatch)
    with TestClient(app) as client:
        yield client, clip_id, video


def test_clip_media_advertises_range_support(range_client):
    client, clip_id, _ = range_client
    response = client.get(f"/media/clip/{clip_id}")
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"


def test_clip_media_serves_the_whole_file_without_a_range(range_client):
    client, clip_id, video = range_client
    response = client.get(f"/media/clip/{clip_id}")
    assert response.status_code == 200
    assert response.content == video.read_bytes()
    assert int(response.headers["content-length"]) == video.stat().st_size


def test_clip_media_returns_partial_content_for_a_range(range_client):
    client, clip_id, video = range_client
    response = client.get(f"/media/clip/{clip_id}",
                          headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert response.content == b"0123456789"
    assert response.headers["content-range"] == "bytes 0-9/1000"
    assert response.headers["accept-ranges"] == "bytes"


def test_clip_media_returns_partial_content_for_a_mid_file_range(range_client):
    client, clip_id, video = range_client
    response = client.get(f"/media/clip/{clip_id}",
                          headers={"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert response.content == video.read_bytes()[100:200]
    assert response.headers["content-range"] == "bytes 100-199/1000"


def test_clip_media_supports_a_suffix_range(range_client):
    client, clip_id, video = range_client
    response = client.get(f"/media/clip/{clip_id}",
                          headers={"Range": "bytes=-100"})
    assert response.status_code == 206
    assert response.content == video.read_bytes()[-100:]


def test_clip_media_supports_an_open_ended_range(range_client):
    client, clip_id, video = range_client
    response = client.get(f"/media/clip/{clip_id}",
                          headers={"Range": "bytes=900-"})
    assert response.status_code == 206
    assert response.content == video.read_bytes()[900:]
    assert response.headers["content-range"] == "bytes 900-999/1000"


def test_clip_media_rejects_an_unsatisfiable_range(range_client):
    client, clip_id, _ = range_client
    response = client.get(f"/media/clip/{clip_id}",
                          headers={"Range": "bytes=5000-6000"})
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */1000"


def test_clip_media_404s_for_an_unknown_clip(range_client):
    client, _, _ = range_client
    assert client.get("/media/clip/999999").status_code == 404


def test_clip_media_refuses_a_file_outside_storage(tmp_path: Path, monkeypatch):
    """A clip row pointing outside storage must not be served."""
    from fastapi.testclient import TestClient
    from viralclips_app import db
    from viralclips_app.main import app
    from viralclips_app.models import Clip

    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not ours" * 10)

    with db.session_scope() as session:
        clip = Clip(video_id=None, task_id=None, job_id=None, index=0,
                    start_seconds=0.0, end_seconds=1.0, duration_seconds=1.0,
                    score=1.0, file_path=str(outside))
        session.add(clip)
        session.flush()
        clip_id = clip.id

    with TestClient(app) as client:
        response = client.get(f"/media/clip/{clip_id}")
    assert response.status_code == 404

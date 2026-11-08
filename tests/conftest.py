"""Shared fixtures for the VIRALCLIPS AI application tests.

Every test runs against a throwaway SQLite database and a throwaway
data directory, so the tests never touch the user's real library,
clips, or job queue.

The application reads its data directory from ``VIRALCLIPS_DATA_DIR``
at import time, so the environment variable has to be set before
``viralclips_app`` is imported. That happens at module import here,
which pytest does before collecting the test modules.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# --- isolate the application state BEFORE importing viralclips_app ------
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="viralclips-tests-"))
os.environ["VIRALCLIPS_DATA_DIR"] = str(_TEST_ROOT)

#: Keep the provider tests away from the real machine credential file.
os.environ["VIRALCLIPS_CREDENTIALS_FILE"] = str(
    _TEST_ROOT / "no-such-credentials.env")

import pytest  # noqa: E402

from viralclips_app import config, db  # noqa: E402
from viralclips_app.db import init_db, session_scope  # noqa: E402
from viralclips_app.models import Base  # noqa: E402
from viralclips_app.models import (Account, ApprovalEvent, Channel, Clip,  # noqa: E402
                                   Episode, Job, Publication, Setting, Task,
                                   Video)

#: Deletion order for the test cleanup. The clips and jobs tables
#: reference each other, so SQLAlchemy cannot sort them; naming the
#: order explicitly avoids the unresolvable-cycle warning.
_DELETION_ORDER = (
    ApprovalEvent.__table__,
    Publication.__table__,
    Clip.__table__,
    Job.__table__,
    Video.__table__,
    Episode.__table__,
    Channel.__table__,
    Task.__table__,
    Account.__table__,
    Setting.__table__,
)


def pytest_sessionfinish(session, exitstatus):
    """Remove the throwaway data directory when the run finishes."""
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Create the schema once for the whole session."""
    init_db()
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    """Empty every table before each test so tests are independent.

    The clips and jobs tables reference each other, so SQLAlchemy
    cannot sort them into a safe deletion order. Foreign key checks
    are switched off for the cleanup instead.

    The pragma has to be set in autocommit mode: SQLite ignores
    ``PRAGMA foreign_keys`` inside a transaction, so running it in a
    transaction would silently leave the setting off and then leak
    that onto a pooled connection for later tests.
    """
    yield
    with db.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for table in _DELETION_ORDER:
            connection.execute(table.delete())
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


@pytest.fixture
def session():
    """A database session with a transaction rolled back afterwards."""
    with session_scope() as active:
        yield active


@pytest.fixture
def client():
    """A FastAPI test client for the application.

    The local API token is read from the running app rather than being
    invented, so the tests exercise the same guard the browser does.
    """
    from fastapi.testclient import TestClient

    from viralclips_app.main import app
    from viralclips_app.security import api_token

    with TestClient(app) as test_client:
        test_client.headers.update({"X-ViralClips-Token": api_token()})
        yield test_client


@pytest.fixture
def anon_client():
    """A client without the token, for testing the auth guard."""
    from fastapi.testclient import TestClient

    from viralclips_app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def real_video_bytes():
    """The bytes of a genuine, playable one-second MP4.

    The upload route validates that what it receives is a readable
    video, so a test that exercises the upload path has to send real
    media rather than placeholder bytes. The file is generated once per
    session with ffmpeg.
    """
    import subprocess

    target = _TEST_ROOT / "fixture.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(target)],
        capture_output=True, timeout=120)
    if result.returncode != 0 or not target.is_file() \
            or target.stat().st_size == 0:
        pytest.skip("ffmpeg could not build the test video fixture")
    return target.read_bytes()

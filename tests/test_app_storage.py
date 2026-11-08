"""Tests for the storage module: backup, restore, cleanup, disk report."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from viralclips_app import storage
from viralclips_app.db import session_scope
from viralclips_app.models import Clip, Task, Video


def _old(days: int = 90):
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)


def _make_clip(path, status="pending", publish_status="not_published",
               created=None, size=1024):
    """Create a clip row backed by a real file on disk."""
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size)
    with session_scope() as session:
        video = Video(title="v", source="", source_type="upload")
        session.add(video)
        session.flush()
        clip = Clip(video_id=video.id, file_path=str(target),
                    approval_status=status, publish_status=publish_status)
        session.add(clip)
        session.flush()
        if created is not None:
            clip.created_at = created
        clip_id = clip.id
    return clip_id


# --- backup ---------------------------------------------------------------

def test_backup_creates_a_readable_database_file():
    with session_scope() as session:
        session.add(Task(name="backup-probe", source_type="upload"))
    info = storage.backup_database(label="probe")
    from pathlib import Path
    assert Path(info["path"]).is_file()
    assert info["size_bytes"] > 0

    connection = sqlite3.connect(info["path"])
    try:
        count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        connection.close()
    assert count >= 1


def test_backup_appears_in_the_backup_list():
    info = storage.backup_database(label="listed")
    names = [entry["name"] for entry in storage.list_backups()]
    assert info["name"] in names


def test_backup_list_is_newest_first():
    first = storage.backup_database(label="older")
    time.sleep(1.1)
    second = storage.backup_database(label="newer")
    names = [entry["name"] for entry in storage.list_backups()]
    assert names.index(second["name"]) < names.index(first["name"])


def test_backup_label_is_sanitised():
    info = storage.backup_database(label="../../evil path!")
    from pathlib import Path
    assert Path(info["path"]).parent == storage.BACKUP_DIR
    assert ".." not in Path(info["path"]).name


# --- validation -----------------------------------------------------------

def test_a_real_backup_validates():
    info = storage.backup_database(label="valid")
    assert storage.validate_backup(info["path"]) is True


def test_a_file_that_is_not_a_database_is_rejected(tmp_path):
    bogus = tmp_path / "not-a-backup.db"
    bogus.write_bytes(b"this is definitely not a sqlite database")
    assert storage.validate_backup(str(bogus)) is False


def test_a_missing_file_is_rejected():
    assert storage.validate_backup("/nonexistent/path/backup.db") is False


def test_a_database_without_our_tables_is_rejected(tmp_path):
    other = tmp_path / "other.db"
    connection = sqlite3.connect(other)
    connection.execute("CREATE TABLE unrelated (id INTEGER)")
    connection.commit()
    connection.close()
    assert storage.validate_backup(str(other)) is False


# --- restore --------------------------------------------------------------

def test_restore_puts_the_backed_up_state_back():
    with session_scope() as session:
        session.add(Task(name="before-backup", source_type="upload"))
    info = storage.backup_database(label="restore")

    with session_scope() as session:
        session.add(Task(name="after-backup", source_type="upload"))
    with session_scope() as session:
        assert session.query(Task).count() == 2

    storage.restore_database(info["path"])

    with session_scope() as session:
        assert session.query(Task).count() == 1
        assert session.query(Task).filter(
            Task.name == "before-backup").count() == 1


def test_restore_takes_a_safety_backup_first():
    info = storage.backup_database(label="safety")
    with session_scope() as session:
        session.add(Task(name="safety-probe", source_type="upload"))
    result = storage.restore_database(info["path"])
    assert result["safety_backup"] is not None
    from pathlib import Path
    assert Path(result["safety_backup"]).is_file()


def test_a_rejected_restore_changes_nothing(tmp_path):
    with session_scope() as session:
        session.add(Task(name="survivor", source_type="upload"))
    bogus = tmp_path / "bad.db"
    bogus.write_bytes(b"not a database")
    with pytest.raises(storage.StorageError):
        storage.restore_database(str(bogus))
    with session_scope() as session:
        assert session.query(Task).filter(
            Task.name == "survivor").count() == 1


def test_restoring_a_missing_file_raises():
    with pytest.raises(storage.StorageError):
        storage.restore_database("/nonexistent/backup.db")


# --- path confinement ------------------------------------------------------

def test_a_restore_from_outside_the_backup_directory_is_refused(tmp_path):
    """A restore may only read from the application's backup directory."""
    outside = tmp_path / "elsewhere.db"
    connection = sqlite3.connect(outside)
    connection.execute("CREATE TABLE jobs (id INTEGER)")
    connection.execute("CREATE TABLE clips (id INTEGER)")
    connection.execute("CREATE TABLE videos (id INTEGER)")
    connection.commit()
    connection.close()

    # The file is a perfectly valid database, so only the path check
    # can stop it.
    assert storage.validate_backup(str(outside)) is True
    with pytest.raises(storage.StorageError) as info:
        storage.restore_database(str(outside))
    assert "backup directory" in str(info.value).lower()


def test_a_traversal_restore_path_is_refused():
    with pytest.raises(storage.StorageError):
        storage.restore_database(
            str(storage.BACKUP_DIR / ".." / ".." / "database" / "viralclips.db"))


def test_an_absolute_path_outside_the_backup_directory_is_refused():
    with pytest.raises(storage.StorageError):
        storage.restore_database(r"C:\Windows\System32\config\SAM")


def test_a_backup_inside_the_backup_directory_is_accepted():
    info = storage.backup_database(label="confinement")
    result = storage.restore_database(info["path"])
    assert result["restored_from"] == str(Path(info["path"]).resolve())


# --- cleanup --------------------------------------------------------------

def test_cleanup_dry_run_deletes_nothing(tmp_path):
    target = tmp_path / "clips" / "old.mp4"
    clip_id = _make_clip(target, created=_old())
    result = storage.cleanup(keep_days=30, dry_run=True)
    assert result["dry_run"] is True
    assert result["removed_clips"] >= 1
    assert target.is_file()
    with session_scope() as session:
        assert session.get(Clip, clip_id) is not None


def test_cleanup_removes_old_unpublished_clips(tmp_path):
    target = tmp_path / "clips" / "old.mp4"
    clip_id = _make_clip(target, created=_old())
    storage.cleanup(keep_days=30, dry_run=False)
    assert not target.exists()
    with session_scope() as session:
        assert session.get(Clip, clip_id) is None


def test_cleanup_never_removes_an_approved_clip(tmp_path):
    target = tmp_path / "clips" / "approved.mp4"
    clip_id = _make_clip(target, status="approved", created=_old())
    result = storage.cleanup(keep_days=30, dry_run=False)
    assert target.is_file()
    with session_scope() as session:
        assert session.get(Clip, clip_id) is not None
    assert any(item["clip_id"] == clip_id for item in result["skipped"])


def test_cleanup_never_removes_a_published_clip(tmp_path):
    target = tmp_path / "clips" / "published.mp4"
    clip_id = _make_clip(target, publish_status="published", created=_old())
    storage.cleanup(keep_days=30, dry_run=False)
    assert target.is_file()
    with session_scope() as session:
        assert session.get(Clip, clip_id) is not None


def test_cleanup_never_removes_a_clip_inside_the_retention_window(tmp_path):
    target = tmp_path / "clips" / "recent.mp4"
    clip_id = _make_clip(target, created=_old(days=1))
    storage.cleanup(keep_days=30, dry_run=False)
    assert target.is_file()
    with session_scope() as session:
        assert session.get(Clip, clip_id) is not None


def test_cleanup_rejects_a_negative_retention():
    with pytest.raises(storage.StorageError):
        storage.cleanup(keep_days=-1)


def test_cleanup_reports_the_space_it_freed(tmp_path):
    target = tmp_path / "clips" / "big.mp4"
    _make_clip(target, created=_old(), size=4096)
    result = storage.cleanup(keep_days=30, dry_run=False)
    assert result["freed_bytes"] >= 4096
    assert result["freed_mb"] >= 0


# --- disk report ----------------------------------------------------------

def test_disk_report_has_the_volume_and_the_threshold():
    report = storage.disk_report()
    assert report["volume"]["free"] > 0
    assert report["volume"]["total"] > 0
    assert report["volume"]["min_free_bytes"] == 2 * 1024 ** 3


def test_disk_report_covers_every_managed_directory():
    report = storage.disk_report()
    names = {row["name"] for row in report["directories"]}
    assert {"database", "videos", "clips", "logs", "exports"} <= names


def test_disk_report_directory_sizes_are_numbers():
    report = storage.disk_report()
    for row in report["directories"]:
        assert isinstance(row["size_bytes"], int)
        assert row["size_bytes"] >= 0


def test_trim_logs_removes_old_logs_only():
    import os

    from pathlib import Path

    from viralclips_app import config
    old = config.LOG_DIR / "old-test.log"
    fresh = config.LOG_DIR / "fresh-test.log"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("old")
    fresh.write_text("fresh")
    old_time = time.time() - 90 * 86400
    os.utime(old, (old_time, old_time))
    try:
        storage.trim_logs(keep_days=30)
        assert not old.exists()
        assert fresh.exists()
    finally:
        if fresh.exists():
            fresh.unlink()
        if old.exists():
            old.unlink()

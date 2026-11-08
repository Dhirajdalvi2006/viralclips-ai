"""Storage management: database backup, restore, cleanup, and disk reporting.

These are operational features a daily-use local application needs:

- **Backup** uses SQLite's online backup API, so the copy is consistent
  even while the worker is writing. The database file is never copied
  byte-for-byte, because a WAL-mode database has a second file with the
  recent transactions and a plain file copy would miss them.
- **Restore** validates the candidate file before it replaces anything,
  and takes a safety backup of the current database first, so a bad
  restore is always recoverable.
- **Cleanup** removes old media files and their database rows, oldest
  first, and never touches a clip that is approved but unpublished.

Everything here is local. Nothing is uploaded and nothing is deleted
without an explicit call.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
from pathlib import Path

from . import config

#: Where backups are written.
BACKUP_DIR = config.DATA_DIR / "backups"

#: The database file itself.
DATABASE_PATH = config.DATABASE_DIR / "viralclips.db"


class StorageError(RuntimeError):
    """A storage operation failed."""


def ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


# --- backup ----------------------------------------------------------------

def backup_database(label: str = "") -> dict:
    """Take a consistent snapshot of the database.

    Uses SQLite's online backup API rather than a file copy, because the
    database runs in WAL mode: a plain copy of the main file can miss
    transactions that are still in the ``-wal`` sidecar.
    """
    ensure_backup_dir()
    if not DATABASE_PATH.is_file():
        raise StorageError("There is no database to back up yet.")

    name = f"viralclips-{_timestamp()}"
    if label:
        safe = "".join(c for c in label if c.isalnum() or c in "-_")[:40]
        if safe:
            name += f"-{safe}"
    target = BACKUP_DIR / f"{name}.db"

    source = sqlite3.connect(str(DATABASE_PATH))
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    except sqlite3.Error as exc:
        raise StorageError(f"Could not write the backup: {exc}") from exc
    finally:
        source.close()

    return {
        "path": str(target),
        "name": target.name,
        "size_bytes": target.stat().st_size,
        "created_at": dt.datetime.now().isoformat(),
    }


def list_backups() -> list[dict]:
    """List available backups, newest first."""
    if not BACKUP_DIR.is_dir():
        return []
    entries = []
    for path in BACKUP_DIR.glob("*.db"):
        stat = path.stat()
        entries.append({
            "path": str(path),
            "name": path.name,
            "size_bytes": stat.st_size,
            "created_at": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return sorted(entries, key=lambda item: item["name"], reverse=True)


def _resolve_backup_path(path: str) -> Path:
    """Resolve a backup path, refusing anything outside the backup dir.

    A restore replaces the live database with the contents of a file,
    so it must only ever read from the application's own backup
    directory. Accepting an arbitrary path would let a request point
    the restore at any file on the machine.
    """
    candidate = Path(path)
    try:
        resolved = candidate.resolve()
        root = BACKUP_DIR.resolve()
    except OSError as exc:
        raise StorageError(
            "That backup path could not be read.") from exc

    if resolved != root and root not in resolved.parents:
        raise StorageError(
            "A restore may only use a backup from the application's own "
            "backup directory. Nothing was changed.")
    return resolved


def validate_backup(path: str) -> bool:
    """True when the file is a readable SQLite database with our tables.

    Checked before a restore replaces anything, so a truncated or
    unrelated file cannot destroy the live database.
    """
    candidate = Path(path)
    if not candidate.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{candidate}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"jobs", "clips", "videos"} <= names:
            return False
        # Prove the file is actually queryable, not just well-formed.
        connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return True
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def restore_database(path: str) -> dict:
    """Restore the database from a backup file.

    The current database is backed up first, so a restore can always be
    undone.
    """
    candidate = _resolve_backup_path(path)
    if not validate_backup(str(candidate)):
        raise StorageError(
            "That file is not a usable VIRALCLIPS AI backup. It was not "
            "applied and nothing was changed.")

    # The live database must not be open while it is being replaced.
    # Windows refuses to unlink a file that still has an open handle,
    # and SQLAlchemy keeps pooled connections open, so the pool has to
    # be disposed first. The next query reconnects to the new file.
    _dispose_engine()

    safety = None
    if DATABASE_PATH.is_file():
        safety = backup_database(label="prerestore")

    # The live database is in WAL mode, so the main file, the -wal file
    # and the -shm file all have to go. Leaving a stale -wal behind
    # would corrupt the restored database.
    for suffix in ("", "-wal", "-shm"):
        live = Path(str(DATABASE_PATH) + suffix)
        if live.exists():
            try:
                live.unlink()
            except PermissionError as exc:
                raise StorageError(
                    "The database file is locked by another process. Stop "
                    "the worker and the API, then restore again. Nothing "
                    "was changed.") from exc

    shutil.copy2(candidate, DATABASE_PATH)
    return {
        "restored_from": str(candidate),
        "safety_backup": safety["path"] if safety else None,
        "restored_at": dt.datetime.now().isoformat(),
    }


def _dispose_engine() -> None:
    """Close every pooled database connection.

    Only used by the restore path, where the database file itself has
    to be replaced on disk.
    """
    try:
        from .db import engine
        engine.dispose()
    except Exception:  # noqa: BLE001  (best effort; the copy below
        #                      raises a clear error if it still fails)
        pass


# --- disk reporting --------------------------------------------------------

def directory_sizes() -> list[dict]:
    """Report the size of every managed directory."""
    rows = []
    for directory in config.ALL_DIRS:
        total = 0
        count = 0
        if directory.is_dir():
            for entry in directory.rglob("*"):
                if entry.is_file():
                    try:
                        total += entry.stat().st_size
                        count += 1
                    except OSError:
                        continue
        rows.append({
            "name": directory.name,
            "path": str(directory),
            "size_bytes": total,
            "file_count": count,
        })
    return rows


def disk_report() -> dict:
    """A full storage report: volume space plus per-directory usage."""
    usage = shutil.disk_usage(str(config.DATA_DIR))
    directories = directory_sizes()
    used_by_app = sum(row["size_bytes"] for row in directories)
    return {
        "volume": {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "free_gb": round(usage.free / 1024 ** 3, 2),
            "enough_for_jobs": usage.free >= config.MIN_FREE_DISK_BYTES,
            "min_free_bytes": config.MIN_FREE_DISK_BYTES,
        },
        "directories": directories,
        "application_bytes": used_by_app,
        "application_gb": round(used_by_app / 1024 ** 3, 3),
        "backup_directory": str(BACKUP_DIR),
        "backup_count": len(list_backups()),
    }


# --- cleanup ----------------------------------------------------------------

def _media_paths(clip) -> list[Path]:
    paths = []
    for value in (clip.file_path, clip.poster_path, clip.srt_path,
                  clip.meta_path):
        if value:
            paths.append(Path(value))
    return paths


def cleanup(keep_days: int = 30, dry_run: bool = True,
            include_published: bool = False) -> dict:
    """Remove old media and their database rows.

    Only clips that are *not* approved and *not* published are eligible,
    so the cleanup can never silently destroy something the user is about
    to publish. The default is a dry run: nothing is deleted until
    ``dry_run=False`` is passed.
    """
    from .db import session_scope
    from .models import Clip, Video

    if keep_days < 0:
        raise StorageError("keep_days cannot be negative.")

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep_days)
    removed_files = []
    removed_bytes = 0
    removed_clips = 0
    removed_videos = 0
    skipped = []

    with session_scope() as session:
        candidates = session.query(Clip).all()
        for clip in candidates:
            created = clip.created_at
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            if created >= cutoff:
                continue
            if clip.approval_status == "approved" and not include_published:
                skipped.append({"clip_id": clip.id,
                                "reason": "approved but not published"})
                continue
            if clip.publish_status == "published" and not include_published:
                skipped.append({"clip_id": clip.id,
                                "reason": "already published"})
                continue

            for path in _media_paths(clip):
                try:
                    if path.is_file():
                        size = path.stat().st_size
                        if not dry_run:
                            path.unlink()
                        removed_bytes += size
                        removed_files.append(str(path))
                except OSError:
                    continue

            removed_clips += 1
            if not dry_run:
                session.delete(clip)

        # Videos whose clips are all gone, and that were uploaded by the
        # user (not fetched from a monitored channel), are dead weight.
        videos = session.query(Video).all()
        for video in videos:
            if video.source_type not in (None, "", "upload"):
                continue
            remaining = session.query(Clip).filter(
                Clip.video_id == video.id).count()
            if remaining:
                continue
            created = video.created_at
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            if created >= cutoff:
                continue
            source = Path(video.source) if video.source else None
            if source and source.is_file() and source.suffix.lower() in (
                    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"):
                try:
                    size = source.stat().st_size
                    if not dry_run:
                        source.unlink()
                    removed_bytes += size
                    removed_files.append(str(source))
                except OSError:
                    pass
            removed_videos += 1
            if not dry_run:
                session.delete(video)

    return {
        "dry_run": dry_run,
        "keep_days": keep_days,
        "removed_clips": removed_clips,
        "removed_videos": removed_videos,
        "removed_files": len(removed_files),
        "freed_bytes": removed_bytes,
        "freed_mb": round(removed_bytes / 1024 ** 2, 2),
        "skipped": skipped,
        "files": removed_files,
    }


def trim_logs(keep_days: int = 30) -> dict:
    """Remove old log files. Never touches the current log."""
    if keep_days < 0:
        raise StorageError("keep_days cannot be negative.")
    cutoff = dt.datetime.now().timestamp() - keep_days * 86400
    removed = []
    freed = 0
    if config.LOG_DIR.is_dir():
        for entry in config.LOG_DIR.iterdir():
            if not entry.is_file():
                continue
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                size = entry.stat().st_size
                entry.unlink()
                removed.append(entry.name)
                freed += size
            except OSError:
                continue
    return {"removed": removed, "freed_bytes": freed,
            "freed_mb": round(freed / 1024 ** 2, 2)}

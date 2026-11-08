"""API-level tests for the storage routes.

These cover the contract the frontend depends on: the routes exist, they
require the local token for mutations, they report real disk numbers,
and they refuse a restore from an unusable file.
"""
from __future__ import annotations

from pathlib import Path


def test_storage_report_returns_real_numbers(client):
    body = client.get("/api/storage").json()
    assert "volume" in body
    assert "directories" in body
    assert body["volume"]["free"] > 0
    assert body["volume"]["total"] > 0
    assert body["volume"]["min_free_bytes"] == 2 * 1024 ** 3
    assert isinstance(body["application_bytes"], int)


def test_storage_report_lists_the_managed_directories(client):
    body = client.get("/api/storage").json()
    names = {row["name"] for row in body["directories"]}
    assert {"database", "videos", "clips", "logs"} <= names


def test_backup_list_is_readable_without_a_token(client):
    body = client.get("/api/storage/backups").json()
    assert "backups" in body
    assert isinstance(body["backups"], list)


def test_creating_a_backup_requires_the_token(anon_client):
    assert anon_client.post("/api/storage/backup").status_code == 403


def test_creating_a_backup_returns_the_new_file(client):
    response = client.post("/api/storage/backup", json={"label": "apitest"})
    assert response.status_code == 200
    body = response.json()
    assert Path(body["path"]).is_file()
    assert body["size_bytes"] > 0


def test_a_created_backup_appears_in_the_list(client):
    created = client.post("/api/storage/backup", json={"label": "listing"})
    names = [entry["name"] for entry in
             client.get("/api/storage/backups").json()["backups"]]
    assert created.json()["name"] in names


def test_restoring_requires_the_token(anon_client):
    assert anon_client.post("/api/storage/restore",
                            json={"path": "x"}).status_code == 403


def test_restoring_without_a_path_is_rejected(client):
    response = client.post("/api/storage/restore", json={})
    assert response.status_code == 400


def test_restoring_an_unusable_file_is_rejected_without_damage(client):
    bogus = Path(client.get("/api/storage").json()["backup_directory"])
    bogus.mkdir(parents=True, exist_ok=True)
    target = bogus / "not-a-backup.db"
    target.write_bytes(b"not a database at all")
    try:
        response = client.post("/api/storage/restore",
                               json={"path": str(target)})
        assert response.status_code == 400
        assert "backup" in response.json()["detail"].lower()
        # The live database still works afterwards.
        assert client.get("/api/health").status_code == 200
    finally:
        if target.exists():
            target.unlink()


def test_cleanup_requires_the_token(anon_client):
    assert anon_client.post("/api/storage/cleanup",
                            json={"keep_days": 30}).status_code == 403


def test_cleanup_defaults_to_a_dry_run(client):
    response = client.post("/api/storage/cleanup", json={"keep_days": 30})
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert "removed_clips" in body
    assert "logs" in body


def test_cleanup_rejects_a_non_numeric_retention(client):
    response = client.post("/api/storage/cleanup",
                            json={"keep_days": "not-a-number"})
    assert response.status_code == 400

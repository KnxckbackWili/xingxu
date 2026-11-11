"""Starting on top of an older version's database, emptying the trash, and backups."""
import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from tests.test_files_history_users import upload
from tests.test_records import snap, url

BACKEND = Path(__file__).resolve().parents[1]
HASH = "$2b$04$Qm1lQm1lQm1lQm1lQm1lQeD3a3dyZ1FqQ0h0bW5hcGhzZWNyZXRzLg"  # any stored hash is carried as it is


def start(data_dir: Path, **env):
    """Initialise the database in a fresh process, as a starting container does."""
    environment = {key: value for key, value in os.environ.items() if key not in ("DATABASE_URL", "SEED_DEMO_USERS", "INITIAL_ADMIN_PASSWORD")}
    environment.update(DATA_DIR=str(data_dir), **env)
    return subprocess.run([sys.executable, "-c", "from app.db import init_db; init_db()"], cwd=BACKEND, env=environment,
                          capture_output=True, text=True)


def old_database(data_dir: Path, users):
    data_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(data_dir / "agvpm.db") as db:
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        db.execute("INSERT INTO alembic_version VALUES ('h0b0000000003')")
        db.execute("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(200), display_name VARCHAR(100), "
                   "role VARCHAR(20), phone VARCHAR(30), is_active BOOLEAN, token_version INTEGER, mfa_enabled BOOLEAN)")
        db.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,0)", users)
        db.execute("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, name VARCHAR(200), status VARCHAR(20))")
        db.execute("INSERT INTO projects VALUES ('p-old', '旧项目', 'executing')")
    (data_dir / "uploads" / "p-old").mkdir(parents=True)
    (data_dir / "uploads" / "p-old" / "photo.jpg").write_bytes(b"old")


def test_an_old_database_is_moved_aside_and_accounts_come_along(tmp_path):
    old_database(tmp_path, [("u1", "boss", HASH, "老板", "admin", "138", 1, 3), ("u2", "wang", HASH, "王强", "employee", "", 1, 0),
                            ("u3", "gone", HASH, "离职的", "pm", "", 0, 0)])
    result = start(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "已原样移到" in result.stderr and "3 个账号" in result.stderr
    aside = [path for path in tmp_path.iterdir() if path.name.startswith("old-")]
    assert len(aside) == 1 and (aside[0] / "uploads" / "p-old" / "photo.jpg").read_bytes() == b"old"
    with sqlite3.connect(aside[0] / "agvpm.db") as old:
        assert old.execute("SELECT name FROM projects").fetchall() == [("旧项目",)]  # untouched
    assert not (tmp_path / "carried-accounts.json").exists() and list((tmp_path / "uploads").iterdir()) == []
    with sqlite3.connect(tmp_path / "agvpm.db") as new:
        tables = {name for (name,) in new.execute("SELECT name FROM sqlite_master WHERE type='table'")} - {"alembic_version", "sqlite_sequence"}
        assert len(tables) == 16 and new.execute("SELECT version_num FROM alembic_version").fetchall() == [("i0c0000000001",)]
        users = new.execute("SELECT username, display_name, role, is_active, password_hash, token_version FROM users ORDER BY username").fetchall()
        assert users == [("boss", "老板", "admin", 1, HASH, 4), ("gone", "离职的", "employee", 0, HASH, 1), ("wang", "王强", "employee", 1, HASH, 1)]
        assert new.execute("SELECT count(*) FROM projects").fetchone() == (0,)
        assert new.execute("SELECT name FROM templates").fetchall() == [("AGV 实施标准模板",)]
        assert new.execute("SELECT count(*) FROM vehicle_types").fetchone() == (7,)
    # the next start changes nothing
    again = start(tmp_path)
    assert again.returncode == 0 and "已原样移到" not in again.stderr
    assert len([path for path in tmp_path.iterdir() if path.name.startswith("old-")]) == 1
    with sqlite3.connect(tmp_path / "agvpm.db") as new:
        assert new.execute("SELECT count(*) FROM users").fetchone() == (3,) and new.execute("SELECT count(*) FROM templates").fetchone() == (1,)


def test_a_first_start_needs_a_way_to_sign_in(tmp_path):
    failed = start(tmp_path / "a")
    assert failed.returncode != 0 and "INITIAL_ADMIN_PASSWORD" in failed.stderr
    assert start(tmp_path / "b", INITIAL_ADMIN_PASSWORD="short").returncode != 0
    assert start(tmp_path / "c", INITIAL_ADMIN_PASSWORD="A-long-enough-1").returncode == 0
    with sqlite3.connect(tmp_path / "c" / "agvpm.db") as db:
        assert db.execute("SELECT username, role FROM users").fetchall() == [("admin", "admin")]
    # an old database whose administrators are all stopped still needs the password
    old_database(tmp_path / "d", [("u2", "wang", HASH, "王强", "employee", "", 1, 0)])
    assert start(tmp_path / "d").returncode != 0
    assert start(tmp_path / "d", INITIAL_ADMIN_PASSWORD="A-long-enough-1").returncode == 0
    with sqlite3.connect(tmp_path / "d" / "agvpm.db") as db:
        assert db.execute("SELECT username, role FROM users ORDER BY username").fetchall() == [("admin", "admin"), ("wang", "employee")]


def test_trash_is_emptied_after_thirty_days(client, staff, admin, project):
    from app import models
    from app.config import UPLOAD_DIR
    from app.db import SessionLocal
    from app.services.cleanup import purge_expired
    from app.time_utils import utcnow
    document, vehicle, step = project["documents"][0], project["vehicles"][0], project["steps"][0]
    pid = project["project"]["id"]
    kept = upload(client, staff, project).json()
    attached = upload(client, staff, project, owner_kind="document", owner_id=document["id"]).json()
    loose = upload(client, staff, project).json()
    client.put(f"/api/projects/{pid}/vehicles/{vehicle['id']}/steps/{step['id']}", headers=staff, json={"done": True})
    issue = client.post(url(project, "issues"), headers=staff, json={"description": "x", "vehicle_id": vehicle["id"]}).json()
    client.delete(url(project, "documents", document["id"]), headers=staff)
    client.delete(url(project, "vehicles", vehicle["id"]), headers=staff)
    client.delete(url(project, "work", project["work"][0]["id"]), headers=staff)
    client.delete(url(project, "work", project["work"][1]["id"]), headers=staff)
    client.delete(f"/api/files/{loose['id']}", headers=staff)
    with SessionLocal() as db:
        assert purge_expired(db) == {"projects": 0, "rows": 0, "files": 0}  # nothing is old enough yet
        long_ago = utcnow() - timedelta(days=31)
        for model, row_id in ((models.Document, document["id"]), (models.Vehicle, vehicle["id"]), (models.WorkItem, project["work"][0]["id"]),
                              (models.File, loose["id"])):
            db.get(model, row_id).deleted_at = long_ago
        db.commit()
        assert purge_expired(db) == {"projects": 0, "rows": 3, "files": 2}
        assert db.get(models.Document, document["id"]) is None and db.get(models.File, attached["id"]) is None
        assert db.query(models.VehicleMark).count() == 0 and db.get(models.Issue, issue["id"]).vehicle_id is None
        assert db.get(models.WorkItem, project["work"][1]["id"]).deleted_at is not None  # deleted yesterday: still restorable
    stored = sorted(path.name for path in (UPLOAD_DIR / pid).iterdir())
    assert stored == [kept["id"]]
    assert client.post(url(project, "work", project["work"][0]["id"]) + "/restore", headers=staff).status_code == 404
    assert client.post(url(project, "work", project["work"][1]["id"]) + "/restore", headers=staff).status_code == 200
    # a project in the trash for a month goes with everything in it; its history lines stay
    client.delete(f"/api/projects/{pid}", headers=admin)
    with SessionLocal() as db:
        db.get(models.Project, pid).deleted_at = utcnow() - timedelta(days=31)
        db.commit()
        assert purge_expired(db)["projects"] == 1
        assert db.query(models.WorkItem).count() == db.query(models.File).count() == db.query(models.Vehicle).count() == 0
        assert db.query(models.ChangeLog).filter_by(project_id=pid).count() > 5
    assert not (UPLOAD_DIR / pid).exists()
    assert snap(client, staff, {"project": {"id": pid}}).get("detail")


def test_encrypted_backup_needs_a_passphrase_and_lists(client, admin):
    assert client.post("/api/system/backups", headers=admin, json={"label": "manual"}).status_code == 400
    assert client.put("/api/system/backup-encryption", headers=admin, json={"passphrase": "test-only-backup-password-2026"}).status_code == 200
    made = client.post("/api/system/backups", headers=admin, json={"label": "manual"})
    assert made.status_code == 200 and made.json()["encrypted"]
    listed = client.get("/api/system/backups", headers=admin).json()
    assert [item["filename"] for item in listed["items"]] == [made.json()["filename"]] and listed["encryption"]["configured"]
    assert client.get(f"/api/system/backups/{made.json()['filename']}", headers=admin).content[:4] != b""
    assert client.delete(f"/api/system/backups/{made.json()['filename']}", headers=admin).status_code == 200
    assert "备份" in {row["kind_label"] for row in client.get("/api/history", headers=admin).json()["items"]}
    assert client.get("/api/system/updates", headers=admin).status_code == 200

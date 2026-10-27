"""T03 retires APIs and schema only after complete, verifiable historical export."""

import io
import json
import os
from datetime import date, datetime
from pathlib import Path
import zipfile

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from migrations import v243_schema as old
from migrations.v3_retirement import RETIRED_TABLES, decrypt_export, finalize_files


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    from app.config import BASE_DIR

    url = os.environ.get(
        "T03_MIGRATION_TEST_DATABASE_URL", f'sqlite:///{tmp_path / "legacy.db"}'
    )
    engine = sa.create_engine(url)
    if not url.startswith("sqlite"):
        # Only an explicit disposable test database may be rebuilt.
        assert any(
            word in engine.url.database for word in ("test", "pytest", "gate", "_ci")
        )
        old.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setattr("app.config.DATABASE_URL", url)
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.config.UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr("app.config.SECRET_KEY", "t03-test-secret-kept-outside-export")
    (tmp_path / "uploads").mkdir()
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.upgrade(cfg, "g3a01b000001")
    yield engine, cfg, tmp_path
    engine.dispose()


def seed_legacy(engine, directory):
    with Session(engine) as db:
        user = old.User(
            id="owner",
            username="owner",
            password_hash="original-hash",
            display_name="现场人员",
            role="worker",
            token_version=9,
            permission_overrides={"project.export": False},
            permission_version=3,
            group_id="old-group",
            skills=["单车调试"],
        )
        db.add(user)
        db.add(old.OrgGroup(id="old-group", name="旧分组"))
        db.flush()
        common = dict(
            manager=user.id,
            created_by=user.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        normal = old.Project(
            id="normal",
            name="真实项目",
            status="planning",
            members=[user.id],
            role_plan={"worker": 2},
            **common,
        )
        demo = old.Project(
            id="demo",
            name="个人演示",
            status="executing",
            members=[user.id],
            is_demo=True,
            **common,
        )
        db.add_all([normal, demo])
        db.flush()
        db.add(old.ProjectMember(project_id=normal.id, user_id=user.id))
        db.add(old.ProjectMember(project_id=demo.id, user_id=user.id))
        phase = old.Phase(id="demo-phase", project_id=demo.id, name="实施")
        db.add(phase)
        db.flush()
        module = old.Module(
            id="demo-module", project_id=demo.id, phase_id=phase.id, name="调试"
        )
        db.add(module)
        db.flush()
        db.add(
            old.Task(
                id="demo-task",
                project_id=demo.id,
                module_id=module.id,
                name="练习",
                reference_docs=[],
            )
        )
        db.flush()
        # Legacy rows omit redundant project_id, so FK OFF cannot be trusted to cascade.
        db.add(
            old.CheckItem(
                id="demo-check", project_id=None, task_id="demo-task", name="安全检查"
            )
        )
        db.add(
            old.PersonalEvent(
                id="private-calendar",
                user_id=user.id,
                project_id=demo.id,
                work_date=date(2026, 1, 2),
                title="私有日程",
            )
        )
        db.add(
            old.Attachment(
                id="normal-file",
                project_id=normal.id,
                filename="共享原件.txt",
                stored_name="shared.txt",
                file_size=6,
                uploaded_by=user.id,
            )
        )
        db.add(
            old.Attachment(
                id="demo-file",
                project_id=demo.id,
                filename="演示私有文件.txt",
                stored_name="demo.txt",
                file_size=4,
                uploaded_by=user.id,
            )
        )
        for identifier, project, attachment, stored in [
            ("unassigned", None, None, "private.txt"),
            ("linked", "normal", "normal-file", "shared.txt"),
            ("known-project", "normal", None, "new.txt"),
        ]:
            db.add(
                old.InboxDocument(
                    id=identifier,
                    filename=identifier + ".txt",
                    stored_name=stored,
                    file_size=6,
                    uploaded_by=user.id,
                    archived_project_id=project,
                    archived_attachment_id=attachment,
                )
            )
        db.add(old.AiChatSession(id="session", user_id=user.id, title="私有聊天"))
        db.flush()
        db.add(
            old.AiChatMessage(
                id="message",
                session_id="session",
                role="user",
                content="private-chat-secret",
            )
        )
        db.add(
            old.AiUserMemory(
                id="memory", user_id=user.id, content="private-memory-secret"
            )
        )
        db.add(
            old.AiApiToken(
                id="legacy-token",
                name="旧令牌",
                token_hash="original-token-hash",
                user_id=user.id,
                scopes=["projects:read", "inbox:read", "change_sets:merge"],
            )
        )
        db.add(
            old.Incident(
                id="incident",
                project_id=normal.id,
                title="临时停电",
                status="open",
                reporter_id=user.id,
                occurred_at=datetime(2026, 1, 3),
                impact={"task_ids": []},
            )
        )
        db.flush()
        db.add(
            old.IncidentAction(
                id="action",
                incident_id="incident",
                project_id=normal.id,
                operator_id=user.id,
                detail="联系电工并恢复供电",
            )
        )
        db.commit()
    for name, data in [
        ("shared.txt", b"shared"),
        ("demo.txt", b"demo"),
        ("private.txt", b"private"),
        ("new.txt", b"new"),
    ]:
        (directory / "uploads" / name).write_bytes(data)


def test_retirement_preserves_normal_projects_accounts_and_all_historical_bytes(
    legacy_db,
):
    engine, cfg, directory = legacy_db
    seed_legacy(engine, directory)
    command.upgrade(cfg, "head")
    inspector = sa.inspect(engine)
    assert not set(RETIRED_TABLES) & set(inspector.get_table_names())
    assert not {"is_demo", "role_plan"} & {
        c["name"] for c in inspector.get_columns("projects")
    }
    assert not {"group_id", "skills"} & {
        c["name"] for c in inspector.get_columns("users")
    }
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT id,name,status FROM projects")
        ).all() == [("normal", "真实项目", "planning")]
        assert connection.execute(
            sa.text(
                "SELECT role,password_hash,token_version,permission_version FROM users"
            )
        ).one() == ("worker", "original-hash", 9, 3)
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM check_items WHERE task_id='demo-task'")
            ).scalar()
            == 0
        )
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM personal_events WHERE project_id='demo'")
            ).scalar()
            == 0
        )
        assert (
            connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM attachments WHERE stored_name='shared.txt'"
                )
            ).scalar()
            == 1
        )
        assert (
            connection.execute(
                sa.text("SELECT COUNT(*) FROM attachments WHERE stored_name='new.txt'")
            ).scalar()
            == 1
        )
        assert (
            connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM change_logs WHERE detail LIKE '%系统迁移关闭%'"
                )
            ).scalar()
            == 1
        )
        scopes = connection.execute(
            sa.select(
                sa.table("ai_api_tokens", sa.column("scopes", sa.JSON())).c.scopes
            )
        ).scalar()
        assert scopes == ["projects:read"]
    root = directory / "migration-exports" / "t03"
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert manifest["deleted_demo_ids"] == ["demo"]
    assert manifest["inbox_destinations"]["linked"]["attachment_id"] == "normal-file"
    assert (
        manifest["inbox_destinations"]["unassigned"]["destination"]
        == "encrypted_owner_export"
    )
    exported = {}
    for item in manifest["exports"]:
        path = root / item["path"]
        assert path.stat().st_mode & 0o777 == 0o600
        data = path.read_bytes()
        assert (
            b"private-chat-secret" not in data and b"private-memory-secret" not in data
        )
        with zipfile.ZipFile(
            io.BytesIO(decrypt_export(data, "t03-test-secret-kept-outside-export"))
        ) as archive:
            exported[item["owner"]] = (
                json.loads(archive.read("records.json")),
                {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name != "records.json"
                },
            )
    private, files = exported["owner"]
    assert private["ai_chat_messages"][0]["content"] == "private-chat-secret"
    assert private["ai_user_memories"][0]["content"] == "private-memory-secret"
    assert private["personal_events"][0]["title"] == "私有日程"
    assert (
        files["files/demo.txt"] == b"demo" and files["files/private.txt"] == b"private"
    )
    csv_path = next((directory / "uploads").glob("t03-incidents-*.csv"))
    csv = csv_path.read_text(encoding="utf-8-sig")
    assert (
        "临时停电" in csv and "联系电工并恢复供电" in csv and "original_status" in csv
    )
    with engine.begin() as connection:
        finalize_files(connection)
    assert (directory / "uploads/shared.txt").read_bytes() == b"shared"
    assert (directory / "uploads/new.txt").read_bytes() == b"new"
    assert not (directory / "uploads/demo.txt").exists()
    assert not (directory / "uploads/private.txt").exists()
    before = sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )
    command.upgrade(cfg, "head")
    with engine.begin() as connection:
        finalize_files(connection)
    assert (
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
        == before
    )


def test_missing_historical_file_blocks_retirement_without_discarding_rows(legacy_db):
    engine, cfg, directory = legacy_db
    seed_legacy(engine, directory)
    (directory / "uploads/private.txt").unlink()
    with pytest.raises(RuntimeError, match="历史文件缺失"):
        command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
            == "g3a01b000001"
        )
        assert (
            connection.execute(sa.text("SELECT COUNT(*) FROM projects")).scalar() == 2
        )
        assert (
            connection.execute(sa.text("SELECT COUNT(*) FROM inbox_documents")).scalar()
            == 3
        )
        assert (
            connection.execute(
                sa.text("SELECT status FROM incidents WHERE id='incident'")
            ).scalar()
            == "open"
        )


def test_wrong_retirement_export_key_cannot_read_private_data(legacy_db):
    engine, cfg, directory = legacy_db
    seed_legacy(engine, directory)
    command.upgrade(cfg, "head")
    from cryptography.exceptions import InvalidTag

    for path in (directory / "migration-exports/t03").rglob("*.agvr"):
        with pytest.raises(InvalidTag):
            decrypt_export(path.read_bytes(), "incorrect-key")


def test_retired_endpoints_and_agent_tools_are_absent(client, admin_headers):
    retired = [
        ("GET", "/api/org/groups"),
        ("GET", "/api/team-templates"),
        ("GET", "/api/inbox/documents"),
        ("GET", "/api/ai/memory"),
        ("POST", "/api/ai/codex/chat"),
        ("POST", "/api/ai-projects/chat"),
        ("POST", "/api/ai-projects/chat/stream"),
        ("GET", "/api/ai-projects/chat/sessions"),
        ("POST", "/api/ai-projects/extract"),
        ("GET", "/api/projects/missing/incidents"),
        ("GET", "/api/projects/missing/change-sets"),
        ("GET", "/api/users/missing/skills"),
        ("GET", "/api/projects/missing/edit-history"),
    ]
    for method, path in retired:
        response = client.request(method, path, headers=admin_headers, json={})
        assert response.status_code == 404, (path, response.status_code, response.text)
    from app.services.ai_mcp import TOOL_SCOPES
    from app.routers.ai_internal import SCOPE_OPTIONS

    assert not any(
        name.startswith("change_set_") or name == "inbox_list" for name in TOOL_SCOPES
    )
    assert not any(
        scope.startswith("change_sets:") or scope == "inbox:read"
        for scope, _ in SCOPE_OPTIONS
    )
    assert client.get("/api/projects", headers=admin_headers).json() == []
    user = client.get("/api/auth/me", headers=admin_headers).json()
    assert not {"group_id", "skills"} & set(user)


def test_old_token_scopes_are_filtered_in_views_and_authentication(
    client, admin_headers
):
    from app.db import SessionLocal
    from app.models import AiApiToken
    from app.services.agent_auth import authenticate_agent

    response = client.post(
        "/api/ai/internal/tokens",
        headers=admin_headers,
        json={
            "name": "旧范围",
            "user_id": "user-admin-001",
            "scopes": ["projects:read"],
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    with SessionLocal() as db:
        row = db.get(AiApiToken, created["id"])
        row.scopes = ["projects:read", "change_sets:merge", "inbox:read"]
        db.commit()
    rows = client.get("/api/ai/internal/tokens", headers=admin_headers).json()["items"]
    assert next(row for row in rows if row["id"] == created["id"])["scopes"] == [
        "projects:read"
    ]
    _, scopes = authenticate_agent("Bearer " + created["token"])
    assert scopes == ["projects:read"]


def test_corrupt_export_prevents_all_source_file_cleanup(legacy_db):
    engine, cfg, directory = legacy_db
    seed_legacy(engine, directory)
    command.upgrade(cfg, "head")
    original_files = {
        path.name: path.read_bytes() for path in (directory / "uploads").iterdir()
    }
    export = next((directory / "migration-exports/t03").rglob("*.agvr"))
    export.write_bytes(export.read_bytes() + b"corrupted")
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="加密导出校验失败"):
            finalize_files(connection)
    assert {
        path.name: path.read_bytes() for path in (directory / "uploads").iterdir()
    } == original_files

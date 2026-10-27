"""System policy CAS, non-delegatable authority, route actions and old-schema safety."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.deps import create_token, get_current_user, require_admin
from app.models import ChangeLog, User
from app.routers.permissions import router
from app.services.system_permissions import (
    PERMISSIONS, catalog, default_permissions, effective_permissions,
    has_permission, permission_for_request, permission_override,
    route_permission, route_permission_exempt, validate_route_permissions,
)


@pytest.fixture()
def policy_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([
            User(id="admin-id", username="admin", display_name="测试管理员", role="admin", password_hash="opaque-password", token_version=3),
            User(id="other-admin", username="other", display_name="另一管理员", role="admin", password_hash="opaque-other"),
            User(id="worker-id", username="worker", display_name="测试成员", role="worker", password_hash="opaque-worker"),
        ])
        db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api")

    @app.post("/api/templates/control")
    @route_permission("system.templates.manage")
    def template_control(_: User = Depends(require_admin)):
        return {"saved": True}

    @app.get("/api/auth/me")
    @route_permission_exempt("测试本人会话资料")
    def me(user: User = Depends(get_current_user)):
        return {"id": user.id, "effective": effective_permissions(user)}

    def fresh_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = fresh_db
    admin = {"Authorization": "Bearer " + create_token(SimpleNamespace(id="admin-id", username="admin", role="admin", token_version=3))}
    # The role claim deliberately lies: permissions must follow the DB actor.
    worker = {"Authorization": "Bearer " + create_token(SimpleNamespace(id="worker-id", username="worker", role="admin", token_version=0))}
    with TestClient(app) as client:
        yield client, admin, worker, sessions
    engine.dispose()


def change(client, headers, values, version=0, target="worker-id"):
    return client.put(f"/api/permissions/users/{target}", headers=headers,
                      json={"version": version, "overrides": values})


def test_catalog_unique_real_actions_and_protected_authority():
    payload = catalog()
    permissions = [p for group in payload["groups"] for p in group["permissions"]]
    assert len(permissions) == len(PERMISSIONS)
    assert PERMISSIONS["system.backups.configure"]["default_roles"] == ["admin"]
    assert not {"system.org.manage", "system.team_templates.view", "system.team_templates.manage", "system.inbox.use"} & set(PERMISSIONS)
    assert len({p["key"] for p in permissions}) == len(permissions)
    assert {r["key"] for r in payload["roles"]} == {"admin", "director", "lead", "pm", "technician", "worker", "intern", "readonly"}
    assert PERMISSIONS["permission.manage"]["admin_locked"] is True
    assert all(p["name"] and p["description"] and p["scope"] and p["risk"] for p in permissions)
    payload["groups"][0]["permissions"][0]["default_roles"].clear()
    assert PERMISSIONS["workspace.view"]["default_roles"]  # callers cannot mutate catalog


def test_legacy_null_inherits_and_explicit_denial_wins_context():
    user = SimpleNamespace(role="pm", is_active=True, permission_overrides=None)
    assert has_permission(user, "projects.create")
    assert not has_permission(user, "project.manage_schedule", default=False)
    assert has_permission(user, "project.manage_schedule", default=True)
    user.permission_overrides = {"project.manage_schedule": False, "system.templates.manage": True}
    assert not has_permission(user, "project.manage_schedule", default=True)
    assert has_permission(user, "system.templates.manage", default=False)
    assert "project.manage_schedule" in default_permissions(user)
    assert "project.manage_schedule" not in effective_permissions(user)
    assert "system.templates.manage" in effective_permissions(user)
    assert not has_permission(user, "unknown")


@pytest.mark.parametrize("malformed", [[], "bad", {"system.templates.manage": 1}, {"system.templates.manage": "true"}])
def test_malformed_legacy_policy_does_not_manufacture_grants(malformed):
    user = SimpleNamespace(role="worker", is_active=True, permission_overrides=malformed)
    assert permission_override(user, "system.templates.manage") is None
    assert not has_permission(user, "system.templates.manage")


def test_protected_manage_only_true_active_role_admin():
    user = SimpleNamespace(role="worker", is_active=True, permission_overrides={"permission.manage": True})
    assert not has_permission(user, "permission.manage", default=True)
    user.role = "admin"
    user.permission_overrides = {"permission.manage": False}
    assert has_permission(user, "permission.manage", default=False)
    user.is_active = False
    assert not effective_permissions(user)




@pytest.mark.parametrize("path,method,capability", [
    ("/api/projects/{project_id}/acceptance", "POST", "project.update"),
    ("/api/projects/{project_id}/vehicle-units", "POST", "project.manage_plan"),
    ("/api/projects/{project_id}/unknown-future-action", "PUT", "project.manage_inventory"),
    ("/api/projects/{project_id}/issues/i/export/quality-form", "GET", "project.export"),
])
def test_declared_project_dependency_is_authoritative_over_path_heuristics(path, method, capability):
    from app.services.permissions import require_project_capability
    app = FastAPI()

    def endpoint(_: object = Depends(require_project_capability(capability))):
        return {}
    app.add_api_route(path, endpoint, methods=[method])
    route = app.routes[-1]
    request = SimpleNamespace(url=SimpleNamespace(path=path.replace("{project_id}", "p")),
                              method=method, scope={"route": route})
    assert permission_for_request(request) == capability


def test_dependency_scan_descends_nested_helpers_and_ignores_unrelated_closure():
    from app.services.permissions import require_project_capability
    capability = "project.update"

    def unrelated():
        return capability

    def wrapped(_: object = Depends(require_project_capability("project.manage_plan")),
                other: object = Depends(unrelated)):
        return None

    app = FastAPI()

    @app.post("/api/projects/{project_id}/other")
    def endpoint(_: object = Depends(wrapped)):
        return {}

    request = SimpleNamespace(url=SimpleNamespace(path="/api/projects/p/other"), method="POST", scope={"route": app.routes[-1]})
    assert permission_for_request(request) == "project.manage_plan"


def test_policy_authority_does_not_follow_forged_jwt_or_delegated_key(policy_api):
    client, admin, worker, sessions = policy_api
    with sessions() as db:
        user = db.get(User, "worker-id")
        user.permission_overrides = {"permission.manage": True}
        db.commit()
    for path in ("/api/permissions/catalog", "/api/permissions/users", "/api/permissions/users/admin-id"):
        assert client.get(path, headers=worker).status_code == 403
    assert change(client, worker, {"projects.create": True}).status_code == 403
    assert client.get("/api/permissions/catalog", headers=admin).status_code == 200


def test_cas_update_clear_audit_and_next_request_effect_same_token(policy_api):
    client, admin, worker, sessions = policy_api
    assert client.post("/api/templates/control", headers=worker).status_code == 403
    saved = change(client, admin, {"system.templates.manage": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert client.post("/api/templates/control", headers=worker).status_code == 200
    stale = change(client, admin, {"projects.create": True}, version=0)
    assert stale.status_code == 409
    denied = change(client, admin, {"system.templates.manage": False}, version=1)
    assert denied.status_code == 200
    assert client.post("/api/templates/control", headers=worker).status_code == 403
    cleared = change(client, admin, {}, version=2)
    assert cleared.status_code == 200 and cleared.json()["overrides"] == {}
    with sessions() as db:
        target = db.get(User, "worker-id")
        assert target.permission_version == 3
        assert target.role == "worker" and target.password_hash == "opaque-worker" and target.token_version == 0
        rows = db.query(ChangeLog).filter(ChangeLog.entity_type == "user_permissions").all()
        assert len(rows) == 3
        assert rows[0].old_value == {"version": 0, "overrides": {}}
        assert rows[-1].new_value == {"version": 3, "overrides": {}}
        assert "password" not in str([r.new_value for r in rows])


@pytest.mark.parametrize("body", [
    {"version": 0, "overrides": {"not.real": True}},
    {"version": 0, "overrides": {"permission.manage": False}},
    {"version": 0, "overrides": {"permission.manage": True}},
    {"version": 0, "overrides": {"projects.create": 1}},
    {"version": 0, "overrides": {"projects.create": "false"}},
    {"version": True, "overrides": {}},
    {"version": -1, "overrides": {}},
    {"version": 0, "overrides": {}, "role": "admin"},
])
def test_invalid_policy_rejected_atomically(policy_api, body):
    client, admin, _, sessions = policy_api
    response = client.put("/api/permissions/users/worker-id", headers=admin, json=body)
    assert response.status_code == 422, response.text
    with sessions() as db:
        assert db.get(User, "worker-id").permission_version == 0
        assert db.get(User, "worker-id").permission_overrides == {}
        assert db.query(ChangeLog).count() == 0


def test_admin_can_deny_own_operations_without_losing_recovery_directory(policy_api):
    client, admin, _, _ = policy_api
    saved = change(client, admin, {"system.users.read": False, "system.backups.restore": False}, target="admin-id")
    assert saved.status_code == 200
    assert "permission.manage" in saved.json()["effective"]
    rows = client.get("/api/permissions/users", headers=admin)
    assert rows.status_code == 200
    assert all(set(row) == {"id", "username", "display_name", "role", "is_active", "permission_version"} for row in rows.json())
    assert client.get("/api/permissions/users/admin-id", headers=admin).status_code == 200


def test_actor_retirement_while_waiting_for_anchor_rejected(policy_api, monkeypatch):
    client, admin, _, sessions = policy_api
    from app.routers import permissions
    original = permissions.lock_record
    first = True

    def retire_during_wait(db, entity, **kwargs):
        nonlocal first
        if first:
            first = False
            # Simulate a committed identity change before the policy lock returns.
            db.execute(text("UPDATE users SET role='worker' WHERE id='admin-id'"))
        original(db, entity, **kwargs)
    monkeypatch.setattr(permissions, "lock_record", retire_during_wait)
    response = change(client, admin, {"projects.create": True})
    assert response.status_code == 403
    with sessions() as db:
        assert db.get(User, "worker-id").permission_version == 0
        assert db.query(ChangeLog).count() == 0


def _migration_module():
    path = Path(__file__).parents[1] / "migrations/versions/b6d4e8f103a2_add_user_system_permissions.py"
    spec = importlib.util.spec_from_file_location("policy_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_old_schema_alembic_adds_only_policy_columns_and_is_idempotent(monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    module = _migration_module()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT, role TEXT, password_hash TEXT, token_version INTEGER)"))
        connection.execute(text("INSERT INTO users VALUES ('a','old-admin','admin','old-hash',9)"))
        old = tuple(connection.execute(text("SELECT * FROM users")).one())
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        module.upgrade()
        row = connection.execute(text("SELECT * FROM users")).one()
        assert tuple(row[:5]) == old
        assert row.permission_overrides is None and row.permission_version == 0
        connection.execute(text("UPDATE users SET permission_overrides='{}',permission_version=7"))
        module.upgrade()
        assert connection.execute(text("SELECT permission_version FROM users")).scalar() == 7
        assert module.down_revision == "a1c7e9b204d6"
    engine.dispose()


def test_actual_alembic_graph_has_one_head_after_latest_acceptance_migration():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    backend = Path(__file__).parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert "d2e7f9a103b4" in {revision.revision for revision in scripts.walk_revisions()}
    assert scripts.get_revision("d2e7f9a103b4").down_revision == "b6d4e8f103a2"
    assert scripts.get_revision("b6d4e8f103a2").down_revision == "a1c7e9b204d6"


def test_postgresql_migration_columns_use_json_and_not_null_default_zero(monkeypatch):
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateColumn
    module = _migration_module()
    added = []
    monkeypatch.setattr(module.sa, "inspect", lambda _: SimpleNamespace(get_columns=lambda _: []))
    monkeypatch.setattr(module, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(as_sql=False),
        get_bind=lambda: object(),
        add_column=lambda table, column: added.append((table, column)),
    ))
    module.upgrade()
    assert [table for table, _ in added] == ["users", "users"]
    statements = [str(CreateColumn(column).compile(dialect=postgresql.dialect())) for _, column in added]
    assert statements[0] == "permission_overrides JSON"
    assert "permission_version INTEGER" in statements[1]
    assert "DEFAULT '0'" in statements[1] and "NOT NULL" in statements[1]


def test_frozen_legacy_postgres_policy_columns_keep_inheritance_defaults():
    from migrations.v243_schema import metadata
    users = metadata.tables['users']
    assert users.c.permission_overrides.nullable
    assert users.c.permission_overrides.server_default is None
    assert not users.c.permission_version.nullable
    assert str(users.c.permission_version.server_default.arg) == '0'


@pytest.mark.parametrize("path,method,expected", [
    ("/api/auth/me", "GET", None),
    ("/api/notifications", "GET", "personal.messages.use"),
    ("/api/notifications/n/read", "POST", "personal.messages.use"),
    ("/api/notifications/read-all", "POST", "personal.messages.use"),
    ("/api/users/all-active", "GET", None),
    ("/api/users", "GET", None),
    ("/api/users/u", "PUT", "system.users.manage"),
    ("/api/users", "POST", "system.users.manage"),
    ("/api/vehicle-types", "GET", None),
    ("/api/vehicle-types/all", "GET", None),
    ("/api/templates/tree", "GET", "system.templates.read"),
    ("/api/templates/import/excel", "POST", "system.template_io.manage"),
    ("/api/templates/t/import/json", "POST", "system.template_io.manage"),
    ("/api/templates/t", "PUT", "system.templates.manage"),
    ("/api/system/backups", "GET", "system.backups.read"),
    ("/api/system/backups", "POST", "system.backups.create"),
    ("/api/system/backups/a.tar.gz", "GET", "system.backups.download"),
    ("/api/system/backups/a.tar.gz", "DELETE", "system.backups.delete"),
    ("/api/system/restore", "POST", "system.backups.restore"),
    ("/api/ai-projects/skill-bundle", "GET", "system.ai.use"),
    ("/api/ai-projects/test-connection", "POST", "system.ai.use"),
    ("/api/ai/internal/tokens", "POST", "system.agent_tokens.manage"),
    ("/api/dashboard/personal-events/e", "DELETE", None),  # retired: authenticated 410 only
    ("/api/dashboard/people-plan/e/self", "PUT", None),
    ("/api/dashboard/people-plan", "GET", None),
    ("/api/dashboard/team-schedule", "GET", None),
    ("/api/dashboard/staffing", "GET", None),
    ("/api/dashboard/people-workload", "GET", None),
    ("/api/dashboard/people-overview", "GET", None),
    ("/api/dashboard/people-summary", "GET", None),
    ("/api/dashboard/stats", "GET", None),
    ("/api/dashboard/trend", "GET", None),
    ("/api/projects/p/schedule/policy", "GET", "project.read"),  # retired daily schedule: read-only 410
    ("/api/projects/p/schedule/preview", "GET", "project.read"),  # retired daily schedule: read-only 410
    ("/api/projects/p/schedule", "GET", "project.read"),
    ("/api/projects/p/procurements/x", "PUT", "project.manage_plan"),
    ("/api/projects/p/tasks/t/deliverables", "POST", None),
    ("/api/projects/p/check-items/i", "PUT", "worker.report"),
    ("/api/projects/p/clone", "POST", ["projects.create", "project.read"]),
    ("/api/projects/p/export/package", "GET", "project.export"),
    ("/api/projects/p/logs", "GET", ["project.read", "system.audit.read"]),
    ("/api/projects/p", "DELETE", "project.delete"),
    ("/api/projects/import/preview", "POST", "system.import.create"),
    ("/api/projects/governance/requests/r/review", "POST", None),
    ("/api/projects/governance/requests", "GET", None),
    ("/api/projects/governance/requests/r/withdraw", "POST", None),
    ("/api/archives/projects/p", "GET", "system.archives.read"),
    ("/api/feedback", "POST", "feedback.submit"),
    ("/api/feedback/f/status", "PATCH", "system.feedback.manage"),
    ("/api/worker/records", "GET", "personal.records.read"),
    ("/api/schedule/calendar", "GET", "project.read"),  # retired calendar: read-only 410
    ("/api/worker/reports/r", "DELETE", None),
    ("/api/worker/operations", "POST", "worker.report"),
    ("/api/worker/records/r", "PUT", "worker.report"),
    ("/api/people/weeks", "GET", None),
    ("/api/worker/sync", "POST", None),
    ("/api/issues/i/reopen", "POST", "project.manage_issues"),
    ("/api/projects/p/task-targets", "PUT", "project.manage_plan"),
    ("/api/projects/p/item-applications/a/status", "PATCH", "project.manage_inventory"),
    ("/api/projects/p/vehicle-units/v/events/e/schedule", "POST", "project.manage_schedule"),
    ("/api/projects/p/vehicle-units/v", "PUT", "project.manage_plan"),
    ("/api/projects/p/vehicle-units/v/events", "POST", "worker.issues"),
    ("/api/projects/p/vehicle-units/v/events/e", "PUT", "worker.issues"),
    ("/api/projects/p/handover-summary", "GET", "project.read"),
    ("/api/projects/p", "PUT", None),
    ("/api/projects/p", "PATCH", None),
    ("/api/projects/p/unknown-future-action", "POST", None),
])
def test_real_route_declarations_preserve_operations_and_shared_candidates(path, method, expected):
    from app.main import app
    from fastapi.routing import APIRoute, _iter_routes_with_context

    route = next((context or original) for original, context in _iter_routes_with_context(app.routes)
                 if isinstance(original, APIRoute)
                 and method in (context or original).methods
                 and (context or original).path_regex.fullmatch(path))
    request = SimpleNamespace(url=SimpleNamespace(path=path), method=method, scope={"route": route})
    result = permission_for_request(request)
    assert result == expected
    assert all(key in PERMISSIONS for key in ([result] if isinstance(result, str) else result or []))


def test_all_production_writes_are_declared_including_lazy_included_routers():
    from app.main import app
    from fastapi.routing import APIRoute, _iter_routes_with_context

    validate_route_permissions(app)
    writes = [(context or original) for original, context in _iter_routes_with_context(app.routes)
              if isinstance(original, APIRoute)
              and set((context or original).methods) - {"GET", "HEAD", "OPTIONS"}]
    assert len(writes) > 100


def test_new_undeclared_write_in_nested_router_fails_startup_check():
    from fastapi import APIRouter

    child, parent, app = APIRouter(), APIRouter(), FastAPI()

    @child.patch("/future")
    def future():
        raise AssertionError("undeclared handler must not run")

    parent.include_router(child, prefix="/nested")
    app.include_router(parent, prefix="/api")
    with pytest.raises(RuntimeError, match=r"PATCH /api/nested/future: 未声明权限"):
        validate_route_permissions(app)


def test_undeclared_authenticated_route_fails_closed_even_without_lifespan_check():
    from fastapi import HTTPException

    request = SimpleNamespace(scope={"route": SimpleNamespace(endpoint=lambda: None)})
    with pytest.raises(HTTPException) as error:
        permission_for_request(request)
    assert error.value.status_code == 403


def test_declarations_validate_unknown_keys_and_document_exemptions():
    with pytest.raises(ValueError, match="未知权限"):
        route_permission("project.typo")
    with pytest.raises(ValueError, match="声明至少"):
        route_permission()
    with pytest.raises(ValueError, match="说明"):
        route_permission_exempt(" ")


def test_route_action_does_not_follow_its_url_name():
    app = FastAPI()

    @app.post("/api/anything-renamed")
    @route_permission("system.templates.manage")
    def action(_: User = Depends(get_current_user)):
        return {}

    validate_route_permissions(app)
    request = SimpleNamespace(scope={"route": app.routes[-1]})
    assert permission_for_request(request) == "system.templates.manage"


def test_unclassified_asgi_mount_cannot_bypass_write_validation():
    app = FastAPI()

    async def unknown_asgi(scope, receive, send):
        raise AssertionError("unclassified mount must not serve requests")

    app.mount("/new-protocol", unknown_asgi)
    with pytest.raises(RuntimeError, match="未声明挂载应用权限边界"):
        validate_route_permissions(app)


def test_hidden_starlette_write_is_also_checked():
    app = FastAPI()

    async def hidden_write(request):
        raise AssertionError("hidden write must not run")

    app.add_route("/hidden", hidden_write, methods=["POST"], include_in_schema=False)
    with pytest.raises(RuntimeError, match="POST /hidden: 未声明权限"):
        validate_route_permissions(app)


def test_action_metadata_without_authentication_cannot_start_a_write_route():
    app = FastAPI()

    @app.post("/accidentally-public")
    @route_permission("system.templates.manage")
    def action():
        return {}

    with pytest.raises(RuntimeError, match="权限声明缺少会话认证依赖"):
        validate_route_permissions(app)

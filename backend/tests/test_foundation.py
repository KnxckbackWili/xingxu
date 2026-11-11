"""The empty system: it starts, people sign in, every route says who may call it."""

def test_health_and_sign_in(client, admin, staff):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/auth/me", headers=admin).json()["role"] == "admin"
    assert client.get("/api/auth/me", headers=staff).json() == {
        "id": client.get("/api/auth/me", headers=staff).json()["id"], "username": "zhangwei", "display_name": "张伟",
        "role": "employee", "is_active": True}
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"}).status_code == 401


def test_every_route_declares_who_may_call_it(client):
    from app.access import api_routes, route_access
    from app.main import app
    routes = list(api_routes(app))
    assert len(routes) > 40
    access = {(sorted(route.methods)[0], route.path): route_access(route) for route in routes}
    assert all(access.values()), [key for key, value in access.items() if not value]
    public = {path for (_, path), value in access.items() if value == "public"}
    assert public == {"/api/auth/login", "/api/auth/refresh", "/api/auth/logout", "/api/{missing_path:path}"}
    admin_only = {key for key, value in access.items() if value == "admin"}
    assert ("DELETE", "/api/projects/{project_id}") in admin_only and ("POST", "/api/users") in admin_only
    assert all(value == "admin" for (_, path), value in access.items()
               if path.startswith(("/api/system", "/api/trash")) or (path.startswith("/api/users") and path != "/api/users/names"))


def test_employees_cannot_use_settings(client, staff, admin):
    for method, path in (("get", "/api/users"), ("get", "/api/system/backups"), ("get", "/api/system/updates"),
                         ("get", "/api/trash/projects")):
        assert getattr(client, method)(path, headers=staff).status_code == 403, path
        assert getattr(client, method)(path, headers=admin).status_code == 200, path


def test_models_match_the_baseline(client):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db import Base, engine
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        from sqlalchemy import inspect
        assert len(set(inspect(connection).get_table_names()) - {"alembic_version", "sqlite_sequence"}) == 16

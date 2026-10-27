"""HTTP and static-serving security regression tests."""

import pytest


def test_health_checks_database_and_sets_security_headers(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"


def test_static_path_cannot_escape_frontend_dist():
    from app.main import _safe_frontend_file

    assert _safe_frontend_file("../../backend/app/main.py") is None


def test_hashed_assets_are_immutable_but_app_shell_is_not(client):
    from app.main import FRONTEND_DIST

    assets = list((FRONTEND_DIST / "assets").glob("*.js"))
    if not assets:
        return

    asset = client.get(f"/assets/{assets[0].name}")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]

    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-store"


def test_fresh_production_seed_requires_admin_password(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import User
    from app.seed.seed_data import seed_all

    db = SessionLocal()
    try:
        db.query(User).delete()
        db.commit()
        monkeypatch.setenv("SEED_DEMO_USERS", "0")
        monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
        with pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
            seed_all(db)
    finally:
        db.rollback()
        db.close()

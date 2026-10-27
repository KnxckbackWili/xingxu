"""HYPE-47 人员可用性（不可用时段）与技能标签测试。

覆盖：不可用时段 CRUD+权限+审计 / 技能标签（按日分配冲突与人员看板已退役）。
"""

from tests.lifecycle_helpers import versioned
from datetime import date, timedelta

from fastapi.testclient import TestClient


def _user_id(db, username: str) -> str:
    from app.models import User
    user = db.query(User).filter(User.username == username).first()
    assert user is not None, f"user {username} not found"
    return user.id


def _worker2_headers(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "worker2", "password": "worker123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ===== 不可用时段 CRUD + 权限 + 审计 =====


def test_unavailability_crud_and_permissions(client, admin_headers, pm_headers, worker_headers):
    from app.db import SessionLocal
    from app.models import User, ChangeLog

    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    # worker 无维护权限 → 403
    r = client.post(f"/api/users/{worker1}/unavailability", headers=worker_headers, json={
        "start_date": "2026-09-01", "end_date": "2026-09-03", "reason": "年假", "note": "陪家人",
    })
    assert r.status_code == 403, r.text

    # PM 登记
    r = client.post(f"/api/users/{worker1}/unavailability", headers=pm_headers, json={
        "start_date": "2026-09-01", "end_date": "2026-09-03", "reason": "年假", "note": "陪家人",
    })
    assert r.status_code == 200, r.text
    ua = r.json()
    assert ua["reason"] == "年假"
    assert ua["start_date"] == "2026-09-01" and ua["end_date"] == "2026-09-03"

    # 审计：写操作落 ChangeLog（org 级，project_id=None）
    db = SessionLocal()
    try:
        audit = (db.query(ChangeLog)
                 .filter(ChangeLog.entity_type == "user", ChangeLog.entity_id == worker1,
                         ChangeLog.action == "create", ChangeLog.project_id.is_(None))
                 .first())
        assert audit is not None, "expected audit log for unavailability create"
        assert "不可用" in (audit.detail or "")
    finally:
        db.close()

    # 本人可查看
    r = client.get(f"/api/users/{worker1}/unavailability", headers=worker_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    # 其他普通 worker 不可查看 → 403
    w2_headers = _worker2_headers(client)
    r = client.get(f"/api/users/{worker1}/unavailability", headers=w2_headers)
    assert r.status_code == 403, r.text

    # PM 修改
    r = client.put(f"/api/users/{worker1}/unavailability/{ua['id']}", headers=pm_headers, json={
        "end_date": "2026-09-05", "note": "延长",
    })
    assert r.status_code == 200, r.text
    assert r.json()["end_date"] == "2026-09-05"

    # 结束日期早于开始日期 → 400
    r = client.post(f"/api/users/{worker1}/unavailability", headers=pm_headers, json={
        "start_date": "2026-09-10", "end_date": "2026-09-05", "reason": "出差",
    })
    assert r.status_code == 400, r.text

    # PM 删除
    r = client.delete(f"/api/users/{worker1}/unavailability/{ua['id']}", headers=pm_headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/users/{worker1}/unavailability", headers=worker_headers)
    assert r.json() == []




# 分配冲突检测与人员看板随按日排程退役（410），见 test_legacy_feature_retirement。


# ===== 技能标签 =====

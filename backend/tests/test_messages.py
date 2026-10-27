from tests.lifecycle_helpers import versioned
"""Message center: notification pagination + batch read tests."""


def _project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "消息中心测试项目",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    # Pagination/read tests require real assignment recipients with project access.
    membership = client.put(f"/api/projects/{pid}", headers=pm_headers,
                            json=versioned(pid, {"members": ["user-worker-001", "user-worker-002"]}))
    assert membership.status_code == 200, membership.text
    return pid


def _notify_worker(client, pm_headers, pid, worker_id, title):
    """Create an issue assigned to a worker (triggers a notification)."""
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": title, "assignee_id": worker_id})
    assert r.status_code == 200, r.json()


def test_notifications_offset_pagination(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    for i in range(3):
        _notify_worker(client, pm_headers, pid, "user-worker-001", f"分页问题{i}")

    # First page: 2 items (desc order)
    r = client.get("/api/notifications", headers=worker_headers, params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    first = r.json()
    assert len(first) == 2

    # Second page: 1 item, no overlap
    r = client.get("/api/notifications", headers=worker_headers, params={"limit": 2, "offset": 2})
    second = r.json()
    assert len(second) == 1
    first_ids = {n["id"] for n in first}
    assert second[0]["id"] not in first_ids

    # Desc order: newest first (third created → index 0)
    assert "分页问题2" in first[0]["title"]


def test_notifications_no_params_backward_compat(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    _notify_worker(client, pm_headers, pid, "user-worker-001", "兼容问题")
    r = client.get("/api/notifications", headers=worker_headers)
    assert r.status_code == 200
    notifs = r.json()
    assert len(notifs) == 1
    assert notifs[0]["title"].startswith("新问题指派给你")


def test_notifications_batch_read_only_own(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    _notify_worker(client, pm_headers, pid, "user-worker-001", "本人问题1")
    _notify_worker(client, pm_headers, pid, "user-worker-001", "本人问题2")
    _notify_worker(client, pm_headers, pid, "user-worker-002", "他人问题")

    # worker1 sees 2, worker2 sees 1
    r = client.get("/api/notifications", headers=worker_headers)
    mine = r.json()
    assert len(mine) == 2

    # worker2's notification id must be ignored when worker1 batch-reads
    r2 = client.post("/api/auth/login", json={"username": "worker2", "password": "worker123"})
    w2_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = client.get("/api/notifications", headers=w2_headers)
    other_id = r.json()[0]["id"]

    r = client.post("/api/notifications/read-batch", headers=worker_headers,
                    json={"ids": [mine[0]["id"], other_id]})
    assert r.status_code == 200
    assert r.json()["updated"] == 1  # only worker1's own notification

    # worker1 unread count decreased by 1
    r = client.get("/api/notifications/unread-count", headers=worker_headers)
    assert r.json()["count"] == 1
    # worker2 unaffected
    r = client.get("/api/notifications/unread-count", headers=w2_headers)
    assert r.json()["count"] == 1


def test_notifications_batch_read_all_clears_count(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    for i in range(3):
        _notify_worker(client, pm_headers, pid, "user-worker-001", f"批量{i}")

    r = client.get("/api/notifications", headers=worker_headers)
    notifs = r.json()
    ids = [n["id"] for n in notifs]
    r = client.post("/api/notifications/read-batch", headers=worker_headers, json={"ids": ids})
    assert r.json()["updated"] == 3

    r = client.get("/api/notifications/unread-count", headers=worker_headers)
    assert r.json()["count"] == 0

    # Is-read persisted
    r = client.get("/api/notifications", headers=worker_headers)
    assert all(n["is_read"] for n in r.json())


def test_legacy_issue_notification_resolves_reporter_without_rewriting_user_content(client, pm_headers, worker_headers):
    from app.db import SessionLocal
    from app.models import Notification

    pid = _project(client, pm_headers)
    created = client.post(f"/api/projects/{pid}/issues", headers=pm_headers,
                          json={"title": "历史文案", "assignee_id": "user-worker-001"}).json()
    reporter = client.get("/api/auth/me", headers=pm_headers).json()
    with SessionLocal() as db:
        notice = db.query(Notification).filter(Notification.entity_id == created["id"]).one()
        notice.content = f"严重程度：medium · 上报人：{reporter['id']}"
        db.commit()
    content = client.get("/api/notifications", headers=worker_headers).json()[0]["content"]
    assert content == f"严重程度：medium · 上报人：{reporter['display_name']}"
    with SessionLocal() as db:
        notice = db.query(Notification).filter(Notification.entity_id == created["id"]).one()
        notice.content = f"用户备注含 medium 和上报人：{reporter['id']}"
        db.commit()
    content = client.get("/api/notifications", headers=worker_headers).json()[0]["content"]
    assert content == f"用户备注含 medium 和上报人：{reporter['id']}"

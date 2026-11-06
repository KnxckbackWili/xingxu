"""Message center: notification pagination + batch read tests."""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "消息中心测试项目",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    return pid


def _notify_worker(client, pm_headers, pid, worker_id, title):
    """Send the worker one project notification."""
    from app.db import SessionLocal
    from app.services.notify import notify
    with SessionLocal() as db:
        notify(db, worker_id, title, "测试通知", ntype="system", project_id=pid)
        db.commit()


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
    assert notifs[0]["title"] == "兼容问题"


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


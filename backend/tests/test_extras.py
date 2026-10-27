"""Attachment + notification tests."""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers, status=None):
    body = {
        "name": "扩展功能测试项目",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    }
    if status is not None:
        body['status'] = status
    r = client.post("/api/projects", headers=pm_headers, json=body)
    assert r.status_code == 200, r.json()
    return r.json()["id"]


# ===== Attachments =====

def test_upload_list_download_delete(client, pm_headers):
    pid = _project(client, pm_headers)
    # Upload
    r = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                    files={"file": ("到货照片.jpg", b"\xff\xd8\xff\xe0fake-jpeg-data", "image/jpeg")})
    assert r.status_code == 200, r.json()
    aid = r.json()["file"]["id"]

    # List
    r = client.get(f"/api/projects/{pid}/documents/files", headers=pm_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["filename"] == "到货照片.jpg"

    # Download
    r = client.get(f"/api/files/{aid}/download", headers=pm_headers)
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xe0fake-jpeg-data"

    # Delete
    r = client.delete(f"/api/files/{aid}", headers=pm_headers)
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}/documents/files", headers=pm_headers)
    assert len(r.json()) == 0


def test_upload_oversize_rejected(client, pm_headers):
    pid = _project(client, pm_headers)
    big = b"x" * (10 * 1024 * 1024 + 1024)  # > 10MB
    r = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                    files={"file": ("big.zip", big, "application/zip")})
    assert r.status_code == 413


def test_worker_cannot_upload(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/documents/files", headers=worker_headers,
                    files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 404  # 不可见项目统一返回 404，避免泄露项目存在性


# ===== Notifications =====

def test_issue_assignment_notifies_assignee(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    assert client.put(f"/api/projects/{pid}", headers=pm_headers,
                      json=versioned(pid, {"members": ["user-worker-001"]})).status_code == 200
    # Create issue assigned to worker1
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "地图建图失败",
        "severity": "high",
        "assignee_id": "user-worker-001",
    })
    assert r.status_code == 200

    # Worker sees notification
    r = client.get("/api/notifications", headers=worker_headers)
    assert r.status_code == 200
    notifs = r.json()
    assert len(notifs) == 1
    assert notifs[0]["title"].startswith("新问题指派给你")
    assert notifs[0]["is_read"] is False

    # Unread count
    r = client.get("/api/notifications/unread-count", headers=worker_headers)
    assert r.json()["count"] == 1

    # Mark read
    r = client.post(f"/api/notifications/{notifs[0]['id']}/read", headers=worker_headers)
    assert r.status_code == 200
    r = client.get("/api/notifications/unread-count", headers=worker_headers)
    assert r.json()["count"] == 0


def test_issue_resolve_notifies_reporter(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    # worker1 加入项目（上报需成员）
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    members = [*client.get(f"/api/projects/{pid}", headers=pm_headers).json()["members"], wid]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": members}))
    # Worker reports an issue (no assignee)
    r = client.post(f"/api/projects/{pid}/issues", headers=worker_headers, json={
        "title": "站点偏差超限",
        "severity": "medium",
    })
    assert r.status_code == 200
    iid = r.json()["id"]

    # PM resolves it
    r = client.put(f"/api/issues/{iid}", headers=pm_headers, json=versioned(iid, {
        "status": "resolved",
        "resolution": "重新标定站点坐标",
    }, 'Issue'))
    assert r.status_code == 200

    # Worker gets notified
    r = client.get("/api/notifications", headers=worker_headers)
    notifs = r.json()
    assert len(notifs) == 1
    assert notifs[0]["title"].startswith("问题已解决")


# ===== 附件挂载实体（v1.2）=====

def test_upload_with_entity_and_filter(client, pm_headers):
    """上传可挂到 issue/task，列表可按 entity 过滤。"""
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={"title": "带附件的问题"})
    iid = r.json()["id"]

    r = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                    files={"file": ("问题照片.jpg", b"\xff\xd8fake", "image/jpeg")},
                    data={"entity_type": "issue", "entity_id": iid})
    assert r.status_code == 200, r.json()
    aid = r.json()["file"]["id"]

    # 按 entity 过滤
    r = client.get(f"/api/projects/{pid}/documents/files?entity_type=issue&entity_id={iid}", headers=pm_headers)
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == aid
    # 项目级列表仍含全部
    r = client.get(f"/api/projects/{pid}/documents/files", headers=pm_headers)
    assert len(r.json()) == 1


def test_upload_with_bad_entity_type(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                    files={"file": ("x.txt", b"hello", "text/plain")},
                    data={"entity_type": "hacker"})
    assert r.status_code == 400


def test_upload_rejects_foreign_or_missing_entity(client, pm_headers):
    pid = _project(client, pm_headers)
    other_pid = _project(client, pm_headers)
    issue = client.post(
        f"/api/projects/{other_pid}/issues",
        headers=pm_headers,
        json={"title": "另一个项目的问题"},
    ).json()

    missing = client.post(
        f"/api/projects/{pid}/documents/files",
        headers=pm_headers,
        files={"file": ("x.txt", b"hello", "text/plain")},
        data={"entity_type": "task"},
    )
    assert missing.status_code == 400

    foreign = client.post(
        f"/api/projects/{pid}/documents/files",
        headers=pm_headers,
        files={"file": ("x.txt", b"hello", "text/plain")},
        data={"entity_type": "issue", "entity_id": issue["id"]},
    )
    assert foreign.status_code == 400


def test_worker_member_can_upload(client, pm_headers, worker_headers):
    """项目成员（现场人员）可上传附件（问题照片/交付文件）。"""
    pid = _project(client, pm_headers)
    # worker1 加入项目
    r = client.get("/api/auth/me", headers=worker_headers)
    wid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    members = [*r.json()["members"], wid]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": members}))

    r = client.post(f"/api/projects/{pid}/documents/files", headers=worker_headers,
                    files={"file": ("现场照片.jpg", b"\xff\xd8photo", "image/jpeg")})
    assert r.status_code == 200, r.json()


# ===== 处理人自动记录（v1.2）=====

def test_start_processing_sets_assignee(client, pm_headers, worker_headers):
    """开始处理时自动把操作者记为处理人（上报不再选处理人）。"""
    pid = _project(client, pm_headers)
    # worker1 加入项目（上报需成员）
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    members = [*client.get(f"/api/projects/{pid}", headers=pm_headers).json()["members"], wid]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": members}))
    r = client.post(f"/api/projects/{pid}/issues", headers=worker_headers, json={"title": "自动处理人"})
    iid = r.json()["id"]

    # pm 开始处理 → 处理人自动记为 pm
    r = client.put(f"/api/issues/{iid}", headers=pm_headers, json=versioned(iid, {"status": "processing"}, 'Issue'))
    assert r.status_code == 200
    r = client.get("/api/auth/me", headers=pm_headers)
    pm_id = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/issues", headers=pm_headers)
    assert r.json()[0]["assignee_id"] == pm_id

    # worker 无权改问题状态（require_pm）
    r = client.put(f"/api/issues/{iid}", headers=worker_headers, json=versioned(iid, {"status": "resolved"}, 'Issue'))
    assert r.status_code == 403


# 按日日程确认通知已随按日排程退役；周计划发布通知见 test_weekly_plans。


def test_mark_all_read(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    assert client.put(f"/api/projects/{pid}", headers=pm_headers,
                      json=versioned(pid, {"members": ["user-worker-001"]})).status_code == 200
    for i in range(3):
        client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
            "title": f"测试问题{i}", "assignee_id": "user-worker-001"})
    r = client.get("/api/notifications/unread-count", headers=worker_headers)
    assert r.json()["count"] == 3

    r = client.post("/api/notifications/read-all", headers=worker_headers)
    assert r.status_code == 200
    r = client.get("/api/notifications/unread-count", headers=worker_headers)
    assert r.json()["count"] == 0

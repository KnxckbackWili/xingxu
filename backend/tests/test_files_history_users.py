"""Files, the history, and accounts."""
from tests.test_records import snap, url


def upload(client, headers, project, name="现场.jpg", data=b"\xff\xd8\xff photo", **form):
    return client.post(f"/api/projects/{project['project']['id']}/files", headers=headers, data=form,
                       files={"file": (name, data, "application/octet-stream")})


def test_upload_under_a_document_an_issue_or_as_other(client, staff, project):
    document = project["documents"][0]
    issue = client.post(url(project, "issues"), headers=staff, json={"description": "外壳划伤"}).json()
    one = upload(client, staff, project, "../../施工方案.pdf", b"%PDF-1.4", owner_kind="document", owner_id=document["id"])
    two = upload(client, staff, project, owner_kind="issue", owner_id=issue["id"])
    three = upload(client, staff, project, "质量问题反馈单.docx", b"PK word")
    assert one.status_code == two.status_code == three.status_code == 200
    assert one.json()["filename"] == "施工方案.pdf" and one.json()["mime"] == "application/pdf" and one.json()["size"] == 8
    files = snap(client, staff, project)["files"]
    assert {(row["owner_kind"], row["owner_id"]) for row in files} == {("document", document["id"]), ("issue", issue["id"]), ("other", None)}
    shown = client.get(f"/api/files/{one.json()['id']}", headers=staff)
    assert shown.content == b"%PDF-1.4" and shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["x-content-type-options"] == "nosniff"
    word = client.get(f"/api/files/{three.json()['id']}", headers=staff)
    assert word.headers["content-disposition"].startswith("attachment") and word.headers["content-type"] == "application/octet-stream"
    assert client.get(f"/api/files/{one.json()['id']}?download=true", headers=staff).headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/files/{one.json()['id']}").status_code == 401


def test_upload_is_refused_when_empty_too_large_or_misplaced(client, staff, project, monkeypatch):
    from uuid import uuid4
    from app.config import UPLOAD_DIR
    from app.services import files as storage
    assert upload(client, staff, project, data=b"").status_code == 400
    assert upload(client, staff, project, owner_kind="document", owner_id="missing").status_code == 404
    assert upload(client, staff, project, owner_kind="vehicle", owner_id="x").status_code == 400
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 10)
    monkeypatch.setattr(storage, "MAX_UPLOAD_MB", 0)
    assert upload(client, staff, project, data=b"x" * 11).status_code == 413
    assert not any(path.is_file() for path in UPLOAD_DIR.rglob("*"))  # nothing half-written stays behind
    monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 0)
    file_id = str(uuid4())
    assert upload(client, staff, project, id=file_id).json()["id"] == upload(client, staff, project, id=file_id).json()["id"]
    assert len(snap(client, staff, project)["files"]) == 1


def test_deleted_files_and_files_of_deleted_rows_disappear_and_return(client, staff, project):
    document = project["documents"][0]
    row = upload(client, staff, project, owner_kind="document", owner_id=document["id"]).json()
    assert client.delete(f"/api/files/{row['id']}", headers=staff).status_code == 200
    assert snap(client, staff, project)["files"] == [] and client.get(f"/api/files/{row['id']}", headers=staff).status_code == 404
    assert client.post(f"/api/files/{row['id']}/restore", headers=staff).status_code == 200
    client.delete(url(project, "documents", document["id"]), headers=staff)
    assert snap(client, staff, project)["files"] == []
    client.post(url(project, "documents", document["id"]) + "/restore", headers=staff)
    assert len(snap(client, staff, project)["files"]) == 1


def test_history_says_who_changed_what_and_offers_restore(client, staff, staff2, admin, project):
    pid, item = project["project"]["id"], project["items"][0]
    vehicle = project["vehicles"][0]
    client.patch(url(project, "items", item["id"]), headers=staff, json={"quantity": {"from": None, "to": 4}})
    client.patch(url(project, "items", item["id"]), headers=staff2, json={"arrived": {"to": True}})
    issue = client.post(url(project, "issues"), headers=staff2, json={"description": "轮子异响", "vehicle_id": vehicle["id"]}).json()
    client.patch(url(project, "issues", issue["id"]), headers=staff, json={"vehicle_id": {"from": vehicle["id"], "to": None}})
    client.delete(url(project, "issues", issue["id"]), headers=staff)
    page = client.get(f"/api/history?project_id={pid}", headers=staff).json()["items"]
    newest = page[0]
    assert (newest["user_name"], newest["kind_label"], newest["action_label"], newest["row_label"]) == ("张伟", "问题", "删除", "轮子异响")
    assert newest["can_restore"] and newest["scope_id"] == pid
    moved = page[1]
    assert (moved["field_label"], moved["old_text"], moved["new_text"]) == ("关联车辆", "车辆1", "")
    ticked = page[3]
    assert (ticked["user_name"], ticked["field_label"], ticked["old_text"], ticked["new_text"]) == ("李娜", "已到", "否", "是")
    amount = page[4]
    assert (amount["field_label"], amount["old_text"], amount["new_text"]) == ("数量", "", "4")
    assert client.post(url(project, "issues", issue["id"]) + "/restore", headers=staff).status_code == 200
    again = client.get(f"/api/history?project_id={pid}&limit=2", headers=staff).json()
    assert again["items"][0]["action_label"] == "恢复" and not again["items"][1]["can_restore"] and again["next_before"]
    older = client.get(f"/api/history?project_id={pid}&before={again['next_before']}", headers=staff).json()["items"]
    assert older[0]["seq"] < again["next_before"]
    mine = client.get(f"/api/history?user_id={issue['created_by']}", headers=staff).json()["items"]
    assert mine and {row["user_name"] for row in mine} == {"李娜"}
    # account and backup events are for administrators
    client.post("/api/users", headers=admin, json={"username": "wang", "display_name": "王强", "password": "Passw0rd-1"})
    assert "账号" not in {row["kind_label"] for row in client.get("/api/history", headers=staff).json()["items"]}
    assert "账号" in {row["kind_label"] for row in client.get("/api/history", headers=admin).json()["items"]}
    assert client.delete("/api/history", headers=admin).status_code in (404, 405)


def test_accounts_two_kinds_and_sessions_end_when_stopped_or_reset(client, admin, staff):
    made = client.post("/api/users", headers=admin, json={"username": "wang", "display_name": "王强", "password": "Passw0rd-1"})
    assert made.status_code == 200 and made.json()["role"] == "employee"
    wang = made.json()["id"]
    for body in ({"username": "wang", "display_name": "x", "password": "Passw0rd-1"}, {"username": "a b", "display_name": "x", "password": "Passw0rd-1"},
                 {"username": "li", "display_name": "x", "password": "short"}, {"username": "li", "display_name": "x", "password": "Passw0rd-1", "role": "pm"}):
        assert client.post("/api/users", headers=admin, json=body).status_code in (400, 422), body
    session = client.post("/api/auth/login", json={"username": "wang", "password": "Passw0rd-1"}).json()
    client.cookies.clear()
    bearer = {"Authorization": "Bearer " + session["access_token"]}
    assert client.get("/api/auth/me", headers=bearer).status_code == 200
    assert client.put(f"/api/users/{wang}", headers=admin, json={"password": "Another-Pass-2"}).status_code == 200
    assert client.get("/api/auth/me", headers=bearer).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "wang", "password": "Another-Pass-2"}).status_code == 200
    client.cookies.clear()
    assert client.put(f"/api/users/{wang}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "wang", "password": "Another-Pass-2"}).status_code == 403
    me = client.get("/api/auth/me", headers=admin).json()["id"]
    assert client.put(f"/api/users/{me}", headers=admin, json={"role": "employee"}).status_code == 400  # the last administrator stays
    assert client.put(f"/api/users/{me}", headers=admin, json={"is_active": False}).status_code == 400
    assert client.put(f"/api/users/{wang}", headers=admin, json={"role": "admin", "is_active": True}).status_code == 200
    assert client.put(f"/api/users/{me}", headers=admin, json={"is_active": False}).status_code == 400  # not oneself
    assert {row["display_name"] for row in client.get("/api/users/names", headers=staff).json()} >= {"王强", "张伟"}


def test_change_my_password_and_login_limit(client, staff):
    changed = client.put("/api/auth/password", headers=staff, json={"old_password": "demo12345", "new_password": "New-Pass-2026"})
    assert changed.status_code == 200
    assert client.get("/api/auth/me", headers=staff).status_code == 401  # the old session is over
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + changed.json()["access_token"]}).status_code == 200
    client.cookies.clear()
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "zhangwei", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "zhangwei", "password": "New-Pass-2026"}).status_code == 429
    assert client.post("/api/auth/login", json={"username": "lina", "password": "demo12345"}).status_code == 200


def test_cookie_sessions_need_the_csrf_header(client):
    assert client.post("/api/auth/login", json={"username": "zhangwei", "password": "demo12345"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/projects", json={"name": "x"}).status_code == 403
    token = client.cookies.get("agvpm_csrf")
    assert client.post("/api/projects", json={"name": "x"}, headers={"X-CSRF-Token": token}).status_code == 200
    assert client.post("/api/auth/logout").status_code in (200, 403)

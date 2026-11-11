"""The project snapshot, 304s, the gap overview, vehicle ticks, deleting and restoring projects."""
from tests.test_records import snap, url


def test_snapshot_is_not_resent_until_something_changes(client, staff, staff2, project):
    pid = project["project"]["id"]
    first = client.get(f"/api/projects/{pid}", headers=staff)
    etag = first.headers["etag"]
    same = client.get(f"/api/projects/{pid}", headers={**staff, "If-None-Match": etag})
    assert same.status_code == 304 and same.content == b"" and same.headers["etag"] == etag
    client.patch(url(project, "work", project["work"][0]["id"]), headers=staff2, json={"done": {"to": True}})
    changed = client.get(f"/api/projects/{pid}", headers={**staff, "If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag and changed.json()["work"][0]["done"]
    # an edit that changes nothing leaves the version alone
    client.patch(url(project, "work", project["work"][0]["id"]), headers=staff2, json={"done": {"to": True}})
    assert client.get(f"/api/projects/{pid}", headers={**staff, "If-None-Match": changed.headers["etag"]}).status_code == 304


def test_overview_counts_the_five_kinds_of_gap(client, staff, project):
    pid = project["project"]["id"]

    def gaps():
        return next(row for row in client.get("/api/overview", headers=staff).json()["projects"] if row["id"] == pid)["gaps"]

    start = gaps()
    assert start["vehicles"]["total"] == 3 and len(start["vehicles"]["missing"]) == 3
    assert start["vehicles"]["missing"][0]["missing"] == [step["name"] for step in project["steps"]]
    assert (len(start["work"]), len(start["issues"]), len(start["documents"]), len(start["items"])) == (14, 0, 10, 5)
    # a vehicle is complete only when every step is ticked
    vehicle = project["vehicles"][0]
    for step in project["steps"][:-1]:
        client.put(f"/api/projects/{pid}/vehicles/{vehicle['id']}/steps/{step['id']}", headers=staff, json={"done": True})
    assert len(gaps()["vehicles"]["missing"]) == 3 and gaps()["vehicles"]["missing"][0]["missing"] == ["交付"]
    client.put(f"/api/projects/{pid}/vehicles/{vehicle['id']}/steps/{project['steps'][-1]['id']}", headers=staff, json={"done": True})
    assert [row["name"] for row in gaps()["vehicles"]["missing"]] == ["车辆2", "车辆3"]
    client.patch(url(project, "work", project["work"][0]["id"]), headers=staff, json={"done": {"to": True}})
    issue = client.post(url(project, "issues"), headers=staff, json={"description": "地面不平"}).json()
    client.patch(url(project, "items", project["items"][0]["id"]), headers=staff, json={"arrived": {"to": True}})
    client.post(f"/api/projects/{pid}/files", headers=staff, data={"owner_kind": "document", "owner_id": project["documents"][0]["id"]},
                files={"file": ("方案.pdf", b"%PDF-1.4 x", "application/pdf")})
    now = gaps()
    assert (len(now["work"]), len(now["issues"]), len(now["documents"]), len(now["items"])) == (13, 1, 9, 4)
    client.patch(url(project, "issues", issue["id"]), headers=staff, json={"is_closed": {"to": True}})
    client.delete(url(project, "documents", project["documents"][1]["id"]), headers=staff)  # not needed here: drop the line
    assert len(gaps()["issues"]) == 0 and len(gaps()["documents"]) == 8


def test_overview_304_and_closed_projects_have_no_gaps(client, staff, project):
    first = client.get("/api/overview", headers=staff)
    assert client.get("/api/overview", headers={**staff, "If-None-Match": first.headers["etag"]}).status_code == 304
    pid = project["project"]["id"]
    closed = client.patch(f"/api/projects/{pid}", headers=staff, json={"is_closed": {"from": False, "to": True}, "customer": {"to": "新客户"}})
    assert closed.status_code == 200 and closed.json()["is_closed"] and closed.json()["customer"] == "新客户"
    again = client.get("/api/overview", headers={**staff, "If-None-Match": first.headers["etag"]})
    assert again.status_code == 200 and again.json()["projects"][0]["gaps"] is None
    assert client.patch(f"/api/projects/{pid}", headers=staff, json={"name": {"from": "别的名字", "to": "x"}}).status_code == 409
    assert client.patch(f"/api/projects/{pid}", headers=staff, json={"name": {"to": ""}}).status_code == 400


def test_tick_a_whole_step_column(client, staff, project):
    pid, step = project["project"]["id"], project["steps"][0]
    assert client.put(f"/api/projects/{pid}/steps/{step['id']}/all", headers=staff, json={"done": True}).json()["changed"] == 3
    assert client.put(f"/api/projects/{pid}/steps/{step['id']}/all", headers=staff, json={"done": True}).json()["changed"] == 0
    marks = snap(client, staff, project)["marks"]
    assert len(marks) == 3 and all(mark["step_id"] == step["id"] and mark["done_at"] for mark in marks)
    vehicle = project["vehicles"][0]["id"]
    client.put(f"/api/projects/{pid}/vehicles/{vehicle}/steps/{step['id']}", headers=staff, json={"done": False})
    assert len(snap(client, staff, project)["marks"]) == 2
    assert client.put(f"/api/projects/{pid}/vehicles/{vehicle}/steps/{step['id']}", headers=staff, json={}).status_code == 400
    assert client.put(f"/api/projects/{pid}/vehicles/missing/steps/{step['id']}", headers=staff, json={"done": True}).status_code == 404


def test_only_administrators_delete_and_restore_projects(client, staff, admin, project):
    pid = project["project"]["id"]
    assert client.delete(f"/api/projects/{pid}", headers=staff).status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers=admin).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=staff).status_code == 404
    assert client.post(url(project, "work"), headers=staff, json={"name": "x"}).status_code == 404
    assert client.get("/api/overview", headers=staff).json()["projects"] == []
    listed = client.get("/api/trash/projects", headers=admin).json()
    assert [row["id"] for row in listed] == [pid] and listed[0]["deleted_by_name"] == "系统管理员"
    assert client.post(f"/api/projects/{pid}/restore", headers=staff).status_code == 403
    assert client.post(f"/api/projects/{pid}/restore", headers=admin).status_code == 200
    assert len(client.get(f"/api/projects/{pid}", headers=staff).json()["work"]) == 14
    client.delete(f"/api/projects/{pid}", headers=admin)
    assert client.delete(f"/api/trash/projects/{pid}", headers=admin).status_code == 200
    assert client.get("/api/trash/projects", headers=admin).json() == []
    assert client.post(f"/api/projects/{pid}/restore", headers=admin).status_code == 404


def test_create_project_validates_and_is_repeatable(client, staff):
    from uuid import uuid4
    pid = str(uuid4())
    for _ in range(2):
        made = client.post("/api/projects", headers=staff, json={"id": pid, "name": "空项目"})
        assert made.status_code == 200 and made.json()["id"] == pid
    assert len(client.get("/api/projects", headers=staff).json()) == 1
    empty = client.get(f"/api/projects/{pid}", headers=staff).json()
    assert empty["steps"] == [] and empty["vehicles"] == []
    for body in ({"name": ""}, {"name": "x", "vehicle_count": 201}, {"name": "x", "vehicle_count": True}, {"name": "x", "template_id": "missing"}):
        assert client.post("/api/projects", headers=staff, json=body).status_code == 400, body

"""Rows of a project's lists: add, edit a cell, collide, delete, restore, reorder."""
from uuid import uuid4

import pytest


def url(project, kind, row_id=""):
    return f"/api/projects/{project['project']['id']}/{kind}" + (f"/{row_id}" if row_id else "")


def snap(client, headers, project):
    return client.get(f"/api/projects/{project['project']['id']}", headers=headers).json()


def test_template_fills_a_new_project(project):
    assert [step["name"] for step in project["steps"]] == ["到货点检", "单车调试", "联调", "试运行", "交付"]
    assert [vehicle["vehicle_no"] for vehicle in project["vehicles"]] == ["车辆1", "车辆2", "车辆3"]
    assert len(project["work"]) == 14 and project["work"][0]["stage"] == "进场准备" and not project["work"][0]["done"]
    assert len(project["documents"]) == 10 and len(project["items"]) == 5
    assert project["items"][2]["quantity"] == 1 and project["items"][2]["unit"] == "套"
    assert project["marks"] == [] and project["issues"] == [] and project["files"] == []
    assert "潜伏式" in project["vehicle_types"] and "张伟" in project["people"].values()


@pytest.mark.parametrize("kind,body,title", [
    ("steps", {"name": "回访"}, "name"), ("vehicles", {"vehicle_no": "A-009", "model": "潜伏式"}, "vehicle_no"),
    ("work", {"stage": "收尾", "name": "清场"}, "name"), ("issues", {"description": "3 号车导航偏移"}, "description"),
    ("documents", {"name": "竣工图"}, "name"), ("items", {"name": "叉齿", "quantity": 2, "unit": "根"}, "name")])
def test_add_a_row_once_even_when_sent_twice(client, staff, project, kind, body, title):
    row_id = str(uuid4())
    first = client.post(url(project, kind), headers=staff, json={"id": row_id, **body})
    assert first.status_code == 200, first.text
    again = client.post(url(project, kind), headers=staff, json={"id": row_id, **body})
    assert again.status_code == 200 and again.json()["id"] == row_id
    rows = snap(client, staff, project)[kind]
    assert [row[title] for row in rows].count(body[title]) == 1
    assert first.json()["created_by"] == client.get("/api/auth/me", headers=staff).json()["id"]


def test_required_unknown_and_malformed_values_are_refused(client, staff, project):
    for kind, body in (("work", {"name": "  "}), ("work", {"name": "x", "owner": "y"}), ("items", {"name": "x", "quantity": "很多"}),
                       ("vehicles", {"vehicle_no": "车辆1"}), ("vehicles", {"vehicle_no": "x" * 101}), ("work", {"id": "not-a-uuid", "name": "x"}),
                       ("vehicle-records", {"content": "换电池"}), ("vehicle-records", {"vehicle_id": str(uuid4()), "content": "换电池"}),
                       ("issues", {"description": "x", "is_closed": "yes"})):
        assert client.post(url(project, kind), headers=staff, json=body).status_code == 400, (kind, body)
    assert client.post(url(project, "weekly-plans"), headers=staff, json={"name": "x"}).status_code == 422
    assert client.post("/api/projects/missing/work", headers=staff, json={"name": "x"}).status_code == 404
    assert client.post(url(project, "work"), json={"name": "x"}).status_code == 401


def test_two_people_editing_different_cells_never_collide(client, staff, staff2, project):
    item = project["items"][0]
    one = client.patch(url(project, "items", item["id"]), headers=staff, json={"quantity": {"from": None, "to": 12}})
    two = client.patch(url(project, "items", item["id"]), headers=staff2, json={"note": {"from": "", "to": "分两批到"}})
    assert one.status_code == two.status_code == 200
    row = next(row for row in snap(client, staff, project)["items"] if row["id"] == item["id"])
    assert row["quantity"] == 12 and row["note"] == "分两批到"


def test_the_same_cell_edited_twice_tells_the_second_person(client, staff, staff2, project):
    item = project["items"][0]
    assert client.patch(url(project, "items", item["id"]), headers=staff, json={"spec": {"from": item["spec"], "to": "600kg"}}).status_code == 200
    late = client.patch(url(project, "items", item["id"]), headers=staff2,
                        json={"spec": {"from": item["spec"], "to": "1000kg"}, "note": {"from": "", "to": "加急"}})
    assert late.status_code == 409
    assert late.json()["conflicts"] == {"spec": {"current": "600kg", "by": "张伟"}}
    row = next(row for row in snap(client, staff, project)["items"] if row["id"] == item["id"])
    assert row["spec"] == "600kg" and row["note"] == ""  # nothing of the refused request was written
    # "use mine": send again, now knowing the current value
    assert client.patch(url(project, "items", item["id"]), headers=staff2, json={"spec": {"from": "600kg", "to": "1000kg"}}).status_code == 200
    # both typed the same thing: not a conflict
    assert client.patch(url(project, "items", item["id"]), headers=staff, json={"spec": {"from": "600kg", "to": "1000kg"}}).status_code == 200


def test_ticks_record_who_and_when_and_are_repeatable(client, staff, staff2, project):
    work = project["work"][0]
    for _ in range(2):
        done = client.patch(url(project, "work", work["id"]), headers=staff, json={"done": {"to": True}})
        assert done.status_code == 200
    body = done.json()
    assert body["done"] and body["done_at"] and project["people"][body["done_by"]] == "张伟"
    cleared = client.patch(url(project, "work", work["id"]), headers=staff2, json={"done": {"to": False}}).json()
    assert not cleared["done"] and cleared["done_by"] is None and cleared["done_at"] is None
    issue = client.post(url(project, "issues"), headers=staff, json={"description": "充电桩不通电"}).json()
    closed = client.patch(url(project, "issues", issue["id"]), headers=staff2,
                          json={"is_closed": {"to": True}, "resolution": {"from": "", "to": "换了保险"}}).json()
    assert closed["is_closed"] and project["people"][closed["closed_by"]] == "李娜" and closed["resolution"] == "换了保险"


def test_fixed_and_unknown_fields_cannot_be_patched(client, staff, project):
    vehicle = project["vehicles"][0]
    record = client.post(url(project, "vehicle-records"), headers=staff, json={
        "vehicle_id": vehicle["id"], "content": "更换驱动轮", "category": "维修", "happened_on": "2026-05-23"}).json()
    assert record["happened_on"] == "2026-05-23"
    other = project["vehicles"][1]["id"]
    assert client.patch(url(project, "vehicle-records", record["id"]), headers=staff, json={"vehicle_id": {"to": other}}).status_code == 400
    assert client.patch(url(project, "vehicle-records", record["id"]), headers=staff, json={"created_by": {"to": "x"}}).status_code == 400
    assert client.patch(url(project, "vehicle-records", record["id"]), headers=staff, json={"content": "x"}).status_code == 400
    assert client.patch(url(project, "vehicle-records", record["id"]), headers=staff, json={"recorded_on": {"to": "5.23"}}).status_code == 400
    assert client.patch(url(project, "vehicles", vehicle["id"]), headers=staff, json={"vehicle_no": {"to": "车辆2"}}).status_code == 400


def test_delete_goes_to_the_trash_and_comes_back(client, staff, staff2, project):
    vehicle = project["vehicles"][0]
    step = project["steps"][0]
    pid = project["project"]["id"]
    client.put(f"/api/projects/{pid}/vehicles/{vehicle['id']}/steps/{step['id']}", headers=staff, json={"done": True})
    client.post(url(project, "vehicle-records"), headers=staff, json={"vehicle_id": vehicle["id"], "content": "保养"})
    assert client.delete(url(project, "vehicles", vehicle["id"]), headers=staff2).json() == {"id": vehicle["id"], "deleted": True}
    assert client.delete(url(project, "vehicles", vehicle["id"]), headers=staff2).status_code == 200  # twice is fine
    after = snap(client, staff, project)
    assert vehicle["id"] not in [row["id"] for row in after["vehicles"]] and after["marks"] == [] and after["vehicle_records"] == []
    assert client.patch(url(project, "vehicles", vehicle["id"]), headers=staff, json={"note": {"to": "x"}}).status_code == 404
    # its number is free meanwhile; restoring then needs the number back
    taken = client.post(url(project, "vehicles"), headers=staff, json={"vehicle_no": "车辆1"}).json()
    assert client.post(url(project, "vehicles", vehicle["id"]) + "/restore", headers=staff).status_code == 400
    client.delete(url(project, "vehicles", taken["id"]), headers=staff)
    assert client.post(url(project, "vehicles", vehicle["id"]) + "/restore", headers=staff).status_code == 200
    back = snap(client, staff, project)
    assert vehicle["id"] in [row["id"] for row in back["vehicles"]] and len(back["marks"]) == 1 and len(back["vehicle_records"]) == 1


def test_reorder_keeps_rows_someone_else_just_added(client, staff, staff2, project):
    ids = [row["id"] for row in project["documents"]]
    added = client.post(url(project, "documents"), headers=staff2, json={"name": "新加的资料"}).json()
    assert client.put(url(project, "documents") + "/order", headers=staff, json={"ids": list(reversed(ids))}).status_code == 200
    assert [row["id"] for row in snap(client, staff, project)["documents"]] == list(reversed(ids)) + [added["id"]]
    assert client.put(url(project, "documents") + "/order", headers=staff, json={"ids": ids + [str(uuid4())]}).status_code == 409
    assert client.put(url(project, "issues") + "/order", headers=staff, json={"ids": []}).status_code == 400

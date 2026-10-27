"""模板任务参考文档：上传/列表/下载/删除 + 生成项目任务自动复制。"""

import io


def _project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "参考文档测试项目", "start_date": "2026-08-10",
        "new_vehicles": False, "end_date": "2026-09-30",
    })
    return r.json()["id"]


def _first_template_task(client, headers):
    """默认模板中未预置参考资料的任务，用于独立 CRUD 测试。

    避开「项目准备」阶段模块（C2-6：其任务不参与项目任务生成）。
    """
    r = client.get("/api/templates/tree", headers=headers)
    assert r.status_code == 200
    mod = next(
        phase["modules"][0]
        for phase in r.json()
        if phase["name"] != "项目准备" and phase["modules"]
    )
    return {**mod["tasks"][1], "module_id": mod["id"]}


def _project_task(tree, name):
    return next(
        task for phase in tree for module in phase["modules"] for task in module["tasks"]
        if task["name"] == name
    )


def test_template_doc_upload_list_download(client, pm_headers, worker_headers, admin_headers):
    t = _first_template_task(client, pm_headers)
    tid, task_id = "default", t["id"]

    # worker 无上传权限
    r = client.post(f"/api/templates/{tid}/tasks/{task_id}/reference-docs",
                    headers=worker_headers, files={"file": ("x.pdf", b"x", "application/pdf")})
    assert r.status_code == 403

    # pm 上传（带说明）
    r = client.post(f"/api/templates/{tid}/tasks/{task_id}/reference-docs",
                    headers=admin_headers, files={"file": ("点位表模板.xlsx", b"fake-excel", "application/vnd.ms-excel")},
                    data={"note": "现场填完交回"})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["filename"] == "点位表模板.xlsx"
    assert doc["note"] == "现场填完交回"

    # 列表（登录可见）
    r = client.get(f"/api/templates/{tid}/tasks/{task_id}/reference-docs", headers=worker_headers)
    assert len(r.json()) == 1

    # 下载
    r = client.get(f"/api/templates/{tid}/tasks/{task_id}/reference-docs/{doc['id']}/download",
                   headers=worker_headers)
    assert r.status_code == 200
    assert r.content == b"fake-excel"

    # 删除（含物理文件）→ 列表空
    r = client.delete(f"/api/templates/{tid}/tasks/{task_id}/reference-docs/{doc['id']}", headers=admin_headers)
    assert r.status_code == 200
    r = client.get(f"/api/templates/{tid}/tasks/{task_id}/reference-docs", headers=pm_headers)
    assert len(r.json()) == 0


def test_generate_copies_reference_docs(client, pm_headers, admin_headers):
    """模板任务带参考文档 → 生成项目任务自动复制（任务 JSON 自包含，可下载）。"""
    t = _first_template_task(client, pm_headers)
    tid, task_id = "default", t["id"]
    r = client.post(f"/api/templates/{tid}/tasks/{task_id}/reference-docs",
                    headers=admin_headers, files={"file": ("施工方案.pdf", b"pdf-body", "application/pdf")},
                    data={"note": "进场前阅读"})
    doc = r.json()

    try:
        pid = _project(client, pm_headers)
        # 生成第一个模块的任务
        r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                        json={"module_ids": [t["module_id"]]})
        assert r.status_code == 200, r.text
        r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
        ptask = _project_task(r.json(), t["name"])
        assert ptask["name"] == t["name"]  # 同名任务已生成
        ptask_id = ptask["id"]  # 项目任务 = 新 UUID
        assert ptask_id != task_id
        r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
        pj = next(x for x in r.json()[0]["modules"][0]["tasks"] if x["id"] == ptask_id)
        refs = pj.get("reference_docs") or []
        assert len(refs) == 1
        assert refs[0]["filename"] == "施工方案.pdf"
        assert refs[0]["note"] == "进场前阅读"

        # 项目任务参考文档下载（成员可见）
        r = client.get(f"/api/projects/{pid}/tasks/{ptask_id}/reference-docs/0/download",
                       headers=pm_headers)
        assert r.status_code == 200
        assert r.content == b"pdf-body"
    finally:
        # 清理模板参考文档（防污染其他用例）
        client.delete(f"/api/templates/{tid}/tasks/{task_id}/reference-docs/{doc['id']}", headers=admin_headers)


def test_generate_without_docs_ok(client, pm_headers):
    """无参考文档的任务生成不受影响。"""
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-01"]})
    assert r.status_code == 200


def test_generate_preserves_existing_reference_snapshot(client, pm_headers, admin_headers):
    """项目参考资料保存为独立快照；模板新增资料不在补充任务时悄悄带入。"""
    t = _first_template_task(client, pm_headers)
    tid, task_id = "default", t["id"]
    pid = _project(client, pm_headers)
    # 先生成（无参考文档）
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": [t["module_id"]]})
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    ptask = _project_task(r.json(), t["name"])
    assert (ptask.get("reference_docs") or []) == []
    try:
        # 模板任务补参考文档
        r = client.post(f"/api/templates/{tid}/tasks/{task_id}/reference-docs",
                        headers=admin_headers, files={"file": ("补充规范.pdf", b"extra", "application/pdf")})
        doc = r.json()
        # 重新生成（幂等跳过已存在任务，但补齐参考文档）
        r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                        json={"module_ids": [t["module_id"]]})
        assert r.status_code == 200
        r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
        ptask2 = _project_task(r.json(), t["name"])
        refs = ptask2.get("reference_docs") or []
        assert refs == []
        # 幂等：再生成不重复
        client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": [t["module_id"]]})
        r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
        assert len(_project_task(r.json(), t["name"]).get("reference_docs") or []) == 0
    finally:
        client.delete(f"/api/templates/{tid}/tasks/{task_id}/reference-docs/{doc['id']}", headers=admin_headers)

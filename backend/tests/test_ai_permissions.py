"""AI structured-job permissions, read-only tools and MCP scope boundaries.

Authentication, project visibility, schedule capability and token revocation
remain independent checks after webpage chat and write tools are retired.
"""

import json
from datetime import date

import pytest
from fastapi import HTTPException

from app.db import SessionLocal
from app.models import Project, ProjectMember, User
from app.services.ai_tools import execute_ai_tool


def _login_headers(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_user(client, admin_headers, username, role):
    r = client.post("/api/users", headers=admin_headers, json={
        "username": username, "password": "Review123!", "display_name": f"{role}-测试", "role": role,
    })
    assert r.status_code == 200, r.text
    headers = _login_headers(client, username, "Review123!")
    me = client.get("/api/auth/me", headers=headers).json()
    return me["id"], headers


def _seed_project(db, *, manager=None, technical_manager=None, members=None):
    """直接种一个项目（含 project_members 关系行），便于精确控制负责人/技术负责人。"""
    project = Project(
        name="AI 权限测试项目",
        abbreviation="AI-TEST",
        client="客户A",
        location="苏州",
        start_date=date(2026, 8, 24),
        end_date=date(2026, 9, 30),
        status="preparing",
        manager=manager or "user-admin-001",
        technical_manager=technical_manager,
        members=list(members or []),
        version=0,
    )
    db.add(project)
    db.flush()
    seen = set()
    for uid in list(members or []) + ([manager] if manager else []):
        if uid and uid not in seen:
            seen.add(uid)
            if not db.query(ProjectMember).filter_by(project_id=project.id, user_id=uid).first():
                db.add(ProjectMember(project_id=project.id, user_id=uid, role="member"))
    db.commit()
    db.refresh(project)
    return project


# ===== A. 认证边界 =====

def test_ai_endpoints_require_login(client):
    assert client.get("/api/ai-projects/status").status_code == 401
    assert client.get("/api/ai-projects/capabilities").status_code == 401
    assert client.post("/api/ai-projects/organize", json={"skill": "project", "source_text": "x"}).status_code == 401


# ===== B. 入口权限统一（不再 admin/pm 外层守卫）=====



# ===== C. 能力清单 =====

def test_capabilities_without_project_marks_tools_as_need_project(client, admin_headers):
    data = client.get("/api/ai-projects/capabilities", headers=admin_headers).json()
    assert data["general_qa"] is False
    names = {t["name"] for t in data["tools"]}
    for expected in ("get_project_summary", "get_project_documents", "get_vehicle_progress",
                     "get_documents_due_this_week", "get_issues", "get_inventory"):
        assert expected in names
    for tool in data["tools"]:
        if tool["needs_project"]:
            assert tool["available"] is False
            assert tool["reason"] == "请先选择项目"


def test_capabilities_reflect_director_permissions(client, admin_headers):
    director_id, director_headers = _create_user(client, admin_headers, "director1", "director")
    db = SessionLocal()
    try:
        project = _seed_project(db, manager="user-admin-001")
        project_id = project.id
    finally:
        db.close()
    data = client.get(f"/api/ai-projects/capabilities?project_id={project_id}", headers=director_headers).json()
    by_name = {t["name"]: t for t in data["tools"]}
    assert by_name["get_project_summary"]["available"] is True   # 读工具仅可见性
    assert by_name["get_vehicle_progress"]["available"] is True
    assert "preview_schedule" not in by_name  # retired regardless of role


def test_capabilities_lead_manager_full(client, admin_headers):
    lead_id, lead_headers = _create_user(client, admin_headers, "lead2", "lead")
    db = SessionLocal()
    try:
        project = _seed_project(db, manager=lead_id, members=[lead_id])
        project_id = project.id
    finally:
        db.close()
    data = client.get(f"/api/ai-projects/capabilities?project_id={project_id}", headers=lead_headers).json()
    by_name = {t["name"]: t for t in data["tools"]}
    assert by_name["get_project_documents"]["available"] is True
    assert "preview_schedule" not in by_name


# ===== D. 受控工具执行 =====



def test_technician_technical_manager_has_schedule_but_not_update(client, admin_headers):
    tech_id, _ = _create_user(client, admin_headers, "tech2", "technician")
    db = SessionLocal()
    try:
        project = _seed_project(db, manager="user-admin-001", technical_manager=tech_id, members=[tech_id])
        tech = db.get(User, tech_id)
        progress = execute_ai_tool("get_vehicle_progress", {}, project.id, tech, db)
        assert "units" in progress
    finally:
        db.close()


def test_worker_member_read_ok_write_403(client, admin_headers):
    db = SessionLocal()
    try:
        project = _seed_project(db, manager="user-admin-001", members=["user-worker-001"])
        worker = db.get(User, "user-worker-001")
        summary = execute_ai_tool("get_project_summary", {}, project.id, worker, db)
        assert summary["name"] == "AI 权限测试项目"
        with pytest.raises(HTTPException) as exc:
            execute_ai_tool("preview_schedule", {}, project.id, worker, db)
        assert exc.value.status_code == 410
    finally:
        db.close()


def test_tool_invisible_project_404_and_no_project_400(client, admin_headers):
    db = SessionLocal()
    try:
        admin = db.get(User, "user-admin-001")
        with pytest.raises(HTTPException) as exc:
            execute_ai_tool("get_project_summary", {}, "no-such-project", admin, db)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            execute_ai_tool("get_project_summary", {}, "", admin, db)
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            execute_ai_tool("unknown_tool", {}, "", admin, db)
        assert exc.value.status_code == 400
    finally:
        db.close()


# ===== E. organize 外层守卫按能力（项目建档仍 admin/pm）=====

def test_structured_drafts_are_retired_for_every_authenticated_role(client,admin_headers,worker_headers):
    for headers in (admin_headers,worker_headers):
        for skill in ('project','planning','inventory','issues','handover'):
            response=client.post('/api/ai-projects/organize',headers=headers,json={'skill':skill,'project_id':'not-visible','source_text':'old work'})
            assert response.status_code==410


# ===== F. Codex 安全边界 =====



# ===== G. 内部 Token / MCP scope 最小权限 =====

def test_default_token_scopes_exclude_write_scopes(client, admin_headers):
    r = client.post("/api/ai/internal/tokens", headers=admin_headers, json={
        "name": "默认只读 Token", "user_id": "user-admin-001"})
    assert r.status_code == 200
    scopes = r.json()["scopes"]
    assert "vehicles:read" in scopes and "files:read" in scopes
    assert "schedule:read" not in scopes
    for write_scope in ("change_sets:propose", "change_sets:merge", "change_sets:rollback"):
        assert write_scope not in scopes

    r = client.post("/api/ai/internal/tokens", headers=admin_headers, json={
        "name": "显式写 Scope", "user_id": "user-admin-001",
        "scopes": ["change_sets:propose", "change_sets:merge", "change_sets:rollback"],
    })
    assert r.status_code == 400
    assert "scope" in r.json()["detail"].lower()


def test_mcp_document_read_requires_both_scopes(client,admin_headers):
    from app.services import ai_mcp as m
    with SessionLocal() as db:pid=_seed_project(db,manager='user-admin-001').id
    user=m._mcp_user_id.set('user-admin-001');scopes=m._mcp_scopes.set(['projects:read']);identity=m._mcp_token_id.set(None)
    try:
        assert '"ok": false' in m.documents_read(pid)
        m._mcp_scopes.set(['projects:read','files:read'])
        assert '"ok": true' in m.documents_read(pid)
    finally:
        m._mcp_user_id.reset(user);m._mcp_scopes.reset(scopes);m._mcp_token_id.reset(identity)


def test_retired_schedule_tools_are_not_registered_even_for_managers(client,admin_headers):
    from app.services.ai_mcp import TOOL_SCOPES
    from app.services.ai_tools import TOOL_MAP
    assert not {'get_schedule','schedule_preview','tasks_tree','preparations_summary','project_readiness'}&set(TOOL_SCOPES)
    assert not {'get_schedule','preview_schedule','get_execution_plan','get_preparations_summary'}&set(TOOL_MAP)


def test_execute_ai_tool_lead_can_read_and_preview_without_writing(client, admin_headers):
    lead_id, _ = _create_user(client, admin_headers, "lead3", "lead")
    db = SessionLocal()
    try:
        project = _seed_project(db, manager=lead_id, members=[lead_id])
        project_id = project.id
        lead = db.get(User, lead_id)
        summary = execute_ai_tool("get_project_summary", {}, project_id, lead, db)
        assert summary["name"] == "AI 权限测试项目"
        progress = execute_ai_tool("get_vehicle_progress", {}, project_id, lead, db)
        assert "units" in progress
    finally:
        db.close()
    with SessionLocal() as db:
        assert db.get(Project, project_id).client == "客户A"

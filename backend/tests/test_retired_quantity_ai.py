"""退役 AI 数量计划不得改写人工进度。"""

import pytest


def test_ai_quantity_plan_is_retired_without_changing_manual_progress(client,pm_headers):
    from app.db import SessionLocal
    from app.models import Project,User
    from app.services.ai_tools import execute_ai_tool
    from fastapi import HTTPException
    import pytest
    response=client.post('/api/projects',headers=pm_headers,json={'name':'retired AI plan','start_date':'2026-01-01','end_date':'2026-12-31'})
    assert response.status_code==200
    pid=response.json()['id']
    with SessionLocal() as db:
        before=db.get(Project,pid).status
        with pytest.raises(HTTPException) as rejected:execute_ai_tool('get_execution_plan',{},pid,db.get(User,'user-pm-001'),db)
        assert rejected.value.status_code==410 and db.get(Project,pid).status==before

"""Retired daily planning transports: original rows remain read-only sources."""
from fastapi import APIRouter, Depends, HTTPException
from app.deps import get_current_user
from app.services.system_permissions import route_permission
router = APIRouter(tags=['旧按天排程（已退休）'])


def gone():
    raise HTTPException(410, '按天排程、甘特、工期倍率与自动重排已退休，请使用项目周计划；原日程保留在只读来源')


@router.api_route('/schedule', methods=['GET','POST','PUT','PATCH','DELETE'])
@router.api_route('/schedule/{path:path}', methods=['GET','POST','PUT','PATCH','DELETE'])
@router.api_route('/projects/{project_id}/schedule', methods=['GET','POST','PUT','PATCH','DELETE'])
@router.api_route('/projects/{project_id}/schedule/{path:path}', methods=['GET','POST','PUT','PATCH','DELETE'])
@route_permission('project.read')
def retired_daily(project_id: str | None = None, path: str = '', user=Depends(get_current_user)):
    return gone()

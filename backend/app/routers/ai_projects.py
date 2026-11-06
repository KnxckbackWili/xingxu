"""Assistant status, budget and the read-only tools an external Agent may use."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.system_permissions import route_permission
from app.services.ai_budget import budget_status
from app.services.ai_project_assistant import assistant_status
from app.services.ai_tools import capabilities_for_user

router=APIRouter(prefix='/ai-projects',tags=['文字整理与只读工具'])


@router.get('/status')
@route_permission('system.ai.use')
def get_status(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    result=assistant_status()
    result.update(available=False,skills=[],drafting_enabled=False,external_agent_readonly=True,budget=budget_status(db))
    return result


@router.get('/capabilities')
@route_permission('system.ai.use')
def get_capabilities(project_id:str|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return capabilities_for_user(db,user,project_id)


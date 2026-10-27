"""Local status/budget and retired structured business drafting routes.

External Agents can organize text using scoped reads. The application never
asks a model to create project/task/quantity/schedule business drafts.
"""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.system_permissions import route_permission
from app.services.ai_budget import budget_status
from app.services.ai_jobs import get_job,set_job
from app.services.ai_project_assistant import assistant_status
from app.services.ai_tools import capabilities_for_user

router=APIRouter(prefix='/ai-projects',tags=['文字整理与只读工具'])
RETIRED_MESSAGE='结构化业务草稿与模型排程已退役；外部工具仅可读取获授权事实整理文字，业务由人员核对后在对应页面操作'


class OrganizeBody(BaseModel):
    """Decode historical queued callbacks only; never admitted as a new job."""
    source_text:str=''
    instruction:str=''
    current_draft:dict|None=None
    project_id:str|None=None
    provider:str=''
    skill:str='project'


def _run_organize_job(job_id,body,user_id):
    try:
        if get_job(job_id,user_id)['status']=='queued':
            set_job(job_id,status='failed',stage='retired',message=RETIRED_MESSAGE,error=RETIRED_MESSAGE)
    except HTTPException:
        return  # Expired/deleted history is never resurrected by an old callback.


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


@router.post('/organize')
@router.post('/organize/jobs')
@router.post('/test-connection')
@router.get('/skill-bundle')
@route_permission('system.ai.use')
def retired_structured_drafting(user:User=Depends(get_current_user)):
    raise HTTPException(410,RETIRED_MESSAGE)


@router.get('/organize/jobs/{job_id}')
@route_permission('system.ai.use')
def get_organize_job(job_id:str,user:User=Depends(get_current_user)):
    return get_job(job_id,user.id)  # Preserve owner-bound existing history only.

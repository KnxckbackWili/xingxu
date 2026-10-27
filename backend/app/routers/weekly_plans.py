"""Canonical weekly plans; publication is explicit scope, actual work is separate."""
from datetime import date
from io import BytesIO
from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.deps import get_current_user
from app.models import WeeklyPlanCell, User, Task, ScheduleEntry
from app.services.scope import ensure_project_visible, visible_projects
from app.services.permissions import C_SCHEDULE, C_EXPORT, authorize_project, project_capabilities
from app.services.system_permissions import route_permission
from app.services import weekly_plans as service


def private_response(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'


router = APIRouter(tags=['周计划'], dependencies=[Depends(private_response)])


class Scope(BaseModel):
    model_config = {'extra': 'forbid'}
    vehicle_type: str | None = Field(default=None, max_length=50)
    vehicle_unit_ids: list[str] = Field(default_factory=list, max_length=2000)
    label: str = Field(default='', max_length=200)


class CreateCell(BaseModel):
    model_config = {'extra': 'forbid'}
    task_id: str
    scope: Scope = Field(default_factory=Scope)
    week_start: date
    mode: Literal['finish', 'in_progress'] = 'in_progress'
    target_count: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    assignee_ids: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default='', max_length=4000)


class UpdateCell(BaseModel):
    model_config = {'extra': 'forbid'}
    version: int = Field(ge=0)
    scope: Scope | None = None
    week_start: date | None = None
    mode: Literal['finish', 'in_progress'] | None = None
    target_count: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    assignee_ids: list[str] | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)
    is_cancelled: bool | None = None
    confirm_intent: bool = Field(default=False, strict=True)
    reason: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def reject_null_definition(self):
        if any(getattr(self, key) is None for key in self.model_fields_set & {'scope','week_start','mode','assignee_ids','notes','is_cancelled'}):
            raise ValueError('周计划定义字段不能置空；清空负责人请提交空列表')
        return self


class CellVersion(BaseModel):
    model_config = {'extra': 'forbid'}
    id: str
    version: int = Field(ge=0)


class PublishCells(BaseModel):
    model_config = {'extra': 'forbid'}
    cells: list[CellVersion] = Field(min_length=1, max_length=2000)
    phase_id: str | None = None


class ClaimCell(BaseModel):
    model_config = {'extra': 'forbid'}
    version: int = Field(ge=0)


class PhaseRule(BaseModel):
    model_config = {'extra': 'forbid'}
    phase_id: str
    anchor: Literal['before_ship', 'after_arrival']
    offset_weeks: int = Field(default=0, ge=0)
    mode: Literal['finish','in_progress'] = 'finish'


class DraftPreview(BaseModel):
    model_config = {'extra': 'forbid'}
    phase_rules: list[PhaseRule] = Field(min_length=1, max_length=100)
    first_week: date | None = None


class DraftCells(DraftPreview):
    preview_token: str = Field(min_length=64,max_length=64,pattern='^[a-f0-9]+$')


class PlanSettings(BaseModel):
    model_config = {'extra':'forbid'}
    version: int = Field(ge=0)
    rest_mode: Literal['none','one','two','single','double']
    rest_days: list[date] = Field(default_factory=list,max_length=5000)
    skip_holidays: bool = False


def committed(db, operation):
    try:
        result = operation()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '同一周计划已被其他操作创建或更新，请刷新核对') from None
    from app.services.cache import cache_clear
    cache_clear('dashboard:')
    return result


@router.get('/projects/{project_id}/weekly-plans')
@route_permission('project.read')
def project_weekly(project_id: str, week_start: date | None = None, weeks: int = Query(8, ge=1, le=104), include_cancelled: bool = False,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    return service.project_view(db, project, user, week_start or service.local_today(project), weeks, include_cancelled=include_cancelled)


@router.get('/worker/weekly-plans')
@route_permission('personal.schedule.read')
def personal_weekly(week_start: date | None = None, weeks: int = Query(1, ge=1, le=104),
                    scope: Literal['mine', 'team'] = 'mine', user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = visible_projects(db, user)
    if scope == 'team':
        projects = [project for project in projects if C_SCHEDULE in project_capabilities(user, project)]
        if not projects and user.role not in ('admin','director','pm','lead','technician'):
            raise HTTPException(403, '仅可查看本人已发布周计划')
    cells, unassigned, warnings = [], [], []
    for project in projects:
        begin = week_start or service.local_today(project)
        selected = service.select_cells(db, [project.id], begin, weeks, published_only=True, user=None if scope == 'team' else user)
        cache = {}
        cells.extend(service.serialize_cell(db, project, cell, user, cache=cache) for cell in selected)
        if service.can_claim(project, user):
            unassigned.extend(service.serialize_cell(db, project, cell, user, cache=cache) for cell in service.select_unassigned_cells(db, [project.id], begin, weeks))
        warnings.extend(service.project_warnings(db, project, selected, user))
    begin = week_start or (service.local_today(projects[0]) if projects else date.today())
    return {'cells': cells, 'unassigned': unassigned, 'weeks': service.weeks_metadata(db, begin, weeks),
            'warnings': warnings, 'permissions': {'team': scope == 'team'}, 'scope': scope}


@router.get('/projects/{project_id}/weekly-plans/legacy-source')
@route_permission('project.read')
def original_daily_source(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    from app.services.project_retention import _row
    return {'read_only': True, 'meaning': '原按日日程与计划量仅作来源，当前完成资格来自工作项和真实车辆矩阵',
            'entries': [_row(row) for row in db.query(ScheduleEntry).filter_by(project_id=project_id).order_by(ScheduleEntry.work_date, ScheduleEntry.id)]}


@router.post('/projects/{project_id}/weekly-plans')
@route_permission('project.manage_schedule')
def create_cell(project_id: str, body: CreateCell, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    row = committed(db, lambda: service.create(db, project, user, body.model_dump()))
    return service.serialize_cell(db, project, row, user)


@router.post('/projects/{project_id}/weekly-plans/publish')
@route_permission('project.manage_schedule')
def publish_cells(project_id: str, body: PublishCells, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    changed = committed(db, lambda: service.publish(db, project, user, [cell.model_dump() for cell in body.cells], phase_id=body.phase_id))
    return {'published_ids': changed, 'count': len(changed)}


@router.get('/projects/{project_id}/weekly-plans/draft-rules')
@route_permission('project.manage_schedule')
def recommended_draft_rules(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project=ensure_project_visible(db,project_id,user)
    return service.default_draft_rules(db,project,user)


@router.post('/projects/{project_id}/weekly-plans/draft/preview')
@route_permission('project.manage_schedule')
def preview_draft(project_id: str, body: DraftPreview, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    return service.draft_preview(db, project, user, [rule.model_dump() for rule in body.phase_rules], first_week=body.first_week)


@router.get('/projects/{project_id}/weekly-plans/settings')
@route_permission('project.manage_schedule')
def read_settings(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    authorize_project(user, project, C_SCHEDULE)
    return service.settings_view(db, project)


@router.put('/projects/{project_id}/weekly-plans/settings')
@route_permission('project.manage_schedule')
def save_settings(project_id: str, body: PlanSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    committed(db, lambda: service.save_settings(db, project, user, body.model_dump()))
    return service.settings_view(db, project)


@router.post('/projects/{project_id}/weekly-plans/draft')
@route_permission('project.manage_schedule')
def generate_draft(project_id: str, body: DraftCells, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    return committed(db, lambda: service.draft(db, project, user, [rule.model_dump() for rule in body.phase_rules], first_week=body.first_week, preview_token=body.preview_token))


@router.get('/projects/{project_id}/weekly-plans/export/excel')
@route_permission('project.export')
def weekly_excel(project_id: str, week_start: date | None = None, weeks: int = Query(8, ge=1, le=104),
                 phase_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    authorize_project(user, project, C_EXPORT)
    data = service.project_view(db, project, user, week_start or service.local_today(project), weeks)
    from app.services.weekly_plan_exports import excel
    from app.services.change_log import log_change
    content = excel(project, data, phase_id=phase_id)
    log_change(db, project.id, 'weekly_plan', project.id, 'export', user.id, '导出所选周计划Excel')
    db.commit()
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': "attachment; filename=\"weekly-plan.xlsx\"; filename*=UTF-8''" + quote(project.name + '-周计划.xlsx'), 'Cache-Control':'private, no-store'})


@router.put('/projects/{project_id}/weekly-plans/{cell_id}')
@route_permission('project.manage_schedule')
def update_cell(project_id: str, cell_id: str, body: UpdateCell, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    row = committed(db, lambda: service.update(db, project, user, cell_id, body.model_dump(exclude_unset=True)))
    return service.serialize_cell(db, project, row, user)


@router.post('/projects/{project_id}/weekly-plans/{cell_id}/claim')
@route_permission('worker.report')
def claim_cell(project_id: str, cell_id: str, body: ClaimCell, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    row = committed(db, lambda: service.claim(db, project, user, cell_id, body.version))
    return service.serialize_cell(db, project, row, user)

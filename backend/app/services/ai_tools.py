"""Read current facts for external text assistance; never simulate or write work."""
from dataclasses import dataclass
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models import Project,User,Issue,ProjectInventoryItem,ProjectDocument
from app.services.scope import ensure_project_visible


@dataclass(frozen=True)
class ToolSpec:
    name:str
    label:str
    description:str
    parameters:dict
    scopes:tuple
    capability:Optional[str]=None
    write_level:str='read'
    needs_project:bool=True


def _project_brief(db,project):
    from app.services.project_events import events_for_project
    from app.services.progress import project_progress_tree
    progress=project_progress_tree(db,project.id)
    return {'id':project.id,'name':project.name,'abbreviation':project.abbreviation,'client':project.client,
        'location':project.location,'status':project.status,'start_date':project.start_date,'end_date':project.end_date,
        'timezone':project.timezone,'dispatch_platform':project.dispatch_platform,'version':project.version,
        'progress':{key:progress[key] for key in ('target','completed','percent','progress_known')},
        'events':[{key:value for key,value in row.items() if key not in ('actual_source','recorded_by','note')} for row in events_for_project(db,project)]}


def _read_issues(db,project):
    return [{key:getattr(row,key) for key in ('id','title','description','issue_type','nature','severity','status','assignee_id','created_at','resolved_at')}
        for row in db.query(Issue).filter_by(project_id=project.id).order_by(Issue.created_at.desc(),Issue.id)]


def _read_inventory(db,project):
    return [{key:getattr(row,key) for key in ('id','name','item_code','category','ownership','quantity','unit','status','location','custodian','serial_number')}
        for row in db.query(ProjectInventoryItem).filter_by(project_id=project.id).order_by(ProjectInventoryItem.created_at.desc(),ProjectInventoryItem.id)]


def _read_project_documents(db,project,user):
    from app.services.project_documents import view
    result=view(db,project,user,audit=True)
    result.pop('owner_options',None)
    result.pop('trigger_events',None)
    result.pop('permissions',None)
    # No frozen original/retirement payload is a text-assistance tool result.
    for key in ('documents','definitions'):
        for row in result[key]:
            row.pop('source_metadata',None)
            if isinstance(row.get('trigger_event'),dict):row['trigger_event']={k:v for k,v in row['trigger_event'].items() if k!='source_metadata'}
    return result


def _read_vehicle_progress(db,project):
    from app.services.vehicle_progress import matrix
    raw=matrix(db,project.id)
    return {'project_id':project.id,'steps':[{key:row[key] for key in ('key','name')} for row in raw['steps']],
        'units':[{key:row[key] for key in ('id','asset_code','fleet_no','vehicle_type','model_name','current_stage')} |
            {'cells':{key:{field:cell[field] for field in ('version','is_done','done_on','recorded_at')} for key,cell in row['cells'].items()}}
            for row in raw['units']], 'summary':raw['summary'],'migration_warnings':raw['migration_warnings']}


def _read_due_documents(db,project,user):
    from app.services.document_deadlines import action_summary
    from app.services.project_documents import audit_access
    result=action_summary(db,project,user)
    ids={row['document_id'] for row in result['this_week']}
    audit_access(db,project,user,documents=db.query(ProjectDocument).filter(ProjectDocument.id.in_(ids)).all())
    db.commit()
    return {'project_id':project.id,'timezone':result['timezone'],'period_key':result['period_key'],
            'as_of':result['as_of'],'items':result['this_week'],'count':result['this_week_count']}


def _param_schema():
    return {'type':'object','properties':{'project_id':{'type':'string','description':'项目ID'}},'required':['project_id'],'additionalProperties':False}


TOOLS=[ToolSpec(name,label,description,_param_schema(),scopes) for name,label,description,scopes in (
    ('get_project_summary','项目摘要','读取当前项目状态、真实进度与里程碑日期。',('projects:read',)),
    ('get_project_documents','资料清单','按当前账号资料/附件权限读取提交状态与版本元数据，不提供私有备份。',('projects:read','files:read')),
    ('get_vehicle_progress','车辆进度表','读取真实车辆与环节完成情况，不填报、不变更状态或检查项。',('projects:read','vehicles:read')),
    ('get_documents_due_this_week','本周待交资料','按项目时区和T23期限规则读取本周待交资料，保密范围逐项校验。',('projects:read','files:read')),
    ('get_issues','问题','读取当前可见项目问题事实用于整理文字。',('issues:read',)),
    ('get_inventory','现场物品','读取项目物品台账事实用于整理文字。',('inventory:read',)),
)]
TOOL_MAP={spec.name:spec for spec in TOOLS}
ALL_TOOL_MAP=dict(TOOL_MAP)
RETIRED_TOOLS=frozenset(('get_execution_plan','get_preparations_summary','get_schedule','preview_schedule'))


def execute_ai_tool(name,arguments,fallback_project_id,user,db):
    if name in RETIRED_TOOLS:raise HTTPException(410,'旧数量计划、准备评审与按天排程AI能力已退役')
    if name not in TOOL_MAP:raise HTTPException(400,'不支持的AI只读工具')
    user=db.get(User,user.id,populate_existing=True)
    if user is None or not user.is_active:raise HTTPException(401,'账号不存在或已停用')
    from app.services.system_permissions import has_permission
    if user.role=='external' or not has_permission(user,'system.ai.use',default=True):raise HTTPException(403,'AI读取权限已被撤销')
    if not fallback_project_id:raise HTTPException(400,'该只读工具需要先选择项目')
    db.get(Project,fallback_project_id,populate_existing=True)
    project=ensure_project_visible(db,fallback_project_id,user)
    if name=='get_project_summary':return _project_brief(db,project)
    if name=='get_project_documents':return _read_project_documents(db,project,user)
    if name=='get_vehicle_progress':return _read_vehicle_progress(db,project)
    if name=='get_documents_due_this_week':return _read_due_documents(db,project,user)
    if name=='get_issues':return _read_issues(db,project)
    return _read_inventory(db,project)


def capabilities_for_user(db,user,project_id=None):
    if project_id:ensure_project_visible(db,project_id,user)
    return {'general_qa':False,'drafting_enabled':False,'readonly':True,'project_id':project_id,
        'tools':[{'name':spec.name,'label':spec.label,'write_level':'read','needs_project':True,
                  'available':bool(project_id),'reason':'' if project_id else '请先选择项目'} for spec in TOOLS]}

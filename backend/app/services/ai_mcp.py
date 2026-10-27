"""AGV PM internal MCP server.

暴露只读业务工具给内部 AI（Claude Desktop / Cursor / Dify / Open WebUI 等）。
认证：Authorization: Bearer agv_ai_<token>，由 ASGI middleware 校验并注入
ContextVar；每个工具按 token 绑定的系统账号做可见性与能力校验。

工具数据复用 app.services.ai_tools；只读查询均校验令牌范围、
当前账号项目可见性及T26保密范围；不执行任何业务写操作。
"""

import contextvars
import json
import logging
from functools import wraps
from contextlib import asynccontextmanager
from datetime import date

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.services.system_permissions import route_permission_contextual
from app.db import SessionLocal
from app.models import Project, User
from app.services.ai_tools import (
    _project_brief, _read_inventory, _read_issues,
    _read_project_documents, _read_vehicle_progress, _read_due_documents,
)
from app.services.scope import ensure_project_visible, visible_projects
from app.services.agent_auth import authenticate_agent

_mcp_user_id = contextvars.ContextVar("agv_ai_mcp_user_id", default="")
_mcp_scopes = contextvars.ContextVar("agv_ai_mcp_scopes", default=[])
_mcp_token_id = contextvars.ContextVar("agv_ai_mcp_token_id", default=None)


def _set_mcp_identity(user_id: str, scopes: list[str]) -> tuple:
    _mcp_user_id.set(user_id)
    _mcp_scopes.set(list(scopes or []))
    _mcp_token_id.set(getattr(scopes, "token_id", None))
    return _mcp_user_id, _mcp_scopes


def _db() -> Session:
    return SessionLocal()


def _current_user(db: Session) -> User:
    user_id = _mcp_user_id.get()
    if not user_id:
        raise RuntimeError("缺少 AI 接口身份")
    user = db.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active:
        raise RuntimeError("AI 接口绑定的系统账号不可用")
    from app.services.agent_auth import enforce_agent_mfa, active_agent_scopes
    from app.models import AiApiToken
    row=db.get(AiApiToken,_mcp_token_id.get(),populate_existing=True) if _mcp_token_id.get() else None
    enforce_agent_mfa(db, user, _mcp_token_id.get())
    if row is not None:
        current=set(active_agent_scopes(row.scopes))
        _mcp_scopes.set([scope for scope in _mcp_scopes.get() if scope in current])
    if user.role=='external':raise RuntimeError('外部分享账号不能取得内部Agent身份')
    from app.services.system_permissions import has_permission

    if not has_permission(user, "system.agent.use", default=True):
        raise RuntimeError("外部工具访问权限已被撤销")
    return user


def _scope_action(scope):
    return {'templates:read':'system.templates.read','dashboard:read':'workspace.view',
            'activity:read':'system.audit.read'}.get(scope,'project.read')


def _require_scope(scope: str) -> None:
    from app.services.system_permissions import has_permission
    with _db() as db:
        user=_current_user(db)
        if scope not in _mcp_scopes.get():raise RuntimeError(f'Token 未授权 scope：{scope}')
        if not has_permission(user,_scope_action(scope),default=True):raise RuntimeError('该工具读取权限已被系统管理员禁止')


def _catalog_names():
    from app.services.system_permissions import has_permission
    with _db() as db:
        user=_current_user(db);scopes=set(_mcp_scopes.get())
        return {name for name,required in TOOL_SCOPES.items() if set(required).issubset(scopes)
                and all(has_permission(user,_scope_action(scope),default=True) for scope in required)}


class ReadOnlyMCP(FastMCP):
    async def list_tools(self):
        tools=await super().list_tools()
        if not _mcp_user_id.get():return tools  # in-process metadata introspection only
        allowed=await run_in_threadpool(_catalog_names)
        return [tool for tool in tools if tool.name in allowed]


def _jsonable(value):
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=_jsonable)


def _fail(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _project_visible(db: Session, user: User, project_id: str) -> Project:
    fresh=_current_user(db)
    if fresh.id!=user.id:raise RuntimeError('Agent身份已变化')
    return ensure_project_visible(db, project_id, fresh)


def _run(db: Session, fn) -> str:
    """统一执行入口：身份 → scope → 可见性/能力 → 具体逻辑，错误一律转 _fail 字符串。"""
    try:
        user = _current_user(db)
        return fn(db, user)
    except RuntimeError as error:
        return _fail(str(error))
    except HTTPException as error:
        return _fail(str(error.detail))
    except Exception:  # 内部工具不允许 500 直接冒泡给 MCP 客户端
        logging.getLogger(__name__).exception("Agent tool failed")
        return _fail("工具执行失败，请稍后重试")
    finally:
        db.close()


def _new_mcp_server():
    server = ReadOnlyMCP(
        "agv-pm",
        stateless_http=True,
        json_response=True,
        instructions=(
            "你是 AGV 项目管理系统的内部数据接口。所有工具基于当前 Token 绑定账号的"
            "项目可见性和资料保密范围；仅可读取事实整理文字，不得修改状态、检查、资料、权限或分享。"
        ),
    )
    server.settings.streamable_http_path = "/"
    # 外层已有 TrustedHostMiddleware + AI Token 鉴权，关闭 MCP 自带的 DNS rebinding 校验。
    server.settings.transport_security.enable_dns_rebinding_protection = False
    return server


mcp = _new_mcp_server()
_REGISTERED_TOOLS = []

TOOL_SCOPES: dict[str, tuple[str, ...]] = {}


def agent_tool(*scopes: str, writes: bool = False):
    """Keep the tool schema, scope catalog and worker-thread dispatch in one place."""

    if writes:raise ValueError('Agent目录只允许读取；业务写工具不得注册')

    def register(fn):
        TOOL_SCOPES[fn.__name__] = scopes

        @wraps(fn)
        async def invoke(*args, **kwargs):
            missing = [scope for scope in scopes if scope not in _mcp_scopes.get()]
            if missing:
                return _fail(f"Token 未授权 scope：{', '.join(missing)}")
            return await run_in_threadpool(fn, *args, **kwargs)

        annotations = ToolAnnotations(
            readOnlyHint=not writes, destructiveHint=writes, openWorldHint=False
        )
        _REGISTERED_TOOLS.append((invoke, annotations))
        mcp.tool(annotations=annotations, structured_output=False)(invoke)
        return fn

    return register


@agent_tool("projects:read")
def projects_list() -> str:
    """列出当前 AI Token 可见的项目。"""

    def _fn(db: Session, user: User) -> str:
        _require_scope("projects:read")
        projects = visible_projects(db, user)
        projects.sort(key=lambda item: item.created_at or item.id, reverse=True)
        return _ok([_project_brief(db, item) for item in projects])

    return _run(_db(), _fn)


@agent_tool("projects:read")
def project_get(project_id: str) -> str:
    """读取单个项目基本信息。"""

    def _fn(db: Session, user: User) -> str:
        _require_scope("projects:read")
        return _ok(_project_brief(db, _project_visible(db, user, project_id)))

    return _run(_db(), _fn)








@agent_tool("issues:read")
def issues_list(project_id: str) -> str:
    """读取项目问题列表。"""

    def _fn(db: Session, user: User) -> str:
        _require_scope("issues:read")
        project = _project_visible(db, user, project_id)
        return _ok(_read_issues(db, project))

    return _run(_db(), _fn)




@agent_tool("inventory:read")
def inventory_list(project_id: str) -> str:
    """读取项目现场物品台账。"""

    def _fn(db: Session, user: User) -> str:
        _require_scope("inventory:read")
        project = _project_visible(db, user, project_id)
        return _ok(_read_inventory(db, project))

    return _run(_db(), _fn)


@agent_tool("dashboard:read")
def dashboard_overview() -> str:
    """读取当前 Token 可见范围的项目组合概览。"""

    def _fn(db: Session, user: User) -> str:
        _require_scope("dashboard:read")
        projects = visible_projects(db, user)
        total = len(projects)
        active = [
            item for item in projects if item.status not in ("completed", "archived")
        ]
        return _ok(
            {
                "total_projects": total,
                "active_projects": len(active),
                "completed_projects": total - len(active),
                "projects": [_project_brief(db, item) for item in projects[:50]],
            }
        )

    return _run(_db(), _fn)


def _project_read(project_id: str, scope: str, read) -> str:
    def _fn(db: Session, user: User) -> str:
        _require_scope(scope)
        return _ok(read(db, user, _project_visible(db, user, project_id)))

    return _run(_db(), _fn)




@agent_tool("templates:read")
def templates_list() -> str:
    """列出可用实施模板的名称、版本与发布状态。模板用于新项目，不自动覆盖已有项目。"""

    def _fn(db, user):
        _require_scope("templates:read")
        from app.routers.templates import list_templates

        return _ok([{key:value for key,value in row.items() if key in ('id','name','description','version','is_active','status')} for row in list_templates(user=user,db=db)])

    return _run(_db(), _fn)


@agent_tool("templates:read")
def template_get(template_id: str) -> str:
    """读取当前资料要求与车辆环节模板；不提供旧数量/任务/自动排程规则。"""

    def _fn(db, user):
        _require_scope("templates:read")
        from app.models import Template
        from app.services.document_requirements import list_requirements
        from app.services.vehicle_progress import template_steps
        if template_id != 'default' and db.get(Template,template_id) is None:raise HTTPException(404,'模板不存在')
        return _ok({'id':template_id,'document_requirements':list_requirements(db,template_id),
            'vehicle_steps':[{'key':row.key,'name':row.name} for row in template_steps(db,template_id)]})

    return _run(_db(), _fn)


@agent_tool("team:read")
def project_members(project_id: str) -> str:
    """读取项目成员与项目角色；不返回密码、私人联系方式或其他项目的成员。"""

    def read(db, user, project):
        from app.models import ProjectMember

        rows = (
            db.query(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .filter(ProjectMember.project_id == project.id)
            .order_by(User.display_name)
            .all()
        )
        return [
            {
                "user_id": member.user_id,
                "name": person.display_name,
                "project_role": member.role,
                "is_active": person.is_active,
            }
            for member, person in rows
        ]

    return _project_read(project_id, "team:read", read)


@agent_tool("vehicles:read")
def project_vehicles(project_id: str) -> str:
    """读取项目车型数量及现场单车编号、阶段、状态、位置和未关闭问题数量。"""

    def read(db,user,project):
        from app.routers.projects import list_vehicles
        progress=_read_vehicle_progress(db,project)
        return {'configurations':list_vehicles(project.id,user,db),'units':progress['units']}

    return _project_read(project_id, "vehicles:read", read)


@agent_tool("files:read")
def project_files(project_id: str, limit: int = 50, offset: int = 0) -> str:
    """分页读取项目文件元数据（最多100条），不返回文件正文、磁盘路径或下载凭据。"""

    def read(db, user, project):
        from app.models import Attachment

        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(400, "limit 应为 1–100，offset 不能为负数")
        query = db.query(Attachment).filter_by(project_id=project.id)
        from app.services.project_documents import can_read_file, audit_access
        rows = [row for row in query.order_by(Attachment.uploaded_at.desc(),Attachment.id)
                if can_read_file(user,project,row)][offset:offset+limit+1]
        audit_access(db,project,user,files=rows[:limit]);db.commit()
        return {
            "items": [
                {
                    "id": row.id,
                    "filename": row.filename,
                    "file_size": row.file_size,
                    "content_type": row.content_type,
                    "category": row.category,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "uploaded_at": row.uploaded_at,
                }
                for row in rows[:limit]
            ],
            "next_offset": offset + limit if len(rows) > limit else None,
        }

    return _project_read(project_id, "files:read", read)


@agent_tool("activity:read")
def project_activity(project_id: str, limit: int = 30) -> str:
    """读取最近项目变更与操作人，最多100条；用于追踪现场进展、生成工作简报。"""

    def read(db, user, project):
        if not 1 <= limit <= 100:
            raise HTTPException(400, "limit 应为 1–100")
        from app.routers.logs import list_logs

        return list_logs(project.id, limit, user, db)

    return _project_read(project_id, "activity:read", read)


@route_permission_contextual(
    "system.agent.use",
    reason="MCP认证中间件校验专用令牌，工具逐次重检账号、scope及资源权限",
)
class AiMcpAuthMiddleware:
    """在进入 MCP app 前校验 agv_ai_ Bearer Token 并注入身份 ContextVar。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            user_id, scopes = await run_in_threadpool(
                authenticate_agent, headers.get("authorization", "")
            )
        except HTTPException as error:
            await JSONResponse({"detail": error.detail}, status_code=error.status_code)(
                scope, receive, send
            )
            return
        user_token = _mcp_user_id.set(user_id)
        scopes_token = _mcp_scopes.set(scopes)
        api_token = _mcp_token_id.set(getattr(scopes, "token_id", None))
        try:
            await self.app(scope, receive, send)
        finally:
            _mcp_user_id.reset(user_token)
            _mcp_scopes.reset(scopes_token)
            _mcp_token_id.reset(api_token)


mcp_http_app = AiMcpAuthMiddleware(None)


@asynccontextmanager
async def agent_mcp_lifespan():
    # The SDK session manager is single-use. Rebuild it on each application lifespan
    # instead of silently leaving a restarted application with a stopped task group.
    server = _new_mcp_server()
    for invoke, annotations in _REGISTERED_TOOLS:
        server.tool(annotations=annotations, structured_output=False)(invoke)
    mcp_http_app.app = server.streamable_http_app()
    try:
        async with server.session_manager.run():
            yield
    finally:
        mcp_http_app.app = None


@agent_tool("projects:read", "files:read")
def documents_read(project_id: str) -> str:
    """读取可见项目的资料清单、版本和未归类文件；保密权限沿用业务模块。"""
    def read(db,user):
        _require_scope('projects:read');_require_scope('files:read')
        return _ok(_read_project_documents(db,_project_visible(db,user,project_id),user))
    return _run(_db(),read)


@agent_tool('projects:read','vehicles:read')
def vehicle_progress_read(project_id:str)->str:
    """读取真实车辆进度表；不修改车辆、检查、状态、日程或资料。"""
    def read(db,user):
        _require_scope('projects:read');_require_scope('vehicles:read')
        return _ok(_read_vehicle_progress(db,_project_visible(db,user,project_id)))
    return _run(_db(),read)


@agent_tool('projects:read','files:read')
def documents_due_this_week(project_id:str)->str:
    """按项目时区和当前资料权限读取本周待交清单；不生成期次、不保存纪要。"""
    def read(db,user):
        _require_scope('projects:read');_require_scope('files:read')
        return _ok(_read_due_documents(db,_project_visible(db,user,project_id),user))
    return _run(_db(),read)

"""System action policies, separate from project visibility and lifecycle gates.

An explicit denial always wins. Contextual project actions still require the
caller's existing relationship/capability check; granting an action never grants
access to another user's private data or to an invisible project.
"""

from copy import deepcopy
import inspect
from dataclasses import dataclass

from fastapi import HTTPException

ROLE_NAMES = {
    "admin": "系统管理员",
    "director": "总监",
    "lead": "技术经理",
    "pm": "项目经理",
    "technician": "技术工程师",
    "worker": "实施工程师",
    "intern": "实习生",
    "readonly": "只读",
}
ALL_ROLES = tuple(ROLE_NAMES)
MANAGEMENT_ROLES = ("admin", "director", "lead", "pm", "technician")
ADMIN = ("admin",)


def _p(key, name, description, roles=ADMIN, scope="system", risk="normal", **extra):
    return dict(
        key=key,
        name=name,
        description=description,
        default_roles=list(roles),
        scope=scope,
        risk=risk,
        **extra
    )


_GROUPS = [
    dict(
        key="workspace",
        name="工作台与个人工作",
        description="进入工作台、查看统计和管理自己的安排。",
        permissions=[
            _p(
                "workspace.view",
                "查看工作台",
                "查看自己可见范围内的项目、人员和日程汇总。",
                MANAGEMENT_ROLES,
                "visible_projects",
            ),
            _p(
                "insights.view",
                "查看统计",
                "查看自己可见项目的统计及运营分析。",
                MANAGEMENT_ROLES,
                "visible_projects",
            ),
            _p(
                "personal.schedule.read",
                "查看个人日程",
                "查看本人日历和个人安排，不扩大他人数据范围。",
                ALL_ROLES,
                "own",
            ),
            _p(
                "personal.schedule.manage",
                "管理个人日程",
                "新增或修改本人个人事件和可自行调整的安排。",
                MANAGEMENT_ROLES,
                "own",
            ),
            _p(
                "personal.messages.use",
                "查看和处理个人消息",
                "查看和处理本人消息，不能读取他人消息。",
                ALL_ROLES,
                "own",
            ),
            _p(
                "personal.records.read",
                "查看个人填报记录",
                "查看本人填报历史与个人统计，不扩大他人数据范围。",
                ALL_ROLES,
                "own",
            ),
            _p(
                "worker.report",
                "现场填报",
                "填报、撤回或修正数量及检查结果；仍受执行人、任务和项目状态规则约束。",
                ALL_ROLES,
                "visible_projects",
            ),
            _p(
                "worker.deliver",
                "提交资料",
                "上传现场资料并提交任务要求，不授予审核资格。",
                ALL_ROLES,
                "visible_projects",
            ),
            _p(
                "worker.issues",
                "上报问题",
                "在可见项目内上报现场问题。",
                ALL_ROLES,
                "visible_projects",
            ),
            _p(
                "feedback.submit",
                "提交系统反馈",
                "提交本人使用系统时发现的问题。",
                ALL_ROLES,
                "own",
            ),
        ],
    ),
    dict(
        key="projects",
        name="项目操作",
        description="操作权限与项目可见范围、职责和状态共同生效。",
        permissions=[
            _p("projects.create", "创建项目", "创建新的项目。", ("admin", "pm")),
            _p(
                "projects.view_all",
                "查看全局项目",
                "查看全局项目；私有资料仍按所有者限制访问。",
                ("admin", "director"),
                "all_projects",
                "high",
            ),
            _p(
                "project.read",
                "查看项目",
                "读取已获可见权限的项目及其共享数据。",
                ALL_ROLES,
                "project",
                contextual_default=True,
            ),
            _p(
                "project.update",
                "修改项目资料",
                "修改可见项目的基本资料、验收记录及允许的项目状态操作。",
                ("admin", "pm", "lead"),
                "project",
                contextual_default=True,
            ),
            _p(
                "project.manage_members",
                "管理项目人员",
                "管理可见项目的成员和项目内职责。",
                ("admin", "pm", "lead"),
                "project",
                "high",
                contextual_default=True,
            ),
            _p(
                "project.manage_plan",
                "管理任务与准备",
                "维护任务目标、检查、资料审核及进场准备。",
                ("admin", "pm", "lead", "technician"),
                "project",
                contextual_default=True,
            ),
            _p(
                "project.manage_schedule",
                "管理日程",
                "安排、发布和调整日期、人员及计划数量，保留锁定与报工限制。",
                ("admin", "pm", "lead", "technician"),
                "project",
                contextual_default=True,
            ),
            _p(
                "project.manage_issues",
                "处理项目问题",
                "指派、处理和关闭可见项目的问题。",
                ("admin", "director", "pm", "lead", "technician"),
                "project",
                contextual_default=True,
            ),
            _p(
                "project.export",
                "导出项目",
                "导出可见项目的共享资料和归档记录。",
                MANAGEMENT_ROLES,
                "project",
                contextual_default=True,
            ),
            _p(
                "project.archive",
                "归档与复盘操作",
                "管理可见项目的归档与复盘；验收记录由修改项目资料权限控制，仍受流程条件约束。",
                ("admin", "director", "pm", "lead"),
                "project",
                "high",
                contextual_default=True,
            ),
            _p(
                "project.manage_inventory",
                "管理现场物品",
                "维护可见项目内物品、库存和出入库记录。",
                MANAGEMENT_ROLES,
                "project",
                contextual_default=True,
            ),
            _p(
                "project.delete",
                "删除与还原项目",
                "在可见项目内直接备份后删除、从回收站还原；无需审批，负责人默认具备。",
                ("admin", "pm", "lead"),
                "project",
                "high",
                contextual_default=True,
            ),
            _p(
                "system.import.create",
                "导入项目",
                "通过文件或模板导入新的项目。",
                ("admin", "pm"),
            ),
            _p("system.projects.purge", "永久删除回收站项目", "仅系统管理员在加密项目备份成功后明确永久删除，保留鉴权下载凭据。", ADMIN, "system", "high"),
            _p(
                "system.archives.read",
                "查阅历史归档库",
                "读取系统历史归档库，保留归档记录的访问边界。",
                ("admin", "director"),
                "archives",
                "high",
            ),
        ],
    ),
    dict(
        key="organization",
        name="人员、组织与基础资料",
        description="普通业务候选读取与管理页面操作分别控制。",
        permissions=[
            _p(
                "system.users.read",
                "仅查看账号列表",
                "仅查看人员管理账号列表；账号维护权限也包含页面必要读取。",
            ),
            _p(
                "system.users.manage",
                "管理人员账号",
                "包含维护所需账号读取；可维护普通账号资料、启停和重置密码，受托人员只能创建现场人员，不能改变角色或维护管理员。",
                risk="high",
            ),
            _p(
                "system.availability.manage",
                "管理人员可用时间",
                "维护允许管理的人员休假、不可用时间。",
                ("admin", "pm"),
                "visible_people",
            ),
            _p(
                "system.templates.read",
                "使用任务模板",
                "读取模板作为项目创建和业务选择项。",
                ALL_ROLES,
            ),
            _p(
                "system.templates.view",
                "仅查看模板管理页",
                "仅进入模板管理页；维护权限也包含页面必要查看，普通模板候选读取另外保留。",
            ),
            _p(
                "system.templates.manage",
                "管理任务模板",
                "新增、编辑、发布和删除任务模板。",
            ),
            _p(
                "system.template_io.manage",
                "导入模板",
                "导入 JSON 或 Excel 模板并维护模板内容。",
            ),
            _p(
                "system.vehicle_types.view",
                "仅查看车型管理页",
                "仅进入车型管理页；维护权限也包含页面必要查看，普通启用车型候选读取另外保留。",
            ),
            _p("system.holidays.read", "查看节假日数据", "查看年度放假、补班、来源与缺失年度。", ALL_ROLES),
            _p("system.holidays.manage", "维护节假日数据", "核对并维护完整年度放假和调休补班安排。", risk="high"),
            _p("system.vehicle_types.manage", "管理车型字典", "维护车型、启停和排序。"),
            _p(
                "system.inventory.read",
                "查看现场物品汇总",
                "查看可见项目内物品汇总，不增加项目可见范围。",
                ALL_ROLES,
                "visible_projects",
            ),
            _p(
                "system.inventory.view",
                "查看现场物品工作台",
                "进入现场物品汇总页面；业务内物品读取仍单独按项目范围控制。",
                MANAGEMENT_ROLES,
                "visible_projects",
            ),
        ],
    ),
    dict(
        key="ai",
        name="AI 与外部工具",
        description="AI后台整理任务归本人所有。",
        permissions=[
            _p(
                "system.ai.use",
                "使用 AI 助手",
                "发起本人 AI 文字整理；写入业务还需相应操作权限。",
                ALL_ROLES,
                "own",
            ),
            _p(
                "system.ai.configure",
                "测试 AI 连接",
                "测试可用 AI 服务连接，不授予业务写入资格。",
                ALL_ROLES,
                "own",
            ),
            _p(
                "system.agent_tokens.manage",
                "管理 AI 接口令牌",
                "维护本人令牌；只有真实管理员能为他人发放令牌，令牌范围不能超出持有者有效权限。",
                ADMIN,
                "own",
                "high",
            ),
            _p(
                "system.agent.use",
                "使用外部 AI 工具接口",
                "允许本人有效接口令牌调用工具；仍需令牌 scope 和可见项目权限共同允许。",
                ALL_ROLES,
                "own",
            ),
            _p(
                "system.skills.download",
                "下载 AI 操作说明",
                "下载系统提供的 AI Skill 文件。",
                ALL_ROLES,
            ),
        ],
    ),
    dict(
        key="system",
        name="系统治理与备份",
        description="高风险操作独立控制；权限策略入口仅真实管理员可用。",
        permissions=[
            _p(
                "permission.manage",
                "管理全系统权限",
                "仅真实且启用的管理员可管理权限；此入口不能委派或关闭。",
                ADMIN,
                risk="high",
                admin_locked=True,
            ),
            _p(
                "system.notifications.configure",
                "配置通知渠道",
                "维护系统通知渠道并测试发送。",
                risk="high",
            ),
            _p(
                "system.backups.read", "查看系统备份", "查看系统备份记录。", risk="high"
            ),
            _p(
                "system.backups.configure", "设置备份口令",
                "仅真实管理员可设置之后生成备份的加密口令。", risk="high"
            ),
            _p(
                "system.backups.create",
                "创建系统备份",
                "创建包含全系统数据的备份。",
                risk="high",
            ),
            _p(
                "system.backups.download",
                "下载系统备份",
                "下载包含系统数据的备份包。",
                risk="high",
            ),
            _p(
                "system.backups.delete", "删除系统备份", "删除指定备份包。", risk="high"
            ),
            _p(
                "system.backups.restore",
                "恢复系统备份",
                "校验并准备恢复全系统备份，仍保留维护与重启条件。",
                risk="high",
            ),
            _p(
                "system.audit.read",
                "查阅操作记录",
                "读取权限允许范围内的操作审计记录。",
                ALL_ROLES,
                "visible_projects",
            ),
            _p(
                "system.feedback.manage",
                "处理系统反馈",
                "查看和处理系统反馈。",
                ("admin", "director", "pm"),
            ),
        ],
    ),
]
PERMISSIONS = {p["key"]: p for g in _GROUPS for p in g["permissions"]}
PERMISSION_KEYS = frozenset(PERMISSIONS)
RETIRED_PERMISSION_KEYS = frozenset({'system.governance.review'})

# A readonly account has a durable role ceiling; future actions are denied
# unless explicitly classified here. Per-user/project grants cannot remove it.
READ_ONLY_ACTIONS = frozenset({
    "workspace.view", "insights.view", "personal.schedule.read",
    "personal.messages.use", "personal.records.read", "project.read",
    "project.export", "projects.view_all", "system.templates.read",
    "system.holidays.read", "system.templates.view", "system.vehicle_types.view", "system.inventory.read",
    "system.inventory.view", "system.archives.read", "system.audit.read",
    "system.agent.use", "system.skills.download",
})
for _key, _permission in PERMISSIONS.items():
    _permission["read_only"] = _key in READ_ONLY_ACTIONS
    if _key not in READ_ONLY_ACTIONS:
        _permission["default_roles"] = [role for role in _permission["default_roles"] if role != "readonly"]



def catalog():
    return {
        "groups": deepcopy(_GROUPS),
        "roles": [{"key": key, "name": name} for key, name in ROLE_NAMES.items()],
    }


def permission_override(user, key):
    """Return only a valid explicit override; NULL/old malformed JSON inherits."""
    if key not in PERMISSIONS or key == "permission.manage":
        return None
    values = getattr(user, "permission_overrides", None)
    value = values.get(key) if isinstance(values, dict) else None
    return value if type(value) is bool else None


def has_permission(user, key, default=None):
    if key not in PERMISSIONS or user is None or not getattr(user, "is_active", False):
        return False
    if getattr(user, "role", None) == "readonly" and key not in READ_ONLY_ACTIONS:
        return False
    if key == "permission.manage":
        return user.role == "admin"
    override = permission_override(user, key)
    if override is not None:
        return override
    if default is not None:
        return bool(default)
    return user.role in PERMISSIONS[key]["default_roles"]


def default_permissions(user):
    if user is None or not getattr(user, "is_active", False):
        return []
    return sorted(
        key for key, item in PERMISSIONS.items() if user.role in item["default_roles"]
        and (user.role != "readonly" or key in READ_ONLY_ACTIONS)
    )


def effective_permissions(user):
    return sorted(key for key in PERMISSIONS if has_permission(user, key))


def _dependency_calls(route):
    root = getattr(route, "dependant", None)
    pending = [root] if root is not None else []
    visited = set()
    while pending:
        dependency = pending.pop()
        if id(dependency) in visited:
            continue
        visited.add(id(dependency))
        pending.extend(getattr(dependency, "dependencies", None) or [])
        yield getattr(dependency, "call", None)


def _declared_project_capabilities(request):
    """Read real project capability dependencies without executing them."""
    route = (getattr(request, "scope", None) or {}).get("route")
    capabilities = set()
    for call in _dependency_calls(route):
        if getattr(call, "__module__", None) != "app.services.permissions":
            continue
        capability = getattr(call, "capability", None)
        if capability is None and inspect.isfunction(call):
            capability = inspect.getclosurevars(call).nonlocals.get("capability")
        if isinstance(capability, str) and capability.startswith("project.") and capability in PERMISSIONS:
            capabilities.add(capability)
    return sorted(capabilities)


@dataclass(frozen=True)
class RoutePermission:
    keys: tuple[str, ...]
    contextual: bool = False
    reason: str = ""
    readonly_session: bool = False


def _declare_policy(policy):
    if any(key not in PERMISSIONS for key in policy.keys):
        raise ValueError("路由声明了未知权限: " + ", ".join(policy.keys))
    if not policy.keys and not policy.reason.strip():
        raise ValueError("权限豁免必须说明处理器的认证或资源校验依据")
    if policy.contextual and not policy.reason.strip():
        raise ValueError("按操作分别校验的路由必须说明校验依据")

    def declare(endpoint):
        if hasattr(endpoint, "__route_permission__"):
            raise ValueError("同一处理器不能重复声明权限")
        endpoint.__route_permission__ = policy
        return endpoint

    return declare


def route_permission(*keys):
    """Declare conjunctive action keys; authentication applies explicit denials.

    The handler still checks the user's resource visibility and business role.
    Put this decorator below the FastAPI route decorator.
    """
    if not keys:
        raise ValueError("请声明至少一项权限；公开/本人操作需明确说明豁免依据")
    return _declare_policy(RoutePermission(tuple(dict.fromkeys(keys))))


def route_permission_contextual(*keys, reason):
    """Declare alternative/body-specific actions checked inside the handler.

    These keys are not an AND gate: each changed item must authorize its own
    action after the resource is resolved. Never use this for a uniform action.
    """
    if not keys:
        raise ValueError("按操作校验必须列出可能使用的权限")
    return _declare_policy(RoutePermission(tuple(dict.fromkeys(keys)), True, reason))


def route_permission_exempt(reason, *, readonly_session=False):
    """Document public, self-session, or non-delegatable administrator guards."""
    return _declare_policy(RoutePermission((), False, reason, readonly_session))


def _route_policy(route):
    return getattr(getattr(route, "endpoint", None), "__route_permission__", None)


def permission_for_request(request):
    """Resolve only declarations, never URL patterns. Unknown routes fail closed."""
    route = (getattr(request, "scope", None) or {}).get("route")
    policy = _route_policy(route)
    declared = _declared_project_capabilities(request)
    if policy is None and not declared:
        raise HTTPException(403, "接口尚未声明权限，已拒绝执行")
    keys = list(declared)
    if policy is not None and not policy.contextual:
        keys.extend(policy.keys)
    result = list(dict.fromkeys(keys))
    return result[0] if len(result) == 1 else result or None


def readonly_request_allowed(request):
    """Apply the action ceiling on every method, including GET actions."""
    route = (getattr(request, "scope", None) or {}).get("route")
    policy = _route_policy(route)
    if policy is not None and policy.readonly_session:
        return True
    required = permission_for_request(request)
    keys = [required] if isinstance(required, str) else required or []
    if keys:
        return all(key in READ_ONLY_ACTIONS for key in keys)
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        return False
    if policy is not None and policy.contextual:
        return any(key in READ_ONLY_ACTIONS for key in policy.keys)
    return policy is not None  # Explicit public/self/shared read boundary.


def validate_route_permissions(app):
    """Reject undeclared writes before database migration or scheduler startup.

    FastAPI 0.141 includes routers lazily. Its pinned iterator resolves nested
    include contexts as well as direct routes; a flat app.routes scan misses
    almost all business endpoints. ASGI-mounted MCP has its own agent guard.
    """
    from fastapi.routing import _iter_routes_with_context
    from starlette.routing import Mount, Route
    from types import SimpleNamespace
    from app.deps import get_current_user

    errors = []
    for original, context in _iter_routes_with_context(app.routes):
        if isinstance(original, Mount):
            policy = getattr(original.app, "__route_permission__", None)
            if policy is None:
                errors.append(f"ASGI {original.path}: 未声明挂载应用权限边界")
            elif set(policy.keys) - PERMISSION_KEYS:
                errors.append(f"ASGI {original.path}: 声明的权限不在目录中")
            continue
        if not isinstance(original, Route):
            continue
        route = context or original
        policy = _route_policy(route)
        declared = _declared_project_capabilities(SimpleNamespace(scope={"route": route}))
        writes = set(route.methods or ()) - {"GET", "HEAD", "OPTIONS"}
        if writes and policy is None and not declared:
            errors.append(f"{','.join(sorted(writes))} {route.path}: 未声明权限")
        if policy is not None and (set(policy.keys) - PERMISSION_KEYS):
            errors.append(f"{route.path}: 声明的权限不在目录中")
        if writes and policy is not None and policy.keys and not policy.contextual:
            if not any(call is get_current_user for call in _dependency_calls(route)):
                errors.append(f"{route.path}: 权限声明缺少会话认证依赖；专用协议应声明并实现独立校验")
    if errors:
        raise RuntimeError("路由权限自检失败：\n" + "\n".join(errors))

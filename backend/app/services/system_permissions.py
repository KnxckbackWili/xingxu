"""What each account may do: a system administrator, or an ordinary employee.

Employees do all project work; system settings, accounts, backups and permanent
deletion are for administrators. Routes declare the action they perform.
"""

import inspect
from dataclasses import dataclass

from fastapi import HTTPException

ROLE_NAMES = {
    "admin": "系统管理员",
    "employee": "员工",
}
ADMIN = ("admin",)
EVERYONE = ("admin", "employee")


def _p(key, name, description, scope="system", risk="normal", **extra):
    return dict(
        key=key,
        name=name,
        description=description,
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
                "visible_projects",
            ),
            _p(
                "insights.view",
                "查看统计",
                "查看自己可见项目的统计及运营分析。",
                "visible_projects",
            ),
            _p(
                "personal.schedule.read",
                "查看个人日程",
                "查看本人日历和个人安排，不扩大他人数据范围。",
                "own",
            ),
            _p(
                "personal.messages.use",
                "查看和处理个人消息",
                "查看和处理本人消息，不能读取他人消息。",
                "own",
            ),
            _p(
                "personal.records.read",
                "查看个人填报记录",
                "查看本人填报历史与个人统计，不扩大他人数据范围。",
                "own",
            ),
            _p(
                "worker.report",
                "现场填报",
                "填报、撤回或修正数量及检查结果；仍受执行人、任务和项目状态规则约束。",
                "visible_projects",
            ),
            _p(
                "worker.deliver",
                "提交资料",
                "上传现场资料并提交任务要求，不授予审核资格。",
                "visible_projects",
            ),
            _p(
                "worker.issues",
                "上报问题",
                "在可见项目内上报现场问题。",
                "visible_projects",
            ),
            _p(
                "feedback.submit",
                "提交系统反馈",
                "提交本人使用系统时发现的问题。",
                "own",
            ),
        ],
    ),
    dict(
        key="projects",
        name="项目操作",
        description="操作权限与项目可见范围、职责和状态共同生效。",
        permissions=[
            _p("projects.create", "创建项目", "创建新的项目。"),
            _p(
                "project.read",
                "查看项目",
                "读取已获可见权限的项目及其共享数据。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.update",
                "修改项目资料",
                "修改可见项目的基本资料、验收记录及允许的项目状态操作。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.manage_plan",
                "管理任务与准备",
                "维护任务目标、检查、资料审核及进场准备。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.manage_schedule",
                "管理日程",
                "安排、发布和调整日期、人员及计划数量，保留锁定与报工限制。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.manage_issues",
                "处理项目问题",
                "指派、处理和关闭可见项目的问题。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.export",
                "导出项目",
                "导出可见项目的共享资料和归档记录。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.archive",
                "归档与复盘操作",
                "管理可见项目的归档与复盘；验收记录由修改项目资料权限控制，仍受流程条件约束。",
                "project",
                "high",
                contextual_default=True,
            ),
            _p(
                "project.manage_inventory",
                "管理现场物品",
                "维护可见项目内物品、库存和出入库记录。",
                "project",
                contextual_default=True,
            ),
            _p(
                "project.delete",
                "删除与还原项目",
                "在可见项目内直接备份后删除、从回收站还原；无需审批，负责人默认具备。",
                "project",
                "high",
                contextual_default=True,
            ),
            _p(
                "system.import.create",
                "导入项目",
                "通过文件或模板导入新的项目。",
            ),
            _p("system.projects.purge", "永久删除回收站项目", "仅系统管理员在加密项目备份成功后明确永久删除，保留鉴权下载凭据。", "system", "high"),
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
                "system.templates.read",
                "使用任务模板",
                "读取模板作为项目创建和业务选择项。",
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
            _p("system.holidays.read", "查看节假日数据", "查看年度放假、补班、来源与缺失年度。"),
            _p("system.holidays.manage", "维护节假日数据", "核对并维护完整年度放假和调休补班安排。", risk="high"),
            _p("system.vehicle_types.manage", "管理车型字典", "维护车型、启停和排序。"),
            _p(
                "system.inventory.read",
                "查看现场物品汇总",
                "查看可见项目内物品汇总，不增加项目可见范围。",
                "visible_projects",
            ),
        ],
    ),
    dict(
        key="system",
        name="系统治理与备份",
        description="高风险操作独立控制；权限策略入口仅真实管理员可用。",
        permissions=[
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
                "visible_projects",
            ),
            _p(
                "system.feedback.manage",
                "处理系统反馈",
                "查看和处理系统反馈。",
            ),
        ],
    ),
]
PERMISSIONS = {p["key"]: p for g in _GROUPS for p in g["permissions"]}
PERMISSION_KEYS = frozenset(PERMISSIONS)
# Administrator-only actions; everything else is open to every employee.
ADMIN_ONLY = frozenset({
    "system.projects.purge", "system.users.read", "system.users.manage", "system.templates.manage",
    "system.template_io.manage", "system.holidays.manage", "system.vehicle_types.manage",
    "system.notifications.configure", "system.backups.read", "system.backups.configure", "system.backups.create",
    "system.backups.download", "system.backups.delete", "system.backups.restore", "system.feedback.manage",
})
for _key, _permission in PERMISSIONS.items():
    _permission["default_roles"] = list(ADMIN if _key in ADMIN_ONLY else EVERYONE)


def has_permission(user, key):
    if key not in PERMISSIONS or user is None or not getattr(user, "is_active", False):
        return False
    return user.role == "admin" or key not in ADMIN_ONLY


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
    """Declare conjunctive action keys; authentication checks them for the account.

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


def route_permission_exempt(reason):
    """Document public, self-session, or non-delegatable administrator guards."""
    return _declare_policy(RoutePermission((), False, reason))


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

"""Explain policy layers without changing grants or exposing private records."""
from app.services.system_permissions import PERMISSIONS, READ_ONLY_ACTIONS, permission_override


def action_denial(user, capability):
    label = PERMISSIONS.get(capability, {}).get("name", capability)
    if not user.is_active:
        return "账号已停用：请联系管理员"
    if user.role == "readonly" and capability not in READ_ONLY_ACTIONS:
        return f"只读预设：不能{label}；请联系管理员调整账号预设"
    if permission_override(user, capability) is False:
        return f"系统禁止：{label}（{capability}）"
    return f"项目角色无此能力：{label}；请联系项目负责人调整项目授权"


def project_permission_reasons(db, project, user):
    from app.services.permissions import ALL_PROJECT_CAPS, C_READ, project_capabilities
    from app.services.scope import visible_project_ids

    visible = project.id in visible_project_ids(db, user)
    caps = project_capabilities(user, project)
    items = []
    for key in sorted({C_READ, *ALL_PROJECT_CAPS}):
        if not user.is_active:
            allowed, layer, reason = False, "account", "账号已停用"
        elif permission_override(user, "project.read") is False or permission_override(user, key) is False:
            allowed, layer, reason = False, "system", "系统管理员已禁止此操作或项目查看"
        elif user.role == "readonly" and key not in READ_ONLY_ACTIONS:
            allowed, layer, reason = False, "preset", "只读预设不允许修改业务资料"
        elif not visible:
            allowed, layer, reason = False, "membership", "不是项目成员，且未获项目查看权限"
        elif key == C_READ or key in caps:
            allowed, layer, reason = True, "allowed", "项目范围和操作权限均允许"
        else:
            allowed, layer, reason = False, "project_role", "项目角色无此能力，且没有相应项目授权"
        items.append({"key": key, "name": PERMISSIONS[key]["name"], "allowed": allowed,
                      "layer": layer, "reason": reason})
    return {"user_id": user.id, "project_id": project.id, "items": items}


def membership_reasons(project_id, user_id):
    """Project-local inspectors learn no global account/policy state for outsiders."""
    from app.services.permissions import ALL_PROJECT_CAPS, C_READ
    return {"user_id": user_id, "project_id": project_id, "items": [
        {"key": key, "name": PERMISSIONS[key]["name"], "allowed": False,
         "layer": "membership", "reason": "不是项目成员，未在本项目分配职责或授权"}
        for key in sorted({C_READ, *ALL_PROJECT_CAPS})
    ]}

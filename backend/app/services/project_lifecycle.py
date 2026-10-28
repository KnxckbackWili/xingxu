"""Project lifecycle vocabulary and transition rules.

This module is the backend's single interface for lifecycle state.  Callers
should not duplicate status sets or transition maps in routers and schedulers.
"""

PROJECT_STATUSES = {
    "preparing": "准备", "executing": "现场实施",
    "acceptance": "验收中", "completed": "已完成", "archived": "已归档",
    "suspended": "突发停工",
}
INITIAL_PROJECT_STATUSES = ("preparing",)
ACTIVE_PROJECT_STATUSES = ("preparing", "executing", "acceptance")
EXECUTION_PROJECT_STATUSES = ("executing", "acceptance")
TERMINAL_PROJECT_STATUSES = ("completed", "archived")
SUSPENDABLE_PROJECT_STATUSES = ACTIVE_PROJECT_STATUSES
# 原“筹备”“待进场”已合并为“准备”；进入现场实施时一次核对原两道门禁。
STATUS_FLOW = {
    "preparing": ("executing",),
    "executing": ("preparing", "acceptance"), "acceptance": ("executing", "completed"),
    "completed": ("acceptance", "archived"), "archived": ("completed",), "suspended": (),
}


def is_project_status(value: str) -> bool:
    return value in PROJECT_STATUSES


def can_transition(current: str, target: str) -> bool:
    return target in STATUS_FLOW.get(current, ())


def ensure_project_writable(p) -> None:
    """归档项目写接口统一拒绝（C8-5）：已归档锁定，任何写操作直接 400。

    仅用于业务写端点；状态流转（change_status）不走此守卫，因为它负责
    completed→archived 以及 archive→completed 的恢复路径。
    """
    if (getattr(p, "legacy_lifecycle", None) or {}).get("requires_repair"):
        from fastapi import HTTPException
        raise HTTPException(400, "历史状态需要管理员根据原始记录明确核对修复，项目暂不可修改")
    if p.status == "archived":
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="项目已归档，不能修改")
    if p.status not in PROJECT_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="项目存在无法识别的历史状态，暂不能修改；请管理员根据备份或审计记录核对修复")


def ensure_schedule_writable(p) -> None:
    """Completed projects must be reopened before their execution plan changes."""
    if p.status not in PROJECT_STATUSES:
        ensure_project_writable(p)
    if p.status in TERMINAL_PROJECT_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="已结束的项目不能调整日程，请先恢复到验收中")


def status_label(value: str) -> str:
    return PROJECT_STATUSES.get(value, value)

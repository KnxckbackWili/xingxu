"""北极星指标（试点）：已确认日程按计划执行率 OTE。

口径（完整文档见 docs/north-star-metric.md）：
- 北极星：AGV 项目交付按计划执行率 ——「现场按排程执行」的健康度。
- 分母：观察窗口内 已确认(is_confirmed) 且 计划日 <= 观察日 的日程条目数。
- 分子：其中「按计划执行」的条目数 —— 存在填报，且最早填报日期 <= 计划日，
  且累计完成量 >= 计划量（planned_quantity 为 0 时只要有填报即算）。
- 基线：试点启动时取「基线窗口」（默认试点前 28 天）同口径 OTE，
  与当期对照 delta。无历史数据时基线 rate 为 None，试点首期仅记录当期值。
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DailyProgress, ScheduleEntry

DEFAULT_WINDOW_DAYS = 14      # 观察窗口：滚动 14 天
DEFAULT_BASELINE_DAYS = 28    # 基线窗口：观察窗口前 28 天


def _period_ote(db: Session, start: date, end: date, as_of: date) -> dict:
    """计算 [start, end] 窗口内、观察日 as_of 前已到期的 OTE。"""
    entries = (
        db.query(ScheduleEntry)
        .filter(
            ScheduleEntry.is_confirmed.is_(True),
            ScheduleEntry.work_date <= as_of,
            ScheduleEntry.work_date >= start,
            ScheduleEntry.work_date <= end,
        )
        .all()
    )
    total = len(entries)
    if total == 0:
        return {"total": 0, "on_time": 0, "rate": None}

    entry_ids = [e.id for e in entries]
    rows = (
        db.query(
            DailyProgress.schedule_entry_id,
            func.sum(DailyProgress.completed_quantity),
            func.min(DailyProgress.work_date),
        )
        .filter(DailyProgress.schedule_entry_id.in_(entry_ids))
        .group_by(DailyProgress.schedule_entry_id)
        .all()
    )
    agg = {sid: (sum_q or 0, min_d) for sid, sum_q, min_d in rows}

    on_time = 0
    for e in entries:
        sum_q, min_d = agg.get(e.id, (0, None))
        if min_d is None or min_d > e.work_date:
            continue  # 无填报，或填报晚于计划日 → 未按计划执行
        planned = e.planned_quantity or 0
        if planned > 0 and sum_q < planned:
            continue  # 有量纲任务：计划量未达成 → 不算按计划执行
        on_time += 1

    return {"total": total, "on_time": on_time, "rate": round(on_time / total, 4)}


def compute_north_star(
    db: Session,
    days: int = DEFAULT_WINDOW_DAYS,
    baseline_days: int = DEFAULT_BASELINE_DAYS,
    as_of: date | None = None,
) -> dict:
    """当期 OTE + 基线 OTE + delta。基线窗口取观察窗口之前的 baseline_days 天。"""
    as_of = as_of or date.today()
    window_start = as_of - timedelta(days=days - 1)
    baseline_end = window_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)

    current = _period_ote(db, window_start, as_of, as_of)
    baseline = _period_ote(db, baseline_start, baseline_end, baseline_end)

    delta = None
    if current["rate"] is not None and baseline["rate"] is not None:
        delta = round(current["rate"] - baseline["rate"], 4)

    return {
        "metric": "on_time_execution_rate",
        "name": "已确认日程按计划执行率",
        "as_of": as_of.isoformat(),
        "window_days": days,
        "window": {"start": window_start.isoformat(), "end": as_of.isoformat()},
        "current": current,
        "baseline": {
            "total": baseline["total"],
            "on_time": baseline["on_time"],
            "rate": baseline["rate"],
            "window_days": baseline_days,
            "start": baseline_start.isoformat(),
            "end": baseline_end.isoformat(),
        },
        "delta": delta,
    }

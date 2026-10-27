"""Annual PRC holiday calendars; missing years stay explicitly unknown.

Bundled official data is immutable/versioned. Administrator overrides are read
from the caller's transaction, without process-global caching or network I/O.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from sqlalchemy.orm import Session

BUNDLED_CALENDARS = json.loads(Path(__file__).with_name("holiday_data.json").read_text(encoding="utf-8"))


def calendar_snapshot(db: Session | None = None) -> dict:
    calendars = {int(year): {**deepcopy(value), "available": True, "source_kind": "bundled_official", "version": 0}
                 for year, value in BUNDLED_CALENDARS.items()}
    if db is not None:
        from app.models import HolidayCalendar
        for row in db.query(HolidayCalendar).all():
            calendars[row.year] = {"year": row.year, "holidays": row.holidays, "workdays": row.workdays,
                "source_name": row.source_name, "source_url": row.source_url,
                "published_on": row.published_on.isoformat(), "note": row.note or "",
                "available": True, "source_kind": "maintained", "version": row.version,
                "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None}
    return calendars


def calendar_year(year: int, snapshot: dict | None = None) -> dict:
    snapshot = calendar_snapshot() if snapshot is None else snapshot
    return deepcopy(snapshot.get(year, {"year": year, "available": False, "source_kind": "missing",
        "holidays": [], "workdays": [], "version": 0, "source_name": "", "source_url": "",
        "published_on": None, "note": "缺少该年度已核对数据，请待国务院公布后维护或导入；不能视为全年无节假日。"}))


def calendar_in_range(start: date | None, end: date | None, db: Session | None = None) -> dict:
    snapshot = calendar_snapshot(db)
    years = range(start.year, end.year + 1) if start and end and start <= end else []
    calendars = [calendar_year(year, snapshot) for year in years]
    return {"holiday_dates": sorted(d for c in calendars for d in c["holidays"] if start.isoformat() <= d <= end.isoformat()),
        "adjusted_work_dates": sorted(d for c in calendars for d in c["workdays"] if start.isoformat() <= d <= end.isoformat()),
        "missing_holiday_years": [c["year"] for c in calendars if not c["available"]],
        "holiday_sources": [{k: c.get(k) for k in ("year", "source_kind", "source_name", "source_url", "published_on", "version")}
                            for c in calendars if c["available"]]}


def is_holiday(day: date, snapshot: dict | None = None) -> bool:
    return day.isoformat() in calendar_year(day.year, snapshot)["holidays"]


def is_adjusted_workday(day: date, snapshot: dict | None = None) -> bool:
    return day.isoformat() in calendar_year(day.year, snapshot)["workdays"]


def holiday_dates(year: str) -> list:
    return calendar_year(int(year))["holidays"]


def holidays_in_range(start, end) -> list:
    return calendar_in_range(start, end)["holiday_dates"]

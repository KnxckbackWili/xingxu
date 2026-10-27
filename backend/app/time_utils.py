"""Shared time helpers.

SQLite stores naive DATETIME values. To stay compatible with existing rows,
``utcnow()`` returns a naive UTC datetime and avoids the deprecated
``datetime.utcnow()`` (removed in future Python versions).
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import TIMEZONE as DEFAULT_TZ


def utcnow() -> datetime:
    """Return current UTC as a naive datetime (SQLite-compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_in(tz_name: str) -> datetime:
    """当前时刻在指定 IANA 时区的本地时间（带 tzinfo）。"""
    return datetime.now(ZoneInfo(tz_name))


def today_in(tz_name: str) -> date:
    """指定时区当前日历日。俄/越等海外现场与服务器(默认上海)日期可能相差一天。"""
    return now_in(tz_name).date()


def project_today(tz_name: str | None) -> date:
    """按项目时区取"当地今天"；时区无效/缺失时回退全局默认时区。"""
    name = tz_name or DEFAULT_TZ
    try:
        return today_in(name)
    except (ZoneInfoNotFoundError, ValueError):
        return today_in(DEFAULT_TZ)


"""Read annual coverage and explicitly replace a reviewed annual calendar."""
from datetime import date
import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import HolidayCalendar, User
from app.services.change_log import log_change
from app.services.holidays import calendar_snapshot, calendar_year
from app.services.system_permissions import route_permission
from app.time_utils import utcnow

router = APIRouter(prefix="/holiday-calendars", tags=["节假日设置"])


class CalendarWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=1900, le=2200)
    holidays: list[str] = Field(min_length=1, max_length=366)
    workdays: list[str] = Field(max_length=366)
    source_name: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=1, max_length=1000)
    published_on: date
    note: str = Field(default="", max_length=5000)
    complete: Literal[True]
    expected_version: int = Field(ge=0)

    @field_validator("source_name", "source_url")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("来源名称和链接不能为空")
        return value

    @field_validator("source_url")
    @classmethod
    def safe_source_link(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("来源链接须为不含账号口令的HTTPS网址")
        return value

    @model_validator(mode="after")
    def annual_dates(self):
        for values in (self.holidays, self.workdays):
            if len(set(values)) != len(values):
                raise ValueError("日期不得重复")
            for value in values:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).year != self.year:
                    raise ValueError("放假和补班日期必须是本年度有效的YYYY-MM-DD日期")
        if set(self.holidays) & set(self.workdays):
            raise ValueError("同一天不能同时放假和补班")
        if self.published_on > date.today():
            raise ValueError("来源发布日期不能晚于今天，不能导入尚未发布的预测安排")
        return self


@router.get("")
@route_permission("system.holidays.read")
def list_calendars(start_year: int = Query(default=2024, ge=1900, le=2200),
                   end_year: int | None = Query(default=None, ge=1900, le=2200),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    end_year = end_year if end_year is not None else min(date.today().year + 1, 2200)
    if end_year < start_year or end_year - start_year > 50:
        raise HTTPException(status_code=422, detail="年度范围须按先后顺序且不超过51年")
    snapshot = calendar_snapshot(db)
    return {"years": [calendar_year(year, snapshot) for year in range(start_year, end_year + 1)]}


@router.get("/{year}")
@route_permission("system.holidays.read")
def get_calendar(year: int = Path(ge=1900, le=2200), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return calendar_year(year, calendar_snapshot(db))


@router.put("/{year}")
@route_permission("system.holidays.manage")
def save_calendar(body: CalendarWrite, year: int = Path(ge=1900, le=2200),
                  user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if year != body.year:
        raise HTTPException(status_code=422, detail="文件年度和所选年度不一致")
    before = calendar_year(year, calendar_snapshot(db))
    values = {"holidays": sorted(body.holidays), "workdays": sorted(body.workdays),
        "source_name": body.source_name, "source_url": body.source_url,
        "published_on": body.published_on, "note": body.note, "updated_at": utcnow(),
        "version": body.expected_version + 1}
    try:
        if body.expected_version == 0:
            db.add(HolidayCalendar(year=year, **values))
            db.flush()
        else:
            result = db.execute(update(HolidayCalendar).where(HolidayCalendar.year == year,
                HolidayCalendar.version == body.expected_version).values(**values))
            if result.rowcount != 1:
                raise HTTPException(status_code=409, detail="该年度已被其他人修改，请重新加载后核对；当前输入未保存")
        after = calendar_year(year, calendar_snapshot(db))
        log_change(db, None, "holiday_calendar", str(year), "update", user.id,
                   "明确维护全年放假日与调休补班日；不改动已发布计划", old_value=before, new_value=after)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该年度已被其他人修改，请重新加载后核对；当前输入未保存") from None
    return calendar_year(year, calendar_snapshot(db))

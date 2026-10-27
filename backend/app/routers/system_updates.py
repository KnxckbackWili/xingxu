"""Software updates are reserved for real administrators, not delegated roles."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission_exempt
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services import system_updates as updates
from app.services.update_source import UpdateSourceError
from app.services.change_log import log_change

router = APIRouter(prefix="/system/updates", tags=["软件更新"])


def update_admin(user: User = Depends(get_current_user)):
    if not user.is_active or user.role != "admin":
        raise HTTPException(status_code=403, detail="只有系统管理员可以管理软件更新")
    return user


class SourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_url: str = Field(min_length=1, max_length=2048)
    ref: str = Field(default="main", min_length=1, max_length=200)
    allow_http: StrictBool = False
    revision: StrictInt = Field(ge=0)
    token: str | None = Field(default=None, max_length=4096)
    clear_token: StrictBool = False
    name: str | None = Field(default=None, min_length=1, max_length=60)


class AddSourceBody(SourceBody):
    name: str = Field(min_length=1, max_length=60)


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=0)


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision: StrictInt = Field(ge=0)


class InstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str = Field(min_length=36, max_length=36)
    confirm: StrictBool


def _call(function, *args):
    try:
        return function(*args)
    except updates.UpdateError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from None
    except UpdateSourceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except OSError:
        raise HTTPException(status_code=503, detail="更新记录暂时无法保存，请检查磁盘空间后重试") from None


@router.get("")
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def status(_: User = Depends(update_admin)):
    return _call(updates.get_status)


@router.put("/source")
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def save_source(body: SourceBody, actor: User = Depends(update_admin), db: Session = Depends(get_db)):
    result = _call(updates.save_source, body.model_dump())
    log_change(db, None, "system_update", "source", "configure", actor.id,
               "修改软件更新源", new_value={key: result["source"][key] for key in (
                   "id", "name", "repository_url", "ref", "allow_http", "revision", "has_token")})
    db.commit()
    return result


@router.post("/sources", status_code=201)
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def add_source(body: AddSourceBody, actor: User = Depends(update_admin), db: Session = Depends(get_db)):
    result = _call(updates.add_source, body.model_dump())
    log_change(db, None, "system_update", result["active_source_id"], "create", actor.id,
               "添加软件更新源", new_value=result["source"])
    db.commit()
    return result


@router.post("/sources/{source_id}/select")
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def select_source(source_id: str, body: RevisionBody,
                  actor: User = Depends(update_admin), db: Session = Depends(get_db)):
    result = _call(updates.select_source, source_id, body.revision)
    log_change(db, None, "system_update", source_id, "select", actor.id,
               "选择软件更新源", new_value=result["source"])
    db.commit()
    return result


@router.delete("/sources/{source_id}")
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def delete_source(source_id: str, revision: int = Query(ge=0),
                  actor: User = Depends(update_admin), db: Session = Depends(get_db)):
    result = _call(updates.delete_source, source_id, revision)
    log_change(db, None, "system_update", source_id, "delete", actor.id,
               "删除软件更新源", new_value={"active_source_id": result["active_source_id"],
                                         "revision": result["source"]["revision"]})
    db.commit()
    return result


@router.post("/check")
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def check(body: CheckBody, actor: User = Depends(update_admin), db: Session = Depends(get_db)):
    result = _call(updates.check_source, body.source_revision)
    log_change(db, None, "system_update", result["check"]["id"], "check", actor.id,
               "检查软件更新", new_value={key: result["check"][key] for key in ("version", "commit")})
    db.commit()
    return result


@router.post("/install", status_code=202)
@route_permission_exempt('软件更新处理器只允许真实启用的系统管理员，权限不可委派')
def install(body: InstallBody, actor: User = Depends(update_admin), db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="请确认更新期间应用将短暂不可用")
    result = _call(updates.request_install, body.check_id, actor.id)
    job = result["job"]
    log_change(db, None, "system_update", job["id"], "request", actor.id,
               "请求安装已检查的软件版本", new_value={"version": job["target_version"], "commit": job["target_commit"]})
    db.commit()
    return result

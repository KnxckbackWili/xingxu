"""Projects: the gap overview, the one-request snapshot, ticks on the vehicle table, the trash."""
import hashlib

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, records
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.records import KINDS, PROJECT_FIELDS, iso
from app.services.change_log import log_change
from app.services.cleanup import purge_project
from app.services.gaps import project_gaps
from app.time_utils import utcnow

router = APIRouter(tags=["项目"])
MAX_NEW_VEHICLES = 200
# template list -> (project kind, fields carried over)
TEMPLATE_COPY = {"work": ("work", ("stage", "name")), "document": ("documents", ("name",)),
                 "step": ("steps", ("name",)), "item": ("items", ("name", "spec", "quantity", "unit"))}


def project_dict(project: models.Project) -> dict:
    return {"id": project.id, "name": project.name, "contract_no": project.contract_no, "customer": project.customer,
            "note": project.note, "is_closed": project.is_closed, "rev": project.rev,
            "created_at": iso(project.created_at), "updated_at": iso(project.updated_at),
            "deleted_at": iso(project.deleted_at)}


def _not_modified(request: Request, etag: str):
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return None


def _live_rows(db: Session, kind_key: str, project_id: str):
    kind = KINDS[kind_key]
    query = db.query(kind.model).filter_by(project_id=project_id, deleted_at=None)
    order = (kind.model.sort_order, kind.model.created_at) if kind.ordered else (kind.model.created_at, kind.model.id)
    return query.order_by(*order).all()


def file_dict(row: models.File) -> dict:
    return {"id": row.id, "owner_kind": row.owner_kind, "owner_id": row.owner_id, "filename": row.filename,
            "size": row.size, "mime": row.mime, "created_by": row.created_by, "created_at": iso(row.created_at)}


def snapshot(db: Session, project: models.Project) -> dict:
    """Everything the project page shows, in one answer."""
    data = {"project": project_dict(project)}
    for key in records.PROJECT_KINDS:
        data[key.replace("-", "_")] = [records.row_dict(KINDS[key], row) for row in _live_rows(db, key, project.id)]
    vehicles = {row["id"] for row in data["vehicles"]}
    steps = {row["id"] for row in data["steps"]}
    data["vehicle_records"] = [row for row in data["vehicle_records"] if row["vehicle_id"] in vehicles]
    data["marks"] = [{"vehicle_id": mark.vehicle_id, "step_id": mark.step_id, "done_by": mark.done_by, "done_at": iso(mark.done_at)}
                     for mark in db.query(models.VehicleMark).filter_by(project_id=project.id)
                     if mark.vehicle_id in vehicles and mark.step_id in steps]
    documents, issues = {row["id"] for row in data["documents"]}, {row["id"] for row in data["issues"]}
    data["files"] = [file_dict(row) for row in db.query(models.File).filter_by(project_id=project.id, deleted_at=None)
                     .order_by(models.File.created_at, models.File.id)
                     if row.owner_kind == "other" or row.owner_id in (documents if row.owner_kind == "document" else issues)]
    data["people"] = {user.id: user.display_name for user in db.query(models.User)}
    data["vehicle_types"] = [row.name for row in db.query(models.VehicleType).filter_by(is_enabled=True)
                             .order_by(models.VehicleType.sort_order, models.VehicleType.name)]
    return data


@router.get("/overview")
def overview(request: Request, _: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every project with what it still lacks. Unchanged since the caller's copy: 304."""
    projects = db.query(models.Project).filter_by(deleted_at=None).order_by(models.Project.created_at.desc()).all()
    stamp = "|".join(f"{project.id}:{project.rev}" for project in projects)
    etag = '"' + hashlib.sha256(stamp.encode()).hexdigest()[:32] + '"'
    if (unchanged := _not_modified(request, etag)) is not None:
        return unchanged
    gaps = project_gaps(db, [project for project in projects if not project.is_closed])
    body = {"projects": [{**project_dict(project), "gaps": gaps.get(project.id)} for project in projects]}
    return JSONResponse(body, headers={"ETag": etag})


@router.get("/projects")
def list_projects(_: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [project_dict(project) for project in
            db.query(models.Project).filter_by(deleted_at=None).order_by(models.Project.created_at.desc())]


@router.post("/projects")
def create_project(body: dict = Body(...), user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    project_id = body.get("id")
    if project_id is not None:
        if not isinstance(project_id, str) or not records._UUID.match(project_id):
            raise HTTPException(400, "项目编号格式不正确")
        existing = db.get(models.Project, project_id)
        if existing is not None:
            return project_dict(existing)
    count = body.get("vehicle_count") or 0
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= MAX_NEW_VEHICLES:
        raise HTTPException(400, f"车辆台数应为 0 到 {MAX_NEW_VEHICLES} 之间的整数")
    project = models.Project(id=project_id or models.gen_uuid(), created_by=user.id)
    for name in ("name", "contract_no", "customer", "note"):
        setattr(project, name, records.clean(PROJECT_FIELDS[name], body.get(name)))
    db.add(project)
    db.flush()
    template = None
    if body.get("template_id"):
        template = db.get(models.Template, body["template_id"])
        if template is None or template.deleted_at is not None:
            raise HTTPException(400, "所选模板不存在或已删除")
        rows = (db.query(models.TemplateRow).filter_by(template_id=template.id, deleted_at=None)
                .order_by(models.TemplateRow.sort_order, models.TemplateRow.created_at).all())
        positions = {}
        for row in rows:
            key, names = TEMPLATE_COPY[row.kind]
            positions[key] = positions.get(key, 0) + 1
            db.add(KINDS[key].model(project_id=project.id, created_by=user.id, sort_order=positions[key],
                                    **{name: getattr(row, name) for name in names}))
    for number in range(1, count + 1):
        db.add(models.Vehicle(project_id=project.id, created_by=user.id, vehicle_no=f"车辆{number}", sort_order=number))
    log_change(db, project.id, "project", project.id, "create", user, "新建项目",
               new_value={"name": project.name, "template": template.name if template else "", "vehicles": count},
               row_label=project.name)
    db.commit()
    return project_dict(project)


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request, _: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = records.load_scope(db, "project", project_id)
    etag = f'"{project.id}-{project.rev}"'
    if (unchanged := _not_modified(request, etag)) is not None:
        return unchanged
    return JSONResponse(snapshot(db, project), headers={"ETag": etag})


@router.patch("/projects/{project_id}")
def update_project(project_id: str, changes: dict = Body(...), user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    project = db.query(models.Project).filter_by(id=project_id, deleted_at=None).with_for_update().first()
    if project is None:
        raise HTTPException(404, "项目不存在或已删除")
    try:
        changed = records.apply_changes(db, user, project, PROJECT_FIELDS, changes, scope_id=project.id,
                                        kind_key="project", label="项目", row_label=project.name, project_id=project.id)
    except records.Conflict as conflict:
        return JSONResponse(status_code=409, content={"detail": "这一格刚被别人改过", "conflicts": conflict.conflicts,
                                                      "row": project_dict(project)})
    if changed:
        records.bump(db, models.Project, project.id)
    db.commit()
    db.refresh(project)
    return project_dict(project)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    project = db.query(models.Project).filter_by(id=project_id, deleted_at=None).with_for_update().first()
    if project is None:
        raise HTTPException(404, "项目不存在或已删除")
    project.deleted_at, project.deleted_by = utcnow(), user.id
    log_change(db, project.id, "project", project.id, "delete", user, "删除项目（30 天内可恢复）", row_label=project.name)
    records.bump(db, models.Project, project.id)
    db.commit()
    return {"message": "项目已删除，30 天内可以在设置里恢复"}


@router.post("/projects/{project_id}/restore")
def restore_project(project_id: str, user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    project = db.query(models.Project).filter_by(id=project_id).with_for_update().first()
    if project is None:
        raise HTTPException(404, "项目已被彻底清除，无法恢复")
    if project.deleted_at is not None:
        project.deleted_at = project.deleted_by = None
        log_change(db, project.id, "project", project.id, "restore", user, "恢复项目", row_label=project.name)
        records.bump(db, models.Project, project.id)
        db.commit()
    return project_dict(project)


@router.get("/trash/projects")
def trash(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    people = {user.id: user.display_name for user in db.query(models.User)}
    return [{**project_dict(project), "deleted_by_name": people.get(project.deleted_by, "")}
            for project in db.query(models.Project).filter(models.Project.deleted_at.isnot(None))
            .order_by(models.Project.deleted_at.desc())]


@router.delete("/trash/projects/{project_id}")
def purge(project_id: str, user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id,
                                              models.Project.deleted_at.isnot(None)).with_for_update().first()
    if project is None:
        raise HTTPException(404, "回收站里没有这个项目")
    log_change(db, project.id, "project", project.id, "purge", user, "彻底清除项目", row_label=project.name)
    purge_project(db, project)
    db.commit()
    return {"message": "项目已彻底清除"}


def _live(db: Session, model, project_id: str, row_id: str, label: str):
    row = db.query(model).filter_by(id=row_id, project_id=project_id, deleted_at=None).first()
    if row is None:
        raise HTTPException(404, f"{label}不存在或已删除")
    return row


def _done(body: dict) -> bool:
    if not isinstance(body.get("done"), bool):
        raise HTTPException(400, "请说明是打勾还是取消")
    return body["done"]


def _set_mark(db: Session, user, project_id: str, vehicle: models.Vehicle, step: models.ProjectStep, done: bool) -> bool:
    mark = db.query(models.VehicleMark).filter_by(vehicle_id=vehicle.id, step_id=step.id).first()
    if done == (mark is not None):
        return False
    if done:
        try:
            with db.begin_nested():
                db.add(models.VehicleMark(project_id=project_id, vehicle_id=vehicle.id, step_id=step.id, done_by=user.id))
        except IntegrityError:
            return False  # someone ticked the same cell at the same moment
    else:
        db.delete(mark)
    log_change(db, project_id, "vehicles", vehicle.id, "update", user, f"{'完成' if done else '取消'}环节 {step.name}",
               old_value=not done, new_value=done, field="step:" + step.id, row_label=vehicle.vehicle_no)
    return True


@router.put("/projects/{project_id}/vehicles/{vehicle_id}/steps/{step_id}")
def set_mark(project_id: str, vehicle_id: str, step_id: str, body: dict = Body(...),
             user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    records.load_scope(db, "project", project_id)
    vehicle = _live(db, models.Vehicle, project_id, vehicle_id, "车辆")
    step = _live(db, models.ProjectStep, project_id, step_id, "环节")
    done = _done(body)
    if _set_mark(db, user, project_id, vehicle, step, done):
        records.bump(db, models.Project, project_id)
    db.commit()
    return {"vehicle_id": vehicle_id, "step_id": step_id, "done": done}


@router.put("/projects/{project_id}/steps/{step_id}/all")
def set_column(project_id: str, step_id: str, body: dict = Body(...),
               user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Tick (or clear) one step for every vehicle of the project."""
    records.load_scope(db, "project", project_id)
    step = _live(db, models.ProjectStep, project_id, step_id, "环节")
    done = _done(body)
    changed = sum(_set_mark(db, user, project_id, vehicle, step, done)
                  for vehicle in db.query(models.Vehicle).filter_by(project_id=project_id, deleted_at=None))
    if changed:
        records.bump(db, models.Project, project_id)
    db.commit()
    return {"step_id": step_id, "done": done, "changed": changed}

"""Add, edit, delete, restore and reorder the rows of a project's lists and of a template's lists."""
from enum import Enum

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import models, records
from app.db import get_db
from app.deps import get_current_user
from app.records import KINDS

router = APIRouter(tags=["记录"])
ProjectKind = Enum("ProjectKind", {key: key for key in records.PROJECT_KINDS}, type=str)


def _create(db, user, kind, scope_id, body):
    records.load_scope(db, kind.scope, scope_id)
    row, _ = records.create(db, user, kind, scope_id, body)
    db.commit()
    return records.row_dict(kind, row)


def _patch(db, user, kind, scope_id, row_id, changes):
    records.load_scope(db, kind.scope, scope_id)
    try:
        row = records.patch(db, user, kind, scope_id, row_id, changes)
    except records.Conflict as conflict:
        db.rollback()
        return JSONResponse(status_code=409, content={
            "detail": "这一格刚被别人改过", "conflicts": conflict.conflicts, "row": records.row_dict(kind, conflict.row)})
    db.commit()
    return records.row_dict(kind, row)


def _remove(db, user, kind, scope_id, row_id):
    records.load_scope(db, kind.scope, scope_id)
    records.remove(db, user, kind, scope_id, row_id)
    db.commit()
    return {"id": row_id, "deleted": True}


def _restore(db, user, kind, scope_id, row_id):
    records.load_scope(db, kind.scope, scope_id)
    row = records.restore(db, user, kind, scope_id, row_id)
    db.commit()
    return records.row_dict(kind, row)


def _reorder(db, user, kind, scope_id, body):
    records.load_scope(db, kind.scope, scope_id)
    records.reorder(db, user, kind, scope_id, body.get("ids"))
    db.commit()
    return {"message": "顺序已保存"}


@router.post("/projects/{project_id}/{kind}")
def create_row(project_id: str, kind: ProjectKind, body: dict = Body(...),
               user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _create(db, user, KINDS[kind.value], project_id, body)


@router.put("/projects/{project_id}/{kind}/order")
def reorder_rows(project_id: str, kind: ProjectKind, body: dict = Body(...),
                 user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _reorder(db, user, KINDS[kind.value], project_id, body)


@router.patch("/projects/{project_id}/{kind}/{row_id}")
def update_row(project_id: str, kind: ProjectKind, row_id: str, changes: dict = Body(...),
               user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _patch(db, user, KINDS[kind.value], project_id, row_id, changes)


@router.delete("/projects/{project_id}/{kind}/{row_id}")
def delete_row(project_id: str, kind: ProjectKind, row_id: str,
               user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _remove(db, user, KINDS[kind.value], project_id, row_id)


@router.post("/projects/{project_id}/{kind}/{row_id}/restore")
def restore_row(project_id: str, kind: ProjectKind, row_id: str,
                user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _restore(db, user, KINDS[kind.value], project_id, row_id)


ROWS = KINDS["rows"]


@router.post("/templates/{template_id}/rows")
def create_template_row(template_id: str, body: dict = Body(...),
                        user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _create(db, user, ROWS, template_id, body)


@router.put("/templates/{template_id}/rows/order")
def reorder_template_rows(template_id: str, body: dict = Body(...),
                          user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _reorder(db, user, ROWS, template_id, body)


@router.patch("/templates/{template_id}/rows/{row_id}")
def update_template_row(template_id: str, row_id: str, changes: dict = Body(...),
                        user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _patch(db, user, ROWS, template_id, row_id, changes)


@router.delete("/templates/{template_id}/rows/{row_id}")
def delete_template_row(template_id: str, row_id: str,
                        user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _remove(db, user, ROWS, template_id, row_id)


@router.post("/templates/{template_id}/rows/{row_id}/restore")
def restore_template_row(template_id: str, row_id: str,
                         user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _restore(db, user, ROWS, template_id, row_id)

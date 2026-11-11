"""Download a project, its lifecycle table or a template as Excel; read Excel back in."""
from enum import Enum
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import models, records
from app.config import MAX_IMPORT_BYTES
from app.db import get_db
from app.deps import get_current_user
from app.services import excel_io
from app.services.upload_safety import read_upload_limited

router = APIRouter(tags=["Excel"])
ImportKind = Enum("ImportKind", {key: key for key in excel_io.IMPORTERS}, type=str)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(data: bytes, name: str) -> Response:
    return Response(data, media_type=XLSX, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "no-store"})


@router.get("/projects/{project_id}/export.xlsx")
def export_project(project_id: str, _: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = records.load_scope(db, "project", project_id)
    return _download(excel_io.export_project(db, project), f"{project.name}.xlsx")


@router.get("/projects/{project_id}/lifecycle.xlsx")
def export_lifecycle(project_id: str, _: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = records.load_scope(db, "project", project_id)
    return _download(excel_io.export_lifecycle(db, project), f"{project.name}-AGV生命周期表.xlsx")


@router.post("/projects/{project_id}/import/{kind}")
async def import_project(project_id: str, kind: ImportKind, preview: bool = False, file: UploadFile = File(...),
                         user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = records.load_scope(db, "project", project_id)
    data = await read_upload_limited(file, MAX_IMPORT_BYTES, "Excel 文件")
    return excel_io.import_project(db, user, project, kind.value, data, preview=preview)


@router.get("/templates/{template_id}/export.xlsx")
def export_template(template_id: str, _: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    template = records.load_scope(db, "template", template_id)
    return _download(excel_io.export_template(db, template), f"模板-{template.name}.xlsx")


@router.post("/templates/{template_id}/import")
async def import_template(template_id: str, preview: bool = False, file: UploadFile = File(...),
                          user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    template = records.load_scope(db, "template", template_id)
    data = await read_upload_limited(file, MAX_IMPORT_BYTES, "Excel 文件")
    return excel_io.import_template(db, user, template, data, preview=preview)

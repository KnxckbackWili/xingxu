"""Transaction-scoped row serialization for mutable quantity/state aggregates."""
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def lock_record(db: Session, entity, *, conflict_detail: str) -> None:
    """Take a database write lock without modifying user data or timestamps.

    Unlike SELECT FOR UPDATE, a no-op UPDATE serializes writers on SQLite too.
    The caller must authorize before calling and commit/rollback the transaction.
    Read aggregate data only after this returns. Keep related locks in a stable
    order; this helper never locks a second record on the caller's behalf.
    """
    model = type(entity)
    values = {"id": model.id}
    if hasattr(model, "updated_at"):
        values["updated_at"] = model.updated_at
    try:
        result = db.execute(update(model).where(model.id == entity.id).values(**values)
                            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="记录不存在")
        db.refresh(entity)
    except OperationalError as exc:
        db.rollback()
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code in {"40001", "40P01", "55P03"} or "locked" in str(exc.orig).lower() or "busy" in str(exc.orig).lower():
            raise HTTPException(status_code=409, detail=conflict_detail) from None
        raise


def lock_writable_project(db: Session, project, user):
    """Re-read project visibility and archive state under the common first lock.

    Callers perform their action-specific capability/member check after this
    returns, so a permission removed while waiting cannot survive in a cached row.
    """
    from app.services.scope import ensure_project_visible
    from app.services.project_lifecycle import ensure_project_writable
    lock_record(db, project, conflict_detail="项目正由另一操作更新，请稍后重试")
    project = ensure_project_visible(db, project.id, user)
    ensure_project_writable(project)
    return project

"""Implementation selections determine preparation groups by explicit template metadata."""
from sqlalchemy.orm import Session
from app.models import Module, Task
from app.services.generate_tasks import selected_execution_module_ids


def conditions_for_scope(db: Session, template_id: str, module_ids: list[str],
                         excluded_ids=None, excluded_names=None) -> list[str]:
    from app.services.work_items import selected_template_work
    tasks=selected_template_work(db,template_id,module_ids,excluded_ids,excluded_names)
    return sorted({condition for task in tasks for condition in (task.scope_conditions or [])
                   if condition in ('need_wms','need_charging')})

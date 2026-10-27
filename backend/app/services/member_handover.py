"""Published weekly obligations need an explicit qualified successor."""
from fastapi import HTTPException
from app.models import WeeklyPlanCell,Task,User


def ensure_member_handover(db, project, removed):
    if not removed or project.status=='completed':return
    from app.services.weekly_plans import completion_fact,member_ids
    remaining=member_ids(project)-set(removed)
    outstanding=[]
    for cell in db.query(WeeklyPlanCell).filter_by(project_id=project.id,published=True,is_cancelled=False):
        affected=set(cell.assignee_ids or []) & set(removed)
        if not affected:continue
        facts=completion_fact(db,project,cell)
        if facts['is_complete']:continue
        successor=any(identity in remaining and (person:=db.get(User,identity)) is not None and person.is_active and person.role not in ('readonly','external')
                      for identity in cell.assignee_ids or [])
        if successor:continue
        task=db.get(Task,cell.task_id)
        outstanding.append(f"{cell.week_start} · {task.name if task else '原工作'}")
    if outstanding:
        raise HTTPException(400,f"这些成员仍有 {len(outstanding)} 格未完成的已发布周计划，请先在周计划明确交接或取消，再移除成员："+'；'.join(outstanding[:5]))

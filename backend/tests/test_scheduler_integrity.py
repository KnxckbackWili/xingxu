"""Scheduling preserves quantity coverage and structural predecessors on replans."""
from datetime import date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models import Project, Phase, Module, Task, ScheduleEntry, DailyProgress, User
from app.services.scheduler import generate_schedule, reschedule_from

@pytest.fixture
def plan():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        p = Project(name='Integrity', start_date=date(2026,9,1), end_date=date(2026,9,30), members=[])
        db.add(p); db.flush()
        ph = Phase(project_id=p.id, name='Execution', sort_order=1)
        db.add(ph); db.flush()
        m = Module(project_id=p.id, phase_id=ph.id, name='Commissioning', sort_order=1)
        db.add(m); db.flush()
        t = Task(project_id=p.id, module_id=m.id, name='First', target_quantity=4, standard_hours=4, sort_order=1)
        following = Task(project_id=p.id, module_id=m.id, name='Next', target_quantity=2, standard_hours=4, sort_order=2)
        db.add_all([t,following]); db.flush()
        generate_schedule(db,p)
        yield db,p,t,following
    engine.dispose()

def entries(db,t):
    return db.query(ScheduleEntry).filter_by(task_id=t.id).order_by(ScheduleEntry.work_date).all()

@pytest.mark.parametrize('field', ['is_locked','is_confirmed'])
def test_partial_protection_keeps_exact_coverage(plan,field):
    db,p,t,_=plan
    protected=entries(db,t)[0]; setattr(protected,field,True); db.flush()
    for _ in range(2):
        generate_schedule(db,p)
        after=entries(db,t)
        assert protected.id in {e.id for e in after}
        assert sum(e.planned_quantity for e in after)==4
        assert len(after)==2
        assert after[-1].work_date==date(2026,9,2)

def report(db,p,t,entry=None,quantity=1):
    user=User(username='audit',display_name='Audit',password_hash='unused',role='worker')
    db.add(user); db.flush()
    r=DailyProgress(project_id=p.id,task_id=t.id,schedule_entry_id=entry.id if entry else None,
                    work_date=date(2026,9,1),user_id=user.id,completed_quantity=quantity,client_uuid='audit')
    db.add(r); db.flush()
    return r

def test_report_keeps_remaining_days_and_link(plan):
    db,p,t,following=plan
    first=entries(db,t)[0]; r=report(db,p,t,first)
    generate_schedule(db,p)
    after=entries(db,t)
    assert r.schedule_entry_id==first.id
    assert first.id in {e.id for e in after}
    assert sum(e.planned_quantity for e in after)==4
    assert entries(db,following)[0].work_date==date(2026,9,3)

def test_confirmed_predecessor_advances_follower(plan):
    db,p,t,following=plan
    for e in entries(db,t): e.is_confirmed=True
    db.flush(); generate_schedule(db,p)
    assert entries(db,following)[0].work_date>entries(db,t)[-1].work_date

def test_reschedule_preserves_task_and_phase_order(plan):
    db,p,t,following=plan
    ph=Phase(project_id=p.id,name='Acceptance',sort_order=2)
    db.add(ph); db.flush()
    m=Module(project_id=p.id,phase_id=ph.id,name='Final',sort_order=1)
    db.add(m); db.flush()
    final=Task(project_id=p.id,module_id=m.id,name='Final check',target_quantity=2,standard_hours=4)
    db.add(final); db.flush(); generate_schedule(db,p)
    reschedule_from(db,p,date(2026,9,10))
    assert entries(db,t)[0].work_date==date(2026,9,10)
    assert entries(db,following)[0].work_date==date(2026,9,12)
    assert entries(db,final)[0].work_date==date(2026,9,13)

def test_equal_sort_orders_do_not_merge_parallel_modules(plan):
    db,p,t,_=plan; source=db.get(Module,t.module_id)
    other=Module(project_id=p.id,phase_id=source.phase_id,name='Parallel',sort_order=source.sort_order)
    db.add(other); db.flush()
    parallel=Task(project_id=p.id,module_id=other.id,name='Parallel work',target_quantity=2,standard_hours=4)
    db.add(parallel); db.flush(); generate_schedule(db,p)
    assert entries(db,parallel)[0].work_date==entries(db,t)[0].work_date

def test_manually_completed_task_not_generated_again(plan):
    db,p,t,_=plan; t.manually_completed=True; db.flush(); generate_schedule(db,p)
    assert entries(db,t)==[]

def test_unlinked_progress_not_generated_again(plan):
    db,p,t,_=plan; report(db,p,t,quantity=3); generate_schedule(db,p)
    assert sum(e.planned_quantity for e in entries(db,t))==1

def test_finishing_on_project_end_is_not_overflow(plan):
    db,p,t,following=plan
    p.end_date=date(2026,9,3)
    db.flush()
    result=generate_schedule(db,p)
    assert entries(db,following)[-1].work_date==p.end_date
    assert '超出项目结束日期' not in result['warning']

@pytest.mark.parametrize('completed, expected', [(3, 1), (4, 0)])
def test_overdue_replan_subtracts_unlinked_progress(plan, completed, expected):
    db, p, t, _ = plan
    report(db, p, t, quantity=completed)
    reschedule_from(db, p, date(2026, 9, 10))
    assert sum(e.planned_quantity for e in entries(db, t)) == expected


def test_overdue_replan_accounts_for_protected_and_unlinked_quantity(plan):
    db, p, t, _ = plan
    protected = entries(db, t)[0]
    protected.is_locked = True
    report(db, p, t, quantity=1)
    reschedule_from(db, p, date(2026, 9, 10))
    after = entries(db, t)
    assert protected.id in {e.id for e in after}
    assert sum(e.planned_quantity for e in after) == 3
    assert sum(e.planned_quantity for e in after if not e.is_locked) == 1

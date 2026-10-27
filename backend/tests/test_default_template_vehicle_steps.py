"""Default-template vehicle work carries explicit H-2 steps into new projects."""
import os
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from tests.test_vehicle_progress_migration import config

REVISION = 'g3a30b000002'


def test_new_project_vehicle_work_is_bound_to_default_steps(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json={'name': '默认环节', 'start_date': '2026-08-01', 'end_date': '2026-09-30'})
    assert created.status_code == 200, created.text
    pid = created.json()['id']
    generated = client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-02', 'mod-03', 'mod-06']})
    assert generated.status_code == 200, generated.text
    from app.db import SessionLocal
    from app.models import Task
    with SessionLocal() as db:
        rows = {t.name: t.vehicle_step_key for t in db.query(Task).filter(Task.project_id == pid, Task.quantity_type == 'per_vehicle')}
    assert rows['开箱检查'] == 'arrival_inspection'
    assert rows['载荷测试'] == 'single_commissioning'
    assert rows['多车联调'] == 'system_integration'
    assert all(rows.values()), rows


def test_upgrade_binds_only_untouched_default_template_rows(monkeypatch, tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'steps.db')
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = config()
    parent = ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    command.upgrade(cfg, parent)
    engine = sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO phases (id,project_id,name) VALUES ('ph',NULL,'到货检查'),('pp','p','到货检查')"))
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status) VALUES ('p','既有项目','2026-01-01','2026-03-01','executing')"))
        c.execute(sa.text(
            "INSERT INTO tasks (id,project_id,template_id,phase_id,name,quantity_type,manually_completed) VALUES "
            "('task-005',NULL,NULL,'ph','开箱检查','per_vehicle',false),"
            "('task-006',NULL,NULL,'ph','配件清点（客户改名）','per_vehicle',false),"
            "('task-022',NULL,NULL,'ph','多车联调','fixed',false),"
            "('proj-005','p',NULL,'pp','开箱检查','per_vehicle',false)"))
    command.upgrade(cfg, 'head')
    with engine.connect() as c:
        keys = dict(c.execute(sa.text('SELECT id, vehicle_step_key FROM tasks')).all())
        audit = c.execute(sa.text("SELECT new_value FROM change_logs WHERE entity_type='migration' AND entity_id=:r"), {'r': REVISION}).scalars().all()
    assert keys == {'task-005': 'arrival_inspection', 'task-006': None, 'task-022': None, 'proj-005': None}
    assert len(audit) == 1

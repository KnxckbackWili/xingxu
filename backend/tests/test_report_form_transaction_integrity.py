"""报告表单导入的审计及归档原子性。"""

import io
import pytest
from fastapi import HTTPException, UploadFile
from app.db import SessionLocal
from app.models import ItemApplication, Issue, Project, User, VehicleUnit, VehicleLifecycleEvent
from tests.test_project_lifecycle_boundaries import project
from tests.test_report_forms import _lifecycle_xlsx, _quality_form_xlsx, _item_application_docx


@pytest.mark.parametrize('kind,payload,model', [
    ('lifecycle', _lifecycle_xlsx, VehicleLifecycleEvent),
    ('quality-form', _quality_form_xlsx, Issue),
    ('item-application', _item_application_docx, ItemApplication),
])
def test_form_import_and_audit_are_one_atomic_commit(client, pm_headers, monkeypatch, kind, payload, model):
    pid = project(client, pm_headers)
    def fail_audit(*args, **kwargs):
        raise RuntimeError('simulated audit storage failure')
    monkeypatch.setattr('app.routers.report_forms.log_change', fail_audit)
    with pytest.raises(RuntimeError, match='simulated audit storage failure'):
        client.post(f'/api/projects/{pid}/import/{kind}', headers=pm_headers,
                    files={'file': ('form', payload(), 'application/octet-stream')})
    with SessionLocal() as db:
        assert db.query(model).filter_by(project_id=pid).count() == 0
        if kind == 'lifecycle':
            assert db.query(VehicleUnit).filter_by(project_id=pid).count() == 0


@pytest.mark.parametrize('kind', ['lifecycle', 'quality-form', 'item-application', 'create', 'update', 'delete'])
def test_form_writes_recheck_archival_after_preload(client, pm_headers, kind):
    from app.routers import report_forms as routes
    pid = project(client, pm_headers)
    with SessionLocal() as db:
        app = ItemApplication(project_id=pid, title='既有申请')
        db.add(app); db.commit(); aid = app.id
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, p.manager)
        with SessionLocal() as newer:
            newer.get(Project, pid).status = 'archived'; newer.commit()
        with pytest.raises(HTTPException) as error:
            if kind in ('create', 'update', 'delete'):
                kwargs = {'project_id': pid, '_': p, 'user': actor, 'db': stale}
                if kind != 'delete':
                    kwargs['body'] = routes.ItemApplicationBody(title='不应保存')
                if kind != 'create':
                    kwargs['app_id'] = aid
                getattr(routes, kind + '_item_application')(**kwargs)
            else:
                payload, handler = {'lifecycle': (_lifecycle_xlsx, routes.import_lifecycle),
                                    'quality-form': (_quality_form_xlsx, routes.import_quality_form),
                                    'item-application': (_item_application_docx, routes.import_item_application)}[kind]
                handler(project_id=pid, file=UploadFile(filename='form', file=io.BytesIO(payload())),
                        user=actor, _=p, db=stale)
        assert error.value.status_code == 400
        stale.rollback()
    with SessionLocal() as db:
        assert db.get(ItemApplication, aid).title == '既有申请'
        assert db.query(ItemApplication).filter_by(project_id=pid).count() == 1

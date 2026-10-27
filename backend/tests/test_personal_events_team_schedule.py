"""旧个人事项只读归原所有者；新安排只来自已发布周计划。"""
from datetime import date
from sqlalchemy import text
from app.db import SessionLocal,engine
from app.models import User,PersonalEvent,ChangeLog,Notification,NotificationOutbox
from tests.test_project_lifecycle_boundaries import project


def old_event(client,headers,*,owner='pm',name='原个人事项归属',title='原私密事项',notes='原私密备注'):
    pid=project(client,headers,name)
    with SessionLocal() as db:
        uid=db.query(User).filter_by(username=owner).one().id
        row=PersonalEvent(user_id=uid,project_id=pid,work_date=date(2026,9,1),title=title,notes=notes)
        db.add(row);db.commit();return row.id,pid,uid


def test_owner_history_get_preserves_original_and_excludes_other_users(client,pm_headers,admin_headers):
    identity,pid,_=old_event(client,pm_headers)
    other,_,_=old_event(client,admin_headers,owner='admin',title='ADMIN-PRIVATE',notes='ADMIN-PRIVATE-NOTE')
    response=client.get('/api/dashboard/personal-events',headers=pm_headers);assert response.status_code==200,response.text
    row=next(r for r in response.json() if r['id']==identity)
    assert row['title']=='原私密事项' and row['notes']=='原私密备注' and row['project_id']==pid
    assert 'ADMIN-PRIVATE' not in response.text and other not in {r['id'] for r in response.json()}
    admin=client.get('/api/dashboard/personal-events',headers=admin_headers)
    assert admin.status_code==200 and identity not in {r['id'] for r in admin.json()}


def test_history_does_not_disclose_current_name_of_invisible_project(client,pm_headers,admin_headers):
    identity,pid,_=old_event(client,admin_headers,owner='pm',name='HIDDEN-CURRENT-PROJECT',title='所有者原文仍可读',notes='所有者原备注')
    response=client.get('/api/dashboard/personal-events',headers=pm_headers);assert response.status_code==200,response.text
    row=next(r for r in response.json() if r['id']==identity)
    assert row['title']=='所有者原文仍可读' and row['notes']=='所有者原备注'
    assert not row['project_name'] and 'HIDDEN-CURRENT-PROJECT' not in response.text


def test_retired_personal_mutations_change_no_rows_audit_or_outbox(client,pm_headers,admin_headers):
    from app.services.project_retention import _row
    identity,pid,_=old_event(client,pm_headers)
    models=(PersonalEvent,ChangeLog,Notification,NotificationOutbox)
    with SessionLocal() as db:before={m.__tablename__:[_row(r) for r in db.query(m).order_by(m.id)] for m in models}
    body={'project_id':pid,'work_date':'2026-09-02','title':'不得再新增或修改','notes':'原文必须保持'}
    for headers in (pm_headers,admin_headers):
        for method,path in [('POST','/api/dashboard/personal-events'),('PUT','/api/dashboard/personal-events/'+identity),('DELETE','/api/dashboard/personal-events/'+identity)]:
            response=client.request(method,path,headers=headers,json=body);assert response.status_code==410,response.text
    with SessionLocal() as db:assert {m.__tablename__:[_row(r) for r in db.query(m).order_by(m.id)] for m in models}==before
    client.cookies.clear()
    for method,path in [('POST','/api/dashboard/personal-events'),('PUT','/api/dashboard/personal-events/'+identity),('DELETE','/api/dashboard/personal-events/'+identity)]:
        assert client.request(method,path).status_code==401


def test_personal_event_missing_project_column_migration_preserves_owner_original(client,pm_headers,upgrade_legacy_schema):
    with SessionLocal() as db:uid=db.query(User).filter_by(username='pm').one().id
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE personal_events'))
        connection.execute(text('CREATE TABLE personal_events (id VARCHAR(36) PRIMARY KEY,user_id VARCHAR(36) NOT NULL,work_date DATE NOT NULL,title VARCHAR(100) NOT NULL,notes VARCHAR(500),created_at TIMESTAMP)'))
        connection.execute(text("INSERT INTO personal_events (id,user_id,work_date,title,notes) VALUES ('original-personal-event',:uid,'2026-09-01','原无项目私密事项','原备注不猜归属')"),{'uid':uid})
    upgrade_legacy_schema()
    with SessionLocal() as db:
        row=db.get(PersonalEvent,'original-personal-event')
        assert row.user_id==uid and row.project_id is None and row.title=='原无项目私密事项' and row.notes=='原备注不猜归属'
    response=client.get('/api/dashboard/personal-events',headers=pm_headers);assert response.status_code==200,response.text
    row=next(r for r in response.json() if r['id']=='original-personal-event')
    assert not row['project_id'] and not row['project_name'] and row['title']=='原无项目私密事项'

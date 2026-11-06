import pytest
"""Stage/work items preserve original identities while removing quantity writes."""
from app.db import SessionLocal
from app.models import Project, Task, Module, CheckItem
from tests.test_vehicle_progress import setup_fleet,write


def phase(client,h,pid):
    r=client.post(f'/api/projects/{pid}/work-phases',headers=h,json={'name':'实施工作'})
    assert r.status_code==200,r.text
    return r.json()['id']


def create(client,h,pid,ph,**extra):
    r=client.post(f'/api/projects/{pid}/work-items',headers=h,json={'phase_id':ph,'name':'现场确认',**extra})
    assert r.status_code==200,r.text
    return r.json()


def test_vehicle_work_uses_real_matrix_and_safety_definitions_no_bool_override(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph,kind='vehicle',vehicle_step_key='arrival_inspection',checks=[{'name':'急停','is_safety_critical':True}])
    assert row['matrix']['name']=='到场点检' and not row['is_completed']
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}/completion",headers=pm_headers,json={'version':0,'is_completed':True,'reason':'不能跳过实车'}).status_code==400
    assert write(client,pm_headers,pid,ids).status_code==400
    with SessionLocal() as db:
        check=db.query(CheckItem).filter_by(task_id=row['id']).one();cid=check.id
        assert check.vehicle_unit_id==ids[0]
    r=client.put(f'/api/projects/{pid}/check-items/{cid}',headers=pm_headers,json={'version':0,'is_done':True})
    assert r.status_code==200,r.text
    assert write(client,pm_headers,pid,ids).status_code==200
    listed=client.get(f'/api/projects/{pid}/work-items',headers=pm_headers).json()
    assert next(w for p in listed['phases'] for w in p['work_items'] if w['id']==row['id'])['is_completed']


def test_before_entry_and_unknown_quantity_fields_cannot_grant_completion(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1,status='preparing');ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph)
    url=f"/api/projects/{pid}/work-items/{row['id']}"
    assert client.put(url,headers=pm_headers,json={'version':0,'target_quantity':100}).status_code==422
    assert client.put(url+'/completion',headers=pm_headers,json={'version':0,'is_completed':True,'reason':'尚未实施'}).status_code==400


def test_member_boolean_completion_and_same_failed_version_override(client,pm_headers,worker_headers):
    from app.models import User
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    with SessionLocal() as db:
        worker=db.query(User).filter_by(username='worker1').one();p=db.get(Project,pid);db.commit()
    row=create(client,pm_headers,pid,ph,checks=[{'name':'普通必检'}]);cid=row['check_items'][0]['id']
    url=f"/api/projects/{pid}/work-items/{row['id']}/completion"
    assert client.put(url,headers=worker_headers,json={'version':0,'is_completed':True,'reason':'尚未检查'}).status_code==400
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=worker_headers,json={'version':0,'failed':True,'failed_reason':'现场缺少测试条件'}).status_code==200
    assert client.put(url,headers=worker_headers,json={'version':0,'is_completed':True,'reason':'普通成员不能覆盖失败','override_failed':True,'failed_checks':[{'id':cid,'version':1}]}).status_code==400
    assert client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':'明确约定后续补测，风险已隔离','override_failed':True,'failed_checks':[{'id':cid,'version':0}]}).status_code==409
    r=client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':'明确约定后续补测，风险已隔离','override_failed':True,'failed_checks':[{'id':cid,'version':1}]})
    assert r.status_code==200,r.text
    assert client.put(url,headers=worker_headers,json={'version':1,'is_completed':False,'reason':'现场仍需继续工作'}).status_code==200


def test_quality_retraction_invalidates_eligibility_without_erasing_completion_fact(client,pm_headers):
    from app.services.progress import project_completion_blocker_tasks,task_progress_maps
    pid,_=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph,checks=[{'name':'必需复测'}]);cid=row['check_items'][0]['id']
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=pm_headers,json={'version':0,'is_done':True}).status_code==200
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}/completion",headers=pm_headers,json={'version':0,'is_completed':True,'reason':'当时验证通过'}).status_code==200
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=pm_headers,json={'version':1,'is_done':False}).status_code==200
    with SessionLocal() as db:
        t=db.get(Task,row['id']);assert t.manually_completed and t.manual_completed_reason=='当时验证通过'
        assert task_progress_maps(db,[t])[2][t.id]<100
        assert t.id in {t.id for t in project_completion_blocker_tasks(db,pid)}


def test_canonical_work_rejects_legacy_quantity_writes_and_new_work_appends(client,pm_headers):
    pid,_=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph,sort_order=9)
    assert create(client,pm_headers,pid,ph,name='追加工作')['sort_order']==10
    assert client.put(f"/api/projects/{pid}/tasks/{row['id']}",headers=pm_headers,json={'target_quantity':9,'version':0}).status_code==422
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}",headers=pm_headers,json={'name':' ', 'version':0}).status_code==400
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}",headers=pm_headers,json={'phase_id':None,'version':0}).status_code==400
    tree=client.get(f'/api/projects/{pid}/tree',headers=pm_headers).json();assert row['id'] in {t['id'] for p in tree for t in p['work_items']}
    response=client.get(f"/api/projects/{pid}/tasks/{row['id']}/workspace",headers=pm_headers)
    assert response.status_code==200 and response.json()['work_item']['id']==row['id'],response.text


def test_project_lock_rechecks_quality_before_boolean_completion(client,pm_headers):
    from app.db import engine
    import pytest
    if engine.dialect.name!='postgresql':pytest.skip('真实 PostgreSQL 双会话锁探针')
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import HTTPException
    from app.models import User
    from app.services.record_lock import lock_writable_project
    from app.services.work_items import complete
    pid,_=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph,checks=[{'name':'必需检查'}]);cid=row['check_items'][0]['id']
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=pm_headers,json={'version':0,'is_done':True}).status_code==200
    entered=Event()
    def attempt():
        with SessionLocal() as db:
            actor=db.query(User).filter_by(username='pm').one();db.get(CheckItem,cid);entered.set()
            try:complete(db,db.get(Project,pid),actor,row['id'],{'version':0,'is_completed':True,'reason':'不能使用旧检查缓存'})
            except HTTPException as exc:db.rollback();return exc.status_code
        return 200
    with SessionLocal() as first,ThreadPoolExecutor(max_workers=1) as pool:
        actor=first.query(User).filter_by(username='pm').one();lock_writable_project(first,first.get(Project,pid),actor)
        check=first.get(CheckItem,cid);check.is_done=False;check.version+=1;first.flush()
        future=pool.submit(attempt);assert entered.wait(2);assert not future.done();first.commit();assert future.result(timeout=10)==400
    with SessionLocal() as db:assert not db.get(Task,row['id']).manually_completed


@pytest.mark.parametrize('status',['suspended','completed','archived'])
def test_canonical_and_legacy_plan_adapters_respect_closed_project_status(client,pm_headers,status):
    pid,_=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid);row=create(client,pm_headers,pid,ph)
    with SessionLocal() as db:db.get(Project,pid).status=status;db.commit()
    listed=client.get(f'/api/projects/{pid}/work-items',headers=pm_headers).json();assert not listed['permissions']['plan'] and not listed['permissions']['record']
    for segment in ('tasks','work-items'):
        assert client.put(f"/api/projects/{pid}/{segment}/{row['id']}",headers=pm_headers,json={'version':0,'name':'不可修改'}).status_code==400
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}/completion",headers=pm_headers,json={'version':0,'is_completed':True,'reason':'不能越过状态'}).status_code==400
    with SessionLocal() as db:assert db.get(Task,row['id']).name=='现场确认' and not db.get(Task,row['id']).manually_completed


def test_flat_work_creates_no_module_and_boolean_completion_requires_reason_and_cas(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    with SessionLocal() as db:before=db.query(Module).filter_by(project_id=pid).count()
    row=create(client,pm_headers,pid,ph,description='完整施工说明',group_label='原模块标签')
    assert row['kind']=='other' and not row['is_completed'] and row['group_label']=='原模块标签'
    with SessionLocal() as db:
        task=db.get(Task,row['id']);assert task.module_id is None and task.phase_id==ph
        assert db.query(Module).filter_by(project_id=pid).count()==before
    url=f"/api/projects/{pid}/work-items/{row['id']}/completion"
    assert client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':' '}).status_code==400
    r=client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':'现场实测已确认'})
    assert r.status_code==200 and r.json()['is_completed'],r.text
    assert client.put(url,headers=pm_headers,json={'version':0,'is_completed':False,'reason':'迟到旧页面'}).status_code==409
    r=client.put(url,headers=pm_headers,json={'version':1,'is_completed':False,'reason':'复测发现需返工'})
    assert r.status_code==200 and not r.json()['is_completed']
    listed=client.get(f'/api/projects/{pid}/work-items',headers=pm_headers).json()
    item=next(w for p in listed['phases'] for w in p['work_items'] if w['id']==row['id'])
    assert item['description']=='完整施工说明'

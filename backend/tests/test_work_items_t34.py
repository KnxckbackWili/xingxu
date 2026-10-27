import pytest
"""Stage/work items preserve original identities while removing quantity writes."""
from app.db import SessionLocal
from app.models import Project,Task,Module,DailyProgress,CheckItem
from tests.test_vehicle_progress import setup_fleet,write


def phase(client,h,pid):
    r=client.post(f'/api/projects/{pid}/work-phases',headers=h,json={'name':'实施工作'})
    assert r.status_code==200,r.text
    return r.json()['id']


def create(client,h,pid,ph,**extra):
    r=client.post(f'/api/projects/{pid}/work-items',headers=h,json={'phase_id':ph,'name':'现场确认',**extra})
    assert r.status_code==200,r.text
    return r.json()


def test_flat_work_creates_no_module_and_boolean_completion_requires_reason_and_cas(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    with SessionLocal() as db:before=db.query(Module).filter_by(project_id=pid).count()
    row=create(client,pm_headers,pid,ph,description='完整施工说明',group_label='原模块标签')
    assert row['kind']=='other' and not row['is_completed'] and row['group_label']=='原模块标签'
    with SessionLocal() as db:
        task=db.get(Task,row['id']);assert task.module_id is None and task.phase_id==ph
        assert task.target_quantity is None and db.query(Module).filter_by(project_id=pid).count()==before
    url=f"/api/projects/{pid}/work-items/{row['id']}/completion"
    assert client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':' '}).status_code==400
    r=client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':'现场实测已确认'})
    assert r.status_code==200 and r.json()['is_completed'],r.text
    assert client.put(url,headers=pm_headers,json={'version':0,'is_completed':False,'reason':'迟到旧页面'}).status_code==409
    r=client.put(url,headers=pm_headers,json={'version':1,'is_completed':False,'reason':'复测发现需返工'})
    assert r.status_code==200 and not r.json()['is_completed']
    with SessionLocal() as db:assert db.query(DailyProgress).filter_by(task_id=row['id']).count()==0
    listed=client.get(f'/api/projects/{pid}/work-items',headers=pm_headers).json()
    item=next(w for p in listed['phases'] for w in p['work_items'] if w['id']==row['id'])
    assert item['description']=='完整施工说明'


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


def test_template_direct_work_copy_generate_export_and_portable_reset(client,admin_headers,pm_headers):
    tid=client.post('/api/templates',headers=admin_headers,json={'name':'工作项模板'}).json()['id']
    r=client.post(f'/api/templates/{tid}/work-phases',headers=admin_headers,json={'name':'自定义实施阶段'})
    assert r.status_code==200,r.text
    ph=r.json()['id']
    r=client.post(f'/api/templates/{tid}/work-items',headers=admin_headers,json={'phase_id':ph,'name':'无数量的工作','description':'原说明完整保留','group_label':'范围标签',
        'scope_conditions':['need_wms'],'checks':[{'name':'接口验证','description':'保存原检查说明'}]})
    assert r.status_code==200,r.text
    source=r.json()
    copied=client.post('/api/templates',headers=admin_headers,json={'name':'新工作模板副本','copy_from':tid})
    assert copied.status_code==200,copied.text
    rows=client.get(f"/api/templates/{copied.json()['id']}/work-items",headers=admin_headers).json()['phases']
    copy=next(w for p in rows for w in p['work_items'] if w['name']=='无数量的工作')
    assert copy['description']=='原说明完整保留' and copy['group_label']=='范围标签' and copy['scope_conditions']==['need_wms']
    assert copy['check_definitions'][0]['description']=='保存原检查说明'
    pid,ids=setup_fleet(client,pm_headers,1)
    r=client.post(f'/api/projects/{pid}/tasks/generate',headers=pm_headers,json={'template_id':tid,'work_item_ids':[source['id']]})
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        task=db.query(Task).filter_by(project_id=pid,source_task_id=source['id']).one();wid=task.id
        assert task.module_id is None and task.target_quantity is None and task.scope_conditions==['need_wms']
        assert db.query(Module).filter_by(project_id=pid).count()==0
        check=db.query(CheckItem).filter_by(task_id=wid).one();cid=check.id
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=pm_headers,json={'version':0,'is_done':True}).status_code==200
    assert client.put(f'/api/projects/{pid}/work-items/{wid}/completion',headers=pm_headers,json={'version':0,'is_completed':True,'reason':'已完成接口闭环'}).status_code==200
    exported=client.get(f'/api/projects/{pid}/export/json',headers=pm_headers)
    assert exported.status_code==200,exported.text
    payload=exported.json();payload['project']['status']='preparing';payload['project']['name']='原工作便携副本'
    assert next(t for m in payload['modules'] for t in m['tasks'] if t['source_id']==wid)['description']=='原说明完整保留'
    imported=client.post('/api/projects/import/json',headers=pm_headers,json=payload)
    assert imported.status_code==200,imported.text
    with SessionLocal() as db:
        fresh=db.query(Task).filter_by(project_id=imported.json()['id'],name='无数量的工作').one()
        assert fresh.module_id is None and fresh.phase_id and not fresh.manually_completed and fresh.target_quantity is None
        assert not db.query(CheckItem).filter_by(task_id=fresh.id).one().is_done
    cloned=client.post(f'/api/projects/{pid}/clone',headers=pm_headers,json={'name':'工作定义克隆'})
    assert cloned.status_code==200,cloned.text
    with SessionLocal() as db:
        fresh=db.query(Task).filter_by(project_id=cloned.json()['id'],name='无数量的工作').one()
        assert fresh.phase_id and fresh.module_id is None and not fresh.manually_completed
        assert not db.query(CheckItem).filter_by(task_id=fresh.id).one().is_done


def test_member_boolean_completion_and_same_failed_version_override(client,pm_headers,worker_headers):
    from app.models import User
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    with SessionLocal() as db:
        worker=db.query(User).filter_by(username='worker1').one();p=db.get(Project,pid);p.members=[worker.id];db.commit()
    row=create(client,pm_headers,pid,ph,checks=[{'name':'普通必检'}]);cid=row['check_items'][0]['id']
    url=f"/api/projects/{pid}/work-items/{row['id']}/completion"
    assert client.put(url,headers=worker_headers,json={'version':0,'is_completed':True,'reason':'尚未检查'}).status_code==400
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=worker_headers,json={'version':0,'failed':True,'failed_reason':'现场缺少测试条件'}).status_code==200
    assert client.put(url,headers=worker_headers,json={'version':0,'is_completed':True,'reason':'普通成员不能覆盖失败','override_failed':True,'failed_checks':[{'id':cid,'version':1}]}).status_code==400
    assert client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':'明确约定后续补测，风险已隔离','override_failed':True,'failed_checks':[{'id':cid,'version':0}]}).status_code==409
    r=client.put(url,headers=pm_headers,json={'version':0,'is_completed':True,'reason':'明确约定后续补测，风险已隔离','override_failed':True,'failed_checks':[{'id':cid,'version':1}]})
    assert r.status_code==200,r.text
    assert client.put(url,headers=worker_headers,json={'version':1,'is_completed':False,'reason':'现场仍需继续工作'}).status_code==200


def test_old_uuid_is_preserved_and_readonly_even_after_structure_changes(client,pm_headers):
    from app.models import User
    from datetime import date
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph)
    uuid='old-report-exact-payload-0001'
    with SessionLocal() as db:
        uid=db.query(User).filter_by(username='pm').one().id
        report=DailyProgress(project_id=pid,task_id=row['id'],user_id=uid,work_date=date(2026,1,1),completed_quantity=2.7,note='原事实',client_uuid=uuid)
        db.add(report);db.commit();rid=report.id
    payload={'task_id':row['id'],'work_date':'2026-01-01','completed_quantity':2.7,'note':'原事实','client_uuid':uuid}
    assert client.post('/api/worker/reports',headers=pm_headers,json=payload).status_code==410
    def sync(values):
        return client.post('/api/worker/sync',headers=pm_headers,json={'ops':[{'type':'report','client_uuid':values['client_uuid'],'payload':values}]}).json()
    assert sync(payload)['accepted']==[uuid]
    assert sync({**payload,'completed_quantity':3})['deferred']==[uuid]
    unknown='unknown-preserve-original-0001'
    assert sync({**payload,'client_uuid':unknown})['deferred']==[unknown]
    assert client.delete(f'/api/worker/reports/{rid}',headers=pm_headers).status_code==410
    history=client.get(f"/api/projects/{pid}/work-items/{row['id']}/history",headers=pm_headers).json()
    assert history['reports'][0]['client_uuid']==uuid and history['reports'][0]['completed_quantity']==2.7
    with SessionLocal() as db:
        assert db.query(DailyProgress).filter_by(task_id=row['id']).count()==1
        assert not db.get(Task,row['id']).manually_completed


def test_unknown_legacy_report_sync_is_deferred_without_clearing_uuid(client,pm_headers):
    from app.models import OfflineOpReceipt
    pid,ids=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid);row=create(client,pm_headers,pid,ph)
    uuid='legacy-unknown-no-clear-0001'
    body={'ops':[{'type':'report','client_uuid':uuid,'payload':{'project_id':pid,'task_id':row['id'],'work_date':'2026-01-01','completed_quantity':2.3,'note':'原始内容保留'}}]}
    for _ in range(2):
        r=client.post('/api/worker/sync',headers=pm_headers,json=body)
        assert r.status_code==200,r.text
        assert r.json()['deferred']==[uuid] and r.json()['accepted']==[] and r.json()['rejected']==[]
    with SessionLocal() as db:
        assert db.query(DailyProgress).filter_by(task_id=row['id']).count()==0
        assert db.query(OfflineOpReceipt).filter_by(client_uuid=uuid).count()==0


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


def test_missing_step_blocks_and_retired_preparation_is_readonly_discoverable(client,pm_headers):
    from app.models import Phase
    from app.services.progress import project_completion_blocker_tasks
    pid,_=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    with SessionLocal() as db:
        prep=Phase(project_id=pid,name='项目准备');db.add(prep);db.flush()
        old=Task(project_id=pid,phase_id=prep.id,name='原资料工作',quantity_type='fixed',target_quantity=2,unit='份');db.add(old);db.flush()
        ci=CheckItem(task_id=old.id,project_id=pid,name='原检查',is_safety_critical=True);db.add(ci)
        car=Task(project_id=pid,phase_id=ph,name='原环节未映射',quantity_type='per_vehicle',target_quantity=2);db.add(car);db.commit();wid=old.id;cid=ci.id;carid=car.id
    data=client.get(f'/api/projects/{pid}/work-items',headers=pm_headers).json()
    assert wid in {t['id'] for t in data['legacy_work_items']}
    assert client.get(f'/api/projects/{pid}/work-items/{wid}/history',headers=pm_headers).status_code==200
    assert client.put(f'/api/projects/{pid}/work-items/{wid}',headers=pm_headers,json={'version':0,'name':'不能修改'}).status_code==400
    assert client.put(f'/api/projects/{pid}/work-items/{wid}/completion',headers=pm_headers,json={'version':0,'is_completed':True,'reason':'旧资料不能重新完成'}).status_code==400
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=pm_headers,json={'version':0,'is_done':True}).status_code==400
    with SessionLocal() as db:
        assert db.get(Task,wid).name=='原资料工作' and not db.get(CheckItem,cid).is_done
        blocked={t.id for t in project_completion_blocker_tasks(db,pid)};assert wid not in blocked and carid in blocked


def test_canonical_work_rejects_legacy_quantity_writes_and_new_work_appends(client,pm_headers):
    pid,_=setup_fleet(client,pm_headers,1);ph=phase(client,pm_headers,pid)
    row=create(client,pm_headers,pid,ph,sort_order=9)
    assert create(client,pm_headers,pid,ph,name='追加工作')['sort_order']==10
    assert client.put(f"/api/projects/{pid}/tasks/{row['id']}",headers=pm_headers,json={'target_quantity':9,'version':0}).status_code==400
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}",headers=pm_headers,json={'name':' ', 'version':0}).status_code==400
    assert client.put(f"/api/projects/{pid}/work-items/{row['id']}",headers=pm_headers,json={'phase_id':None,'version':0}).status_code==400
    tree=client.get(f'/api/projects/{pid}/tree',headers=pm_headers).json();assert row['id'] in {t['id'] for p in tree for t in p['work_items']}
    response=client.get(f"/api/projects/{pid}/tasks/{row['id']}/workspace",headers=pm_headers)
    assert response.status_code==200 and response.json()['work_item']['id']==row['id'],response.text
    with SessionLocal() as db:assert db.get(Task,row['id']).target_quantity is None


def test_template_roundtrip_keeps_readonly_snapshot_and_edit_returns_to_draft(client,admin_headers):
    from app.models import Template
    tid=client.post('/api/templates',headers=admin_headers,json={'name':'来源保全'}).json()['id']
    ph=client.post(f'/api/templates/{tid}/work-phases',headers=admin_headers,json={'name':'来源阶段'}).json()['id']
    row=client.post(f'/api/templates/{tid}/work-items',headers=admin_headers,json={'phase_id':ph,'name':'来源工作','group_label':'独立标签','scope_conditions':['need_wms']}).json()
    source={'kind':'original_source','target':2.7,'unit':'套','unmodified':{'name':'原始工作'}}
    with SessionLocal() as db:db.get(Task,row['id']).legacy_work_snapshot=source;db.commit()
    tree=client.get(f'/api/templates/{tid}/tree',headers=admin_headers).json()
    r=client.put(f'/api/templates/{tid}/tree',headers=admin_headers,json={'phases':tree});assert r.status_code==200,r.text
    with SessionLocal() as db:
        t=db.get(Task,row['id']);assert (t.legacy_work_snapshot,t.scope_conditions,t.group_label)==(source,['need_wms'],'独立标签')
        db.get(Template,tid).status='published';db.commit()
    current=next(w for p in client.get(f'/api/templates/{tid}/work-items',headers=admin_headers).json()['phases'] for w in p['work_items'] if w['id']==row['id'])
    assert client.put(f"/api/templates/{tid}/work-items/{row['id']}",headers=admin_headers,json={'version':current['version'],'name':'修订工作'}).status_code==200
    with SessionLocal() as db:assert db.get(Template,tid).status=='draft' and db.get(Task,row['id']).legacy_work_snapshot==source


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


def test_work_stage_labels_change_without_destroying_original_phase_names(client,admin_headers,pm_headers):
    from app.models import Phase
    tid=client.post('/api/templates',headers=admin_headers,json={'name':'阶段原名保全'}).json()['id']
    ph=client.post(f'/api/templates/{tid}/work-phases',headers=admin_headers,json={'name':'原自定义阶段'}).json()['id']
    row=client.post(f'/api/templates/{tid}/work-items',headers=admin_headers,json={'phase_id':ph,'name':'联调工作内容'}).json()
    with SessionLocal() as db:db.get(Phase,ph).name='系统联调';db.commit()
    stage=next(p for p in client.get(f'/api/templates/{tid}/work-items',headers=admin_headers).json()['phases'] if p['id']==ph)
    assert stage['name']=='联调工作' and stage['source_name']=='系统联调'
    pid,_=setup_fleet(client,pm_headers,1)
    r=client.post(f'/api/projects/{pid}/tasks/generate',headers=pm_headers,json={'template_id':tid,'work_item_ids':[row['id']]});assert r.status_code==200,r.text
    with SessionLocal() as db:
        assert db.get(Phase,ph).name=='系统联调'
        task=db.query(Task).filter_by(project_id=pid,source_task_id=row['id']).one();assert db.get(Phase,task.phase_id).name=='联调工作'

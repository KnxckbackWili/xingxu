"""Explicit human decisions required by lifecycle fixtures, using real API gates."""


def approve_risk_entry(client, headers, project_id):
    path = f'/api/projects/{project_id}/documents/dispatch-review'
    manifest = client.post(path, headers=headers)
    assert manifest.status_code == 200, manifest.text
    response = client.post(path + '/confirm', headers=headers, json={
        'conclusion': 'risky', 'notes': '测试项目负责人已核对当前条件，接受遗留风险并负责跟进',
        'review_token': manifest.json()['review_token'],
    })
    assert response.status_code == 200, response.text
    assert response.json()['summary']['entry_confirmed']


def sign_current_scope(client, headers, project_id):
    response = client.post(f'/api/projects/{project_id}/acceptance', headers=headers, json={
        'accepted_by_name': '客户验收代表', 'accepted_at': '2026-09-30',
        'conclusion': 'accepted', 'notes': '已复核当前实施范围和必需质量、交付要求',
    })
    assert response.status_code == 200, response.text
    assert response.json()['scope_current']


def complete_vehicle_progress(client, headers, project_id):
    """Explicit real-identity fixture for tests that intend a fully complete scope."""
    from app.time_utils import project_today
    current = client.get(f'/api/projects/{project_id}', headers=headers)
    assert current.status_code == 200, current.text
    completed_on = project_today(current.json().get('timezone')).isoformat()
    vehicles=client.get(f'/api/projects/{project_id}/vehicles',headers=headers).json()
    if not vehicles:
        response=client.post(f'/api/projects/{project_id}/vehicles',headers=headers,json={
            'vehicle_type':'潜伏式','model_name':'测试实车','quantity':1})
        assert response.status_code==200,response.text
        vehicles=[response.json()]
    units=client.get(f'/api/projects/{project_id}/vehicle-units',headers=headers).json()
    for vehicle in vehicles:
        existing=[u for u in units if u['vehicle_id']==vehicle['id']]
        for index in range(len(existing),vehicle['quantity']):
            response=client.post(f'/api/projects/{project_id}/vehicle-units',headers=headers,json={
                'vehicle_id':vehicle['id'],'asset_code':f"TEST-REAL-{vehicle['id']}-{index+1}"})
            assert response.status_code==200,response.text
    response=client.get(f'/api/projects/{project_id}/vehicle-progress',headers=headers)
    assert response.status_code==200,response.text
    matrix=response.json()
    for step in matrix['steps']:
        cells=[{'vehicle_unit_id':u['id'],'step_key':step['key'],'version':u['cells'].get(step['key'],{}).get('version',0)}
               for u in matrix['units'] if not u['cells'].get(step['key'],{}).get('is_done')]
        if not cells:continue
        response=client.put(f'/api/projects/{project_id}/vehicle-progress',headers=headers,json={
            'cells':cells,'is_done':True,'done_on':completed_on,'note':'测试明确登记实车环节'})
        assert response.status_code==200,response.text


def register_kickoff(client, headers, project_id, day='2026-08-03'):
    """Record the actual internal kickoff so lifetime (stage 9) documents exist."""
    version = client.get(f'/api/projects/{project_id}', headers=headers).json()['version']
    response = client.put(f'/api/projects/{project_id}/events/internal_kickoff', headers=headers,
                          json={'actual_date': day, 'version': version})
    assert response.status_code == 200, response.text


def project_version(client, headers, project_id):
    response = client.get(f'/api/projects/{project_id}', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()['version']


def versioned(entity_id, body, model='Project'):
    """Edit body carrying the entity's current version, as a real client would.

    Leaves an explicit version untouched so stale-version tests keep their intent.
    """
    if not isinstance(body, dict) or 'version' in body:
        return body
    import app.models as models
    from app.db import SessionLocal
    with SessionLocal() as db:
        row = db.get(getattr(models, model), entity_id)
        return {**body, 'version': (row.version or 0) if row is not None else 0}


def enter_execution(client, headers, project_id):
    """Walk a new (preparing) project through the real v3 gates into on-site execution.

    Stage-4 kickoff documents are submitted, the project is marked ready, the
    current stage-5 risk is explicitly approved, then execution is entered.
    """
    from tests.document_helpers import documents, upload_documents
    rows = documents(client, headers, project_id)['documents']
    kickoff = [row['id'] for row in rows if row['stage_key'] == '4' and row['required'] and row['applicable'] and row['status'] != 'submitted']
    if kickoff:
        upload_documents(client, headers, project_id, kickoff)
    for target in ('ready', 'executing'):
        if target == 'executing':
            approve_risk_entry(client, headers, project_id)
        response = client.post(f'/api/projects/{project_id}/status', headers=headers, json={'status': target})
        assert response.status_code == 200, response.text


def complete_all_work(client, headers, project_id, *, recorder_headers=None):
    """Record every real vehicle step, required check and non-vehicle work item as done."""
    from app.db import SessionLocal
    from app.models import CheckItem, Task
    recorder = recorder_headers or headers
    complete_vehicle_progress(client, headers, project_id)
    with SessionLocal() as db:
        tasks = [t.id for t in db.query(Task).filter_by(project_id=project_id) if t.quantity_type != 'per_vehicle']
        checks = [(c.id, c.version or 0) for c in db.query(CheckItem).filter(CheckItem.task_id.in_(tasks), CheckItem.is_done.is_not(True))]
    for cid, version in checks:
        response = client.put(f'/api/projects/{project_id}/check-items/{cid}', headers=recorder, json={'is_done': True, 'version': version})
        assert response.status_code == 200, response.text
    for tid in tasks:
        with SessionLocal() as db:
            task = db.get(Task, tid)
            if task.manually_completed:
                continue
            version = task.version or 0
        response = client.put(f'/api/projects/{project_id}/work-items/{tid}/completion', headers=recorder,
                              json={'version': version, 'is_completed': True, 'reason': '现场完成并自检'})
        assert response.status_code == 200, response.text
    return tasks


def read_tasks(client, headers, pid):
    tree = client.get(f'/api/projects/{pid}/tree', headers=headers).json()
    return [task for phase in tree for module in phase['modules'] for task in module['tasks']]


def setup_project(client, headers):
    """Project created from the default template with module mod-01; returns (pid, work items)."""
    response = client.post('/api/projects', headers=headers, json={
        'name': '开工安排测试', 'client': '客户', 'start_date': '2026-09-16',
        'end_date': '2026-10-30', 'new_vehicles': False,
        'template_id': 'default', 'module_ids': ['mod-01'],
    })
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    return pid, read_tasks(client, headers, pid)


def put_check(client, headers, pid, check_id, body):
    """Check-item registration with the row's current version (required by the API)."""
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        version = db.get(CheckItem, check_id).version or 0
    return client.put(f"/api/projects/{pid}/check-items/{check_id}", headers=headers, json={**body, "version": version})


def transfer_manager(client, headers, pid, target_id, reason='负责人交接，测试转移'):
    """Change the project manager via the dedicated transfer endpoint (PUT manager_id is rejected)."""
    preview = client.get(f'/api/projects/{pid}/transfer-preview', headers=headers)
    confirmations = [row['user_id'] for row in preview.json().get('removed', [])] if preview.status_code == 200 else []
    version = client.get(f'/api/projects/{pid}', headers=headers).json()['version']
    return client.post(f'/api/projects/{pid}/transfer', headers=headers, json={
        'target_manager_id': target_id, 'reason': reason, 'version': version,
        'member_removal_confirmations': confirmations})


def second_pm(client, admin_headers, username='pm-successor'):
    """An additional active PM (transfer targets must be PMs)."""
    created = client.post('/api/users', headers=admin_headers, json={
        'username': username, 'password': 'successor12345', 'display_name': '接任项目经理', 'role': 'pm'})
    assert created.status_code == 200, created.text
    return created.json()['id']

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

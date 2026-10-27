def _project(client, headers):
    result = client.post('/api/projects', headers=headers, json={
        'name': '快捷状态测试', 'start_date': '2026-10-06', 'end_date': '2026-11-30', 'status': 'preparing',
    })
    assert result.status_code == 200, result.text
    return result.json()['id']


def test_item_quick_status_preserves_details_balance_and_rejects_stale_or_extra_fields(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    body = {'name': '测试网线', 'quantity': 25, 'unit': '米', 'status': 'on_site', 'location': '控制柜',
            'custodian': '李工', 'item_code': 'QUICK-01', 'category': 'material', 'ownership': 'client',
            'note': '这段信息不能被快捷状态覆盖', 'received_date': '2026-10-06', 'extra': {'source': 'QA'}}
    created = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers, json=body)
    assert created.status_code == 200, created.text
    endpoint = f"/api/projects/{pid}/inventory/{created.json()['id']}/status"
    updated = client.patch(endpoint, headers=pm_headers, json={'status': 'in_use', 'expected_status': 'on_site'})
    assert updated.status_code == 200, updated.text
    for key, value in body.items():
        assert updated.json()[key] == ('in_use' if key == 'status' else value)
    assert updated.json()['movement_count'] == created.json()['movement_count']
    assert client.patch(endpoint, headers=pm_headers, json={'status': 'lost', 'expected_status': 'on_site'}).status_code == 409
    assert client.patch(endpoint, headers=pm_headers, json={'status': 'lost', 'expected_status': 'in_use', 'quantity': 0}).status_code == 422
    assert client.patch(endpoint, headers=worker_headers, json={'status': 'lost', 'expected_status': 'in_use'}).status_code in (403, 404)
    listing = client.get(f'/api/projects/{pid}/inventory', headers=pm_headers).json()['items'][0]
    assert listing['status'] == 'in_use' and listing['quantity'] == 25 and listing['note'] == body['note']


def test_application_quick_status_preserves_form_and_rejects_stale_changes(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    body = {'title': '吊车申请', 'item_name': '25吨吊车', 'amount': '3200', 'applicant': '李工',
            'approver': '王工', 'department': '实施部', 'apply_date': '2026-10-06', 'requirement': '厂区移位一天',
            'reason': '设备进场', 'contract_no': 'QUICK-02', 'status': 'pending', 'note': '保留审批信息'}
    created = client.post(f'/api/projects/{pid}/item-applications', headers=pm_headers, json=body)
    assert created.status_code == 200, created.text
    endpoint = f"/api/projects/{pid}/item-applications/{created.json()['id']}/status"
    updated = client.patch(endpoint, headers=pm_headers, json={'status': 'approved', 'expected_status': 'pending'})
    assert updated.status_code == 200, updated.text
    for key, value in body.items():
        assert updated.json()[key] == ('approved' if key == 'status' else value)
    assert client.patch(endpoint, headers=pm_headers, json={'status': 'rejected', 'expected_status': 'pending'}).status_code == 409
    assert client.patch(endpoint, headers=pm_headers, json={'status': 'rejected', 'expected_status': 'approved', 'amount': '0'}).status_code == 422
    assert client.patch(endpoint, headers=worker_headers, json={'status': 'rejected', 'expected_status': 'approved'}).status_code in (403, 404)
    final = client.get(f"/api/projects/{pid}/item-applications/{created.json()['id']}", headers=pm_headers).json()
    assert final['status'] == 'approved' and final['amount'] == '3200' and final['requirement'] == body['requirement']


def test_quick_status_does_not_write_archived_or_unknown_history(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Project
    for state in ['archived', 'legacy_unknown']:
        pid = _project(client, pm_headers)
        item = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers, json={'name': '只读物品', 'quantity': 3}).json()
        app = client.post(f'/api/projects/{pid}/item-applications', headers=pm_headers, json={'title': '只读申请', 'amount': '500'}).json()
        with SessionLocal() as db:
            db.get(Project, pid).status = state
            db.commit()
        result = client.patch(f"/api/projects/{pid}/inventory/{item['id']}/status", headers=pm_headers,
                              json={'status': 'lost', 'expected_status': 'on_site'})
        assert result.status_code == 400
        result = client.patch(f"/api/projects/{pid}/item-applications/{app['id']}/status", headers=pm_headers,
                              json={'status': 'approved', 'expected_status': 'pending'})
        assert result.status_code == 400
        current_item = client.get(f'/api/projects/{pid}/inventory', headers=pm_headers).json()['items'][0]
        current_app = client.get(f"/api/projects/{pid}/item-applications/{app['id']}", headers=pm_headers).json()
        assert current_item['status'] == 'on_site' and current_item['quantity'] == 3
        assert current_app['status'] == 'pending' and current_app['amount'] == '500'

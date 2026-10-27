"""最后一位管理员的并发与交接保护。"""




def test_last_active_admin_cannot_demote_themself(client, admin_headers):
    me = client.get('/api/auth/me', headers=admin_headers).json()
    response = client.put(f"/api/users/{me['id']}", headers=admin_headers, json={'role': 'worker'})
    assert response.status_code == 400, response.text
    assert client.get('/api/users', headers=admin_headers).status_code == 200


def test_admin_handover_then_last_replacement_cannot_be_disabled(client, admin_headers):
    me = client.get('/api/auth/me', headers=admin_headers).json()
    replacement = client.post('/api/users', headers=admin_headers, json={
        'username': 'replacement', 'display_name': 'Replacement', 'password': 'Secure123!', 'role': 'admin'}).json()
    token = client.post('/api/auth/login', json={'username': 'replacement', 'password': 'Secure123!'}).json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    assert client.put(f"/api/users/{me['id']}", headers=headers, json={'role': 'worker'}).status_code == 200
    for method, body in [('put', {'is_active': False}), ('delete', None)]:
        response = client.request(method.upper(), f"/api/users/{replacement['id']}", headers=headers, json=body)
        assert response.status_code == 400, response.text
        assert client.get('/api/users', headers=headers).status_code == 200


def test_two_administrators_cannot_concurrently_retire_all_admins(client, admin_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.db import SessionLocal
    from app.models import User
    from app.routers.users import update_user, UserUpdate
    from fastapi import HTTPException
    created = client.post('/api/users', headers=admin_headers, json={
        'username': 'second-admin', 'display_name': 'Second admin', 'password': 'Secure123!', 'role': 'admin'}).json()
    ids = [client.get('/api/auth/me', headers=admin_headers).json()['id'], created['id']]
    gate = Barrier(2)
    def retire(uid):
        with SessionLocal() as db:
            actor = db.get(User, uid)
            gate.wait(timeout=5)
            try:
                update_user(uid, UserUpdate(role='worker'), actor, db)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(retire, ids))
    assert results.count(200) == 1, results
    assert all(result in (200, 400, 403, 409) for result in results)
    with SessionLocal() as db:
        assert db.query(User).filter_by(role='admin', is_active=True).count() == 1

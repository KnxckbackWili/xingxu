"""Archived retrospective retrieval respects project scope and legacy JSON."""
import pytest

from app.db import SessionLocal
from app.models import Project, User


def _project(client, pm_headers, retrospective, member=False):
    response = client.post('/api/projects', headers=pm_headers, json={
        'name': '复盘读取回归', 'start_date': '2026-10-01',
        'end_date': '2026-10-31', 'new_vehicles': False,
    })
    assert response.status_code == 200
    project_id = response.json()['id']
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        project.status = 'archived'
        project.retrospective = retrospective
        if member:
            project.members = [db.query(User).filter_by(username='worker1').one().id]
        db.commit()
    return project_id


def test_detail_returns_full_retrospective_to_owner_and_member_without_listing_it(client, pm_headers, worker_headers):
    with SessionLocal() as db:
        author = db.query(User).filter_by(username='pm').one()
        author_id, author_name = author.id, author.display_name
    original = {'content': '成功经验\n' + '完整长复盘记录。' * 600,
                'written_at': '2026-10-04T23:05:10', 'author': author_id}
    pid = _project(client, pm_headers, original, member=True)
    for headers in (pm_headers, worker_headers):
        response = client.get(f'/api/projects/{pid}', headers=headers)
        assert response.status_code == 200
        assert response.json()['retrospective'] == {**original, 'author_name': author_name}
    listed = client.get('/api/projects', headers=pm_headers).json()
    rows = listed if isinstance(listed, list) else listed['items']
    assert 'retrospective' not in next(row for row in rows if row['id'] == pid)
    with SessionLocal() as db:
        assert db.get(Project, pid).retrospective == original  # Read does not rewrite historical data.


def test_unrelated_worker_cannot_read_retrospective(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers, {'content': '只有本项目成员可见的复盘'})
    response = client.get(f'/api/projects/{pid}', headers=worker_headers)
    assert response.status_code == 404  # Existing project scope conceals unrelated projects.
    assert '只有本项目成员可见的复盘' not in response.text


@pytest.mark.parametrize('original, expected', [
    (None, {}), ({}, {}),
    ('旧版文本复盘\n保留换行', {'content': '旧版文本复盘\n保留换行'}),
    ({'success': '顺利验收', 'problems': '接口返工', 'improvements': '提前联调'},
     {'success': '顺利验收', 'problems': '接口返工', 'improvements': '提前联调'}),
    ({'content': '作者已删除的旧记录', 'author': 'missing-person-id'},
     {'content': '作者已删除的旧记录', 'author': 'missing-person-id'}),
])
def test_legacy_retrospective_and_missing_author_are_preserved(client, pm_headers, original, expected):
    pid = _project(client, pm_headers, original)
    response = client.get(f'/api/projects/{pid}', headers=pm_headers)
    assert response.status_code == 200
    assert response.json()['retrospective'] == {**expected, 'author_name': ''}
    with SessionLocal() as db:
        assert db.get(Project, pid).retrospective == original

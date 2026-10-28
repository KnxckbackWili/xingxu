"""Templates hang everything on one stage backbone (document stages 4–9); work groups belong to a stage."""
import ast
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import config
from app.db import engine


def _phases(client, headers, tid='default'):
    response = client.get(f'/api/templates/{tid}/work-items', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()['phases']


def test_default_template_work_groups_sit_on_the_stage_backbone(client, admin_headers):
    phases = _phases(client, admin_headers)
    stages = {phase['name']: phase['stage_key'] for phase in phases}
    assert stages['进场准备'] == '5' and stages['培训验收'] == '7'
    assert {stages[name] for name in ('到货检查', '单车调试', '地图与站点', '系统部署')} == {'6'}
    order = [phase['stage_key'] for phase in phases]
    assert order == sorted(order), 'work groups are listed in backbone order'
    assert all(phase['stage_name'] for phase in phases)


def test_work_groups_can_be_added_renamed_moved_and_removed(client, admin_headers):
    created = client.post('/api/templates/default/work-phases', headers=admin_headers, json={'name': '启动准备', 'stage_key': '4'})
    assert created.status_code == 200, created.text
    group = created.json()
    assert group['stage_key'] == '4' and group['stage_name'] == '内部启动会'
    assert _phases(client, admin_headers)[0]['id'] == group['id']
    moved = client.put(f'/api/templates/default/work-phases/{group["id"]}', headers=admin_headers, json={'name': '交付整理', 'stage_key': '8'})
    assert moved.status_code == 200, moved.text
    assert moved.json()['name'] == '交付整理' and moved.json()['stage_key'] == '8'
    assert client.put(f'/api/templates/default/work-phases/{group["id"]}', headers=admin_headers, json={'stage_key': '3'}).status_code == 422
    assert client.put(f'/api/templates/default/work-phases/{group["id"]}', headers=admin_headers, json={'stage_key': None}).status_code == 400
    busy = next(phase for phase in _phases(client, admin_headers) if phase['work_items'])
    denied = client.delete(f'/api/templates/default/work-phases/{busy["id"]}', headers=admin_headers)
    assert denied.status_code == 400 and '工作项' in denied.json()['detail']
    assert client.delete(f'/api/templates/default/work-phases/{group["id"]}', headers=admin_headers).status_code == 200
    assert group['id'] not in {phase['id'] for phase in _phases(client, admin_headers)}


def test_unmarked_new_group_is_inferred_and_others_cannot_edit_structure(client, admin_headers, pm_headers):
    created = client.post('/api/templates/default/work-phases', headers=admin_headers, json={'name': '培训验收补充'})
    assert created.status_code == 200 and created.json()['stage_key'] == '6'
    assert client.put(f'/api/templates/default/work-phases/{created.json()["id"]}', headers=pm_headers, json={'stage_key': '7'}).status_code == 403


def test_projects_and_template_copies_keep_the_stage_of_each_group(client, admin_headers, pm_headers):
    phases = _phases(client, admin_headers)
    survey = next(phase for phase in phases if phase['name'] == '进场准备')
    assert client.put(f'/api/templates/default/work-phases/{survey["id"]}', headers=admin_headers, json={'stage_key': '4'}).status_code == 200
    copy = client.post('/api/templates', headers=admin_headers, json={'name': '主线复制模板', 'copy_from': 'default'})
    assert copy.status_code == 200, copy.text
    copied = {phase['name']: phase['stage_key'] for phase in _phases(client, admin_headers, copy.json()['id'])}
    assert copied['进场准备'] == '4' and copied['培训验收'] == '7'
    work_ids = [item['id'] for phase in _phases(client, pm_headers) for item in phase['work_items']]
    project = client.post('/api/projects', headers=pm_headers, json={'name': '主线项目', 'start_date': '2026-10-01', 'end_date': '2026-12-31',
                                                                     'template_id': 'default', 'work_item_ids': work_ids})
    assert project.status_code == 200, project.text
    generated = client.get(f'/api/projects/{project.json()["id"]}/work-items', headers=pm_headers).json()['phases']
    stages = {phase['name']: phase['stage_key'] for phase in generated}
    assert stages['进场准备'] == '4' and stages['培训验收'] == '7' and stages['单车调试'] == '6'
    added = client.post(f'/api/projects/{project.json()["id"]}/work-phases', headers=pm_headers, json={'name': '现场补充', 'stage_key': '7'})
    assert added.status_code == 200 and added.json()['stage_key'] == '7'


def test_migration_places_existing_groups_on_the_backbone(client, tmp_path, monkeypatch):
    source = config.BASE_DIR / 'migrations/versions/g3a91b000001_phase_stage_backbone.py'
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or '').startswith('app')
                   for node in ast.walk(ast.parse(source.read_text())))
    url = make_url(config.DATABASE_URL)
    pg = url.drivername.startswith('postgresql')
    schema = 'stage_backbone_' + uuid4().hex
    if pg:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    else:
        url = make_url('sqlite:///' + str(tmp_path / 'pre-stage-backbone.db'))
        isolated = create_engine(url)
    cfg = Config(str(config.BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(config.BASE_DIR / 'migrations'))
    monkeypatch.setattr(config, 'DATABASE_URL', str(url))

    def upgrade(revision):
        with isolated.connect() as connection:
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, revision)

    try:
        upgrade('g3a90b000001')
        with isolated.begin() as connection:
            for pid, name in (('a', '进场准备'), ('b', '单车调试'), ('c', '培训验收'), ('d', '客户自定义分组'), ('e', '项目准备')):
                connection.execute(text('INSERT INTO phases(id,name,sort_order) VALUES (:id,:name,1)'), {'id': pid, 'name': name})
        upgrade('head')
        with isolated.connect() as connection:
            stages = dict(connection.execute(text('SELECT id,stage_key FROM phases')).all())
        assert stages == {'a': '5', 'b': '6', 'c': '7', 'd': '6', 'e': '4'}
    finally:
        isolated.dispose()
        if pg:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

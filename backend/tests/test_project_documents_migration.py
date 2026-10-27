"""T22 accounts for every retired document item and preserves original evidence bytes."""
import hashlib
import json
import os
import pytest
from datetime import datetime, date
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.config import BASE_DIR
from app.db import Base


@pytest.mark.parametrize("dialect",["sqlite", "postgresql"])
def test_legacy_document_sources_and_files_survive_once(monkeypatch, tmp_path,dialect):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    url = 'sqlite:///' + str(tmp_path / 'old.db') if dialect=='sqlite' else os.getenv('T22_MIGRATION_TEST_URL')
    if not url:pytest.skip('T22_MIGRATION_TEST_URL points to an isolated PostgreSQL migration test DB')
    if dialect=='postgresql':
        assert sa.engine.make_url(url).database.startswith('agvm_v3_20261027_t22_migration')
        with sa.create_engine(url).begin() as c:
            c.execute(sa.text('DROP SCHEMA public CASCADE'));c.execute(sa.text('CREATE SCHEMA public'))
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = Config(str(BASE_DIR / 'alembic.ini')); cfg.set_main_option('script_location', str(BASE_DIR / 'migrations'))
    command.upgrade(cfg, 'g3a21b000001')
    uploads = tmp_path / 'uploads'; uploads.mkdir()
    (uploads / 'original.bin').write_bytes(bytes(range(256)))
    (uploads / 'prep.bin').write_bytes(b'preparation original')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in uploads.iterdir()}
    old_items = [
        {'name':'已签交付物','done':True,'required':True,'attachment_id':'a','status':'approved','submitted_by':'u','submitted_at':'2026-10-01T03:04:05Z','review_by':'reviewer','review_at':'2026-10-02T08:00:00Z'},
        {'name':'旧完成无附件','done':True,'required':True},
        {'name':'已退回','done':False,'attachment_id':'a','status':'rejected','reject_reason':'原退回说明','review_by':'reviewer'},
    ]
    engine = sa.create_engine(url)
    with engine.begin() as c:
        metadata=sa.MetaData()
        def insert(table_name,**values):
            target=sa.Table(table_name,metadata,autoload_with=c,extend_existing=True)
            c.execute(target.insert().values(**values))
        insert('users',id='u',username='u',password_hash='opaque',display_name='原提交人',role='worker')
        insert('projects',id='p',name='原项目',status='executing',start_date=date(2026,1,1),end_date=date(2026,12,31))
        insert('phases',id='ph',name='旧第1阶段，不等于新公司4阶段',sort_order=1)
        insert('modules',id='m',project_id='p',phase_id='ph',name='原模块')
        insert('tasks',id='t',project_id='p',module_id='m',name='原任务',quantity_type='manual',deliverables=old_items)
        insert('attachments',id='a',project_id='p',filename='原文件.bin',stored_name='original.bin',file_size=256,content_type='application/octet-stream',uploaded_by='u',uploaded_at=datetime(2026,10,1,3,4,5),entity_type='project',entity_id='')
        insert('attachments',id='b',project_id='p',filename='准备原件.bin',stored_name='prep.bin',file_size=20,content_type='application/octet-stream',uploaded_by='u',uploaded_at=datetime(2026,10,3,3,4,5),entity_type='preparation_item',entity_id='prep-known')
        insert('archive_checklists',id='arc',project_id='p',category='验收文件',item_name='原验收单',is_required=True,is_done=True,attachment_id='a',done_by='u',done_at=datetime(2026,10,1,3,4,5),requirements={'signature':'原签字要求'})
        insert('archive_checklists',id='arc2',project_id='p',category='培训资料',item_name='无附件归档勾选',is_required=True,is_done=True)
        insert('project_preparation_items',id='prep-known',project_id='p',category='scope',name='现场布局图',is_required=True,status='passed',completed_by='u',completed_at=datetime(2026,10,3,3,4,5),extra={'retained':'专属原字段'})
        insert('project_preparation_items',id='prep-other',project_id='p',category='site',name='未能对应的原现场条件',is_required=True,status='na',note='普通备注不能猜为不适用理由')
        insert('project_preparation_items',id='proc',project_id='p',category='procurement',name='采购保持',is_required=True,status='passed')
        insert('templates',id='custom',name='旧模板',is_system=False)
        insert('modules',id='tm',template_id='custom',phase_id='ph',name='旧模板模块')
        insert('tasks',id='tt',template_id='custom',module_id='tm',name='旧模板任务',quantity_type='manual',deliverables=[{'name':'旧模板自定义交付要求','required':False}])
        old_preps = c.execute(sa.text('SELECT * FROM project_preparation_items ORDER BY id')).all()
    command.upgrade(cfg,'head'); command.upgrade(cfg,'head')
    with engine.connect() as c:
        docs = {row['instance_key']:dict(row) for row in c.execute(sa.text('SELECT * FROM project_documents')).mappings()}
        assert len(docs) == 7
        assert docs['task:t:0']['status'] == 'submitted'
        assert docs['task:t:1']['status'] == docs['task:t:2']['status'] == 'pending'
        assert docs['archive:arc']['stage_key'] == '7' and docs['archive:arc2']['stage_key'] == '8'
        assert docs['archive:arc2']['status'] == 'pending'
        assert docs['preparation:prep-known']['stage_key'] == '5' and docs['preparation:prep-known']['status'] == 'submitted'
        assert docs['preparation:prep-other']['stage_key'] == 'legacy' and docs['preparation:prep-other']['status'] == 'pending'
        assert all(docs['task:t:'+str(index)]['stage_key']=='legacy' for index in range(3))
        decoded=lambda value:json.loads(value) if isinstance(value,str) else value
        facts = decoded(docs['task:t:0']['source_metadata'])
        assert facts['original'] == old_items[0] and facts['phase']['name'].startswith('旧第1阶段')
        assert c.execute(sa.text('SELECT count(*) FROM document_versions')).scalar() == 4
        assert decoded(c.execute(sa.text("SELECT deliverables FROM tasks WHERE id='t'")).scalar()) == []
        assert c.execute(sa.text('SELECT * FROM project_preparation_items ORDER BY id')).all() == old_preps
        inherited = c.execute(sa.text("SELECT stage_key,source_metadata FROM document_requirements WHERE template_id='custom'")).mappings().one()
        assert inherited['stage_key']=='legacy' and decoded(inherited['source_metadata'])['original']['name']=='旧模板自定义交付要求'
        assert c.execute(sa.text('SELECT count(*) FROM attachments')).scalar()==2
        if dialect=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
        assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
    assert hashes == {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in uploads.iterdir()}
    engine.dispose()

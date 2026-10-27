"""Legacy public snapshots keep existing readers; private originals never bypass ACL."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.services.retained_document_access import authorize_archive_content


def test_proven_public_archive_still_allows_existing_admin_reader_without_owner_relationship():
    snapshot={'project':{'manager':'owner'},'records':{'attachments':[{
        'id':'file','stored_name':'retained','confidential':False,'confidential_user_ids':[]}],
        'project_documents':[],'project_document_definitions':[],'document_versions':[]}}
    archive=SimpleNamespace(project_id='project',snapshot=snapshot)
    reader=SimpleNamespace(id='other-admin',role='admin',is_active=True)
    before=deepcopy(snapshot)
    assert authorize_archive_content(archive,reader) is False
    assert authorize_archive_content(archive,reader,stored_name='retained') is False
    assert snapshot==before


def test_frozen_designations_and_all_private_families_are_used_without_live_admin_bypass():
    snapshot={'project':{'manager':'owner'},'records':{
        'project_document_definitions':[{'id':'rule','code':'6.99','confidential_default':True,'confidential_user_ids':['reader']}],
        'project_documents':[{'id':'doc','definition_id':'rule','code':'6.99','confidential':True,'confidential_user_ids':['reader']}],
        'document_versions':[{'project_document_id':'doc','attachment_id':'file'}],
        'attachments':[{'id':'file','stored_name':'retained','confidential':True,'confidential_explicit':False,'confidential_user_ids':[]}]}}
    archive=SimpleNamespace(project_id='project',snapshot=snapshot)
    before=deepcopy(snapshot)
    reader=SimpleNamespace(id='reader',role='admin',is_active=True)
    assert authorize_archive_content(archive,reader)
    assert authorize_archive_content(archive,reader,stored_name='retained')
    other=SimpleNamespace(id='other-admin',role='admin',is_active=True)
    with pytest.raises(HTTPException):authorize_archive_content(archive,other)
    with pytest.raises(HTTPException):authorize_archive_content(archive,other,stored_name='retained')
    assert snapshot==before


def test_legacy_path_without_provable_file_scope_is_not_a_general_admin_read_capability():
    archive=SimpleNamespace(project_id='project',snapshot={'project':{'manager':'owner'},'records':{}})
    other=SimpleNamespace(id='other-admin',role='admin',is_active=True)
    assert authorize_archive_content(archive,other) is False  # Non-private old metadata stays readable.
    with pytest.raises(HTTPException):authorize_archive_content(archive,other,stored_name='unproven')

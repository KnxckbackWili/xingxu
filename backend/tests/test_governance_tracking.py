"""Retired approval history is preserved; new direct transfers remain versioned."""
from app.db import SessionLocal
from app.models import Project,ProjectGovernanceRequest
from tests.test_workspace_transfer_t50 import recipient,preview,transfer
from tests.test_confidential_documents_t26 import setup_project


def test_withdraw_and_reapply_are_retired_without_changing_frozen_history(client,pm_headers,admin_headers,worker_headers):
    pid,people=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    with SessionLocal() as db:
        row=ProjectGovernanceRequest(project_id=pid,project_name='历史原名',request_type='transfer',status='pending',
            requested_by=people['pm'],source_manager_id=people['pm'],target_manager_id=target,reason='原始申请理由')
        db.add(row);db.commit();identity=row.id
    for headers in (admin_headers,pm_headers,worker_headers):
        assert client.post(f'/api/projects/governance/requests/{identity}/withdraw',headers=headers).status_code==410
        assert client.post(f'/api/projects/{pid}/governance-requests',headers=headers,json={'request_type':'transfer','target_manager_id':target,'reason':'不再产生新申请'}).status_code==410
    with SessionLocal() as db:
        assert db.get(ProjectGovernanceRequest,identity).status=='pending'
        assert db.get(ProjectGovernanceRequest,identity).reason=='原始申请理由'
        assert db.get(Project,pid).manager==people['pm']


def test_cannot_directly_transfer_to_deactivated_target(client,pm_headers,admin_headers):
    pid,_=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,pm_headers,pid)
    assert client.put('/api/users/'+target,headers=admin_headers,json={'is_active':False}).status_code==200
    assert transfer(client,pm_headers,pid,target,view).status_code==400
    assert client.get('/api/projects/'+pid,headers=pm_headers).status_code==200


def test_stale_admin_transfer_cannot_overwrite_current_manager(client,pm_headers,admin_headers):
    pid,_=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,admin_headers,pid)
    assert transfer(client,admin_headers,pid,target,view).status_code==200
    stale=transfer(client,admin_headers,pid,target,view)
    assert stale.status_code==409
    with SessionLocal() as db:assert db.get(Project,pid).manager==target

"""Direct project transfer stays versioned and only reaches an active account."""
from app.db import SessionLocal
from app.models import Project
from tests.test_workspace_transfer_t50 import recipient,preview,transfer
from tests.test_confidential_documents_t26 import setup_project


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

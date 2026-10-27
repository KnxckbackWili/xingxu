"""物品库存流水的幂等、并发及失败原子性。"""

from app.db import SessionLocal
from tests.test_execution_workflow_audit import _execution
import pytest
from app.models import Project


def test_concurrent_inventory_issue_cannot_spend_same_stock_twice(client, pm_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import User, ProjectInventoryItem, ProjectInventoryMovement
    from app.routers.inventory import create_movement, MovementBody
    pid, _, _ = _execution(client)
    result = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers, json={'name': '现场备件', 'quantity': 1})
    iid = result.json()['id']; gate = Barrier(2)
    def send(n):
        with SessionLocal() as db:
            user = db.get(User, 'user-pm-001'); gate.wait(timeout=5)
            try:
                create_movement(pid, iid, MovementBody(movement_type='issue', quantity=1), user=user, db=db)
                return 200
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(send, range(2)))
    assert outcomes == [200, 400], outcomes
    with SessionLocal() as db:
        assert db.get(ProjectInventoryItem, iid).quantity == 0
        assert db.query(ProjectInventoryMovement).filter_by(item_id=iid, movement_type='issue').count() == 1


def test_fractional_stock_can_be_fully_consumed(client, pm_headers):
    pid, _, _ = _execution(client)
    item = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
                       json={'name': '按米计电缆', 'quantity': 0.3, 'unit': '米'}).json()['id']
    url = f'/api/projects/{pid}/inventory/{item}/movements'
    assert client.post(url, headers=pm_headers, json={'movement_type': 'consume', 'quantity': 0.1}).status_code == 200
    result = client.post(url, headers=pm_headers, json={'movement_type': 'consume', 'quantity': 0.2})
    assert result.status_code == 200, result.text
    assert result.json()['item']['quantity'] == 0
    assert result.json()['item']['status'] == 'consumed'


@pytest.mark.parametrize('movement_type,amount,expected', [('issue', 2, 8), ('receive', 2, 12), ('transfer', 10, 10), ('inventory', 7, 7)])
def test_inventory_retry_applies_same_movement_once(client, pm_headers, movement_type, amount, expected):
    from app.models import ProjectInventoryMovement
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
                     json={'name': '重试测试库存', 'quantity': 10}).json()['id']
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    body = {'movement_type': movement_type, 'client_uuid': 'round6-inventory-intent',
            'to_location': '现场', 'handler': '保管员'}
    body['quantity_after' if movement_type == 'inventory' else 'quantity'] = amount
    first = client.post(url, headers=pm_headers, json=body)
    assert first.status_code == 200, first.text
    second = client.post(url, headers=pm_headers, json=body)
    assert second.status_code == 200, second.text
    assert second.json()['item']['quantity'] == expected
    assert second.json()['movement']['id'] == first.json()['movement']['id']
    assert first.json()['accepted'] is True and second.json()['accepted'] is False
    with SessionLocal() as db:
        assert db.query(ProjectInventoryMovement).filter_by(item_id=iid).count() == 2  # opening + actual action


def test_inventory_uuid_cannot_hide_changed_intent_and_next_uuid_is_independent(client, pm_headers):
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
                     json={'name': '动作编号', 'quantity': 10}).json()['id']
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    body = {'movement_type': 'issue', 'quantity': 2, 'client_uuid': 'round6-same-action'}
    assert client.post(url, headers=pm_headers, json=body).status_code == 200
    mismatch = client.post(url, headers=pm_headers, json={**body, 'quantity': 3})
    assert mismatch.status_code == 409, mismatch.text
    next_action = client.post(url, headers=pm_headers, json={**body, 'quantity': 3, 'client_uuid': 'round6-next-action'})
    assert next_action.status_code == 200 and next_action.json()['item']['quantity'] == 5, next_action.text


def test_inventory_saved_retry_acknowledged_after_archive_but_new_action_blocked(client, pm_headers):
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
                     json={'name': '归档前领料', 'quantity': 10}).json()['id']
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    body = {'movement_type': 'issue', 'quantity': 2, 'client_uuid': 'round6-archive-retry'}
    first = client.post(url, headers=pm_headers, json=body)
    assert first.status_code == 200, first.text
    with SessionLocal() as db:
        db.get(Project, pid).status = 'archived'; db.commit()
    retry = client.post(url, headers=pm_headers, json=body)
    assert retry.status_code == 200 and retry.json()['accepted'] is False, retry.text
    new = client.post(url, headers=pm_headers, json={**body, 'client_uuid': 'round6-archived-new'})
    assert new.status_code == 400, new.text


def test_concurrent_inventory_same_uuid_creates_one_movement(client, pm_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.models import ProjectInventoryItem, ProjectInventoryMovement, User
    from app.routers.inventory import create_movement, MovementBody
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
                     json={'name': '并发重复领料', 'quantity': 10}).json()['id']
    gate = Barrier(2)
    def submit(_):
        with SessionLocal() as db:
            user = db.get(User, 'user-pm-001')
            gate.wait(timeout=5)
            return create_movement(pid, iid, MovementBody(movement_type='issue', quantity=2,
                client_uuid='round6-concurrent-stock'), user=user, db=db)['accepted']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [False, True]
    with SessionLocal() as db:
        assert db.get(ProjectInventoryItem, iid).quantity == 8
        assert db.query(ProjectInventoryMovement).filter_by(item_id=iid, movement_type='issue').count() == 1


def test_inventory_failed_commit_never_reserves_uuid_or_changes_stock(client, pm_headers, monkeypatch):
    from app.models import OfflineOpReceipt, ProjectInventoryItem, ProjectInventoryMovement
    from app.routers import inventory
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
                     json={'name': '原子领料', 'quantity': 10}).json()['id']
    body = {'movement_type': 'issue', 'quantity': 2, 'client_uuid': 'round6-atomic-stock'}
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    original = inventory.log_change
    with monkeypatch.context() as patch:
        def fail_audit(*args, **kwargs):
            raise RuntimeError('synthetic movement audit failure')
        patch.setattr(inventory, 'log_change', fail_audit)
        with pytest.raises(RuntimeError, match='synthetic movement audit failure'):
            client.post(url, headers=pm_headers, json=body)
    with SessionLocal() as db:
        assert db.get(ProjectInventoryItem, iid).quantity == 10
        assert db.query(ProjectInventoryMovement).filter_by(item_id=iid, movement_type='issue').count() == 0
        assert db.query(OfflineOpReceipt).filter_by(project_id=pid, op_type='inventory_movement').count() == 0
    retried = client.post(url, headers=pm_headers, json=body)
    assert retried.status_code == 200 and retried.json()['accepted'] is True, retried.text
    assert retried.json()['item']['quantity'] == 8


@pytest.mark.parametrize('movement_type', ['issue', 'consume', 'return_owner'])
def test_partial_outbound_preserves_remaining_stock_location_and_custodian(client, pm_headers, movement_type):
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
        json={'name': '分发材料', 'quantity': 10, 'location': '仓库A', 'custodian': '原保管员'}).json()['id']
    result = client.post(f'/api/projects/{pid}/inventory/{iid}/movements', headers=pm_headers,
        json={'movement_type': movement_type, 'quantity': 2, 'to_location': '工位B', 'handler': '领取人'})
    assert result.status_code == 200, result.text
    assert result.json()['item']['quantity'] == 8
    assert result.json()['item']['location'] == '仓库A'
    assert result.json()['item']['custodian'] == '原保管员'
    assert result.json()['movement']['to_location'] == '工位B'
    assert result.json()['movement']['handler'] == '领取人'


def test_partial_transfer_rejected_and_full_transfer_moves_whole_record(client, pm_headers):
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
        json={'name': '分区库存', 'quantity': 10, 'location': '仓库A', 'custodian': '原保管员'}).json()['id']
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    body = {'movement_type': 'transfer', 'quantity': 2, 'to_location': '仓库B', 'handler': '新保管员'}
    refused = client.post(url, headers=pm_headers, json=body)
    assert refused.status_code == 400 and '拆分' in refused.json()['detail'], refused.text
    moved = client.post(url, headers=pm_headers, json={**body, 'quantity': 10})
    assert moved.status_code == 200, moved.text
    assert moved.json()['item']['quantity'] == 10
    assert moved.json()['item']['location'] == '仓库B' and moved.json()['item']['custodian'] == '新保管员'


def test_receiving_into_another_location_requires_separate_stock_record(client, pm_headers):
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
        json={'name': '待补货物料', 'quantity': 8, 'location': '仓库A', 'custodian': '原保管员'}).json()['id']
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    received = client.post(url, headers=pm_headers,
        json={'movement_type': 'receive', 'quantity': 2, 'to_location': '仓库B', 'handler': '送货人'})
    assert received.status_code == 400 and '拆分' in received.json()['detail'], received.text
    same_location = client.post(url, headers=pm_headers,
        json={'movement_type': 'receive', 'quantity': 2, 'to_location': '仓库A', 'handler': '送货人'})
    assert same_location.status_code == 200, same_location.text
    assert same_location.json()['item']['quantity'] == 10
    assert same_location.json()['item']['custodian'] == '原保管员'


def test_serial_item_whole_transfer_and_return_remain_supported(client, pm_headers):
    pid, _, _ = _execution(client)
    iid = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers,
        json={'name': '定位仪', 'tracking_mode': 'serial', 'serial_number': 'S-R6',
              'quantity': 1, 'location': '仓库A', 'custodian': '原保管员'}).json()['id']
    url = f'/api/projects/{pid}/inventory/{iid}/movements'
    moved = client.post(url, headers=pm_headers,
        json={'movement_type': 'transfer', 'quantity': 1, 'to_location': '工具柜B', 'handler': '新保管员'})
    assert moved.status_code == 200 and moved.json()['item']['location'] == '工具柜B', moved.text
    returned = client.post(url, headers=pm_headers,
        json={'movement_type': 'return_owner', 'quantity': 1, 'to_location': '资产公司', 'handler': '收件人'})
    assert returned.status_code == 200 and returned.json()['item']['quantity'] == 0, returned.text
    assert returned.json()['item']['status'] == 'returned'
    received = client.post(url, headers=pm_headers,
        json={'movement_type': 'return_site', 'quantity': 1, 'to_location': '工具柜C', 'handler': '接收保管员'})
    assert received.status_code == 200 and received.json()['item']['quantity'] == 1, received.text
    assert received.json()['item']['location'] == '工具柜C' and received.json()['item']['status'] == 'on_site'

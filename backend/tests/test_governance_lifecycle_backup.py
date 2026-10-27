import io
import tarfile
import json
import subprocess
import pytest


def _create_user(client, admin_headers, username, role="pm"):
    response = client.post("/api/users", headers=admin_headers, json={
        "username": username, "password": "Review123!", "display_name": username, "role": role,
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": "Review123!"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}




def test_project_transfer_and_delete_workflow(client, admin_headers, pm_headers):
    target_id = _create_user(client, admin_headers, "targetpm")
    project = client.post("/api/projects", headers=pm_headers, json={
        "name": "待移交项目", "start_date": "2026-08-01", "end_date": "2026-09-01",
    }).json()
    view=client.get(f"/api/projects/{project['id']}/transfer-preview",headers=pm_headers).json()
    transferred=client.post(f"/api/projects/{project['id']}/transfer",headers=pm_headers,json={
        'target_manager_id':target_id,'reason':'岗位调整，已完成风险交底','version':view['version'],
        'member_removal_confirmations':[row['user_id'] for row in view['removed']]})
    assert transferred.status_code==200,transferred.text
    assert client.get(f"/api/projects/{project['id']}", headers=pm_headers).status_code == 404
    assert client.get(f"/api/projects/{project['id']}", headers=_login(client, "targetpm")).status_code == 200

    fresh = client.get(f"/api/projects/{project['id']}", headers=_login(client, "targetpm")).json()
    deletion = client.delete(f"/api/projects/{project['id']}", headers=_login(client, "targetpm"), params={"version": fresh["version"]})
    assert deletion.status_code == 200, deletion.text
    assert deletion.json()["backup"]["available"] is True
    assert client.get(f"/api/projects/{project['id']}", headers=admin_headers).status_code == 404


def test_vehicle_lifecycle_and_json_roundtrip_data(client, admin_headers, pm_headers):
    project = client.post("/api/projects", headers=pm_headers, json={
        "name": "生命周期项目", "start_date": "2026-08-01", "end_date": "2026-09-01",
    }).json()
    unit = client.post(f"/api/projects/{project['id']}/vehicle-units", headers=pm_headers, json={
        "asset_code": "AGV-001", "serial_number": "SN-01", "current_stage": "planned",
    })
    assert unit.status_code == 200, unit.text
    event = client.post(f"/api/projects/{project['id']}/vehicle-units/{unit.json()['id']}/events", headers=pm_headers, json={
        "event_type": "shipment", "event_date": "2026-08-10", "title": "车辆发运",
        "stage_after": "shipping", "status_after": "normal", "location_after": "运输途中",
    })
    assert event.status_code == 200
    issue = client.post(f"/api/projects/{project['id']}/vehicle-units/{unit.json()['id']}/events", headers=pm_headers, json={
        "event_type": "fault", "event_date": "2026-08-11", "title": "左前避障传感器报警",
        "description": "运行中间歇报警", "fault_part": "左前避障传感器", "cause": "接插件松动",
        "status_after": "attention", "is_closed": False,
    })
    assert issue.status_code == 200, issue.text
    repaired = client.put(
        f"/api/projects/{project['id']}/vehicle-units/{unit.json()['id']}/events/{issue.json()['id']}",
        headers=pm_headers,
        json={
            "action_taken": "重新压接并固定线束", "replaced_parts": [{"name": "M12 接插件", "model": "A-12", "quantity": 1}],
            "downtime_hours": 1.5, "verification": "连续运行 2 小时正常", "handler": "张工",
            "status_after": "normal", "is_closed": True,
        },
    )
    assert repaired.status_code == 200, repaired.text
    client.put(f"/api/projects/{project['id']}", headers=pm_headers, json={
        "client_contacts": [{"department": "设备部", "team": "自动化组", "name": "李经理", "phone": "13800000000", "is_primary": True}],
        "entry_plan": {"mode": "collective", "meeting_point": "东门 1 号岗", "client_contact": "李经理"},
    })
    detail = client.get(f"/api/projects/{project['id']}/vehicle-units/{unit.json()['id']}", headers=pm_headers).json()
    assert detail["current_stage"] == "planned"
    assert detail["issue_count"] == 1
    assert detail["events"][0]["replaced_parts"][0]["model"] == "A-12"
    snapshot = client.get(f"/api/projects/{project['id']}/export/json", headers=pm_headers).json()
    assert snapshot["version"] == "2.4"
    assert any(event["stage_after"]=="shipping" for event in snapshot["vehicle_units"][0]["events"])  # full history stays portable
    assert snapshot["project"]["client_contacts"][0]["name"] == "李经理"
    assert snapshot["project"]["entry_plan"]["meeting_point"] == "东门 1 号岗"
    assert any(event["stage_after"] == "shipping" for event in snapshot["vehicle_units"][0]["events"])
    fault = next(event for event in snapshot["vehicle_units"][0]["events"] if event["event_type"] == "fault")
    assert fault["action_taken"] == "重新压接并固定线束"
    assert fault["is_closed"] is True

    imported = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert imported.status_code == 200, imported.text
    imported_project = client.get(f"/api/projects/{imported.json()['id']}", headers=pm_headers).json()
    assert imported_project["client_contacts"][0]["team"] == "自动化组"
    imported_units = client.get(f"/api/projects/{imported.json()['id']}/vehicle-units", headers=pm_headers).json()
    imported_detail = client.get(
        f"/api/projects/{imported.json()['id']}/vehicle-units/{imported_units[0]['id']}", headers=pm_headers,
    ).json()
    assert imported_detail["events"][0]["replaced_parts"][0]["name"] == "M12 接插件"


def test_system_backup_contains_database_and_manifest(client, admin_headers, tmp_path, backup_passphrase):
    response = client.post("/api/system/backups", headers=admin_headers, json={"label": "test"})
    assert response.status_code == 200, response.text
    archive = client.get(f"/api/system/backups/{response.json()['filename']}", headers=admin_headers)
    from app.services import backup_crypto as codec
    encrypted = tmp_path / "download.agvenc"; encrypted.write_bytes(archive.content)
    with codec.decrypted_file(encrypted, backup_passphrase) as plaintext:
        raw = plaintext.read_bytes()
    assert not archive.content.startswith(b"\x1f\x8b")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as bundle:
        from app.db import _is_sqlite
        database_name = 'agvpm.db' if _is_sqlite else 'agvpm.dump'
        assert {'manifest.json', database_name} <= set(bundle.getnames())
        manifest = json.load(bundle.extractfile('manifest.json'))
        assert manifest['database'] == ('sqlite' if _is_sqlite else 'postgres')
        if not _is_sqlite:
            dump = tmp_path / 'backup.dump'
            dump.write_bytes(bundle.extractfile(database_name).read())
            assert dump.read_bytes().startswith(b'PGDMP')
            listing = subprocess.run(['pg_restore', '--list', str(dump)], capture_output=True, text=True)
            assert listing.returncode == 0, listing.stderr
            assert 'TABLE public projects' in listing.stdout


def test_restore_rejects_path_traversal_and_invalid_database(client, admin_headers, tmp_path, backup_passphrase):
    malicious = io.BytesIO()
    with tarfile.open(fileobj=malicious, mode="w:gz") as bundle:
        manifest = b'{"type":"agvpm-system-backup"}'
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        bundle.addfile(info, io.BytesIO(manifest))
        database = b"not sqlite"
        info = tarfile.TarInfo("agvpm.db")
        info.size = len(database)
        bundle.addfile(info, io.BytesIO(database))
        escaped = b"unsafe"
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(escaped)
        bundle.addfile(info, io.BytesIO(escaped))
    from app.services import backup_crypto as codec
    raw = tmp_path / "malicious.tar.gz"; raw.write_bytes(malicious.getvalue())
    sealed = tmp_path / "malicious.agvenc"; codec.encrypt_file(raw, sealed, backup_passphrase)
    response = client.post(
        "/api/system/restore?confirm=RESTORE", headers=admin_headers, data={"passphrase": backup_passphrase},
        files={"file": ("malicious.agvenc", sealed.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 400
    from app.db import _is_sqlite
    expected = '不安全' if _is_sqlite else 'PostgreSQL 部署不支持网页恢复'
    assert expected in response.json()['detail']
    # The common archive validator still rejects traversal on both database jobs.
    from app.services.system_backup import validate_archive
    path = tmp_path / 'malicious.tar.gz'
    path.write_bytes(malicious.getvalue())
    with pytest.raises(ValueError, match='不安全'):
        validate_archive(path)


@pytest.mark.parametrize('name,kind', [
    ('agvpm.dump/nested', tarfile.REGTYPE),
    ('agvpm.dump', tarfile.DIRTYPE),
    ('agvpm.dump', tarfile.SYMTYPE),
    ('./agvpm.dump', tarfile.REGTYPE),
])
def test_postgres_dump_root_does_not_allow_nested_aliased_or_linked_files(name, kind):
    from app.services.backup_safety import safe_members
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w:gz') as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = '/private/other.dump'
        archive.addfile(member)
    raw.seek(0)
    with tarfile.open(fileobj=raw, mode='r:gz') as archive:
        with pytest.raises(ValueError, match='路径|结构'):
            safe_members(archive)

"""T03 frozen data retirement: verify encrypted evidence before removing old data."""

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID, uuid5
import zipfile
from datetime import datetime, timezone

import sqlalchemy as sa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from migrations.v243_schema import metadata

REVISION = "g3a03b000001"
RETIRED_TABLES = (
    "incident_actions",
    "incidents",
    "project_change_sets",
    "project_edit_history",
    "inbox_documents",
    "ai_chat_messages",
    "ai_chat_sessions",
    "ai_user_memories",
    "team_templates",
    "org_groups",
)
HEADER = b"AGV-V3-RETIREMENT-1\n"
_NAMESPACE = UUID("a9a8caf7-f01a-41d8-a167-37301ee82573")


def _json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=lambda v: v.isoformat(),
        separators=(",", ":"),
    ).encode()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _stable_id(value):
    return str(uuid5(_NAMESPACE, value))


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".t03-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def decrypt_export(data, secret):
    if not data.startswith(HEADER):
        raise ValueError("不是T03加密历史导出")
    head, payload = data[len(HEADER) :].split(b"\n", 1)
    fields = json.loads(head)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=base64.b64decode(fields["salt"]),
        info=("agvpm:t03:" + fields["owner"]).encode(),
    ).derive(secret.encode())
    result = AESGCM(key).decrypt(base64.b64decode(fields["nonce"]), payload, head)
    if _digest(result) != fields["sha256"]:
        raise ValueError("历史导出完整性校验失败")
    return result


def _export(root, owner, records, files, secret):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in [("records.json", _json(records)), *sorted(files.items())]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    raw = content.getvalue()
    fingerprint = _digest(raw)
    owner_key = _digest(owner.encode())[:24]
    target = root / "owners" / owner_key / f"{fingerprint}.agvr"
    if not target.exists():
        salt, nonce = os.urandom(16), os.urandom(12)
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=("agvpm:t03:" + owner).encode(),
        ).derive(secret.encode())
        header = _json(
            {
                "version": 1,
                "owner": owner,
                "salt": base64.b64encode(salt).decode(),
                "nonce": base64.b64encode(nonce).decode(),
                "sha256": fingerprint,
            }
        )
        _atomic(
            target, HEADER + header + b"\n" + AESGCM(key).encrypt(nonce, raw, header)
        )
    if decrypt_export(target.read_bytes(), secret) != raw:
        raise RuntimeError("T03历史导出验证失败，原数据未删除")
    return {
        "path": str(target.relative_to(root)),
        "sha256": _digest(target.read_bytes()),
        "payload_sha256": fingerprint,
        "owner": owner,
        "record_counts": {name: len(rows) for name, rows in records.items()},
        "file_count": len(files),
    }


def _rows(bind, table, condition=None):
    query = sa.select(table)
    if condition is not None:
        query = query.where(condition)
    return [
        dict(row)
        for row in bind.execute(query.order_by(*table.primary_key.columns)).mappings()
    ]


def _upload(stored, upload_dir):
    if (
        not isinstance(stored, str)
        or not stored
        or Path(stored).name != stored
        or "\\" in stored
    ):
        raise RuntimeError("T03发现不安全文件引用，拒绝删除原记录")
    path = upload_dir / stored
    if (
        path.is_symlink()
        or path.resolve().parent != upload_dir.resolve()
        or not path.is_file()
    ):
        raise RuntimeError(f"T03历史文件缺失或不安全：{stored}；原数据未删除")
    return path.read_bytes()


def retire_data(bind):
    from app.config import DATA_DIR, UPLOAD_DIR, SECRET_KEY

    root = DATA_DIR / "migration-exports" / "t03"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    tables = metadata.tables
    before_counts = {
        name: bind.execute(sa.select(sa.func.count()).select_from(table)).scalar()
        for name, table in tables.items()
    }
    projects = _rows(bind, tables["projects"])
    normal = {p["id"]: p for p in projects if not p["is_demo"]}
    demos = {p["id"]: p for p in projects if p["is_demo"]}
    users_before = _rows(bind, tables["users"])
    original_attachments = _rows(bind, tables["attachments"])
    owners, owner_files, cleanup, dispositions = {}, {}, {}, {}

    def keep(owner, name, rows):
        if rows:
            owners.setdefault(str(owner or "unassigned"), {}).setdefault(
                name, []
            ).extend(rows)

    def keep_file(owner, stored):
        data = _upload(stored, UPLOAD_DIR)
        owner_files.setdefault(str(owner or "unassigned"), {})["files/" + stored] = data
        cleanup[stored] = {"sha256": _digest(data), "size": len(data)}

    # Global retirement metadata is encrypted, never published as project evidence.
    for name in ("org_groups", "team_templates"):
        keep("system", name, _rows(bind, tables[name]))
    keep(
        "system",
        "user_retired_fields",
        [{k: u[k] for k in ("id", "group_id", "skills")} for u in users_before],
    )
    keep(
        "system",
        "project_role_plans",
        [{"id": p["id"], "role_plan": p["role_plan"]} for p in projects],
    )
    for name in (
        "project_change_sets",
        "project_edit_history",
        "incidents",
        "incident_actions",
    ):
        for row in _rows(bind, tables[name]):
            project = demos.get(row.get("project_id"))
            keep(project.get("created_by") if project else "system", name, [row])
    sessions = _rows(bind, tables["ai_chat_sessions"])
    by_session = {row["id"]: row.get("user_id") for row in sessions}
    for row in sessions:
        keep(row["user_id"], "ai_chat_sessions", [row])
    for row in _rows(bind, tables["ai_chat_messages"]):
        keep(by_session.get(row["session_id"]), "ai_chat_messages", [row])
    for row in _rows(bind, tables["ai_user_memories"]):
        keep(row["user_id"], "ai_user_memories", [row])

    # Every removed demo record is exported explicitly; FK OFF cannot cascade.
    demo_conditions = {}
    demo_task_ids = (
        [
            r["id"]
            for r in _rows(
                bind, tables["tasks"], tables["tasks"].c.project_id.in_(demos)
            )
        ]
        if demos
        else []
    )
    demo_notification_ids = (
        [
            r["id"]
            for r in _rows(
                bind,
                tables["notifications"],
                tables["notifications"].c.project_id.in_(demos),
            )
        ]
        if demos
        else []
    )
    for table in metadata.sorted_tables:
        if table.name == "projects" or table.name in RETIRED_TABLES:
            continue
        condition = table.c.project_id.in_(demos) if "project_id" in table.c else None
        if table.name == "notification_outbox":
            child = table.c.notification_id.in_(demo_notification_ids)
            condition = sa.or_(condition, child) if condition is not None else child
        if table.name in ("check_items", "template_docs"):
            child = table.c.task_id.in_(demo_task_ids)
            condition = sa.or_(condition, child) if condition is not None else child
        if condition is None or not demos:
            continue
        rows = _rows(bind, table, condition)
        demo_conditions[table.name] = condition
        for row in rows:
            if table.name == "personal_events":
                owner = row["user_id"]
            else:
                project = demos.get(row.get("project_id"))
                if project is None and row.get("task_id"):
                    task = (
                        bind.execute(
                            sa.select(tables["tasks"]).where(
                                tables["tasks"].c.id == row["task_id"]
                            )
                        )
                        .mappings()
                        .one()
                    )
                    project = demos[task["project_id"]]
                owner = (project or {}).get("created_by")
            keep(owner, table.name, [row])
            if table.name in ("attachments", "template_docs"):
                keep_file(owner, row["stored_name"])
            elif table.name == "tasks":
                for ref in row.get("reference_docs") or []:
                    if isinstance(ref, dict) and ref.get("stored_name"):
                        keep_file(owner, ref["stored_name"])
            elif table.name == "project_deletion_records":
                path = DATA_DIR / "project-deletion-backups" / row["backup_name"]
                if (
                    Path(row["backup_name"]).name != row["backup_name"]
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    raise RuntimeError("T03演示项目删除备份缺失，拒绝删除记录")
                owner_files.setdefault(str(owner or "unassigned"), {})[
                    "project-backups/" + path.name
                ] = path.read_bytes()
    for project in demos.values():
        keep(project.get("created_by"), "projects", [project])

    inbox = _rows(bind, tables["inbox_documents"])
    attachment_by_id = {r["id"]: r for r in original_attachments}
    inbox_to_attach = []
    for row in inbox:
        owner = row["uploaded_by"]
        keep(owner, "inbox_documents", [row])
        keep_file(owner, row["stored_name"])
        old = attachment_by_id.get(row["archived_attachment_id"])
        if old and old["project_id"] in normal:
            if old["stored_name"] != row["stored_name"]:
                raise RuntimeError("T03收集箱附件引用不一致，拒绝猜测归属")
            dispositions[row["id"]] = {
                "destination": "existing_attachment",
                "attachment_id": old["id"],
            }
        elif row["archived_project_id"] in normal:
            new_id = _stable_id("inbox:" + row["id"])
            inbox_to_attach.append(
                dict(
                    id=new_id,
                    project_id=row["archived_project_id"],
                    entity_type="project",
                    entity_id=row["archived_project_id"],
                    category="未归类文件",
                    filename=row["filename"],
                    stored_name=row["stored_name"],
                    file_size=row["file_size"],
                    content_type=row["content_type"],
                    uploaded_by=row["uploaded_by"],
                    uploaded_at=row["uploaded_at"],
                )
            )
            dispositions[row["id"]] = {
                "destination": "project_unclassified",
                "attachment_id": new_id,
            }
        else:
            dispositions[row["id"]] = {
                "destination": "encrypted_owner_export",
                "owner": owner,
            }

    exports = [
        _export(root, owner, records, owner_files.get(owner, {}), SECRET_KEY)
        for owner, records in sorted(owners.items())
    ]
    # Nothing is deleted until all encrypted exports have been read back and verified.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    log = tables["change_logs"]

    def audit(project_id, entity_type, entity_id, detail, old=None, new=None):
        bind.execute(
            log.insert().values(
                id=_stable_id("audit:" + entity_type + ":" + entity_id),
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action="migration",
                operator_id=None,
                detail=detail,
                old_value=json.loads(_json(old)) if old is not None else None,
                new_value=json.loads(_json(new)) if new is not None else None,
                created_at=now,
            )
        )

    incidents_by_project = {}
    for row in _rows(bind, tables["incidents"]):
        if row["project_id"] in normal:
            incidents_by_project.setdefault(row["project_id"], []).append(row)
        if row["status"] != "closed":
            bind.execute(
                tables["incidents"]
                .update()
                .where(tables["incidents"].c.id == row["id"])
                .values(status="closed", closed_at=now)
            )
            audit(
                row["project_id"] if row["project_id"] in normal else None,
                "incident",
                row["id"],
                "系统迁移关闭：突发状况功能下线，原始记录及处置流水已保全",
                row,
                {"status": "closed"},
            )
    csv_reports = []
    for pid, rows in sorted(incidents_by_project.items()):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id",
                "title",
                "original_status",
                "migration_status",
                "original_record",
                "actions",
            ],
        )
        writer.writeheader()
        for row in rows:
            actions = _rows(
                bind,
                tables["incident_actions"],
                tables["incident_actions"].c.incident_id == row["id"],
            )
            writer.writerow(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "original_status": row["status"],
                    "migration_status": "closed",
                    "original_record": _json(row).decode(),
                    "actions": _json(actions).decode(),
                }
            )
        raw = ("\ufeff" + output.getvalue()).encode()
        stored = (
            "t03-incidents-"
            + _digest(pid.encode())[:16]
            + "-"
            + _digest(raw)[:16]
            + ".csv"
        )
        path = UPLOAD_DIR / stored
        if path.exists() and path.read_bytes() != raw:
            raise RuntimeError("T03历史CSV目标已存在且内容不符，原文件未覆盖")
        _atomic(path, raw)
        if _digest(path.read_bytes()) != _digest(raw):
            raise RuntimeError("T03事故CSV校验失败，原记录未删除")
        attachment_id = _stable_id("incidents:" + pid)
        bind.execute(
            tables["attachments"]
            .insert()
            .values(
                id=attachment_id,
                project_id=pid,
                entity_type="project",
                entity_id=pid,
                category="历史记录",
                filename="突发状况历史记录.csv",
                stored_name=stored,
                file_size=len(raw),
                content_type="text/csv; charset=utf-8",
                uploaded_by=None,
                uploaded_at=now,
            )
        )
        csv_reports.append(
            {
                "project_id": pid,
                "attachment_id": attachment_id,
                "incidents": len(rows),
                "sha256": _digest(raw),
            }
        )
    for row in inbox_to_attach:
        bind.execute(tables["attachments"].insert().values(**row))
    # Reverse dependency order is mandatory on both SQLite (FK OFF) and PG.
    for table in reversed(metadata.sorted_tables):
        if table.name in demo_conditions:
            bind.execute(table.delete().where(demo_conditions[table.name]))
    for name in (
        "incident_actions",
        "incidents",
        "project_change_sets",
        "project_edit_history",
    ):
        bind.execute(tables[name].delete().where(tables[name].c.project_id.in_(demos)))
    if demos:
        bind.execute(
            tables["projects"].delete().where(tables["projects"].c.id.in_(demos))
        )
    for project in demos.values():
        audit(
            None,
            "project",
            project["id"],
            "系统迁移删除个人演示项目；所有记录及原文件已加密保全",
            {"id": project["id"], "owner": project.get("created_by")},
            {"export_revision": REVISION},
        )
    # Existing project identities, states and user security fields are invariant.
    remaining = {p["id"]: p for p in _rows(bind, tables["projects"])}
    if remaining != normal or _rows(bind, tables["users"]) != users_before:
        raise RuntimeError("T03正式项目或账号核对不一致，事务已中止")
    for row in original_attachments:
        if row["project_id"] in normal:
            current = (
                bind.execute(
                    sa.select(tables["attachments"]).where(
                        tables["attachments"].c.id == row["id"]
                    )
                )
                .mappings()
                .one()
            )
            if dict(current) != row:
                raise RuntimeError("T03原项目附件记录变化，事务已中止")
    audit(
        None,
        "migration",
        REVISION,
        "T03旧功能数据保全及删除：正式项目和账号核对通过",
        {"table_counts": before_counts},
        {
            "exports": exports,
            "incident_csv": csv_reports,
            "inbox_destinations": dispositions,
        },
    )
    report = {
        "revision": REVISION,
        "table_counts_before": before_counts,
        "normal_project_ids": sorted(normal),
        "deleted_demo_ids": sorted(demos),
        "exports": exports,
        "incident_csv": csv_reports,
        "inbox_destinations": dispositions,
        "source_files": cleanup,
        "cleanup_complete": False,
    }
    _atomic(root / "manifest.json", _json(report))
    return report


def finalize_files(bind):
    """After committed schema upgrade, remove only exported bytes with no remaining owner."""
    from app.config import DATA_DIR, UPLOAD_DIR, SECRET_KEY

    manifest = DATA_DIR / "migration-exports" / "t03" / "manifest.json"
    if not manifest.exists():
        return
    report = json.loads(manifest.read_bytes())
    if (
        report.get("cleanup_complete")
        or "inbox_documents" in sa.inspect(bind).get_table_names()
    ):
        return
    root = manifest.parent
    for item in report["exports"]:
        exported = root / item["path"]
        if (
            exported.is_symlink()
            or root.resolve() not in exported.resolve().parents
            or not exported.is_file()
        ):
            raise RuntimeError("T03加密导出不可用，保留原始文件")
        data = exported.read_bytes()
        if _digest(data) != item["sha256"]:
            raise RuntimeError("T03加密导出校验失败，保留原始文件")
        decrypt_export(data, SECRET_KEY)
    live = set()
    for name in ("attachments", "template_docs"):
        live.update(bind.execute(sa.text(f"SELECT stored_name FROM {name}")).scalars())
    for refs in bind.execute(
        sa.select(metadata.tables["tasks"].c.reference_docs)
    ).scalars():
        live.update(
            r["stored_name"]
            for r in refs or []
            if isinstance(r, dict) and r.get("stored_name")
        )
    # Old immutable snapshots retain file ownership even after active rows disappear.
    archives = sa.Table("project_archives", sa.MetaData(), autoload_with=bind)
    for snapshot in bind.execute(sa.select(archives.c.snapshot)).scalars():
        live.update(
            r.get("stored_name")
            for r in (snapshot or {}).get("binary_files", {}).get("manifest", [])
        )
    outcome = {}
    for stored, item in report["source_files"].items():
        path = UPLOAD_DIR / stored
        if stored in live:
            outcome[stored] = "shared_reference_preserved"
        elif not path.exists():
            outcome[stored] = "already_removed"
        elif (
            path.is_symlink()
            or path.resolve().parent != UPLOAD_DIR.resolve()
            or _digest(path.read_bytes()) != item["sha256"]
        ):
            outcome[stored] = "changed_source_preserved"
        else:
            path.unlink()
            outcome[stored] = "encrypted_export_verified_source_removed"
    report.update(cleanup_complete=True, file_cleanup=outcome)
    _atomic(manifest, _json(report))

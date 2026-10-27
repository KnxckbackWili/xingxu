#!/usr/bin/env python3
"""Verify an old system backup on a newly-created, private migration copy.

Never accepts an existing application database as its target and never runs
pytest. stdout contains aggregate evidence only; identifying evidence stays in
the new 0700 work directory. Run with the backend Python environment.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import logging
from math import floor, fsum, isclose, isfinite
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
from uuid import uuid4
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
T01 = "g3a01b000001"
FORMAT = "xingxu-v3-migration-verification-1"


class VerificationError(Exception):
    """Messages are fixed diagnostic codes, never database/backup contents."""


def normalized(value):
    if isinstance(value, float) and not isfinite(value):
        return {"invalid_original_number": str(value)}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return normalized(float(value))
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if isinstance(value, dict):
        return {str(k): normalized(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalized(v) for v in value]
    return value


def encoded(value):
    return json.dumps(normalized(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_sha(path):
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def private_json(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(normalized(value), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def status_counts(rows):
    allowed = {"draft", "planning", "preparing", "ready", "executing", "commissioning", "pilot", "acceptance", "completed", "archived", "suspended"}
    return dict(Counter(r["status"] if r["status"] in allowed else "unknown_redacted" for r in rows))


def new_private_directory(path):
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise VerificationError("WORK_DIRECTORY_MUST_BE_NEW_ABSOLUTE_PATH")
    for parent in path.parents:
        if parent.is_symlink() or (parent / ".git").exists():
            raise VerificationError("WORK_DIRECTORY_MUST_BE_OUTSIDE_GIT_AND_SYMLINKS")
    path.mkdir(mode=0o700, parents=False)
    path.chmod(0o700)


def safe_name(raw):
    name = PurePosixPath(raw)
    if name.is_absolute() or ".." in name.parts or "\\" in raw or "\x00" in raw:
        raise VerificationError("UNSAFE_ARCHIVE_MEMBER")
    return name


def extract_backup(archive, target):
    """Manual extraction rejects links, duplicate names and special devices."""
    seen = set()
    total = 0
    with tarfile.open(archive, "r:*") as source:
        for member in source:
            name = safe_name(member.name)
            if str(name) in ("", "."):
                continue
            if name in seen or not (member.isdir() or member.isfile()):
                raise VerificationError("DUPLICATE_OR_NONREGULAR_ARCHIVE_MEMBER")
            seen.add(name)
            total += member.size
            if total > 128 * 1024**3:
                raise VerificationError("BACKUP_EXPANDED_SIZE_LIMIT")
            destination = target.joinpath(*name.parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if member.isdir():
                destination.mkdir(mode=0o700, exist_ok=True)
            else:
                with source.extractfile(member) as incoming, destination.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                destination.chmod(0o600)
    manifest = target / "manifest.json"
    key = target / "secret.key"
    if not manifest.is_file() or not key.is_file() or not key.read_text().strip():
        raise VerificationError("BACKUP_MANIFEST_OR_INSTALLATION_KEY_MISSING")
    result = json.loads(manifest.read_text())
    if result.get("type") != "agvpm-system-backup":
        raise VerificationError("NOT_A_SYSTEM_BACKUP")
    return result


def files_snapshot(root):
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise VerificationError("SYMLINK_IN_PRIVATE_STORAGE")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"sha256": file_sha(path), "size": path.stat().st_size}
    return result


def database_snapshot(engine):
    import sqlalchemy as sa
    result = {}
    with engine.connect() as connection:
        metadata = sa.MetaData()
        metadata.reflect(connection)
        for name, table in sorted(metadata.tables.items()):
            rows = [normalized(dict(row)) for row in connection.execute(sa.select(table)).mappings()]
            result[name] = sorted(rows, key=encoded)
    return result


def frozen_progress(snapshot):
    """2.4.3 quantity weighting, copied as arithmetic, without importing old ORM."""
    modules = {r["id"]: r for r in snapshot.get("modules", [])}
    phases = {r["id"]: r for r in snapshot.get("phases", [])}
    checks = defaultdict(list)
    completed = defaultdict(float)
    for row in snapshot.get("check_items", []):
        checks[row["task_id"]].append(row)
    for row in snapshot.get("daily_progress", []):
        completed[row["task_id"]] += row.get("completed_quantity") or 0
    result = {}
    for project in snapshot.get("projects", []):
        total = weighted = done = 0.0
        task_values = []
        for task in snapshot.get("tasks", []):
            module = modules.get(task.get("module_id"), {})
            phase = phases.get(module.get("phase_id"), {})
            if task.get("project_id") != project["id"] or not module or not phase or phase.get("name") == "项目准备":
                continue
            items = checks[task["id"]]
            target = task.get("target_quantity") or 0
            if target <= 0 or (items and not any(c.get("is_applicable") for c in items)):
                target = 0
            count = round(completed[task["id"]], 2)
            pct = 100.0 if task.get("manually_completed") else min(100, round(count / target * 100, 1)) if target else 100.0 if items and not any(c.get("is_applicable") for c in items) else 0.0
            if not task.get("manually_completed") and any(c.get("failed") or (c.get("is_applicable") and not c.get("is_done") and (c.get("is_required") or c.get("is_safety_critical"))) for c in items):
                pct = min(pct, 99)
            if any(c.get("is_safety_critical") and (not c.get("is_done") or c.get("failed") or not c.get("is_applicable")) for c in items):
                pct = min(pct, 99)
            total += target
            weighted += target * pct / 100
            done += count
            task_values.append({"id": task["id"], "target": target, "completed": count, "percent": pct})
        result[project["id"]] = {"calculation": "v2.4.3_quantity_weighted", "target": total,
                                 "completed": done, "percent": round(weighted / total * 100, 1) if total else 0,
                                 "tasks": task_values}
    return result


def encrypted_exports(data):
    from migrations.v3_retirement import decrypt_export
    manifest = data / "migration-exports" / "t03" / "manifest.json"
    if not manifest.exists():
        return {}, {}, []
    report = json.loads(manifest.read_bytes())
    records, files, proof = defaultdict(list), {}, []
    for item in report["exports"]:
        path = manifest.parent / safe_name(item["path"])
        if file_sha(path) != item["sha256"]:
            raise VerificationError("RETIREMENT_EXPORT_SHA_MISMATCH")
        payload = decrypt_export(path.read_bytes(), (data / "secret.key").read_text().strip())
        if hashlib.sha256(payload).hexdigest() != item["payload_sha256"]:
            raise VerificationError("RETIREMENT_EXPORT_PAYLOAD_SHA_MISMATCH")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name, rows in json.loads(archive.read("records.json")).items():
                records[name].extend(normalized(rows))
            for member in archive.infolist():
                if not member.filename.startswith("files/") or member.is_dir():
                    continue
                sha = hashlib.sha256()
                with archive.open(member) as incoming:
                    for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                        sha.update(chunk)
                files[member.filename[6:]] = {"sha256": sha.hexdigest(), "size": member.file_size}
        proof.append({"sha256": item["sha256"], "payload_sha256": item["payload_sha256"],
                      "record_counts": item["record_counts"], "file_count": item["file_count"]})
    return records, files, proof


def subset(original, destination):
    return all(k in destination and destination[k] == v for k, v in original.items())


def t01_dispositions(before, after, sqlite, source_user_version=0):
    """Audit g01 too: only the frozen repairs below can explain an old field."""
    from migrations.v243_data import PREP_PHASE_MODULES
    renamed = {name: identity for identity, name, _ in PREP_PHASE_MODULES}
    renamed["自动充电"] = "mod-15"
    changes, failures = [], []
    old_modules = {r["id"]: r for r in before.get("modules", [])}
    old_phases = {r["id"]: r for r in before.get("phases", [])}
    new_phases = {r["id"]: r for r in after.get("phases", [])}
    module_ids = {}
    for row in before.get("modules", []):
        if row.get("project_id") is None and row["name"] in renamed:
            candidates = [r for r in after.get("modules", []) if r["id"] == renamed[row["name"]] and r["name"] == row["name"]]
            if candidates:
                module_ids[row["id"]] = candidates[0]["id"]
    for table, rows in before.items():
        if table == "alembic_version":
            continue
        indexed = {r.get("id", digest(r)): r for r in after.get(table, [])}
        for row in rows:
            identity = row.get("id", digest(row))
            now = indexed.get(identity)
            if now is None and table == "modules":
                now = indexed.get(module_ids.get(identity, identity))
            if now is None:
                failures.append({"table": table, "id": identity, "kind": "t01_unexplained_row_loss"})
                continue
            for column, value in row.items():
                if column in now and now[column] == value:
                    continue
                reason = None
                if table == "users" and column == "role" and value == "sub_pm" and now[column] == "pm":
                    reason = "frozen_sub_pm_to_pm"
                elif table == "vehicles" and column == "vehicle_type" and value in ("custom", "自定义") and now[column] == "其他/定制":
                    reason = "frozen_vehicle_type_alias"
                elif table == "tasks" and column == "applicable_vehicle_types" and now[column] == [{"custom": "其他/定制", "自定义": "其他/定制"}.get(v, v) for v in (value or [])]:
                    reason = "frozen_vehicle_type_alias"
                elif sqlite and source_user_version < 2 and table == "tasks" and column == "standard_hours" and row.get("project_id") is None and now[column] is None:
                    reason = "frozen_sqlite_user_version_lt2_template_hours_reset"
                elif sqlite and table == "modules" and column == "id" and module_ids.get(identity) == now[column]:
                    reason = "frozen_template_module_stable_id_repair"
                elif sqlite and table == "tasks" and column == "module_id" and row.get("project_id") is None and module_ids.get(value) == now[column]:
                    reason = "frozen_template_module_stable_id_repair"
                elif table == "modules" and column == "phase_id":
                    original_phase = old_phases.get(value)
                    if original_phase is None and value is None:
                        sources = [m for m in before.get("modules", []) if m.get("project_id") is None and m["name"] == row["name"] and m.get("phase_id")]
                        sources.sort(key=lambda m: (m.get("template_id") is not None, m["id"]))
                        original_phase = old_phases.get(sources[0]["phase_id"]) if sources else None
                    destination = new_phases.get(now[column])
                    keys = ("name", "sort_order", "color", "entry_criteria", "exit_criteria")
                    if original_phase and destination and all(original_phase[k] == destination[k] for k in keys) and destination.get("project_id") in (row.get("project_id"), None):
                        reason = "frozen_missing_phase_link_or_project_phase_detachment"
                elif table == "modules" and column == "source_module_id" and not value:
                    source = old_modules.get(now[column])
                    if source and source.get("project_id") is None and source["name"] == row["name"] and source["phase_id"] == row["phase_id"]:
                        reason = "frozen_phase_detachment_source_link"
                elif table == "modules" and column == "preparation_conditions" and not value and row.get("project_id") is None:
                    expected = ["need_charging"] if row["name"] == "自动充电" else ["need_wms"] if row["name"] in ("WMS 接口", "WMS/MES 接口", "WMS/MES 对接") else None
                    if now[column] == expected:
                        reason = "frozen_scope_preparation_condition_backfill"
                elif table == "template_preparation_items" and column == "condition" and value == "default" and now[column] == "need_wms" and row["name"] == "客户系统接口文档（WMS/MES）":
                    reason = "frozen_wms_preparation_scope_correction"
                elif sqlite and table == "phases" and column == "sort_order" and row.get("project_id") is None:
                    prep = next((p for p in before.get("phases", []) if p.get("project_id") is None and p["name"] == "项目准备"), None)
                    entry = next((p for p in before.get("phases", []) if p.get("project_id") is None and p["name"] == "进场准备"), None)
                    expected = entry["sort_order"] if prep and entry and prep["sort_order"] > entry["sort_order"] and identity == prep["id"] else prep["sort_order"] if prep and entry and prep["sort_order"] > entry["sort_order"] and identity == entry["id"] else value + 1 if prep is None and value >= 2 else value
                    if now[column] == expected:
                        reason = "frozen_preparation_phase_order_repair"
                evidence = {"table": table, "id": identity, "column": column,
                            "before_sha256": digest(value), "after_sha256": digest(now.get(column)), "reason": reason}
                changes.append(evidence)
                if reason is None:
                    failures.append({**evidence, "kind": "t01_unexplained_field_change"})
    return changes, failures


def t01_additions(before, after):
    """Allow named frozen definitions/backfills, never invented execution facts."""
    from migrations.v243_data import DEFAULT_ITEMS, PREP_PHASE_MODULES, TEMPLATE_PREP_ITEMS
    additions, failures = [], []
    users = {r["id"] for r in before.get("users", [])}
    projects = {r["id"]: r for r in before.get("projects", [])}
    modules = {r["id"]: r for r in after.get("modules", [])}
    phases = {r["id"]: r for r in after.get("phases", [])}
    prep_modules = {identity: (name, tasks) for identity, name, tasks in PREP_PHASE_MODULES}
    wms = {"业务接口与数据映射": "接口字段、鉴权及状态映射确认", "业务订单闭环联调": "下发、执行、完成反馈全流程通过", "接口异常恢复验证": "超时重试、断线恢复及重复订单处理通过"}
    tasks = {r["id"]: r for r in after.get("tasks", [])}
    team_roles = {"标准实施团队": {"pm": 1, "lead": 1, "technician": 1, "worker": 2},
                  "快速响应团队": {"lead": 1, "worker": 1},
                  "复杂集成团队": {"pm": 1, "lead": 1, "technician": 1, "worker": 3, "intern": 1}}
    for table, rows in after.items():
        original_ids = {r.get("id", digest(r)) for r in before.get(table, [])}
        for row in rows:
            identity = row.get("id", digest(row))
            if table == "alembic_version" or identity in original_ids:
                continue
            reason = None
            if table == "archive_checklists":
                seed = (row["category"], row["item_name"], row["is_required"])
                if row["project_id"] in projects and not any(r["project_id"] == row["project_id"] for r in before.get(table, [])) and seed in DEFAULT_ITEMS and row["sort_order"] == DEFAULT_ITEMS.index(seed) and not any(row.get(k) for k in ("is_done", "done_by", "done_at", "attachment_id", "requirements")):
                    reason = "frozen_missing_archive_checklist_definitions_not_submissions"
            elif table == "template_preparation_items":
                seed = (row["name"], row["category"], row["is_required"], row["blocks_entry"], row["owner_party"], row["risk"], "default" if row["name"] == "客户系统接口文档（WMS/MES）" and row["condition"] == "need_wms" else row["condition"])
                if row.get("template_id") is None and not any(r.get("template_id") is None for r in before.get(table, [])) and seed in TEMPLATE_PREP_ITEMS and row["sort_order"] == TEMPLATE_PREP_ITEMS.index(seed):
                    reason = "frozen_default_preparation_definition_seed"
            elif table == "team_templates":
                if not before.get(table) and row.get("roles") == team_roles.get(row.get("name")) and row.get("name") in team_roles:
                    reason = "frozen_team_definition_seed_later_encrypted_retirement"
            elif table == "project_members":
                project = projects.get(row["project_id"], {})
                members = set(project.get("members") or []) | {project.get("manager"), project.get("technical_manager")}
                members.update(g.get("user_id") for g in (project.get("co_managers") or []))
                if row["user_id"] in members & users and row.get("role") == "member":
                    reason = "frozen_existing_project_membership_relationship_backfill"
            elif table == "phases":
                keys = ("name", "sort_order", "color", "entry_criteria", "exit_criteria")
                if row.get("project_id") in projects and any(p.get("project_id") is None and all(row[k] == p[k] for k in keys) for p in before.get("phases", [])):
                    reason = "frozen_detached_project_phase_definition"
                elif row.get("project_id") is None and row.get("name") == "项目准备" and row.get("sort_order") == 1 and row.get("entry_criteria") == "准备清单确认" and row.get("exit_criteria") == "必需准备项完成":
                    reason = "frozen_missing_preparation_phase_definition"
            elif table == "modules" and row.get("project_id") is None:
                prep = prep_modules.get(identity)
                phase = phases.get(row.get("phase_id"), {})
                if prep and row["name"] == prep[0] and phase.get("name") == "项目准备":
                    reason = "frozen_preparation_module_definition"
                elif row["name"] == "WMS/MES 对接" and phase.get("name") == "系统联调" and row.get("category") == "extra" and row.get("is_selected") is False and row.get("preparation_conditions") == ["need_wms"]:
                    reason = "frozen_optional_wms_module_definition"
                elif any(r.get("project_id") is None and r["name"] == row["name"] and row["id"] in {"mod-15", *prep_modules} and subset({k: v for k, v in r.items() if k != "id"}, row) for r in before.get(table, [])):
                    reason = "frozen_template_module_id_repair"
            elif table == "tasks" and row.get("project_id") is None:
                module = modules.get(row.get("module_id"), {})
                no_facts = not any(row.get(k) for k in ("manually_completed", "manual_completed_by", "manual_completed_at", "deliverables", "reference_docs"))
                prep = prep_modules.get(row.get("module_id"))
                if no_facts and row.get("target_quantity") == 1 and row.get("unit") == "项":
                    if prep and row["name"] in prep[1] and row.get("quantity_type") == "manual":
                        reason = "frozen_preparation_work_definition"
                    elif module.get("name") == "WMS/MES 对接" and row["name"] in wms and row.get("quantity_type") == "fixed":
                        reason = "frozen_optional_wms_work_definition"
            elif table == "check_items":
                task = tasks.get(row.get("task_id"), {})
                if row.get("project_id") is None and task.get("project_id") is None and row.get("name") == wms.get(task.get("name")) and row.get("is_required") and not any(row.get(k) for k in ("is_done", "failed", "done_by", "done_at")):
                    reason = "frozen_optional_wms_check_definition_not_review"
            elif table == "change_logs" and row.get("entity_type") == "migration":
                if row.get("entity_id") == "scope-preparation-v1" and row.get("action") == "update" and row.get("project_id") is None:
                    reason = "frozen_scope_backfill_audit"
                elif row.get("entity_id") == "t01-missing-member" and row.get("action") == "review" and row.get("project_id") in projects:
                    project = projects[row["project_id"]]
                    refs = set(project.get("members") or []) | {project.get("manager"), project.get("technical_manager")}
                    refs.update(g.get("user_id") for g in (project.get("co_managers") or []))
                    if any(row.get("detail") == f"保留项目原始成员引用 {uid}；账号不存在，未伪造关系，请核对" for uid in refs - users if uid):
                        reason = "frozen_missing_member_reference_warning_not_invented_account"
            item = {"table": table, "id": identity, "row_sha256": digest(row), "destination": reason}
            additions.append(item)
            if reason is None:
                failures.append({**item, "kind": "t01_unexplained_added_row"})
    return additions, failures


def final_acceptance(args, source_version, head, passed):
    if args.final_head is None:
        return False
    if not args.expected_sha256 or source_version != "2.4.3" or args.final_head != head or not args.fresh_backup_attested:
        raise VerificationError("FINAL_REQUIRES_FRESH_V243_ATTESTATION_PINNED_SHA_AND_FINAL_HEAD")
    return passed


def verify_t34(before, after, enabled):
    """Independently verify frozen work provenance and effective completion.

    A preserved snapshot alone never authorizes a changed qualification. Audit,
    original quantities/checks, current fields and scope must all agree.
    """
    if not enabled:
        return [], [], {}
    task_keys = ("id", "name", "description", "quantity_type", "target_quantity", "unit", "standard_hours",
                 "sort_order", "safety_flag", "source_task_id", "source_vehicle_event_id", "manually_completed",
                 "manual_completed_by", "manual_completed_role", "manual_completed_at", "manual_completed_reason",
                 "depends_on", "applicable_vehicle_types", "manual_check_overrides")
    module_keys = ("id", "name", "category", "phase_id", "source_module_id")
    phase_keys = ("id", "name", "project_id")
    manual_keys = ("manually_completed", "manual_completed_by", "manual_completed_role", "manual_completed_at", "manual_completed_reason")
    old_modules = {r["id"]: r for r in before.get("modules", [])}
    old_phases = {r["id"]: r for r in before.get("phases", [])}
    phases = {r["id"]: r for r in after.get("phases", [])}
    current = {r["id"]: r for r in after.get("tasks", [])}
    reports, checks, audits = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in before.get("daily_progress", []):
        reports[row["task_id"]].append(float(row.get("completed_quantity") or 0))
    for row in before.get("check_items", []):
        checks[row["task_id"]].append(row)
    for row in after.get("change_logs", []):
        if row.get("action") == "migrate_work":
            audits[row.get("entity_id")].append(row)
    dispositions, failures, verified = [], [], {}

    def equal(value, original, key):
        if key == "manual_completed_at" and isinstance(value, str) and isinstance(original, str):
            try:
                return datetime.fromisoformat(value) == datetime.fromisoformat(original)
            except ValueError:
                return False
        if key in ("safety_flag", "manually_completed") and isinstance(original, bool):
            return type(value) in (bool, int) and value in (0, 1) and bool(value) == original
        return value == original

    for task in before.get("tasks", []):
        now = current.get(task["id"])
        if now is None:
            continue  # generic field audit separately demands exact T03 export
        errors_before = len(failures)
        source = now.get("legacy_work_snapshot")
        if not isinstance(source, dict) or set(source) != {"kind", "task", "module", "phase", "completed_quantity", "report_count", "scope_conditions"} or source.get("kind") != "t34_legacy_work":
            failures.append({"kind": "t34_missing_or_changed_source_shape", "task_id": task["id"]})
            continue
        module = old_modules.get(task.get("module_id"), {})
        phase = old_phases.get(module.get("phase_id"), {})
        for name, original, keys in (("task", task, task_keys), ("module", module, module_keys), ("phase", phase, phase_keys)):
            part = source.get(name)
            if not isinstance(part, dict) or set(part) != set(keys):
                failures.append({"kind": "t34_missing_source_field", "task_id": task["id"], "part": name})
                continue
            for key in keys:
                if not equal(part[key], original.get(key), key):
                    failures.append({"kind": "t34_changed_original_source_field", "task_id": task["id"], "part": name, "column": key})
        quantity = fsum(reports[task["id"]])
        recorded = source.get("completed_quantity")
        if not isinstance(recorded, (int, float)) or isinstance(recorded, bool) or not isclose(recorded, quantity, abs_tol=1e-9, rel_tol=1e-12) or type(source.get("report_count")) is not int or source["report_count"] != len(reports[task["id"]]):
            failures.append({"kind": "t34_changed_original_quantity_or_count", "task_id": task["id"]})
        scope = module.get("preparation_conditions") or []
        if source.get("scope_conditions") != scope or now.get("scope_conditions") != scope or now.get("group_label") != (module.get("name") or ""):
            failures.append({"kind": "t34_changed_group_or_scope", "task_id": task["id"]})
        actual_phase = phases.get(now.get("phase_id"), {})
        if phase.get("id") and (not task.get("project_id") or phase.get("project_id") == task.get("project_id")):
            correct_phase = now.get("phase_id") == phase["id"]
        else:
            expected_phase = {"project_id": task.get("project_id"), "template_id": task.get("template_id") if not task.get("project_id") else None,
                              "name": phase.get("name") or "历史未分类", "sort_order": phase.get("sort_order") or 0,
                              "color": phase.get("color") or "#1890ff", "entry_criteria": phase.get("entry_criteria") or "",
                              "exit_criteria": phase.get("exit_criteria") or ""}
            correct_phase = bool(actual_phase) and all(actual_phase.get(k) == v for k, v in expected_phase.items())
        if not correct_phase:
            failures.append({"kind": "t34_changed_phase_ownership_or_definition", "task_id": task["id"]})
        items = checks[task["id"]]
        blocked = any((c.get("is_safety_critical") and (not c.get("is_done") or c.get("failed") or not c.get("is_applicable"))) or
                      (c.get("is_applicable") and (c.get("failed") or c.get("is_required") and not c.get("is_done"))) for c in items)
        all_na = bool(items) and not any(c.get("is_applicable") for c in items)
        target = task.get("target_quantity")
        converted = bool(task.get("project_id") and phase.get("name") != "项目准备" and task.get("quantity_type") != "per_vehicle" and
                         not task.get("manually_completed") and not blocked and (all_na or target is not None and target > 0 and quantity >= target - 1e-9))
        reason = "迁移：原检查全部不适用" if all_na else "迁移：原报工达到原目标且质量条件满足"
        expected = {k: task.get(k) for k in manual_keys}
        if converted:
            expected.update(manually_completed=True, manual_completed_by=None, manual_completed_role=None, manual_completed_at=None, manual_completed_reason=reason)
        if any(not equal(now.get(k), v, k) for k, v in expected.items()):
            failures.append({"kind": "t34_incorrect_effective_completion", "task_id": task["id"]})
        events = audits[task["id"]]
        if converted:
            valid_audit = len(events) == 1 and events[0].get("project_id") == task.get("project_id") and events[0].get("entity_type") == "task" and events[0].get("operator_id") is None and events[0].get("created_at") is not None and events[0].get("detail") == reason and events[0].get("old_value") == {"manually_completed": False} and events[0].get("new_value") == {"manually_completed": True, "basis": "legacy_verified_quantity", "identity": "unknown", "date": "unknown"}
        else:
            valid_audit = not events
        if not valid_audit:
            failures.append({"kind": "t34_missing_or_fabricated_system_audit", "task_id": task["id"]})
        if len(failures) == errors_before:
            dispositions.append({"task_id": task["id"], "destination": "tasks.legacy_work_snapshot", "effective_completion_converted": converted,
                                 "completed_quantity": quantity, "report_count": len(reports[task["id"]]), "identity": "unknown" if converted else "unchanged", "date": "unknown" if converted else "unchanged"})
            if converted:
                for key in manual_keys:
                    verified[("tasks", task["id"], key)] = "t34_original_snapshot_and_independent_verified_completion_audit"
    return dispositions, failures, verified


def exact_decimal_sum(numbers):
    """Add finite old numeric values using integer scaling, without context rounding."""
    if not numbers:
        return Decimal(0)
    minimum = min(0, *(number.as_tuple().exponent for number in numbers))
    if abs(minimum) > 10000 or any(abs(number.adjusted()) > 10000 for number in numbers):
        raise VerificationError("T40_ORIGINAL_NUMBER_EXPONENT_OUT_OF_BOUNDS")
    total = 0
    for number in numbers:
        sign, digits, exponent = number.as_tuple()
        coefficient = int(''.join(str(digit) for digit in digits))
        total += (-coefficient if sign else coefficient) * 10 ** (exponent - minimum)
    return Decimal((int(total < 0), tuple(int(digit) for digit in str(abs(total))), minimum))


def verify_t40(before, after, enabled):
    """Rebuild weekly obligations from original rows, never from claimed source.

    This verification uses the pre-g01 database snapshot. The new cell's source
    is evidence to compare, not input from which to derive its expected values.
    Retired projects remain subject to the independent encrypted-export check.
    """
    if not enabled:
        return [], []
    from datetime import timedelta
    from decimal import InvalidOperation
    source_kind = 't40_legacy_daily_rollup'
    original_columns = {'id', 'project_id', 'task_id', 'work_date', 'assignee_id',
                        'planned_quantity', 'status', 'notes', 'is_confirmed', 'is_locked', 'version'}
    source_tasks = {r['id']: r for r in before.get('tasks', [])}
    current_tasks = {r['id']: r for r in after.get('tasks', [])}
    source_projects = {r['id'] for r in before.get('projects', [])}
    surviving = source_projects & {r['id'] for r in after.get('projects', [])}
    modules = {r['id']: r for r in before.get('modules', [])}
    phases = {r['id']: r for r in before.get('phases', [])}
    groups, actual, audits = defaultdict(list), defaultdict(list), defaultdict(list)
    failures, records = [], []
    current_originals = {r['id']: r for r in after.get('schedule_entries', [])}
    source_ids = {r['id'] for r in before.get('schedule_entries', [])}

    def fail(kind, **details):
        failures.append({'kind': kind, **details})

    def boolean(value):
        return value is None or type(value) is bool or type(value) is int and value in (0, 1)

    for row in before.get('schedule_entries', []):
        if row.get('project_id') not in surviving:
            continue
        retained_row = current_originals.get(row.get('id'))
        if retained_row is None:
            fail('t40_original_live_row_missing', entry_id=row.get('id'))
        else:
            for column, value in row.items():
                if column not in retained_row or encoded(retained_row[column]) != encoded(value):
                    fail('t40_original_live_field_changed', entry_id=row.get('id'), column=column)
        task = source_tasks.get(row.get('task_id'))
        if not original_columns.issubset(row) or not task or task.get('project_id') != row['project_id']:
            fail('t40_invalid_original_columns_or_owner', entry_id=row.get('id'))
            continue
        if not boolean(row['is_confirmed']) or not boolean(row['is_locked']):
            fail('t40_invalid_original_boolean', entry_id=row['id'])
            continue
        try:
            day = date.fromisoformat(row['work_date']) if isinstance(row['work_date'], str) else row['work_date']
            if type(day) is not date:
                raise ValueError
            monday = (day - timedelta(days=day.weekday())).isoformat()
        except (ValueError, TypeError, AttributeError):
            fail('t40_invalid_original_date', entry_id=row['id'])
            continue
        key = (row['project_id'], row['task_id'], monday, bool(row['is_confirmed']), row['status'] == 'skipped')
        groups[key].append(row)
    for row in after.get('schedule_entries', []):
        if row['id'] not in source_ids:
            fail('t40_unexplained_new_daily_row', entry_id=row['id'])
    for cell in after.get('weekly_plan_cells', []):
        if type(cell.get('published')) is not bool or type(cell.get('is_cancelled')) is not bool:
            fail('t40_invalid_weekly_boolean', cell_id=cell.get('id'))
            continue
        key = (cell.get('project_id'), cell.get('task_id'), cell.get('week_start'), cell['published'], cell['is_cancelled'])
        actual[key].append(cell)
    for event in after.get('change_logs', []):
        if event.get('action') == 'migrate_weeks':
            audits[event.get('project_id')].append(event)

    verified_cell_ids = defaultdict(list)
    covered_entry_ids = set()
    for key, original_rows in groups.items():
        pid, tid, monday, published, cancelled = key
        rows = sorted(original_rows, key=lambda r: (r['work_date'], r['id']))
        cells = actual.pop(key, [])
        if len(cells) != 1:
            fail('t40_missing_weekly_cell' if not cells else 't40_duplicate_weekly_cell',
                 project_id=pid, task_id=tid, week_start=monday, count=len(cells))
            continue
        cell, task = cells[0], source_tasks[tid]
        start_errors = len(failures)
        verified_cell_ids[pid].append(cell.get('id'))
        phase = phases.get(modules.get(task.get('module_id'), {}).get('phase_id'))
        expected_step = 'legacy_' + tid if task.get('quantity_type') == 'per_vehicle' and phase and phase.get('name') != '项目准备' else None
        current = current_tasks.get(tid)
        if not current or current.get('project_id') != pid or current.get('quantity_type') != task.get('quantity_type') or current.get('vehicle_step_key') != expected_step:
            fail('t40_changed_work_scope', cell_id=cell.get('id'), task_id=tid)
        numbers, nulls, invalid = [], 0, 0
        for row in rows:
            value = row['planned_quantity']
            if value is None:
                nulls += 1
                continue
            try:
                if isinstance(value, dict) or isinstance(value, bool):
                    raise InvalidOperation
                number = Decimal(str(value))
                if not number.is_finite():
                    raise InvalidOperation
                numbers.append(number)
            except (InvalidOperation, ValueError, TypeError):
                invalid += 1
        known = exact_decimal_sum(numbers)
        unknown = nulls + invalid
        vehicle = task.get('quantity_type') == 'per_vehicle'
        positive = not unknown and known > 0
        target = int(known) if vehicle and positive and known == known.to_integral_value() and known <= 2147483647 else None
        expected_mode = 'finish' if unknown or positive else 'in_progress'
        review_required = bool(unknown or vehicle and positive and target is None)
        expected = {
            'scope_key': f"all:legacy:{'published' if published else 'draft'}:{'cancelled' if cancelled else 'active'}",
            'scope': {'vehicle_unit_ids': []}, 'vehicle_step_key': expected_step,
            'mode': expected_mode, 'target_count': target,
            'assignee_ids': sorted({row['assignee_id'] for row in rows if row['assignee_id']}),
            'published_at': None, 'published_by': None, 'created_by': None, 'updated_by': None,
            'version': 0, 'intent_review_required': review_required,
        }
        for field, value in expected.items():
            if field not in cell or cell[field] != value:
                fail('t40_wrong_weekly_cell_field', cell_id=cell.get('id'), column=field)
        if type(cell.get('version')) is not int or target is not None and type(cell.get('target_count')) is not int:
            fail('t40_invalid_weekly_numeric_type', cell_id=cell.get('id'))
        try:
            created = datetime.fromisoformat(cell['created_at'])
            updated = datetime.fromisoformat(cell['updated_at'])
            if updated < created:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            fail('t40_invalid_creation_chronology', cell_id=cell.get('id'))
        source = cell.get('source_metadata')
        required = {'kind', 'original_entries', 'original_entry_ids', 'original_planned_sum',
                    'migration_review_required', 'publication_time', 'publication_actor'}
        required |= {'known_planned_sum', 'unknown_quantity_count', 'null_quantity_count', 'invalid_quantity_count'}
        if not isinstance(source, dict) or set(source) != required:
            fail('t40_missing_or_unexplained_source_shape', cell_id=cell.get('id'))
            continue
        expected_source = {'kind': source_kind, 'original_entry_ids': [row['id'] for row in rows],
            'original_planned_sum': None if unknown else str(known),
            'migration_review_required': review_required,
            'publication_time': 'unknown', 'publication_actor': 'unknown',
            'known_planned_sum': str(known), 'unknown_quantity_count': unknown,
            'null_quantity_count': nulls, 'invalid_quantity_count': invalid}
        for field, value in expected_source.items():
            if field not in source or source[field] != value:
                fail('t40_incorrect_quantity_or_source_disposition', cell_id=cell.get('id'), column=field)
        if type(source.get('migration_review_required')) is not bool or any(type(source.get(k)) is not int for k in ('unknown_quantity_count', 'null_quantity_count', 'invalid_quantity_count')) or type(cell.get('intent_review_required')) is not bool:
            fail('t40_invalid_source_numeric_type', cell_id=cell.get('id'))
        originals = source.get('original_entries')
        if not isinstance(originals, list) or len(originals) != len(rows):
            fail('t40_original_entry_coverage_mismatch', cell_id=cell.get('id'))
        else:
            for original, retained in zip(rows, originals):
                if not isinstance(retained, dict) or set(retained) != set(original):
                    fail('t40_original_entry_columns_mismatch', entry_id=original['id'])
                    continue
                for column, value in original.items():
                    candidate = retained[column]
                    if column in ('is_confirmed', 'is_locked') and value is not None:
                        equal = boolean(candidate) and candidate is not None and bool(candidate) == bool(value)
                    else:
                        try:
                            equal = encoded(candidate) == encoded(value)
                        except (ValueError, TypeError):
                            equal = isinstance(candidate, dict) and candidate == {'invalid_original_number': str(value)}
                    if not equal:
                        fail('t40_changed_original_entry_field', entry_id=original['id'], column=column)
                if original['id'] in covered_entry_ids:
                    fail('t40_duplicate_original_entry', entry_id=original['id'])
                covered_entry_ids.add(original['id'])
        if len(failures) == start_errors:
            records.append({'cell_id': cell['id'], 'project_id': pid, 'task_id': tid,
                'week_start': monday, 'published': published, 'cancelled': cancelled,
                'original_entry_ids': [row['id'] for row in rows], 'known_planned_sum': str(known),
                'unknown_quantity_count': unknown, 'target_count': target, 'mode': expected_mode,
                'intent_review_required': review_required,
                'destination': 'weekly_plan_cells_with_exact_immutable_original_rows'})
    for cells in actual.values():
        for cell in cells:
            fail('t40_unexplained_weekly_cell', cell_id=cell.get('id'))
    expected_projects = {key[0] for key in groups}
    for pid in expected_projects | set(audits):
        events = audits[pid]
        expected_ids = verified_cell_ids.get(pid, [])
        valid = pid in expected_projects and len(events) == 1
        if valid:
            event = events[0]
            value = event.get('new_value')
            valid = (event.get('entity_type') == 'weekly_plan' and event.get('entity_id') == pid
                and event.get('operator_id') is None and event.get('created_at') is not None
                and event.get('old_value') == {'source': 'schedule_entries', 'unchanged': True}
                and isinstance(value, dict) and set(value) == {'cell_ids', 'source_kind'}
                and value['source_kind'] == source_kind and isinstance(value['cell_ids'], list)
                and all(isinstance(identity, str) for identity in value['cell_ids'])
                and len(value['cell_ids']) == len(expected_ids) and set(value['cell_ids']) == set(expected_ids))
        if not valid:
            fail('t40_missing_or_incorrect_system_audit', project_id=pid)
    review_cells = defaultdict(list)
    for record in records:
        if record['intent_review_required']:
            review_cells[record['project_id']].append(record)
    review_audits = defaultdict(list)
    for event in after.get('change_logs', []):
        if event.get('action') == 'review_plan_intent':
            review_audits[event.get('project_id')].append(event)
    for pid in set(review_cells) | set(review_audits):
        cells, events = review_cells[pid], review_audits[pid]
        valid = bool(cells) and len(events) == 1
        if valid:
            event = events[0]
            old, new = event.get('old_value'), event.get('new_value')
            expected_old = [{'id': row['cell_id'], 'previous_mode': row['mode'],
                'previous_target_count': row['target_count'], 'previous_version': 0,
                'unknown_quantity_count': row['unknown_quantity_count']} for row in cells]
            valid = (event.get('project_id') == pid and event.get('entity_id') == pid
                and event.get('entity_type') == 'weekly_plan' and event.get('operator_id') is None
                and event.get('created_at') is not None and isinstance(old, dict) and set(old) == {'cells'}
                and isinstance(old['cells'], list) and all(isinstance(row, dict) for row in old['cells'])
                and encoded(sorted(old['cells'], key=lambda row: str(row.get('id', '')))) == encoded(sorted(expected_old, key=lambda row: row['id']))
                and isinstance(new, dict) and set(new) == {'cell_ids', 'intent_review_required'}
                and new['intent_review_required'] is True and isinstance(new['cell_ids'], list)
                and all(isinstance(identity, str) for identity in new['cell_ids'])
                and len(new['cell_ids']) == len(cells) and set(new['cell_ids']) == {row['cell_id'] for row in cells})
        if not valid:
            fail('t40_missing_or_incorrect_intent_review_audit', project_id=pid)
    if after.get('field_operations'):
        fail('migration_fabricated_actual_field_operation', count=len(after['field_operations']))
    return records, failures


def verify_fields(before, after, exported, verified_fields=None):
    """Every changed old field must have a verified, exact preservation seam."""
    destinations, failures = [], []
    current = {name: {r.get("id", digest(r)): r for r in rows} for name, rows in after.items()}
    rules = after.get("document_requirements", []) + after.get("project_document_definitions", [])
    for table, rows in before.items():
        if table == "alembic_version":
            continue
        for row in rows:
            identity = row.get("id", digest(row))
            now = current.get(table, {}).get(identity)
            removed = now is None
            exact_export = next((r for r in exported.get(table, []) if subset(row, r)), None)
            if removed and exact_export is not None:
                destinations.append({"table": table, "id": identity, "destination": "t03_encrypted_owner_export", "row_sha256": digest(row)})
                continue
            if removed and table == "scheduler_watermarks" and row.get("job_id") == "daily_report":
                destinations.append({"table": table, "id": identity, "destination": "retired_daily_report_watermark", "row_sha256": digest(row)})
                continue
            if removed:
                failures.append({"table": table, "id": identity, "kind": "unpreserved_row", "before_sha256": digest(row)})
                continue
            for column, value in row.items():
                if column in now and now[column] == value:
                    continue
                target = None
                if table == "users" and column in ("group_id", "skills"):
                    if any(r.get("id") == identity and r.get(column) == value for r in exported.get("user_retired_fields", [])):
                        target = "t03_encrypted_user_retired_fields"
                elif table == "projects" and column == "role_plan":
                    if any(r.get("id") == identity and r.get(column) == value for r in exported.get("project_role_plans", [])):
                        target = "t03_encrypted_project_role_plans"
                elif table == "projects" and column == "is_demo" and not value:
                    target = "t03_manifest_normal_project_ids"
                elif table == "projects" and column in ("status", "suspension", "version"):
                    legacy = now.get("legacy_lifecycle") or {}
                    if legacy.get("original_status") == row.get("status") and legacy.get("original_suspension") == row.get("suspension"):
                        expected = {"draft": "preparing", "planning": "preparing", "commissioning": "executing", "pilot": "executing"}.get(row.get("status"), row.get("status"))
                        if now.get("status") == expected or (now.get("status") == "suspended" and legacy.get("requires_repair")):
                            target = "projects.legacy_lifecycle"
                elif table == "vehicle_units" and column == "current_stage" and now.get("legacy_current_stage") == value:
                    target = "vehicle_units.legacy_current_stage"
                elif table == "tasks" and column == "deliverables" and now.get(column) == []:
                    matches = [r.get("source_metadata") or {} for r in rules]
                    if all(any(s.get("kind") == "task_deliverable" and (s.get("task") or {}).get("id") == identity and s.get("index") == i and s.get("original") == original for s in matches) for i, original in enumerate(value or [])):
                        target = "canonical_document_rules_exact_source_item_positions"
                elif (table, identity, column) in (verified_fields or {}):
                    target = verified_fields[(table, identity, column)]
                if target:
                    destinations.append({"table": table, "id": identity, "column": column, "destination": target,
                                         "before_sha256": digest(value), "after_sha256": digest(now.get(column))})
                else:
                    failures.append({"table": table, "id": identity, "column": column, "kind": "unexplained_field_change",
                                     "before_sha256": digest(value), "after_sha256": digest(now.get(column))})
    return destinations, failures


def document_dispositions(before, after):
    definitions = {r["source_key"]: r for r in after.get("project_document_definitions", [])}
    instances = {r["instance_key"]: r for r in after.get("project_documents", [])}
    versions = defaultdict(list)
    assets = {r["id"]: r for r in after.get("attachments", [])}
    users = {r["id"] for r in before.get("users", [])}
    tasks = {r["id"]: r for r in before.get("tasks", [])}
    for row in after.get("document_versions", []):
        versions[row["project_document_id"]].append(row)
    results, failures = [], []
    expected = []
    surviving = {r["id"] for r in after.get("projects", [])}
    for row in before.get("tasks", []):
        if row.get("project_id") not in surviving:
            continue
        for index, original in enumerate(row.get("deliverables") or []):
            expected.append(("task:" + row["id"] + ":" + str(index), "task_deliverable", original))
    for row in before.get("archive_checklists", []):
        if row["project_id"] in surviving:
            expected.append(("archive:" + row["id"], "archive_checklist", row))
    for row in before.get("project_preparation_items", []):
        if row["project_id"] in surviving and row["category"] != "procurement":
            expected.append(("preparation:" + row["id"], "preparation_item", row))
    for key, kind, original in expected:
        definition, document = definitions.get(key), instances.get(key)
        if not definition or not document or definition.get("source_metadata", {}).get("original") != original or document.get("source_metadata", {}).get("original") != original:
            failures.append({"source_key": key, "kind": "missing_or_changed_legacy_source"})
            continue
        attached = versions[document["id"]]
        item = original if isinstance(original, dict) else {}
        if kind == "task_deliverable":
            source_task = (document.get("source_metadata") or {}).get("task") or {}
            project_id = (tasks.get(source_task.get("id")) or {}).get("project_id")
            candidate = item.get("attachment_id")
            candidates = [candidate] if isinstance(candidate, str) and candidate else []
            claimed = (bool(item.get("done")) or item.get("status") in ("submitted", "approved")) and item.get("status") != "rejected"
            actor, when = item.get("submitted_by") or item.get("done_by"), item.get("submitted_at") or item.get("done_at")
            reason = ""
        elif kind == "archive_checklist":
            project_id = item["project_id"]
            candidates = [item["attachment_id"]] if item.get("attachment_id") else []
            claimed, actor, when, reason = item.get("is_done"), item.get("done_by"), item.get("done_at"), ""
        else:
            project_id = item["project_id"]
            candidates = [r["id"] for r in before.get("attachments", []) if r["project_id"] == project_id
                          and r.get("entity_type") in ("preparation_item", "preparation") and r.get("entity_id") == item["id"]]
            claimed, actor, when = item.get("status") == "passed", item.get("completed_by"), item.get("completed_at")
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            reason = next((extra[k] for k in ("not_applicable_reason", "waived_reason", "na_reason") if isinstance(extra.get(k), str) and extra[k].strip()), "") if item.get("status") == "na" else ""
        evidence = [assets[a] for a in dict.fromkeys(candidates) if a in assets and assets[a]["project_id"] == project_id]
        expected_status = "waived" if reason.strip() else "submitted" if claimed and any(a.get("sha256") for a in evidence) else "pending"
        instant = None
        if isinstance(when, str):
            try:
                value = datetime.fromisoformat(when.replace("Z", "+00:00"))
                if "T" in when or " " in when:
                    instant = normalized(value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value)
            except ValueError:
                pass
        if document["project_id"] != project_id or definition["project_id"] != project_id or document["status"] != expected_status or document.get("waived_reason") != reason:
            failures.append({"source_key": key, "kind": "legacy_submission_state_changed"})
        if document.get("submitted_by") != (actor if expected_status == "submitted" and actor in users else None) or document.get("submitted_at") != (instant if expected_status == "submitted" else None):
            failures.append({"source_key": key, "kind": "legacy_submission_actor_or_time_changed"})
        by_asset = {r["attachment_id"]: r for r in attached}
        if len(attached) != len(evidence) or set(by_asset) != {a["id"] for a in evidence}:
            failures.append({"source_key": key, "kind": "legacy_version_attachment_refs_changed"})
        for asset in evidence:
            version = by_asset.get(asset["id"], {})
            expected_actor = actor if actor in users else asset.get("uploaded_by") if asset.get("uploaded_by") in users else None
            if version.get("uploaded_by") != expected_actor or version.get("uploaded_at") != (instant or asset.get("uploaded_at")) or (version.get("review_metadata") or {}).get("original") != original:
                failures.append({"source_key": key, "kind": "legacy_version_actor_time_or_review_changed"})
        results.append({"source_key": key, "kind": kind, "definition_id": definition["id"], "document_id": document["id"],
                        "status": document["status"], "stage_key": document["stage_key"], "version_count": len(attached),
                        "destination": "project_custom_legacy_pending_classification" if document["stage_key"] == "legacy" else "canonical_project_document_with_exact_legacy_source",
                        "invalid_attachment_refs": (document.get("source_metadata") or {}).get("invalid_attachment_refs", [])})
    referenced = {v["attachment_id"] for group in versions.values() for v in group}
    unclassified = [{"attachment_id": r["id"], "project_id": r["project_id"], "destination": "project_unclassified_files"}
                    for r in after.get("attachments", []) if r["id"] not in referenced]
    known_documents = {r["document_id"] for r in results}
    known_definitions = {r["definition_id"] for r in results}
    for row in after.get("project_documents", []):
        if row["id"] not in known_documents:
            failures.append({"kind": "unexplained_migrated_document", "document_id": row["id"]})
    for row in after.get("project_document_definitions", []):
        if row["id"] not in known_definitions:
            failures.append({"kind": "unexplained_migrated_document_definition", "definition_id": row["id"]})
    return results, unclassified, failures


def vehicle_dispositions(before, after):
    """Recalculate T30 credits from frozen quantities; never guess a car/date."""
    surviving = {r["id"] for r in after.get("projects", [])}
    phases = {r["id"]: r for r in before.get("phases", [])}
    modules = {r["id"]: r for r in before.get("modules", [])}
    quantities = defaultdict(float)
    for row in before.get("daily_progress", []):
        quantities[row["task_id"]] += row.get("completed_quantity") or 0
    credits = {(r["project_id"], r["step_key"]): r for r in after.get("vehicle_progress_migrations", [])}
    result, failures = [], []
    for task in before.get("tasks", []):
        phase = phases.get(modules.get(task.get("module_id"), {}).get("phase_id"), {})
        if task.get("project_id") not in surviving or task.get("quantity_type") != "per_vehicle" or phase.get("name") == "项目准备":
            continue
        target = max(0, floor(task["target_quantity"] + 0.5)) if task.get("target_quantity") is not None and task["target_quantity"] > 0 else None
        raw = quantities[task["id"]]
        count = max(0, floor(raw + 0.5))
        count = target if task.get("manually_completed") and target is not None else min(target, count) if target is not None else count
        credit = credits.get((task["project_id"], "legacy_" + task["id"]))
        metadata = (credit or {}).get("source_metadata") or {}
        expected = {"task_id": task["id"], "task_name": task["name"], "target_quantity": task["target_quantity"],
                    "completed_quantity": float(raw), "rounded_target": target, "rounded_completed": count,
                    "quantity_unknown": target is None, "unit": task["unit"], "applicable_vehicle_types": task["applicable_vehicle_types"],
                    "target_rounding_difference": target - float(task["target_quantity"]) if target is not None else None,
                    "completion_rounding_difference": count - float(raw), "manually_completed": bool(task.get("manually_completed")),
                    "identity": "unknown", "date": "unknown"}
        if credit is None or metadata != expected or credit["total_count"] != count or credit["unassigned_count"] != count:
            failures.append({"kind": "vehicle_quantity_credit_mismatch", "task_id": task["id"]})
        else:
            result.append({"project_id": credit["project_id"], "step_key": credit["step_key"], "unassigned_count": count,
                           "source_metadata": metadata, "destination": "vehicle_progress_migrations_pending_real_vehicle_identity"})
    if after.get("vehicle_progress"):
        failures.append({"kind": "migration_fabricated_real_vehicle_completion"})
    return result, failures


def attachment_integrity(before, after, source_files, current_files):
    failures = []
    for row in before.get("attachments", []):
        proof = source_files.get(row["stored_name"])
        if proof is None or proof["size"] != row["file_size"]:
            failures.append({"kind": "source_attachment_missing_or_size_mismatch", "attachment_id": row["id"]})
    for row in after.get("attachments", []):
        proof = current_files.get(row["stored_name"])
        if proof is None or proof["size"] != row["file_size"] or proof["sha256"] != row.get("sha256"):
            failures.append({"kind": "migrated_attachment_integrity_mismatch", "attachment_id": row["id"]})
    return failures


def create_postgres(args, data):
    import psycopg2
    from psycopg2 import sql
    from sqlalchemy.engine import URL
    if args.pg_host not in ("127.0.0.1", "::1", "localhost"):
        raise VerificationError("ONLY_LOOPBACK_POSTGRES_ALLOWED")
    password = args.pg_password_file.read_text().strip() if args.pg_password_file else None
    name = "agvm_v3_verify_" + uuid4().hex
    connection = psycopg2.connect(host=args.pg_host, port=args.pg_port, user=args.pg_user,
                                  password=password, dbname="postgres", connect_timeout=10)
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        cursor.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
    connection.close()
    private_json(data.parent / "created-database.private.json", {"run_id": args.run_id, "created_database": name,
                                                               "host": args.pg_host, "port": args.pg_port, "user": args.pg_user})
    command = [str(args.pg_restore), "--exit-on-error", "--no-owner", "--no-privileges", "--host", args.pg_host,
               "--port", str(args.pg_port), "--username", args.pg_user, "--dbname", name, str(data / "agvpm.dump")]
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    if password is not None:
        environment["PGPASSWORD"] = password
    result = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        private_json(data.parent / "restore-error.private.json", {"returncode": result.returncode,
                     "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(), "stderr_bytes": len(result.stderr)})
        raise VerificationError("RESTORE_FAILED_DIAGNOSTIC_DIGEST_RECORDED")
    return URL.create("postgresql+psycopg2", username=args.pg_user, password=password,
                      host=args.pg_host, port=args.pg_port, database=name).render_as_string(hide_password=False)


def run(args):
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    new_private_directory(args.work_dir)
    args.owns_work_dir = True
    data = args.work_dir / "data"
    data.mkdir(mode=0o700)
    archive_sha = file_sha(args.backup)
    if args.expected_sha256 and archive_sha != args.expected_sha256.lower():
        raise VerificationError("SOURCE_ARCHIVE_SHA_MISMATCH")
    import importlib.util
    runtime_spec = importlib.util.spec_from_file_location("verification_backup_runtime", BACKEND.parent / "docker" / "scripts" / "backup_runtime.py")
    runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime)
    passphrase = args.backup_passphrase_file.read_text().strip() if args.backup_passphrase_file else None
    with runtime.plain_archive(args.backup, passphrase, allow_legacy=True, directory=args.work_dir) as plain:
        manifest = extract_backup(plain, data)
    source_files = files_snapshot(data / "uploads")
    supporting_files = {name: proof for name, proof in files_snapshot(data).items()
                        if not name.startswith("uploads/") and name not in ("agvpm.db", "agvpm.dump", "agvpm.db-wal", "agvpm.db-shm")}
    source_database_sha = file_sha(data / ("agvpm.dump" if manifest.get("database") == "postgres" else "agvpm.db"))
    if manifest.get("database") == "postgres" and (data / "agvpm.dump").is_file():
        url = create_postgres(args, data)
    elif manifest.get("database") == "sqlite" and (data / "agvpm.db").is_file():
        url = "sqlite:///" + str(data / "agvpm.db")
    else:
        raise VerificationError("UNSUPPORTED_BACKUP_DATABASE")
    # Set before importing any live config/ORM. Do not consume a machine-wide
    # app key, scheduler, pending restore, or externally configured service.
    os.environ.update(DATA_DIR=str(data), DATABASE_URL=url, SCHEDULER_ENABLED="0", PUBLIC_MODE="0")
    os.environ.pop("SECRET_KEY", None)
    engine = sa.create_engine(url, echo=False)
    if engine.dialect.name == "sqlite":
        @sa.event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    scripts = ScriptDirectory.from_config(cfg)
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise VerificationError("MIGRATION_REQUIRES_SINGLE_HEAD")
    final_acceptance(args, manifest.get("app_version"), heads[0], False)
    chain = [r.revision for r in reversed(list(scripts.iterate_revisions(heads[0], "base")))]
    applied_chain = [r.revision for r in reversed(list(scripts.iterate_revisions(heads[0], "d2e7f9a103b4")))]
    before = database_snapshot(engine)
    source_user_version = None
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            source_user_version = connection.exec_driver_sql("PRAGMA user_version").scalar()
    if before.get("alembic_version") != [{"version_num": "d2e7f9a103b4"}]:
        raise VerificationError("SOURCE_MUST_BE_UNMIGRATED_V243_SCHEMA_D2")
    old_progress = frozen_progress(before)
    private_json(args.work_dir / "source-before.private.json", {"source_archive_sha256": archive_sha,
                 "source_database_sha256": source_database_sha, "source_head": before.get("alembic_version"),
                 "table_counts": {k: len(v) for k, v in before.items()}, "table_fingerprints": {k: digest(v) for k, v in before.items()},
                 "original_files": source_files, "supporting_files": supporting_files, "progress": old_progress})

    def upgrade(target):
        # No raw SQL exception, row parameters, connection URL or original
        # migration message can reach stdout/stderr.
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            command.upgrade(cfg, target)

    upgrade(T01)
    baseline = database_snapshot(engine)
    t01_changes, t01_failures = t01_dispositions(before, baseline, engine.dialect.name == "sqlite", source_user_version)
    additions, addition_failures = t01_additions(before, baseline)
    t01_failures.extend(addition_failures)
    private_json(args.work_dir / "t01-checkpoint.private.json", {"target": T01, "field_changes": t01_changes,
                 "added_rows": additions, "failures": t01_failures, "table_fingerprints": {k: digest(v) for k, v in baseline.items()}})
    upgrade(heads[0])
    # Match the real startup postcommit seam, without init_db or live seeding.
    # The frozen finalizer first verifies every encrypted export, then removes
    # only exported bytes with no live or immutable archive owner.
    def finalize_retirement():
        from migrations.v3_retirement import finalize_files
        with engine.begin() as connection:
            finalize_files(connection)

    finalize_retirement()
    after = database_snapshot(engine)
    exported, exported_files, export_proof = encrypted_exports(data)
    t34_records, t34_failures, t34_fields = verify_t34(baseline, after, "g3a34b000001" in applied_chain)
    destinations, failures = verify_fields(baseline, after, exported, t34_fields)
    failures.extend(t34_failures)
    weekly, weekly_failures = verify_t40(before, after, "g3a40b000001" in applied_chain)
    failures.extend(weekly_failures)
    failures.extend(t01_failures)
    documents, unclassified, document_failures = document_dispositions(baseline, after)
    failures.extend(document_failures)
    current_files = files_snapshot(data / "uploads")
    for name, proof in supporting_files.items():
        path = data / safe_name(name)
        if not path.is_file() or path.is_symlink() or path.stat().st_size != proof["size"] or file_sha(path) != proof["sha256"]:
            failures.append({"kind": "source_supporting_file_changed", "relative_path": name})
    failures.extend(attachment_integrity(before, after, source_files, current_files))
    original_files = []
    for name, proof in source_files.items():
        destination = "uploads" if current_files.get(name) == proof else "t03_encrypted_owner_export" if exported_files.get(name) == proof else None
        original_files.append({"stored_name": name, **proof, "destination": destination})
        if destination is None:
            failures.append({"kind": "original_file_not_preserved", "stored_name": name})
    from app.db import Base
    from app.services.progress import project_progress_tree
    from sqlalchemy.orm import Session
    with engine.connect() as connection:
        schema_differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        if engine.dialect.name == "sqlite":
            foreign_key_violations = len(connection.exec_driver_sql("PRAGMA foreign_key_check").all())
        else:
            foreign_key_violations = connection.execute(sa.text("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE c.contype='f' AND NOT c.convalidated AND n.nspname='public'")).scalar()
    if schema_differences:
        failures.append({"kind": "schema_drift", "difference_count": len(schema_differences)})
    if foreign_key_violations:
        failures.append({"kind": "invalid_foreign_keys", "violation_count": foreign_key_violations})
    with Session(engine) as session:
        new_progress = {p["id"]: project_progress_tree(session, p["id"]) for p in after["projects"]}
    repeat_before = digest(after), digest(files_snapshot(data))
    upgrade(heads[0])
    finalize_retirement()
    repeated = repeat_before == (digest(database_snapshot(engine)), digest(files_snapshot(data)))
    if not repeated:
        failures.append({"kind": "repeat_upgrade_changed_data_or_files"})
    unchanged_source = file_sha(args.backup) == archive_sha
    if not unchanged_source:
        failures.append({"kind": "source_archive_changed"})
    credits, vehicle_failures = vehicle_dispositions(baseline, after)
    failures.extend(vehicle_failures)
    private = {"format": FORMAT, "run_id": args.run_id, "source_app_version": manifest.get("app_version"),
               "backup_sha256": archive_sha, "source_head": before["alembic_version"], "target_head": heads[0], "chain": chain,
               "source_database_sha256": source_database_sha,
               "applied_chain": applied_chain,
               "counts_before": {k: len(v) for k, v in before.items()}, "counts_t01": {k: len(v) for k, v in baseline.items()},
               "counts_after": {k: len(v) for k, v in after.items()}, "t01_frozen_normalizations": t01_changes,
               "t01_added_rows": additions, "source_sqlite_user_version": source_user_version,
               "table_row_fingerprints_before": {k: digest(v) for k, v in before.items()},
               "table_row_fingerprints_t01": {k: digest(v) for k, v in baseline.items()},
               "table_row_fingerprints_after": {k: digest(v) for k, v in after.items()},
               "frozen_schema_sha256": file_sha(BACKEND / "migrations" / "v243_schema.py"),
               "frozen_data_sha256": file_sha(BACKEND / "migrations" / "v243_data.py"),
               "preserved_transformations": destinations, "original_files": original_files, "retirement_exports": export_proof,
               "document_destinations": documents, "unclassified_files": unclassified, "unknown_vehicle_assignments": credits,
               "work_item_destinations": t34_records, "weekly_plan_destinations": weekly,
               "progress_before": old_progress, "progress_t01": frozen_progress(baseline), "progress_after": new_progress,
               "schema_difference_count": len(schema_differences), "repeat_upgrade_unchanged": repeated,
               "foreign_key_violation_count": foreign_key_violations,
               "source_archive_unchanged": unchanged_source, "failures": failures}
    private_json(args.work_dir / "verification.private.json", private)
    version = str(manifest.get("app_version", ""))
    safe_version = version if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.]+)?", version) and len(version) <= 50 else "unknown_redacted"
    accepted = final_acceptance(args, manifest.get("app_version"), heads[0], not failures)
    public = {"format": FORMAT, "source_app_version": safe_version, "source_archive_sha256": archive_sha,
              "source_head": "d2e7f9a103b4", "target_head": heads[0], "total_chain_count": len(chain),
              "applied_migration_count": len(applied_chain),
              "final_acceptance": accepted, "acceptance_scope": "final_pinned_head_fresh_v243_backup" if args.final_head else "provisional_until_final_migration_chain_and_fresh_backup",
              "checks_passed": not failures, "failure_counts": dict(Counter(f["kind"] for f in failures)),
              "projects": {"before": len(before.get("projects", [])), "after": len(after.get("projects", []))},
              "demo_retirement": {"project_rows_in_verified_encrypted_exports": len(exported.get("projects", [])),
                                  "attachment_rows_in_verified_encrypted_exports": len(exported.get("attachments", [])),
                                  "vehicle_unit_rows_in_verified_encrypted_exports": len(exported.get("vehicle_units", []))},
              "users": {"before": len(before.get("users", [])), "after": len(after.get("users", []))},
              "attachments": {"before": len(before.get("attachments", [])), "after": len(after.get("attachments", []))},
              "vehicles": {"before": len(before.get("vehicle_units", [])), "after": len(after.get("vehicle_units", []))},
              "vehicle_batches": {"before": len(before.get("vehicles", [])), "after": len(after.get("vehicles", []))},
              "documents": {"legacy_sources": len(documents), "instances": len(after.get("project_documents", [])),
                            "definitions": len(after.get("project_document_definitions", [])), "unclassified_files": len(unclassified),
                            "versions": len(after.get("document_versions", [])),
                            "before": {"project_task_deliverables": sum(len(r.get("deliverables") or []) for r in before.get("tasks", []) if r.get("project_id")),
                                       "template_task_deliverables": sum(len(r.get("deliverables") or []) for r in before.get("tasks", []) if not r.get("project_id")),
                                       "archive_checklists": len(before.get("archive_checklists", [])),
                                       "nonprocurement_preparation_items": sum(r["category"] != "procurement" for r in before.get("project_preparation_items", [])),
                                       "template_blank_files": len(before.get("template_docs", []))}},
              "status_before": status_counts(before.get("projects", [])),
              "status_after": status_counts(after.get("projects", [])),
              "original_files": {"total": len(original_files), "preserved": sum(r["destination"] is not None for r in original_files)},
              "original_file_destinations": dict(Counter(r["destination"] or "missing" for r in original_files)),
              "field_transformations_preserved": len(destinations), "t01_normalization_rows": len(t01_changes),
              "source_row_count": sum(len(v) for k, v in before.items() if k != "alembic_version"),
              "source_field_count": sum(len(r) for k, v in before.items() if k != "alembic_version" for r in v),
              "t01_added_rows_by_table": dict(Counter(r["table"] for r in additions)),
              "unknown_vehicle_assignments": {"rows": len(credits), "units": sum(r["unassigned_count"] for r in credits)},
              "weekly_plans": {"source_entries_verified": sum(len(r["original_entry_ids"]) for r in weekly),
                               "cells_verified": len(weekly), "unknown_quantity_sources": sum(r["unknown_quantity_count"] for r in weekly),
                               "published_cells": sum(r["published"] for r in weekly), "cancelled_cells": sum(r["cancelled"] for r in weekly),
                               "intent_review_cells": sum(r["intent_review_required"] for r in weekly)},
              "work_items": {"source_snapshots_verified": len(t34_records), "effective_completion_converted": sum(r["effective_completion_converted"] for r in t34_records)},
              "progress_comparisons": [{"project": i + 1, "before_percent": old_progress.get(p["id"], {}).get("percent"),
                                        "after_percent": new_progress[p["id"]]["percent"],
                                        "after_calculation": new_progress[p["id"]].get("calculation"),
                                        "progress_known": new_progress[p["id"]].get("progress_known")}
                                       for i, p in enumerate(sorted(after.get("projects", []), key=lambda p: p["id"]))],
              "schema_difference_count": len(schema_differences), "repeat_upgrade_unchanged": repeated,
              "foreign_key_violation_count": foreign_key_violations,
              "source_archive_unchanged": unchanged_source}
    private_json(args.work_dir / "summary.sanitized.json", public)
    print(json.dumps(public, indent=2, ensure_ascii=False))
    engine.dispose()
    return 0 if not failures else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--final-head", help="Explicitly approved final Alembic head; must equal dynamically discovered head")
    parser.add_argument("--fresh-backup-attested", action="store_true", help="Operator attests this is the fresh original 2.4.3 backup, not a reconstructed fixture")
    parser.add_argument("--backup-passphrase-file", type=Path, help="Optional private passphrase file for an encrypted backup")
    parser.add_argument("--work-dir", type=Path, required=True, help="New absolute directory outside Git; parent must already exist")
    parser.add_argument("--pg-host", default="127.0.0.1", choices=("127.0.0.1", "::1", "localhost"))
    parser.add_argument("--pg-port", default=5432, type=int)
    parser.add_argument("--pg-user", default=os.environ.get("USER"))
    parser.add_argument("--pg-password-file", type=Path)
    parser.add_argument("--pg-restore", type=Path, default=Path(shutil.which("pg_restore") or "pg_restore"))
    args = parser.parse_args()
    args.run_id = uuid4().hex
    args.owns_work_dir = False
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    try:
        return run(args)
    except BaseException as error:
        code = str(error) if isinstance(error, VerificationError) else "MIGRATION_VERIFICATION_FAILED"
        # Exceptions often embed SQL parameters, URLs and customer data. Only
        # type + fixed code + traceback line locations are recorded.
        diagnostic = {"format": FORMAT, "run_id": args.run_id, "checks_passed": False, "code": code,
                      "exception_type": type(error).__name__}
        if args.owns_work_dir and args.work_dir.is_dir() and not args.work_dir.is_symlink():
            import traceback
            diagnostic["stack"] = [{"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
                                   for f in traceback.extract_tb(error.__traceback__)]
            path = args.work_dir / "failure.private.json"
            if not path.exists():
                private_json(path, diagnostic)
        print(json.dumps({k: v for k, v in diagnostic.items() if k != "stack"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

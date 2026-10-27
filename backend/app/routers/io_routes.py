"""Import/export routes: Excel/JSON for template and project, project clone."""

import json
import math
from copy import deepcopy
import re
import uuid
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import quote
from app.services.system_permissions import route_permission
from app.time_utils import utcnow
from typing import Optional


def _parse_date(v):
    return date.fromisoformat(v) if v else None
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, AwareDatetime, TypeAdapter
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_pm, require_admin
from app.models import User, Project, Vehicle, Phase, Module, Task, CheckItem, VehicleUnit, VehicleLifecycleEvent, ProjectPreparationItem, ArchiveChecklist, Issue, ScheduleEntry, ProjectInventoryItem, ProjectInventoryMovement
from app.routers.projects import get_project_or_404
from app.routers.vehicle_types import normalize_vehicle_type
from app.services.scope import ensure_project_visible
from app.services.permissions import require_project_capability
from app.services import import_export
from app.services.inventory_time import resolve_inventory_time_basis


def _stream_bytes(data: bytes, chunk_size: int = 1024 * 1024):
    """B5/E5：大导出流式返回——按 1MB 分块发送，避免整块驻留内存/响应缓冲。"""
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]
from app.services.change_log import log_change
from app.services.rate_limit import rate_limit_export
from app.config import MAX_UPLOAD_SIZE
from app.services.project_lifecycle import PROJECT_STATUSES, INITIAL_PROJECT_STATUSES

router = APIRouter(tags=["导入导出"])


def _quick_import_template() -> dict:
    """Use the portable Skill template as the single source of truth."""
    from app.services.ai_project_assistant import template_payload
    return template_payload()


def _portable_deliverable(item) -> dict:
    # Historical task requirements may be bare names. They remain required by
    # default, like the ordinary task/delivery paths, but never retain evidence.
    requirement = {"name": item.strip()} if isinstance(item, str) else {
        key: deepcopy(value) for key, value in item.items()
        if key in {"name", "required", "doc_type", "note", "description"}
    }
    return {**requirement, "status": "pending", "done": False, "attachment_id": None}


def _planning_schedule_errors(value, source_tasks: dict) -> list[str]:
    """Quarantine original planning JSON; no source is copied to active policy."""
    if not isinstance(value, dict):
        return ['planning_schedule 历史来源必须是对象']
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        return ['planning_schedule 历史来源包含非法JSON值']
    return []


def _validate_quick_import(payload: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    def nonnegative(value):
        if isinstance(value, bool):
            raise ValueError("布尔值不能用作数量")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError("数量必须是有限非负数")
        return number

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["导入内容必须是 JSON 对象"], "warnings": [], "summary": {}}
    if payload.get("type") != "agvpm-project":
        errors.append("type 必须为 agvpm-project")

    project = payload.get("project") or {}
    if not isinstance(project, dict):
        errors.append("project 必须是对象")
        project = {}
    arrays = ("vehicles", "vehicle_units", "project_events", "modules", "preparations", "inventory_items", "archive_checklist", "schedule", "progress", "issues", "document_definitions", "project_documents", "document_versions")
    normalized: dict[str, list] = {}
    for key in arrays:
        value = payload.get(key, [])
        if not isinstance(value, list):
            errors.append(f"{key} 必须是数组")
            value = []
        normalized[key] = value

    from app.services.vehicle_progress import parse_snapshot as parse_vehicle_snapshot
    try:
        parse_vehicle_snapshot(payload)
    except (ValueError, TypeError, KeyError) as error:
        errors.append('车辆进度校验失败：'+str(error))
    from app.services.project_documents import parse_snapshot
    try:
        parse_snapshot(payload)
    except (ValueError,TypeError) as error:
        errors.append(f"资料定义格式错误：{error}")
    forbidden = [key for key in ("members", "member_permissions", "manager_id", "technical_manager_id", "co_managers") if key in project]
    if forbidden:
        errors.append(f"不得通过导入绑定系统账号：{', '.join(forbidden)}")
    if not str(project.get("name", "")).strip():
        errors.append("project.name 项目名称不能为空")

    def checked_date(value, path: str, required: bool = False):
        if value in (None, ""):
            if required:
                errors.append(f"{path} 必须是 YYYY-MM-DD")
            return None
        try:
            return _parse_date(value)
        except (TypeError, ValueError):
            errors.append(f"{path} 必须是 YYYY-MM-DD")
            return None

    start = checked_date(project.get("start_date"), "project.start_date", True)
    end = checked_date(project.get("end_date"), "project.end_date", True)
    if start and end and end < start:
        errors.append("项目结束日期不能早于开始日期")
    checked_date(project.get("planned_entry_date"), "project.planned_entry_date")
    from app.services.project_events import EVENT_LABELS
    if project.get("dispatch_platform") not in (None, "NDC", "GRACE", "integrated"):
        errors.append("project.dispatch_platform 必须是 NDC/GRACE/integrated 或空")
    seen_event_keys = set()
    for index, event in enumerate(normalized["project_events"]):
        path = f"project_events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{path} 必须是对象")
            continue
        key = event.get("event_key")
        if not isinstance(key, str) or key not in EVENT_LABELS:
            errors.append(f"{path}.event_key 无效")
        elif key in seen_event_keys:
            errors.append(f"{path}.event_key 不能重复")
        else:
            seen_event_keys.add(key)
        checked_date(event.get("planned_date"), path + ".planned_date")
        if event.get("actual_at") is not None:
            try:
                TypeAdapter(AwareDatetime).validate_python(event["actual_at"])
            except ValueError:
                errors.append(f"{path}.actual_at 必须是带时区的实际时间")
        if not isinstance(event.get("note", ""), str) or len(event.get("note", "")) > 2000:
            errors.append(f"{path}.note 必须是2000字以内文本")

    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(project.get("timezone", "Asia/Shanghai"))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        errors.append("project.timezone 必须是有效的 IANA 时区")
    if project.get("rest_mode", "none") not in {"none", "one", "two"}:
        errors.append("project.rest_mode 只能是 none/one/two")
    if project.get("status", "preparing") not in {*PROJECT_STATUSES, "draft", "planning"}:
        errors.append("project.status 枚举值无效")
    elif project.get("status", "preparing") not in {"preparing", "draft", "planning", "ready"}:
        errors.append("新建项目导入不能直接进入实施或后续阶段；请将 project.status 改为 preparing 后导入（旧筹备状态会统一重置为筹备），再由有权限的人按流程确认推进。历史项目恢复请使用完整备份恢复流程。")
    for idx, value in enumerate(project.get("rest_days") or []):
        checked_date(value, f"project.rest_days[{idx}]")

    conditions = project.get("conditions") or {}
    if not isinstance(conditions, dict):
        errors.append("project.conditions 必须是对象")
    else:
        for key in ("need_wms", "need_charging", "client_server", "new_vehicles", "overseas"):
            if key in conditions and not isinstance(conditions[key], bool):
                errors.append(f"project.conditions.{key} 必须是布尔值")

    contacts = project.get("client_contacts") or []
    if not isinstance(contacts, list):
        errors.append("project.client_contacts 必须是数组")
        contacts = []
    if len(contacts) > 100:
        errors.append("甲方联系人不能超过 100 人")
    for idx, item in enumerate(contacts):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            errors.append(f"project.client_contacts[{idx}].name 不能为空")
    if sum(1 for item in contacts if isinstance(item, dict) and item.get("is_primary")) > 1:
        errors.append("甲方主联系人最多 1 人")
    entry = project.get("entry_plan") or {}
    if not isinstance(entry, dict):
        errors.append("project.entry_plan 必须是对象")
    else:
        if entry.get("mode", "") not in {"", "collective", "staggered", "self_arranged", "client_pickup", "resident", "other"}:
            errors.append("project.entry_plan.mode 枚举值无效")
        checked_date(entry.get("entry_date"), "project.entry_plan.entry_date")

    for idx, vehicle in enumerate(normalized["vehicles"]):
        if not isinstance(vehicle, dict) or not str(vehicle.get("vehicle_type", "")).strip():
            errors.append(f"vehicles[{idx}].vehicle_type 不能为空")
        try:
            value = vehicle.get("quantity", 0)
            count = int(value)
            if isinstance(value, bool) or count <= 0 or count != float(value):
                raise ValueError
        except (AttributeError, TypeError, ValueError, OverflowError):
            errors.append(f"vehicles[{idx}].quantity 必须是正整数")
        if isinstance(vehicle, dict) and not isinstance(vehicle.get("configuration") or {}, dict):
            errors.append(f"vehicles[{idx}].configuration 必须是对象")

    vehicle_matrix=payload.get("vehicle_progress_matrix") if isinstance(payload.get("vehicle_progress_matrix"),dict) else {}
    assets: list[str] = []
    event_count = 0
    for unit_idx, unit in enumerate(normalized["vehicle_units"]):
        if not isinstance(unit, dict):
            errors.append(f"vehicle_units[{unit_idx}] 必须是对象")
            continue
        asset = str(unit.get("asset_code", "")).strip()
        assets.append(asset)
        if not asset:
            errors.append("每台现场车辆都必须填写 asset_code")
        if unit.get("current_stage", "planned") not in {step.get("key") for step in vehicle_matrix.get("steps",[]) if isinstance(step,dict)} | {"planned", "production", "factory_test", "shipping", "on_site", "commissioning", "running", "maintenance", "retired"}:
            errors.append(f"vehicle_units[{unit_idx}].current_stage 枚举值无效")
        if unit.get("current_status", "normal") not in {"normal", "attention", "fault", "stopped", "retired"}:
            errors.append(f"vehicle_units[{unit_idx}].current_status 枚举值无效")
        checked_date(unit.get("warranty_end"), f"vehicle_units[{unit_idx}].warranty_end")
        checked_date(unit.get("commissioned_at"), f"vehicle_units[{unit_idx}].commissioned_at")
        checked_date(unit.get("arrived_at"), f"vehicle_units[{unit_idx}].arrived_at")
        events = unit.get("events") or []
        if not isinstance(events, list):
            errors.append(f"vehicle_units[{unit_idx}].events 必须是数组")
            events = []
        for event_idx, event in enumerate(events):
            event_count += 1
            path = f"vehicle_units[{unit_idx}].events[{event_idx}]"
            if not isinstance(event, dict) or not str(event.get("title", "")).strip():
                errors.append(f"{path}.title 不能为空")
                continue
            checked_date(event.get("event_date"), f"{path}.event_date", True)
            if event.get("event_type", "other") not in {"created", "production", "test", "shipment", "arrival", "commission", "handover", "maintenance", "repair", "inspection", "fault", "retire", "other"}:
                errors.append(f"{path}.event_type 枚举值无效")
            if event.get("is_closed") and not (event.get("action_taken") or event.get("verification")):
                warnings.append(f"车辆 {asset} 的已解决事件未写处理或验证结论")
    if len(set(assets)) != len(assets):
        errors.append("vehicle_units 中的 asset_code 不能重复")

    task_names: list[str] = []
    task_sources: dict[str, list[str]] = {}
    source_ids: set[str] = set()
    for mod_idx, module in enumerate(normalized["modules"]):
        if not isinstance(module, dict) or not str(module.get("name", "")).strip():
            errors.append(f"modules[{mod_idx}].name 不能为空")
            continue
        if module.get("phase_name") == "项目准备":
            errors.append(f"modules[{mod_idx}] 不得使用「项目准备」阶段，请改写到 preparations")
        tasks = module.get("tasks") or []
        if not isinstance(tasks, list):
            errors.append(f"modules[{mod_idx}].tasks 必须是数组")
            continue
        for task_idx, task in enumerate(tasks):
            if not isinstance(task, dict):
                errors.append(f"modules[{mod_idx}].tasks[{task_idx}] 必须是对象")
                continue
            name = str(task.get("name", "")).strip()
            path = f"modules[{mod_idx}].tasks[{task_idx}]"
            if not name:
                errors.append(f"{path}.name 不能为空")
            else:
                task_names.append(name)
            source_id = task.get("source_id")
            if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
                errors.append(f"{path}.source_id 必须是非空字符串")
                source_id = None
            if source_id:
                if source_id in source_ids:
                    errors.append(f"任务 source_id 不能重复：{source_id}")
                source_ids.add(source_id)
            task_sources.setdefault(name, []).append(source_id or "")
            qtype = task.get("quantity_type", "manual")
            if qtype not in {"per_vehicle", "manual", "fixed"}:
                errors.append(f"{path}.quantity_type 只能是 per_vehicle/manual/fixed")
            if qtype != "per_vehicle" and task.get("target_quantity") in (None, ""):
                warnings.append(f"任务「{name}」未填目标数量，将按 1 处理")
            for field in ("target_quantity", "standard_hours"):
                if task.get(field) not in (None, ""):
                    try:
                        nonnegative(task[field])
                    except (TypeError, ValueError):
                        errors.append(f"{path}.{field} 必须是非负数")
            for field in ("depends_on", "applicable_vehicle_types"):
                values = task.get(field, [])
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                    errors.append(f"{path}.{field} 必须是字符串数组")
            deliveries = task.get("deliverables") or []
            if not isinstance(deliveries, list):
                errors.append(f"{path}.deliverables 必须是数组")
            elif any(not ((isinstance(item, str) and item.strip()) or (
                    isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()))
                    for item in deliveries):
                errors.append(f"{path}.deliverables 每项必须包含有效名称")
            elif any(isinstance(item, dict) and any(key in item for key in (
                    "attachment_id", "submitted_by", "reviewed_by", "done", "status")) for item in deliveries):
                warnings.append(f"任务「{name}」的附件、提交和审核记录不属于新项目；交付项将重置为待提交，需重新上传与审核")
            checks = task.get("check_items") or []
            if not isinstance(checks, list):
                errors.append(f"{path}.check_items 必须是数组")
            else:
                for check_idx, check in enumerate(checks):
                    if not isinstance(check, dict) or not str(check.get("name", "")).strip():
                        errors.append(f"{path}.check_items[{check_idx}].name 不能为空")

    dependency_graph = {}
    for module in normalized["modules"]:
        if not isinstance(module, dict) or not isinstance(module.get("tasks", []), list):
            continue
        for task in module.get("tasks", []):
            if not isinstance(task, dict):
                continue
            dependencies = task.get("depends_on", [])
            if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
                continue
            if any(dep not in source_ids for dep in dependencies):
                errors.append(f"任务「{task.get('name', '')}」依赖未在导入任务中找到")
            source_id = task.get("source_id")
            if dependencies and not source_id:
                errors.append(f"任务「{task.get('name', '')}」含依赖时必须提供 source_id")
            if isinstance(source_id, str):
                dependency_graph[source_id] = dependencies
    # Iterative traversal avoids recursion failures for large portable plans.
    remaining = {source: set(deps) & dependency_graph.keys() for source, deps in dependency_graph.items()}
    while remaining:
        ready = {source for source, deps in remaining.items() if not deps}
        if not ready:
            errors.append("任务依赖不能循环")
            break
        remaining = {source: deps - ready for source, deps in remaining.items() if source not in ready}

    for name, sources in task_sources.items():
        if len(sources) > 1 and not all(sources):
            errors.append(f"同名任务「{name}」缺少 source_id，无法区分；请重新导出备份或为任务提供唯一 source_id")

    def validate_task_reference(item: dict, label: str):
        source_id = item.get("task_source_id")
        if "task_source_id" in item:
            if not isinstance(source_id, str) or source_id not in source_ids:
                errors.append(f"{label} task_source_id 未在导入任务中找到")
        elif len(task_sources.get(item.get("task_name", ""), [])) > 1:
            errors.append(f"{label}任务「{item.get('task_name', '')}」有重名，必须提供 task_source_id")
        elif item.get("task_name") not in task_names:
            warnings.append(f"{label}任务「{item.get('task_name', '')}」未在导入任务中找到，将跳过")

    for idx, item in enumerate(normalized["preparations"]):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            errors.append(f"preparations[{idx}].name 不能为空")
            continue
        if item.get("category", "scope") not in {"scope", "procurement", "vehicle", "software", "site"}:
            errors.append(f"preparations[{idx}].category 枚举值无效")
        if item.get("status", "not_started") not in {"not_started", "in_progress", "pending", "passed", "failed", "na"}:
            errors.append(f"preparations[{idx}].status 枚举值无效")
        if item.get("owner_party", "project") not in {"project", "client", "procurement", "production", "software", "company"}:
            errors.append(f"preparations[{idx}].owner_party 枚举值无效")
        if item.get("risk", "low") not in {"low", "medium", "high"}:
            errors.append(f"preparations[{idx}].risk 枚举值无效")
        for field in ("required_date", "committed_date", "forecast_date", "actual_date"):
            checked_date(item.get(field), f"preparations[{idx}].{field}")
        if item.get("category") == "procurement":
            extra = item.get("extra") or {}
            if not isinstance(extra, dict):
                errors.append(f"preparations[{idx}].extra 必须是对象")
            elif not extra.get("quantity") or not extra.get("unit"):
                warnings.append(f"采购项「{item.get('name', '')}」未填数量或单位")

    for idx, item in enumerate(normalized["archive_checklist"]):
        if not isinstance(item, dict) or not str(item.get("item_name", "")).strip():
            errors.append(f"archive_checklist[{idx}].item_name 不能为空")
    inventory_categories = {"equipment", "tool", "spare_part", "material", "consumable", "document", "other"}
    inventory_statuses = {"expected", "in_transit", "on_site", "in_use", "loaned", "consumed", "returned", "lost", "damaged", "scrapped"}
    inventory_movements = {"receive", "issue", "transfer", "consume", "return_owner", "return_site", "adjust", "inventory"}
    if len(normalized["inventory_items"]) > 500:
        errors.append("inventory_items 一次最多导入 500 条")
    for idx, item in enumerate(normalized["inventory_items"]):
        path = f"inventory_items[{idx}]"
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            errors.append(f"{path}.name 不能为空")
            continue
        if item.get("ownership", "company") not in {"company", "client", "third_party"}:
            errors.append(f"{path}.ownership 无效")
        if item.get("category", "other") not in inventory_categories:
            errors.append(f"{path}.category 无效")
        if item.get("tracking_mode", "quantity") not in {"quantity", "serial"}:
            errors.append(f"{path}.tracking_mode 无效")
        if item.get("status", "on_site") not in inventory_statuses:
            errors.append(f"{path}.status 无效")
        try:
            quantity = nonnegative(item.get("quantity", 0) or 0)
            if item.get("tracking_mode") == "serial" and quantity not in (0, 1):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{path}.quantity 无效")
        minimum = item.get("minimum_quantity")
        if minimum not in (None, ""):
            try:
                nonnegative(minimum)
            except (TypeError, ValueError):
                errors.append(f"{path}.minimum_quantity 必须是非负数")
        checked_date(item.get("received_date"), f"{path}.received_date")
        checked_date(item.get("expected_return_date"), f"{path}.expected_return_date")
        movements = item.get("movements") or []
        if not isinstance(movements, list):
            errors.append(f"{path}.movements 必须是数组")
            continue
        if len(movements) > 10000:
            errors.append(f"{path}.movements 最多 10000 条")
        for movement_idx, movement in enumerate(movements):
            movement_path = f"{path}.movements[{movement_idx}]"
            if not isinstance(movement, dict):
                errors.append(f"{movement_path} 必须是对象")
                continue
            if movement.get("movement_type", "inventory") not in inventory_movements:
                errors.append(f"{movement_path}.movement_type 无效")
            for field in ("quantity", "balance_after"):
                try:
                    nonnegative(movement.get(field, 0) or 0)
                except (TypeError, ValueError):
                    errors.append(f"{movement_path}.{field} 必须是非负数")
            if movement.get("time_basis") not in (None, "utc", "legacy_local"):
                errors.append(f"{movement_path}.time_basis 无效")
            occurred_at = movement.get("occurred_at")
            if occurred_at:
                try:
                    datetime.fromisoformat(occurred_at)
                except (TypeError, ValueError):
                    errors.append(f"{movement_path}.occurred_at 必须是 ISO 日期时间")
    for item in normalized["schedule"]:
        if not isinstance(item, dict):
            errors.append("schedule 中每项必须是对象")
            continue
        validate_task_reference(item, "排程")
        if item.get("status", "planned") not in {"planned", "done", "skipped"}:
            errors.append(f"排程「{item.get('task_name', '')}」.status 枚举值无效")
        try:
            nonnegative(item.get("planned_quantity", 0) or 0)
        except (TypeError, ValueError):
            errors.append(f"排程「{item.get('task_name', '')}」.planned_quantity 必须是非负数")
        work = checked_date(item.get("work_date"), f"排程「{item.get('task_name', '')}」.work_date", True)
        if work and start and end and not start <= work <= end:
            warnings.append(f"排程「{item.get('task_name', '')}」日期不在项目周期内")
    for item in normalized["progress"]:
        if not isinstance(item, dict):
            errors.append("progress 中每项必须是对象")
            continue
        validate_task_reference(item, "进度")
        checked_date(item.get("work_date"), f"进度「{item.get('task_name', '')}」.work_date", True)
        try:
            nonnegative(item.get("completed_quantity", 0) or 0)
        except (TypeError, ValueError):
            errors.append(f"进度「{item.get('task_name', '')}」.completed_quantity 必须是非负数")
    for idx, item in enumerate(normalized["issues"]):
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            errors.append(f"issues[{idx}].title 不能为空")
            continue
        if item.get("issue_type", "other") not in {"hardware", "software", "environment", "process", "safety", "other"}:
            errors.append(f"issues[{idx}].issue_type 枚举值无效")
        if item.get("severity", "medium") not in {"critical", "high", "medium", "low"}:
            errors.append(f"issues[{idx}].severity 枚举值无效")
        if item.get("status", "open") not in {"open", "processing", "resolved", "closed", "cancelled"}:
            errors.append(f"issues[{idx}].status 枚举值无效")
        if not isinstance(item.get("extra") or {}, dict):
            errors.append(f"issues[{idx}].extra 必须是对象")
        if item.get("status") in {"resolved", "closed"} and not str(item.get("resolution", "")).strip():
            warnings.append(f"已解决问题「{item.get('title', '')}」未写解决方案")

    if "planning_schedule" in payload:
        source_tasks = {}
        for module in normalized["modules"]:
            if not isinstance(module, dict) or not isinstance(module.get("tasks", []), list):
                continue
            for task in module.get("tasks", []):
                if isinstance(task, dict) and isinstance(task.get("source_id"), str):
                    source_tasks[task["source_id"]] = task
        errors.extend(_planning_schedule_errors(payload["planning_schedule"], source_tasks))
    return {
        "valid": not errors, "errors": errors, "warnings": warnings,
        "summary": {
            "project": project.get("name", ""), "contacts": len(contacts),
            "vehicle_types": len(normalized["vehicles"]), "vehicle_units": len(normalized["vehicle_units"]),
            "vehicle_issues": event_count, "modules": len(normalized["modules"]), "tasks": len(task_names),
            "document_definitions": len(normalized["document_definitions"]),
            "project_documents": len(normalized["project_documents"]),
            "legacy_document_requirements": sum(len(task.get("deliverables") or []) for module in normalized["modules"] if isinstance(module,dict) for task in module.get("tasks",[]) if isinstance(task,dict)) + len(normalized["archive_checklist"]) + sum(1 for item in normalized["preparations"] if isinstance(item,dict) and item.get("category")!="procurement"),
            "procurements": sum(1 for item in normalized["preparations"] if isinstance(item, dict) and item.get("category") == "procurement"),
            "inventory_items": len(normalized["inventory_items"]),
            "archive": len(normalized["archive_checklist"]), "schedule": len(normalized["schedule"]),
            "progress": len(normalized["progress"]), "issues": len(normalized["issues"]),
        },
    }


@router.get("/projects/import/template")
@route_permission('system.import.create')
def download_quick_import_template(_: User = Depends(require_pm)):
    return Response(
        content=json.dumps(_quick_import_template(), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''AGV-AI-project-import-template.json"},
    )


@router.post("/projects/import/preview")
@route_permission('system.import.create')
def preview_quick_import(payload: dict, _: User = Depends(require_pm)):
    try:
        return _validate_quick_import(payload)
    except (TypeError, ValueError) as error:
        return {"valid": False, "errors": [f"日期或字段格式错误：{error}"], "warnings": [], "summary": {}}


# ===== Template export =====

@router.get("/templates/export/excel")
@route_permission('system.templates.read')
def export_template_excel(template_id: str = "default", db: Session = Depends(get_db), _: User = Depends(rate_limit_export())):
    try:
        data = import_export.template_to_excel(db, template_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    # B5/E5：流式返回，避免大文件整块驻留响应缓冲；导出接口按用户限流
    return StreamingResponse(
        _stream_bytes(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''AGV%E5%AE%9E%E6%96%BD%E6%A8%A1%E6%9D%BF.xlsx"},
    )


@router.post("/templates/import/excel")
@route_permission('system.template_io.manage')
def import_template_excel(
    file: UploadFile = File(...),
    template_id: str = "default",
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    data = file.file.read(MAX_UPLOAD_SIZE + 1)
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"文件超过大小限制（{MAX_UPLOAD_SIZE // 1024 // 1024}MB）")
    try:
        result = import_export.template_from_excel(db, data, template_id, actor_id=user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{str(e)[:200]}")
    log_change(db, None, "template", template_id, "import", user.id,
               f"导入模板 Excel：{result['tasks']} 任务")
    db.commit()
    return result


# ===== Project export =====

def _safe_export_name(name: str) -> str:
    """安全化项目名：非法文件名字符替换为下划线，去掉首尾空白/点，限长 80，空则回退「项目」。"""
    s = re.sub(r"[\\/:*?\"<>|]", "_", name or "").strip().strip(".").strip()
    if not s:
        s = "项目"
    return s[:80]


def _export_content_disposition(project_name: str, ext: str) -> str:
    """项目导出文件名：安全化项目名_YYYY-MM-DD.ext。

    Content-Disposition 用 RFC 5987 filename*（UTF-8 编码，中文不乱码），
    同时带 ASCII fallback filename（不支持 filename* 的旧客户端也能拿到正确扩展名）。
    """
    fname = f"{_safe_export_name(project_name)}_{date.today().isoformat()}.{ext}"
    ascii_fallback = f"project-export-{date.today().isoformat()}.{ext}"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(fname)}"


@router.get("/projects/{project_id}/export/excel")
@route_permission('project.export')
def export_project_excel(project_id: str, p: Project = Depends(require_project_capability("project.export")), db: Session = Depends(get_db), user: User = Depends(rate_limit_export())):
    data = import_export.project_to_excel(db, project_id, actor=user)
    # B5/E5：流式返回 + 导出限流
    return StreamingResponse(
        _stream_bytes(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _export_content_disposition(p.name, "xlsx"),"Cache-Control":"private, no-store"},
    )


@router.get("/projects/{project_id}/export/json")
@route_permission('project.export')
def export_project_json(project_id: str, p: Project = Depends(require_project_capability("project.export")), db: Session = Depends(get_db), user: User = Depends(rate_limit_export())):
    snapshot = import_export.project_to_json(db, project_id, actor=user)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    # B5/E5：流式返回 + 导出限流
    return StreamingResponse(
        _stream_bytes(payload),
        media_type="application/json",
        headers={"Content-Disposition": _export_content_disposition(p.name, "json"),"Cache-Control":"private, no-store"},
    )


@router.get("/projects/{project_id}/export/package")
@route_permission('project.export')
def export_project_package(project_id: str, p: Project = Depends(require_project_capability("project.export")), db: Session = Depends(get_db), user: User = Depends(rate_limit_export())):
    """HYPE-58：项目整包导出 ZIP（项目数据.xlsx + 项目备份.json + files/ + manifest.json）。"""
    data = import_export.project_package_stream(db, project_id, actor=user)
    from app.services.document_packages import chunks
    return StreamingResponse(
        chunks(data),
        media_type="application/zip",
        headers={"Content-Disposition": _export_content_disposition(p.name, "zip"),'Cache-Control':'private, no-store'},
    )


@router.post("/projects/import/json")
@route_permission('system.import.create')
def import_project_json(
    payload: dict,
    user: User = Depends(require_pm),
    db: Session = Depends(get_db),
):
    """Create a new project from a JSON snapshot."""
    try:
        validation = _validate_quick_import(payload)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"日期或字段格式错误：{error}")
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail="；".join(validation["errors"]))
    proj = payload.get("project", {})
    p = Project(
        name=proj.get("name", "导入项目"),
        abbreviation=proj.get("abbreviation", ""),
        manager=user.id,
        client=proj.get("client", ""),
        location=proj.get("location", ""),
        timezone=proj.get("timezone", "Asia/Shanghai"),
        start_date=_parse_date(proj.get("start_date")),
        end_date=_parse_date(proj.get("end_date")),
        description=proj.get("description", ""),
        staffing_notes=proj.get("staffing_notes", ""),
        # New-project import accepts only validated initial states; it cannot
        # confer execution/acceptance authority. Full backup restore is separate.
        status="preparing",
        suspension=proj.get("suspension") or {},  # 突发停工上下文（旧备份无该字段 → 空 {}）
        rest_mode=proj.get("rest_mode", "none"),
        rest_days=proj.get("rest_days", []),
        skip_holidays=bool(proj.get("skip_holidays", False)),
        planned_entry_date=_parse_date(proj.get("planned_entry_date")),
        dispatch_platform=proj.get("dispatch_platform"),
        client_contacts=proj.get("client_contacts", []),
        entry_plan=proj.get("entry_plan", {}),
        created_by=user.id,
    )
    conditions = proj.get("conditions") or {}
    p.prep_conditions = [key for key in ("need_wms", "need_charging", "client_server", "new_vehicles", "overseas") if conditions.get(key)]
    db.add(p)
    db.flush()
    from app.routers.projects import _sync_project_members
    _sync_project_members(db, p)
    from app.models import ProjectEvent
    from app.services.project_events import normalize_actual, planned_event_date, sync_arrival_all, update_plans
    declared_arrival = None
    if "project_events" in payload:
        for data in payload["project_events"]:
            actual = (normalize_actual(TypeAdapter(AwareDatetime).validate_python(data["actual_at"]))
                      if data.get("actual_at") is not None else None)
            if data["event_key"] == "arrival_all":
                declared_arrival = actual
                actual = None  # Always recompute from the full imported fleet below.
            db.add(ProjectEvent(project_id=p.id, event_key=data["event_key"],
                planned_date=_parse_date(data.get("planned_date")), actual_at=actual,
                recorded_by=user.id if actual else None, note=data.get("note", "")))
    else:
        # Old portable snapshots have the same date meaning as the Alembic migration.
        update_plans(db, p, {"ship": p.planned_entry_date,
            "arrival_all": _parse_date((p.entry_plan or {}).get("entry_date"))}, user.id)
    db.flush()

    # Vehicles
    vehicle_lookup = {}
    for v in payload.get("vehicles", []):
        vehicle = Vehicle(
            project_id=p.id, vehicle_type=normalize_vehicle_type(v.get("vehicle_type", "自定义")),
            model_name=v.get("model_name", ""), quantity=int(v.get("quantity", 1)),
            configuration=v.get("configuration") or {}, notes=v.get("notes", ""),
            sort_order=v.get("sort_order", 0),
        )
        db.add(vehicle)
        db.flush()
        vehicle_lookup[(vehicle.vehicle_type, vehicle.model_name)] = vehicle.id

    task_by_source = {}
    explicit_per_vehicle_targets = []
    # Import the supplied task tree exactly. Name-based template matching used
    # to discard AI-edited descriptions, checks and deliverables.
    for module_index, m in enumerate(payload.get("modules", [])):
        phase_name = m.get("phase_name", "自定义")
        pphase = db.query(Phase).filter(Phase.project_id == p.id, Phase.name == phase_name).first()
        if pphase is None:
            pphase = Phase(project_id=p.id, name=phase_name, sort_order=m.get("phase_sort_order", module_index),
                           color=m.get("phase_color", "#1890ff"), entry_criteria=m.get("phase_entry_criteria", ""),
                           exit_criteria=m.get("phase_exit_criteria", ""))
            db.add(pphase)
            db.flush()
        for task_index, t in enumerate(m.get("tasks", [])):
            description = t.get("description", "")
            if t.get("acceptance_criteria"):
                description = f"{description}\n\n验收标准：{t['acceptance_criteria']}".strip()
            target = t.get("target_quantity")
            if t.get("quantity_type", "manual") != "per_vehicle" and target in (None, ""):
                target = 1
            task = Task(
                project_id=p.id, module_id=None, phase_id=pphase.id, name=t.get("name", "任务"), description=description,
                group_label=t.get("group_label",m.get("source_group_label",m.get("name",""))), scope_conditions=t.get("scope_conditions",m.get("preparation_conditions",[])),
                source_task_id=t.get("source_task_id"),
                legacy_work_snapshot={"kind":"portable_unverified_work_source","source_task_id":t.get("source_id"),"original":t.get("legacy_work_snapshot"),
                    "quantity":{"type":t.get("quantity_type"),"target":target,"unit":t.get("unit")},"source_group_label":m.get("name","")},
                quantity_type="per_vehicle" if t.get("kind", "vehicle" if t.get("quantity_type")=="per_vehicle" else "other")=="vehicle" else "fixed", target_quantity=None,
                vehicle_step_key=t.get("vehicle_step_key") or None,
                unit="台" if t.get("kind", "vehicle" if t.get("quantity_type")=="per_vehicle" else "other")=="vehicle" else "项", standard_hours=None,
                safety_flag=bool(t.get("safety_flag", False)), sort_order=t.get("sort_order", task_index),
                deliverables=[],
                applicable_vehicle_types=t.get("applicable_vehicle_types") or [],
            )
            db.add(task)
            db.flush()
            if t.get("source_id"):
                task_by_source[t["source_id"]] = task
            if task.quantity_type == "per_vehicle" and target not in (None, ""):
                explicit_per_vehicle_targets.append((task, float(target)))
            if task.quantity_type == 'per_vehicle':
                from app.services.vehicle_checks import import_definitions
                import_definitions(db,task,t.get('check_items',[]))
            else:
                for check_index, ci in enumerate(t.get("check_items", [])):
                    check_description = "\n".join(filter(None, [
                        ci.get("description", ""),
                        f"验收标准：{ci.get('acceptance_standard')}" if ci.get("acceptance_standard") else "",
                        f"证据要求：{ci.get('evidence_required')}" if ci.get("evidence_required") else "",
                    ]))
                    db.add(CheckItem(
                        project_id=p.id, task_id=task.id, name=ci.get("name", "检查项"),
                        description=check_description, is_required=ci.get("is_required", True),
                        is_safety_critical=ci.get("is_safety_critical", False), sort_order=check_index,
                    ))

    for module in payload.get("modules", []):
        for task_data in module.get("tasks", []):
            if task_data.get("source_id"):
                task_by_source[task_data["source_id"]].depends_on = [
                    task_by_source[source_id].id for source_id in task_data.get("depends_on", [])]

    from app.services.generate_tasks import recompute_per_vehicle_targets
    recompute_per_vehicle_targets(db, p.id)
    # Portable definitions may contain an explicit per-vehicle quantity override.
    # Only absent quantities are inferred; exporting/importing is not a fleet edit.
    # Original quantities remain in each read-only source snapshot; never become active targets.


    # Portable operational records. Binary attachments are intentionally restored only by system backup.
    imported_unit_map = {}
    for unit_data in payload.get("vehicle_units", []):
        linked_vehicle_id = vehicle_lookup.get((unit_data.get("vehicle_type", ""), unit_data.get("model_name", "")))
        unit = VehicleUnit(project_id=p.id, vehicle_id=linked_vehicle_id, asset_code=unit_data.get("asset_code", "AGV"),
                           serial_number=unit_data.get("serial_number", ""), fleet_no=unit_data.get("fleet_no", ""),
                           current_stage="planned",
                           legacy_current_stage=unit_data.get("legacy_current_stage") or (unit_data.get("current_stage") if not payload.get("vehicle_progress_matrix") else None),
                           current_status=unit_data.get("current_status", "normal"), location=unit_data.get("location", ""),
                           warranty_end=_parse_date(unit_data.get("warranty_end")), commissioned_at=_parse_date(unit_data.get("commissioned_at")),
                           arrived_at=_parse_date(unit_data.get("arrived_at")),
                           note=unit_data.get("note", ""))
        db.add(unit); db.flush()
        imported_unit_map[unit_data.get("source_id")] = unit
        for event in unit_data.get("events", []):
            db.add(VehicleLifecycleEvent(vehicle_unit_id=unit.id, project_id=p.id,
                event_type=event.get("event_type", "other"), event_date=_parse_date(event.get("event_date")) or date.today(),
                title=event.get("title", "导入事件"), description=event.get("description", ""),
                stage_after=event.get("stage_after", ""), status_after=event.get("status_after", ""),
                location_after=event.get("location_after", ""), fault_part=event.get("fault_part", ""),
                cause=event.get("cause", ""), action_taken=event.get("action_taken", ""),
                replaced_parts=event.get("replaced_parts", []), downtime_hours=event.get("downtime_hours"),
                verification=event.get("verification", ""), handler=event.get("handler", ""),
                is_closed=bool(event.get("is_closed", False)), operator_id=user.id))
    sync_arrival_all(db, p, user.id, "从导入车辆资料重新汇总")
    if declared_arrival is not None:
        derived = db.query(ProjectEvent).filter_by(project_id=p.id, event_key="arrival_all").one_or_none()
        if derived is None or derived.actual_at != declared_arrival:
            raise HTTPException(400, "全部到场实际日期与完整逐台车辆记录不一致，导入未保存")
    if payload.get("preparations"):
        for item in payload["preparations"]:
            if item.get("category")!="procurement":
                continue
            db.add(ProjectPreparationItem(project_id=p.id, category=item.get("category", "scope"), name=item.get("name", "准备事项"),
                is_required=bool(item.get("is_required", True)), blocks_entry=bool(item.get("blocks_entry", False)), status=item.get("status", "not_started"),
                owner_party=item.get("owner_party", "project"), required_date=_parse_date(item.get("required_date")), committed_date=_parse_date(item.get("committed_date")),
                forecast_date=_parse_date(item.get("forecast_date")), actual_date=_parse_date(item.get("actual_date")), risk=item.get("risk", "low"),
                note=item.get("note", ""), extra=item.get("extra", {}), sort_order=item.get("sort_order", 0)))
    else:
        from app.routers.preparations import seed_default_preparations
        seed_default_preparations(db, p.id, conditions, planned_event_date(db, p.id))
    for item in payload.get("issues", []):
        db.add(Issue(project_id=p.id, title=item.get("title", "导入问题"), description=item.get("description", ""),
                     issue_type=item.get("issue_type", "other"), severity=item.get("severity", "medium"),
                     nature='normal',source_metadata={'kind':'portable_unverified_issue','original_id':item.get('source_id'),
                         'original_nature':item.get('nature'),'original_created_at':item.get('created_at'),'original_source_metadata':item.get('source_metadata')},
                     status=item.get("status", "open"), reporter_id=user.id, resolution=item.get("resolution", ""), extra=item.get("extra", {})))
    for item_data in payload.get("inventory_items", []):
        item = ProjectInventoryItem(
            project_id=p.id, item_code=item_data.get("item_code", ""), name=item_data.get("name", "物品"),
            category=item_data.get("category", "other"), ownership=item_data.get("ownership", "company"),
            tracking_mode=item_data.get("tracking_mode", "quantity"), specification=item_data.get("specification", ""),
            serial_number=item_data.get("serial_number", ""), quantity=float(item_data.get("quantity", 0) or 0),
            minimum_quantity=float(item_data["minimum_quantity"]) if item_data.get("minimum_quantity") not in (None, "") else None,
            unit=item_data.get("unit", "件"),
            status=item_data.get("status", "on_site"), location=item_data.get("location", ""),
            custodian=item_data.get("custodian", ""), supplier=item_data.get("supplier", ""),
            received_date=_parse_date(item_data.get("received_date")),
            expected_return_date=_parse_date(item_data.get("expected_return_date")),
            note=item_data.get("note", ""), extra=item_data.get("extra") or {}, created_by=user.id,
        )
        db.add(item); db.flush()
        movements = item_data.get("movements") or []
        if movements:
            for movement in movements:
                occurred_at = datetime.fromisoformat(movement["occurred_at"]) if movement.get("occurred_at") else utcnow()
                time_basis = resolve_inventory_time_basis(movement.get("time_basis"),
                    movement.get("movement_type", "inventory"), movement.get("note", ""))
                if occurred_at.tzinfo:
                    occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
                    time_basis = "utc"
                elif not movement.get("occurred_at"):
                    time_basis = "utc"
                db.add(ProjectInventoryMovement(
                    project_id=p.id, item_id=item.id, movement_type=movement.get("movement_type", "inventory"),
                    quantity=float(movement.get("quantity", 0) or 0), balance_after=float(movement.get("balance_after", item.quantity) or 0),
                    from_location=movement.get("from_location", ""), to_location=movement.get("to_location", ""),
                    handler=movement.get("handler", ""), occurred_at=occurred_at,
                    time_basis=time_basis,
                    note=movement.get("note", ""), operator_id=user.id,
                ))
        elif item.quantity:
            db.add(ProjectInventoryMovement(project_id=p.id, item_id=item.id, movement_type="inventory",
                quantity=item.quantity, balance_after=item.quantity, to_location=item.location,
                handler=item.custodian, note="导入项目时的初始数量", operator_id=user.id))

    db.flush()
    # Original daily plans are quarantined below with their exact source values.
    # They are never recreated as active day assignments or implicitly published.
    # Original quantity reports remain in the immutable portable source below.
    # Importing another project's execution must not complete this new scope.

    db.flush()
    from app.services.project_documents import parse_snapshot,import_snapshot,import_legacy_requirements,initialize
    from app.services.vehicle_progress import parse_snapshot as parse_vehicle_snapshot, import_snapshot as import_vehicle_snapshot
    import_vehicle_snapshot(db,p,parse_vehicle_snapshot(payload),task_by_source,imported_unit_map,planning_only=True)
    from app.services.vehicle_progress import retain_portable_source
    retain_portable_source(p,payload)
    from app.services.vehicle_checks import validate_step,generate_for_units
    for work in db.query(Task).filter_by(project_id=p.id):
        work.vehicle_step_key=validate_step(db,work,work.vehicle_step_key)
    generate_for_units(db,p.id,list(imported_unit_map.values()))
    parsed_documents=parse_snapshot(payload)
    if not import_snapshot(db,p,parsed_documents,user):
        if not import_legacy_requirements(db,p,payload,user):initialize(db,p)
    log_change(db, p.id, "project", p.id, "import", user.id, f"从快捷导入创建项目「{p.name}」")
    db.commit()
    return {"message": f"项目「{p.name}」已创建，请确认人员与排程", "id": p.id, "warnings": validation["warnings"]}


class CloneBody(BaseModel):
    name: Optional[str] = None
    client: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@router.post("/projects/{project_id}/clone")
@route_permission('projects.create', 'project.read')
def clone_project(
    project_id: str,
    body: CloneBody,
    user: User = Depends(require_pm),
    db: Session = Depends(get_db),
):
    """Clone a project: new dates + same vehicles, modules, tasks (fresh quantities)."""
    src = ensure_project_visible(db, project_id, user)
    from app.services.permissions import authorize_project, C_UPDATE
    from app.services.record_lock import lock_record
    lock_record(db, src, conflict_detail="源项目计划正被修改，请稍后重试克隆")
    db.refresh(user)
    if not user.is_active:raise HTTPException(401,"账号已停用，请重新登录")
    src=ensure_project_visible(db,project_id,user)
    authorize_project(user, src, C_UPDATE)
    snapshot = import_export.project_to_json(db, project_id, actor=user,include_documents=False)
    # Validate portable intent before creating rows or copying physical files.
    # A transaction rollback cannot remove an already-copied reference file.
    if "planning_schedule" in snapshot:
        source_tasks = {
            task["source_id"]: task
            for module in snapshot.get("modules", [])
            for task in module.get("tasks", [])
        }
        planning_errors = _planning_schedule_errors(snapshot["planning_schedule"], source_tasks)
        if planning_errors:
            raise HTTPException(status_code=400, detail="克隆计划偏好校验失败：" + "；".join(planning_errors))
    if body.name:
        snapshot["project"]["name"] = body.name
    if body.client:
        snapshot["project"]["client"] = body.client
    if body.start_date:
        snapshot["project"]["start_date"] = body.start_date.isoformat()
    if body.end_date:
        snapshot["project"]["end_date"] = body.end_date.isoformat()

    start = _parse_date(snapshot["project"].get("start_date"))
    end = _parse_date(snapshot["project"].get("end_date"))
    if start is None or end is None or end < start:
        raise HTTPException(status_code=400, detail="项目结束日期不能早于开始日期")
    # Clone planning context only. Actual execution/acceptance remains fresh.
    p = Project(
        name=snapshot["project"].get("name", f"{src.name}（克隆）"),
        abbreviation=snapshot["project"].get("abbreviation", ""),
        manager=user.id,
        client=snapshot["project"].get("client", ""),
        location=snapshot["project"].get("location", ""),
        timezone=src.timezone,
        dispatch_platform=src.dispatch_platform,
        description=src.description,
        staffing_notes=src.staffing_notes,
        prep_conditions=deepcopy(src.prep_conditions or []),
        rest_mode=src.rest_mode,
        rest_days=deepcopy(src.rest_days or []),
        skip_holidays=bool(src.skip_holidays),
        start_date=_parse_date(snapshot["project"].get("start_date")),
        end_date=_parse_date(snapshot["project"].get("end_date")),
        created_by=user.id,
    )
    db.add(p)
    db.flush()
    from app.routers.projects import _sync_project_members
    _sync_project_members(db, p)
    from app.services.project_events import update_plans
    update_plans(db, p, {event["event_key"]: _parse_date(event.get("planned_date"))
                        for event in snapshot.get("project_events", [])}, user.id)
    for v in snapshot.get("vehicles", []):
        db.add(Vehicle(project_id=p.id, vehicle_type=normalize_vehicle_type(v.get("vehicle_type", "自定义")),
                       model_name=v.get("model_name", ""), quantity=int(v.get("quantity", 1)),
                       configuration=deepcopy(v.get("configuration") or {}), notes=v.get("notes", ""),
                       sort_order=v.get("sort_order", 0)))
    # A new project inherits the source project's chosen work, including local
    # edits and omissions, rather than regenerating the latest global template.
    p.template_id, p.template_version = src.template_id, src.template_version
    phase_map, task_map = {}, {}
    from app.services.work_items import phase_of,group_of
    for old_task in db.query(Task).filter_by(project_id=src.id).order_by(Task.sort_order,Task.id):
        old_phase=phase_of(db,old_task)
        if old_phase is None:continue
        if old_phase.id not in phase_map:
            phase=Phase(project_id=p.id,**{key:getattr(old_phase,key) for key in ('name','sort_order','color','entry_criteria','exit_criteria')})
            db.add(phase);db.flush();phase_map[old_phase.id]=phase.id
        task=Task(project_id=p.id,phase_id=phase_map[old_phase.id],module_id=None,group_label=group_of(db,old_task),
            scope_conditions=deepcopy(old_task.scope_conditions or []),
            name=old_task.name,description=old_task.description,quantity_type='per_vehicle' if old_task.quantity_type=='per_vehicle' else 'fixed',
            target_quantity=None,unit='台' if old_task.quantity_type=='per_vehicle' else '项',safety_flag=old_task.safety_flag,
            applicable_vehicle_types=deepcopy(old_task.applicable_vehicle_types or []),sort_order=old_task.sort_order,
            source_task_id=old_task.source_task_id,vehicle_step_key=old_task.vehicle_step_key,
            legacy_work_snapshot={'kind':'clone_unverified_work_source','source_task_id':old_task.id,'source_project_id':src.id,
                'original':deepcopy(old_task.legacy_work_snapshot),'quantity':{'type':old_task.quantity_type,'target':old_task.target_quantity,'unit':old_task.unit}})
        task.deliverables=[];db.add(task);db.flush();task_map[old_task.id]=task
        # Reference files must also be independent of the source project.
        from app.services.generate_tasks import _upload_dir
        import shutil
        refs = []
        for ref in old_task.reference_docs or []:
            stored = ref.get("stored_name", "")
            if not stored or stored != Path(stored).name:
                continue
            source_file = _upload_dir() / stored
            if source_file.is_file():
                new_name = f"{uuid.uuid4().hex}{source_file.suffix}"
                destination=_upload_dir()/new_name
                if source_file.is_symlink() or destination.exists() or source_file.resolve().parent!=_upload_dir().resolve():
                    raise HTTPException(409,"来源参考文件路径无效，克隆未保存")
                from app.services.document_requirements import track_new_file
                track_new_file(db,destination)
                shutil.copy2(source_file,destination)
                refs.append({**ref, "stored_name": new_name})
        task.reference_docs = refs
        if task.quantity_type == 'per_vehicle':
            from app.services.vehicle_checks import definition_data,import_definitions
            import_definitions(db,task,definition_data(db,old_task))
        else:
            for old_check in db.query(CheckItem).filter_by(task_id=old_task.id).all():
                db.add(CheckItem(project_id=p.id, task_id=task.id,
                    **{key: getattr(old_check, key) for key in
                       ("name", "description", "is_safety_critical", "is_required", "sort_order")}))
    for old_id, task in task_map.items():
        old_task = db.get(Task, old_id)
        task.depends_on = [task_map[dep].id for dep in (old_task.depends_on or []) if dep in task_map]
    for prep in db.query(ProjectPreparationItem).filter_by(project_id=src.id,category="procurement").all():
        db.add(ProjectPreparationItem(project_id=p.id, required_date=p.start_date,
            **{key: getattr(prep, key) for key in
               ("category", "name", "is_required", "blocks_entry", "owner_party", "risk", "sort_order")}))
    db.flush()
    from app.services.vehicle_progress import import_snapshot as import_vehicle_snapshot
    import_vehicle_snapshot(db,p,snapshot.get('vehicle_progress_matrix'),task_map,{},planning_only=True)
    from app.services.vehicle_progress import retain_portable_source
    retain_portable_source(p,snapshot,source_project_id=src.id)
    from app.services.vehicle_checks import validate_step
    for work in task_map.values():
        work.vehicle_step_key=validate_step(db,work,work.vehicle_step_key)
    from app.services.project_documents import clone_definitions
    clone_definitions(db,src,p,user)
    log_change(db, p.id, "project", p.id, "create", user.id, f"克隆项目「{src.name}」")
    db.commit()
    return {"message": f"项目「{p.name}」已创建", "id": p.id}

"""Template document definitions, rule validation and portable blank-form ownership.

Callers own the transaction. New physical files are removed when the outer
transaction ends without a commit; immutable existing files are never destroyed
by editing or deleting a definition, because project/history snapshots may own them.
"""
from copy import deepcopy
import base64
import hashlib
import os
import logging
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictInt, model_validator
from sqlalchemy import event, text, update
from sqlalchemy.exc import OperationalError

from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE
from app.models import DocumentRequirement, DocumentTemplateFile, Template, User
from app.services.change_log import log_change

EVENTS = {"internal_kickoff", "ship", "arrival_all", "delivery_signed", "commissioning_done", "go_live", "training_done", "acceptance", "handover"}
MILESTONES = {"delivery_signed", "commissioning_done", "go_live", "training_done", "acceptance", "handover"}
RULE_FIELDS = ("timing_type", "timing_event", "timing_offset_hours", "timing_weekday", "trigger_type")
FIELDS = ("stage_key", "code", "name", "template_no", "is_group", "required", "scope", "platform", *RULE_FIELDS,
          "confidential_default", "external_visible_default", "external_never_visible", "sort_order", "note")
MAX_BUNDLE_FILES = 100


class RequirementInput(BaseModel):
    model_config = {"extra": "forbid"}
    stage_key: Literal["4", "5", "6", "7", "8", "9", "legacy"]
    code: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=300)
    template_no: str = Field(default="", max_length=100)
    is_group: bool = False
    parent_id: str | None = None
    required: bool = True
    scope: Literal["project", "vehicle"] | None = None
    platform: Literal["NDC", "GRACE", "integrated"] | None = None
    timing_type: Literal["before_event", "after_event", "weekly", "on_trigger", "after_milestone", "on_demand", "lifetime"] | None = None
    timing_event: str | None = Field(default=None, max_length=32)
    timing_offset_hours: StrictInt | None = Field(default=None, ge=0, le=876000)
    timing_weekday: StrictInt | None = Field(default=None, ge=1, le=7)
    trigger_type: Literal["accident", "quality", "member_leave"] | None = None
    confidential_default: bool = False
    external_visible_default: bool = False
    external_never_visible: bool = False
    sort_order: StrictInt = Field(default=0, ge=0, le=100000)
    note: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def rules(self):
        self.name, self.code = self.name.strip(), self.code.strip()
        if self.code in {'6.11.6','6.11.6a','6.11.6b','6.11.6c'} and 'confidential_default' not in self.model_fields_set:
            self.confidential_default=True
        valid_code = bool(re.fullmatch(r"legacy\.[a-f0-9]{32}", self.code)) if self.stage_key == "legacy" else bool(re.fullmatch(r"[4-9]\.[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*", self.code)) and self.code.split('.')[0] == self.stage_key
        if not self.name or not valid_code:
            raise ValueError("名称不能为空；编号必须属于所选第4–9阶段（如6.11.1a）")
        if (self.confidential_default or self.external_never_visible or self.code in {"6.11.6", "6.11.6a", "6.11.6b", "6.11.6c"}) and self.external_visible_default:
            raise ValueError("保密资料或禁止外部查看的资料不能默认对外可见")
        if self.code in {"6.11.6", "6.11.6a", "6.11.6b", "6.11.6c"}:
            self.external_never_visible = True
        if self.is_group:
            if self.scope is not None or any(getattr(self, key) is not None for key in RULE_FIELDS) or self.required:
                raise ValueError("分组不能设置资料范围、输出规则或必需提交")
            return self
        if not self.scope or not self.timing_type:
            raise ValueError("资料必须选择范围和输出时机")
        kind = self.timing_type
        allowed = {"timing_type"}
        if kind in {"before_event", "after_event", "after_milestone"}:
            valid = MILESTONES if kind == "after_milestone" else EVENTS | ({"vehicle_arrival"} if kind == "after_event" else set())
            if self.timing_event not in valid or self.timing_offset_hours is None:
                raise ValueError("事件规则必须选择有效事件并填写非负偏移小时")
            if self.timing_event == "vehicle_arrival" and self.scope != "vehicle":
                raise ValueError("逐车到场规则仅适用于车辆范围")
            allowed |= {"timing_event", "timing_offset_hours"}
        elif kind == "weekly":
            if self.timing_weekday is None:
                raise ValueError("weekly每周规则必须选择星期")
            allowed.add("timing_weekday")
        elif kind == "on_trigger":
            if self.trigger_type is None or self.timing_offset_hours is None:
                raise ValueError("触发规则必须选择触发类型和非负偏移小时")
            allowed |= {"trigger_type", "timing_offset_hours"}
        elif kind == "lifetime":
            if self.timing_event != "internal_kickoff":
                raise ValueError("全周期资料在内部启动会建档")
            allowed.add("timing_event")
        if any(getattr(self, key) is not None for key in RULE_FIELDS if key not in allowed):
            raise ValueError("输出时机包含不适用于当前规则的字段，请清除后保存")
        return self


def template_key(db, template_id):
    tid = None if template_id in (None, "default") else template_id
    if tid is not None and db.get(Template, tid) is None:
        raise HTTPException(404, "模板不存在")
    return tid


def lock_templates(db, *template_ids):
    """One stable order for copies, imports and edits; re-read after serialization."""
    keys = sorted({template_key(db, value) for value in template_ids}, key=lambda value: value or "")
    db.flush()
    try:
        for tid in keys:
            if tid is not None:
                from app.services.record_lock import lock_record
                template = db.get(Template, tid)
                if template is None:
                    raise HTTPException(404, "模板不存在")
                lock_record(db, template, conflict_detail="模板正由其他操作修改，请刷新重试")
            elif db.bind.dialect.name == "postgresql":
                # Fixed namespace, independent of Python's randomized hash seed.
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 6361691648859915313})
            else:
                db.execute(update(DocumentRequirement).where(DocumentRequirement.template_id.is_(None))
                           .values(id=DocumentRequirement.id, updated_at=DocumentRequirement.updated_at)
                           .execution_options(synchronize_session=False))
    except OperationalError as error:
        db.rollback()
        raise HTTPException(409, "模板正由其他操作修改，请稍后重试") from error
    db.expire_all()
    # A template deleted while waiting is not a new default or an empty template.
    for tid in keys:
        template_key(db, tid)


def recheck_authority(db, actor_id, capability="system.templates.manage"):
    if actor_id is None:  # Trusted seed/import module callers without an HTTP actor.
        return
    from app.services.system_permissions import has_permission
    actor = db.get(User, actor_id)
    if actor is None:
        raise HTTPException(401, "账号已停用，请重新登录")
    db.refresh(actor)
    if not actor.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    if not has_permission(actor, capability, default=actor.role == "admin"):
        raise HTTPException(403, "模板操作权限已被撤销")


def rows_for(db, template_id):
    tid = template_key(db, template_id)
    return db.query(DocumentRequirement).filter_by(template_id=tid).order_by(DocumentRequirement.sort_order, DocumentRequirement.code).all()


def file_dict(row):
    return {key: getattr(row, key) for key in ("id", "filename", "file_size", "content_type", "sha256")}


def requirement_dict(row):
    return {"id": row.id, "parent_id": row.parent_id, "source_metadata": deepcopy(row.source_metadata), **{key: getattr(row, key) for key in FIELDS}, "blank_file_id": row.blank_file_id}


def list_requirements(db, template_id):
    rows = rows_for(db, template_id)
    codes = {row.id: row.code for row in rows}
    files = {row.id: row for row in db.query(DocumentTemplateFile).filter(DocumentTemplateFile.id.in_([r.blank_file_id for r in rows if r.blank_file_id])).all()}
    return [{**requirement_dict(row), "parent_code": codes.get(row.parent_id),
             "blank_file": file_dict(files[row.blank_file_id]) if row.blank_file_id in files else None} for row in rows]


def owned_requirement(db, template_id, requirement_id):
    tid = template_key(db, template_id)
    row = db.get(DocumentRequirement, requirement_id)
    if row is None or row.template_id != tid:
        raise HTTPException(404, "资料要求不存在或不属于当前模板")
    return row


def draft(db, template_id):
    tid = template_key(db, template_id)
    if tid is not None:
        db.get(Template, tid).status = "draft"


def save_requirement(db, template_id, body, actor_id, requirement_id=None):
    if body.stage_key == "legacy":
        raise HTTPException(400, "历史来源只读，请明确分类到第4–9阶段后保存")
    lock_templates(db, template_id)
    recheck_authority(db, actor_id)
    tid = template_key(db, template_id)
    row = owned_requirement(db, template_id, requirement_id) if requirement_id else DocumentRequirement(template_id=tid)
    existing = db.query(DocumentRequirement).filter_by(template_id=tid, code=body.code).first()
    if existing and existing.id != row.id:
        raise HTTPException(409, "当前模板已有相同编号的资料要求")
    if row.id and row.is_group and not body.is_group and db.query(DocumentRequirement.id).filter_by(parent_id=row.id).first():
        raise HTTPException(400, "该分组仍有子项，不能改为资料；请先移动子项")
    if row.id and row.is_group and row.stage_key != body.stage_key and db.query(DocumentRequirement.id).filter_by(parent_id=row.id).first():
        raise HTTPException(400, "分组仍有子项，不能跨阶段移动；请先移动子项")
    if body.is_group and row.blank_file_id:
        raise HTTPException(400, "请先移除空白模板引用，再改为分组")
    if body.parent_id:
        parent = owned_requirement(db, template_id, body.parent_id)
        if not parent.is_group or parent.stage_key != body.stage_key:
            raise HTTPException(400, "父项必须是当前模板同阶段的分组")
        seen = {row.id} if row.id else set()
        while parent:
            if parent.id in seen:
                raise HTTPException(400, "资料分组不能形成循环")
            seen.add(parent.id)
            parent = db.get(DocumentRequirement, parent.parent_id) if parent.parent_id else None
    before = requirement_dict(row) if row.id else None
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    draft(db, template_id)
    log_change(db, None, "document_requirement", row.id, "update" if before else "create", actor_id,
               f"资料要求：{row.code} {row.name}", before, requirement_dict(row))
    return row


def delete_requirement(db, template_id, requirement_id, actor_id):
    lock_templates(db, template_id)
    recheck_authority(db, actor_id)
    row = owned_requirement(db, template_id, requirement_id)
    if db.query(DocumentRequirement.id).filter_by(parent_id=row.id).first():
        raise HTTPException(400, "分组仍有子项，请先移动或删除子项")
    before = requirement_dict(row)
    db.delete(row)
    draft(db, template_id)
    log_change(db, None, "document_requirement", requirement_id, "delete", actor_id, f"删除资料要求：{before['code']} {before['name']}", before, None)


def track_new_file(db, path):
    if path.parent.resolve() != UPLOAD_DIR.resolve() or path.is_symlink():
        raise ValueError("拒绝登记上传目录外的临时文件")
    key = "document_template_new_files"
    if key not in db.info:
        db.info[key] = []
        def committed(session):
            if not session.in_nested_transaction():
                session.info[key].clear()
        event.listen(db, "after_commit", committed)
        def cleanup(session, transaction):
            if transaction.parent is None:
                for item in session.info[key]:
                    try:
                        item.unlink(missing_ok=True)
                    except OSError:
                        logging.getLogger(__name__).warning("Uncommitted blank-template file cleanup deferred")
                session.info[key].clear()
        event.listen(db, "after_transaction_end", cleanup)
    db.info[key].append(path)


def create_file(db, data, filename, content_type, actor_id):
    if not data or len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(413 if data else 400, "空白模板文件为空或超过10MB限制")
    if not isinstance(filename, str) or not filename or len(filename) > 300 or any(ord(ch) < 32 for ch in filename) or '/' in filename or '\\' in filename:
        raise HTTPException(400, "空白模板文件名无效")
    content_type = content_type or "application/octet-stream"
    if len(content_type) > 100 or not re.fullmatch(r"[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+(?:;[ A-Za-z0-9=\-]+)?", content_type):
        raise HTTPException(400, "空白模板文件类型无效")
    stored = uuid4().hex
    path = UPLOAD_DIR / stored
    db.connection()  # Ensure outer transaction end also cleans a failed first file write.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    track_new_file(db, path)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    row = DocumentTemplateFile(filename=filename, stored_name=stored, file_size=len(data),
        content_type=(content_type or "application/octet-stream")[:100], sha256=hashlib.sha256(data).hexdigest(), uploaded_by=actor_id)
    db.add(row)
    db.flush()
    return row


def asset_path(row):
    path = UPLOAD_DIR / row.stored_name
    if Path(row.stored_name).name != row.stored_name or path.is_symlink() or path.parent.resolve() != UPLOAD_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "空白模板原文件缺失或路径无效，请重新上传")
    return path


def read_asset(row):
    path = asset_path(row)
    if path.stat().st_size > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "空白模板原文件超过大小限制")
    data = path.read_bytes()
    if len(data) != row.file_size or hashlib.sha256(data).hexdigest() != row.sha256:
        raise HTTPException(409, "空白模板原文件完整性校验失败，请核对或重新上传")
    return data


def copy_requirements(db, source_id, target_id):
    lock_templates(db, source_id, target_id)
    source = rows_for(db, source_id)
    tid = template_key(db, target_id)
    ids = {row.id: str(uuid4()) for row in source}
    assets = {}
    for row in source:
        if row.blank_file_id and row.blank_file_id not in assets:
            asset = db.get(DocumentTemplateFile, row.blank_file_id)
            if asset is None:
                raise HTTPException(409, "来源空白模板记录缺失，复制已取消")
            copied = create_file(db, read_asset(asset), asset.filename, asset.content_type, asset.uploaded_by)
            copied.uploaded_at = asset.uploaded_at
            assets[row.blank_file_id] = copied.id
    for row in source:
        db.add(DocumentRequirement(id=ids[row.id], template_id=tid, parent_id=None,
            blank_file_id=assets.get(row.blank_file_id), source_metadata=deepcopy(row.source_metadata), **{key: getattr(row, key) for key in FIELDS}))
    db.flush()
    for row in source:
        if row.parent_id:
            db.get(DocumentRequirement, ids[row.id]).parent_id = ids[row.parent_id]
    db.flush()


def clear_requirements(db, template_id):
    lock_templates(db, template_id)
    tid = template_key(db, template_id)
    db.query(DocumentRequirement).filter_by(template_id=tid).update({"parent_id": None}, synchronize_session=False)
    db.query(DocumentRequirement).filter_by(template_id=tid).delete(synchronize_session=False)
    db.flush()


def export_bundle(db, template_id):
    rows = list_requirements(db, template_id)
    definitions, files = [], {}
    total = 0
    for row in rows:
        definitions.append({**{key: row[key] for key in FIELDS}, "parent_code": row["parent_code"], "blank_file_key": row["blank_file_id"], "source_metadata": row.get("source_metadata")})
        key = row["blank_file_id"]
        if key and key not in files:
            asset = db.get(DocumentTemplateFile, key)
            if asset is None:
                raise HTTPException(409, "空白模板记录缺失，不能生成完整导出")
            data = read_asset(asset)
            total += len(data)
            if total > MAX_UPLOAD_SIZE or len(files) >= MAX_BUNDLE_FILES:
                raise HTTPException(413, "模板文件总量超过10MB，无法便携导出；请压缩空白文件后重试")
            files[key] = {**file_dict(asset), "data": base64.b64encode(data).decode('ascii')}
            files[key].pop("id")
    return {"document_requirements": definitions, "document_template_files": files}


def _portable_reference(value, label, max_length):
    if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > max_length):
        raise ValueError(f"{label}必须为空或不超过{max_length}字符的非空字符串")
    return value


def parse_bundle(bundle):
    definitions = bundle.get("document_requirements")
    if definitions is None:
        if bundle.get("document_template_files"):
            raise ValueError("缺少资料要求，不能导入无归属空白模板文件")
        return None
    if not isinstance(definitions, list) or len(definitions) > 2000:
        raise ValueError("资料要求必须是列表，最多2000项")
    files = bundle.get("document_template_files", {})
    if not isinstance(files, dict) or len(files) > MAX_BUNDLE_FILES:
        raise ValueError("空白模板文件清单无效或过多")
    decoded, total = {}, 0
    for key, item in files.items():
        if key is None:
            raise ValueError("空白模板文件键必须是非空字符串")
        _portable_reference(key, "空白模板文件键", 36)
        if not isinstance(key, str) or not isinstance(item, dict) or not isinstance(item.get("data"), str) or len(item['data']) > (MAX_UPLOAD_SIZE * 4 // 3 + 8):
            raise ValueError("空白模板文件内容或大小无效")
        try:
            data = base64.b64decode(item['data'], validate=True)
        except (ValueError, TypeError):
            raise ValueError("空白模板文件编码无效") from None
        total += len(data)
        if not data or total > MAX_UPLOAD_SIZE or len(data) != item.get("file_size") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise ValueError("空白模板文件大小或SHA256校验失败，未修改现有模板")
        name = item.get('filename')
        if not isinstance(name, str) or not name or len(name) > 300 or '/' in name or '\\' in name or any(ord(ch) < 32 for ch in name):
            raise ValueError("空白模板文件名无效")
        decoded[key] = (data, name, str(item.get('content_type') or 'application/octet-stream'))
    parsed, codes = [], {}
    for item in definitions:
        if not isinstance(item, dict):
            raise ValueError("资料要求内容必须是对象")
        item = dict(item)
        parent = _portable_reference(item.pop('parent_code', None), '资料父编号', 40)
        asset = _portable_reference(item.pop('blank_file_key', None), '空白模板文件键', 36)
        source = item.pop('source_metadata', None)
        if source is not None and not isinstance(source, dict):
            raise ValueError('历史来源必须是只读对象快照')
        body = RequirementInput.model_validate(item)
        if body.stage_key == 'legacy' and (not source or body.is_group or body.scope != 'project' or body.timing_type != 'on_demand'):
            raise ValueError('历史待分类要求必须携带只读来源快照，不能伪造已分类规则')
        if body.parent_id is not None:
            raise ValueError("便携资料定义必须用父编号，不能包含本地父ID")
        if body.code in codes:
            raise ValueError("资料要求编号重复")
        if asset and (asset not in decoded or body.is_group):
            raise ValueError("空白模板引用无效或分组不能挂文件")
        codes[body.code] = body
        parsed.append((body, parent, asset, source))
    for body, parent, asset, source in parsed:
        seen = {body.code}
        current = parent
        while current:
            if current not in codes or not codes[current].is_group or codes[current].stage_key != body.stage_key or current in seen:
                raise ValueError("资料父分组不存在、跨阶段或形成循环")
            seen.add(current)
            current = next(value[1] for value in parsed if value[0].code == current)
    used = {asset for _, _, asset, _ in parsed if asset}
    if used != set(decoded):
        raise ValueError("空白模板文件含无归属内容")
    return parsed, decoded


def replace_bundle(db, template_id, parsed_bundle, actor_id, capability="system.templates.manage"):
    if parsed_bundle is None:
        return
    lock_templates(db, template_id)
    recheck_authority(db, actor_id, capability)
    parsed, files = parsed_bundle
    tid = template_key(db, template_id)
    previous = {row.code: deepcopy(row.source_metadata) for row in rows_for(db, template_id)}
    before_count = len(previous)
    assets = {key: create_file(db, *values, actor_id).id for key, values in files.items()}
    clear_requirements(db, template_id)
    ids = {body.code: str(uuid4()) for body, _, _, _ in parsed}
    for body, parent, asset, source in parsed:
        values = body.model_dump(exclude={'parent_id'})
        values['source_metadata'] = previous.get(body.code) or ({'kind':'portable_unverified_snapshot','original':deepcopy(source)} if source else None)
        db.add(DocumentRequirement(id=ids[body.code], template_id=tid, **values, blank_file_id=assets.get(asset)))
    db.flush()
    for body, parent, asset, source in parsed:
        if parent:
            db.get(DocumentRequirement, ids[body.code]).parent_id = ids[parent]
    draft(db, template_id)
    log_change(db, None, 'template', template_id or 'default', 'import', actor_id,
               f"导入资料要求：{len(parsed)}项", {'count': before_count}, {'count': len(parsed)})
    db.flush()

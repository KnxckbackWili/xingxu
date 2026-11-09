"""Templates as sections of one-row items: reading, validation, compiling, copying and the Excel workbook.

A template is an ordered list of sections. Each section has a free title and sits on one company stage
(4–9) that decides when its files are due before the lifecycle gates. Each row is one thing:

* ``work``     – something to do; optionally once per vehicle (a vehicle step), with checks;
* ``file``     – a bundle of files to hand in;
* ``purchase`` – something to buy, at any stage (also spare parts once the site runs).

Any row may hand in files. Optional rows are chosen per project when it is created.

The rows are the only editing source. ``compile_template`` regenerates the rows projects are
generated from (phases, tasks, check items, document requirements, vehicle steps and procurement
items) with the same ids, so project documents that point at a template requirement keep their link.
Callers own the transaction; every write locks the template and re-checks the actor first.
"""
from __future__ import annotations

import io
import os
import re
import shutil
from typing import Literal, Optional
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR
from app.models import (CheckItem, DocumentRequirement, DocumentTemplateFile, Phase, Task, Template,
                        TemplateDoc, TemplateItem, TemplateProcurementItem, TemplateSection, VehicleStep)
from app.services.change_log import log_change
from app.services.template_stages import STAGE_NAMES, STAGE_KEYS
from app.time_utils import utcnow

DEFAULT_TEMPLATE_ID = 'default'
KINDS = ('work', 'file', 'purchase')
KIND_NAMES = {'work': '工作', 'file': '资料', 'purchase': '采购'}
SECTION_STAGES = STAGE_KEYS
FILE_RULE_KEYS = ('code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type', 'timing_event',
                  'timing_offset_hours', 'timing_weekday', 'trigger_type', 'confidential_default',
                  'note')
TIMINGS = ('before_event', 'after_event', 'weekly', 'on_trigger', 'after_milestone', 'on_demand', 'lifetime')


def tid_of(template_id: Optional[str]) -> Optional[str]:
    return None if template_id in (None, DEFAULT_TEMPLATE_ID) else template_id


def _scope(column, tid):
    return column.is_(None) if tid is None else column == tid


def template_label(db: Session, template_id: Optional[str]) -> str:
    tid = tid_of(template_id)
    if tid is None:
        return '通用模板'
    row = db.get(Template, tid)
    return row.name if row else tid


# ===== Input =====

class CheckIn(BaseModel):
    model_config = {'extra': 'forbid'}
    id: Optional[str] = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default='', max_length=2000)
    required: bool = True
    safety: bool = False

    @field_validator('name')
    @classmethod
    def _name(cls, value):
        if not value.strip():
            raise ValueError('检查要点不能为空')
        return value.strip()


class FileIn(BaseModel):
    model_config = {'extra': 'forbid'}
    id: Optional[str] = Field(default=None, max_length=36)
    code: str = Field(default='', max_length=40)
    name: str = Field(min_length=1, max_length=300)
    template_no: str = Field(default='', max_length=100)
    required: bool = True
    scope: Literal['project', 'vehicle'] = 'project'
    platform: Optional[Literal['NDC', 'GRACE', 'integrated']] = None
    timing_type: Literal[TIMINGS] = 'on_demand'
    timing_event: Optional[str] = Field(default=None, max_length=32)
    timing_offset_hours: Optional[StrictInt] = Field(default=None, ge=0, le=876000)
    timing_weekday: Optional[StrictInt] = Field(default=None, ge=1, le=7)
    trigger_type: Optional[Literal['accident', 'quality', 'member_leave']] = None
    confidential_default: bool = False
    note: str = Field(default='', max_length=5000)

    @model_validator(mode='after')
    def _rules(self):
        from app.services.document_requirements import check_rule
        self.name, self.code = self.name.strip(), self.code.strip()
        if not self.name:
            raise ValueError('文件名称不能为空')
        if self.code and not re.fullmatch(r'[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*', self.code):
            raise ValueError(f'文件编号「{self.code}」只能用字母、数字、点和短横线，如 6.11.1a')
        if self.code in {'6.11.6', '6.11.6a', '6.11.6b', '6.11.6c'} and 'confidential_default' not in self.model_fields_set:
            self.confidential_default = True
        check_rule(self)
        return self


class ItemIn(BaseModel):
    model_config = {'extra': 'forbid'}
    section_id: Optional[str] = Field(default=None, max_length=36)
    kind: Literal['work', 'file', 'purchase'] = 'work'
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default='', max_length=5000)
    optional: bool = False
    per_vehicle: bool = False
    checks: list[CheckIn] = Field(default_factory=list, max_length=200)
    files: list[FileIn] = Field(default_factory=list, max_length=100)
    quantity: Optional[float] = Field(default=None, ge=0, le=1e9, allow_inf_nan=False)
    unit: str = Field(default='', max_length=20)
    spec: str = Field(default='', max_length=300)
    version: Optional[int] = None

    @model_validator(mode='after')
    def _shape(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('名称不能为空')
        if self.kind != 'work':
            if self.per_vehicle:
                raise ValueError('只有工作可以按每台车记录')
            if self.checks:
                raise ValueError('只有工作可以设置检查要点')
        if self.kind == 'file' and not self.files:
            raise ValueError('资料至少要有一份文件')
        if self.kind != 'purchase':
            self.quantity, self.unit, self.spec = None, '', ''
        return self


class SectionIn(BaseModel):
    model_config = {'extra': 'forbid'}
    title: str = Field(min_length=1, max_length=200)
    stage_key: Literal[SECTION_STAGES] = '6'
    after_id: Optional[str] = Field(default=None, max_length=36)

    @field_validator('title')
    @classmethod
    def _title(cls, value):
        if not value.strip():
            raise ValueError('段落标题不能为空')
        return value.strip()


class SectionUpdate(BaseModel):
    model_config = {'extra': 'forbid'}
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    stage_key: Optional[Literal[SECTION_STAGES]] = None


class LayoutSection(BaseModel):
    id: str = Field(max_length=36)
    item_ids: list[str] = Field(default_factory=list, max_length=2000)


class LayoutIn(BaseModel):
    sections: list[LayoutSection] = Field(max_length=500)


class CopyIn(BaseModel):
    source_template_id: str = Field(min_length=1, max_length=100)
    item_ids: list[str] = Field(min_length=1, max_length=500)
    section_id: Optional[str] = Field(default=None, max_length=36)


# ===== Reading =====

def sections_of(db: Session, tid):
    return db.query(TemplateSection).filter(_scope(TemplateSection.template_id, tid)).order_by(
        TemplateSection.sort_order, TemplateSection.id).all()


def items_of(db: Session, tid):
    order = {row.id: index for index, row in enumerate(sections_of(db, tid))}
    rows = db.query(TemplateItem).filter(_scope(TemplateItem.template_id, tid)).all()
    return sorted(rows, key=lambda row: (order.get(row.section_id, 1 << 30), row.sort_order or 0, row.id))


def item_dict(row: TemplateItem, refs=(), blanks=None) -> dict:
    blanks = blanks or {}
    return {
        'id': row.id, 'section_id': row.section_id, 'kind': row.kind, 'name': row.name, 'note': row.note or '',
        'optional': bool(row.optional), 'per_vehicle': bool(row.per_vehicle), 'step_key': row.step_key,
        'checks': [dict(check) for check in row.checks or []],
        'files': [{**{key: document.get(key) for key in ('id', *FILE_RULE_KEYS)},
                   'blank_file': blanks.get(document.get('blank_file_id'))} for document in row.files or []],
        'quantity': row.quantity, 'unit': row.unit or '', 'spec': row.spec or '',
        'reference_docs': [{'id': ref.id, 'filename': ref.filename, 'note': ref.note or ''} for ref in refs],
        'version': row.version or 0, 'sort_order': row.sort_order or 0,
    }


def tree(db: Session, template_id) -> dict:
    """Sections with their rows and the stages a section may sit on."""
    from collections import defaultdict
    tid = tid_of(template_id)
    if tid is not None and db.get(Template, tid) is None:
        raise HTTPException(404, '模板不存在')
    sections = sections_of(db, tid)
    items = items_of(db, tid)
    refs = defaultdict(list)
    work_ids = [row.id for row in items if row.kind == 'work']
    if work_ids:
        for ref in db.query(TemplateDoc).filter(TemplateDoc.task_id.in_(work_ids)).order_by(TemplateDoc.uploaded_at, TemplateDoc.id):
            refs[ref.task_id].append(ref)
    blank_ids = {document.get('blank_file_id') for row in items for document in row.files or [] if document.get('blank_file_id')}
    blanks = {row.id: {'id': row.id, 'filename': row.filename, 'file_size': row.file_size}
              for row in db.query(DocumentTemplateFile).filter(DocumentTemplateFile.id.in_(blank_ids))} if blank_ids else {}
    by_section = defaultdict(list)
    for row in items:
        by_section[row.section_id].append(item_dict(row, refs[row.id], blanks))
    return {
        'template_id': template_id if tid else DEFAULT_TEMPLATE_ID,
        'sections': [{'id': row.id, 'title': row.title, 'stage_key': row.stage_key, 'stage_name': STAGE_NAMES.get(row.stage_key, '历史待分类'),
                      'sort_order': index, 'items': by_section[row.id]} for index, row in enumerate(sections)],
        'stages': [{'key': key, 'name': STAGE_NAMES[key]} for key in STAGE_KEYS],
    }


def summary(db: Session) -> dict:
    """Row counts per template for the library cards, in one grouped query."""
    from sqlalchemy import func
    result = {}
    for tid, kind, count in db.query(TemplateItem.template_id, TemplateItem.kind, func.count(TemplateItem.id)).group_by(
            TemplateItem.template_id, TemplateItem.kind):
        result.setdefault(tid or DEFAULT_TEMPLATE_ID, {'work': 0, 'file': 0, 'purchase': 0, 'files': 0, 'sections': 0})[kind] = count
    for tid, count in db.query(TemplateSection.template_id, func.count(TemplateSection.id)).group_by(TemplateSection.template_id):
        result.setdefault(tid or DEFAULT_TEMPLATE_ID, {'work': 0, 'file': 0, 'purchase': 0, 'files': 0, 'sections': 0})['sections'] = count
    for tid, files in db.query(TemplateItem.template_id, TemplateItem.files):
        result[tid or DEFAULT_TEMPLATE_ID]['files'] += len(files or [])
    return result


# ===== Writes =====

def lock(db: Session, template_id, actor_id, capability='system.templates.manage'):
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, actor_id, capability)
    return tid_of(template_id)


def _section(db: Session, tid, section_id) -> TemplateSection:
    row = db.get(TemplateSection, section_id) if section_id else None
    if row is None or row.template_id != tid:
        raise HTTPException(404, '段落不存在或不属于当前模板，请刷新后重试')
    return row


def _item(db: Session, tid, item_id) -> TemplateItem:
    row = db.get(TemplateItem, item_id)
    if row is None or row.template_id != tid:
        raise HTTPException(404, '事项不存在或不属于当前模板，请刷新后重试')
    return row


def _snapshot(row: TemplateItem) -> dict:
    return {key: getattr(row, key) for key in ('section_id', 'kind', 'name', 'note', 'optional', 'per_vehicle', 'step_key',
                                               'checks', 'files', 'quantity', 'unit', 'spec')}


def _new_step_key() -> str:
    return f'step_{uuid4().hex}'


def _codes_in_use(db: Session, tid, skip_item_id=None) -> dict:
    used = {}
    for row in db.query(TemplateItem).filter(_scope(TemplateItem.template_id, tid)):
        if row.id == skip_item_id:
            continue
        for document in row.files or []:
            if document.get('code'):
                used[document['code']] = row.name
    return used


def _next_code(stage: str, used) -> str:
    prefix = stage if stage in STAGE_KEYS else '6'
    numbers = [int(code.split('.')[1]) for code in used if code.startswith(prefix + '.') and len(code.split('.')) > 1 and code.split('.')[1].isdigit()]
    number = max(numbers, default=0) + 1
    while f'{prefix}.{number}' in used:
        number += 1
    return f'{prefix}.{number}'


def _apply_files(db: Session, tid, row: TemplateItem, files: list[FileIn], stage: str):
    """Keep ids and blank forms of files that stay; give new and blank-coded files a free code."""
    previous = {document['id']: document for document in row.files or [] if document.get('id')}
    used = _codes_in_use(db, tid, skip_item_id=row.id)
    result = []
    for document in files:
        data = document.model_dump()
        old = previous.get(data.get('id') or '')
        data['id'] = old['id'] if old else str(uuid4())
        data['blank_file_id'] = old.get('blank_file_id') if old else None
        data['source_metadata'] = old.get('source_metadata') if old else None
        if not data['code']:
            data['code'] = old['code'] if old and old.get('code') and old['code'] not in used else _next_code(stage, used)
        if data['code'] in used:
            raise HTTPException(409, f'文件编号「{data["code"]}」已被「{used[data["code"]]}」使用，请换一个编号')
        used[data['code']] = row.name
        result.append(data)
    row.files = result


def _apply_checks(row: TemplateItem, checks: list[CheckIn]):
    previous = {check['id'] for check in row.checks or [] if check.get('id')}
    row.checks = [{**check.model_dump(), 'id': check.id if check.id in previous else str(uuid4())} for check in checks]


def _apply(db: Session, tid, row: TemplateItem, data: ItemIn, section: TemplateSection):
    row.kind, row.name, row.note, row.optional = data.kind, data.name, data.note.strip(), data.optional
    row.per_vehicle = data.per_vehicle and data.kind == 'work'
    if row.per_vehicle and not row.step_key:
        row.step_key = _new_step_key()
    if not row.per_vehicle:
        row.step_key = None
    _apply_checks(row, data.checks if data.kind == 'work' else [])
    _apply_files(db, tid, row, data.files, section.stage_key)
    row.quantity, row.unit, row.spec = data.quantity, data.unit.strip(), data.spec.strip()


def create_section(db: Session, template_id, data: SectionIn, actor_id):
    tid = lock(db, template_id, actor_id)
    sections = sections_of(db, tid)
    row = TemplateSection(id=str(uuid4()), template_id=tid, title=data.title, stage_key=data.stage_key)
    position = len(sections)
    if data.after_id:
        position = [section.id for section in sections].index(_section(db, tid, data.after_id).id) + 1
    sections.insert(position, row)
    db.add(row)
    for index, section in enumerate(sections):
        section.sort_order = index
    db.flush()
    log_change(db, None, 'template', template_id, 'update', actor_id, f'{template_label(db, template_id)}：新增段落「{row.title}」')
    compile_template(db, tid)
    return row


def update_section(db: Session, template_id, section_id, data: SectionUpdate, actor_id):
    tid = lock(db, template_id, actor_id)
    row = _section(db, tid, section_id)
    before = {'title': row.title, 'stage_key': row.stage_key}
    if data.title is not None:
        if not data.title.strip():
            raise HTTPException(400, '段落标题不能为空')
        row.title = data.title.strip()
    if data.stage_key is not None:
        row.stage_key = data.stage_key
    log_change(db, None, 'template', template_id, 'update', actor_id, f'{template_label(db, template_id)}：修改段落「{row.title}」',
               before, {'title': row.title, 'stage_key': row.stage_key})
    compile_template(db, tid)
    return row


def delete_section(db: Session, template_id, section_id, actor_id):
    tid = lock(db, template_id, actor_id)
    row = _section(db, tid, section_id)
    items = db.query(TemplateItem).filter_by(section_id=row.id).all()
    log_change(db, None, 'template', template_id, 'update', actor_id,
               f'{template_label(db, template_id)}：删除段落「{row.title}」及其中 {len(items)} 件事',
               {'title': row.title, 'items': [item.name for item in items]}, None)
    for item in items:
        db.delete(item)
    db.delete(row)
    db.flush()
    for index, section in enumerate(sections_of(db, tid)):
        section.sort_order = index
    compile_template(db, tid)


def set_layout(db: Session, template_id, data: LayoutIn, actor_id):
    """Section order and which rows sit where, in one go (drag and drop)."""
    tid = lock(db, template_id, actor_id)
    sections = {row.id: row for row in sections_of(db, tid)}
    items = {row.id: row for row in items_of(db, tid)}
    listed_sections = [entry.id for entry in data.sections]
    listed_items = [item_id for entry in data.sections for item_id in entry.item_ids]
    if set(listed_sections) != set(sections) or len(listed_sections) != len(sections) \
            or set(listed_items) != set(items) or len(listed_items) != len(items):
        raise HTTPException(409, '模板内容已变化，请刷新后再调整顺序')
    for index, entry in enumerate(data.sections):
        sections[entry.id].sort_order = index
        for position, item_id in enumerate(entry.item_ids):
            items[item_id].section_id, items[item_id].sort_order = entry.id, position
    log_change(db, None, 'template', template_id, 'update', actor_id, f'{template_label(db, template_id)}：调整段落与事项顺序')
    compile_template(db, tid)


def create_item(db: Session, template_id, data: ItemIn, actor_id):
    tid = lock(db, template_id, actor_id)
    section = _section(db, tid, data.section_id)
    position = db.query(TemplateItem).filter_by(section_id=section.id).count()
    row = TemplateItem(id=str(uuid4()), template_id=tid, section_id=section.id, sort_order=position, checks=[], files=[], extra={}, version=0)
    _apply(db, tid, row, data, section)
    db.add(row)
    db.flush()
    log_change(db, None, 'template_item', row.id, 'create', actor_id,
               f'{template_label(db, template_id)}：新增{KIND_NAMES[row.kind]}「{row.name}」', None, _snapshot(row))
    compile_template(db, tid)
    return row


def update_item(db: Session, template_id, item_id, data: ItemIn, actor_id):
    tid = lock(db, template_id, actor_id)
    row = _item(db, tid, item_id)
    if data.version is not None and data.version != (row.version or 0):
        raise HTTPException(409, '这件事已被其他人修改，请刷新后再保存')
    section = _section(db, tid, data.section_id) if data.section_id else _section(db, tid, row.section_id)
    before = _snapshot(row)
    if section.id != row.section_id:
        row.section_id = section.id
        row.sort_order = db.query(TemplateItem).filter_by(section_id=section.id).count()
    _apply(db, tid, row, data, section)
    row.version = (row.version or 0) + 1
    db.flush()
    log_change(db, None, 'template_item', row.id, 'update', actor_id,
               f'{template_label(db, template_id)}：修改{KIND_NAMES[row.kind]}「{row.name}」', before, _snapshot(row))
    compile_template(db, tid)
    return row


def delete_item(db: Session, template_id, item_id, actor_id):
    tid = lock(db, template_id, actor_id)
    row = _item(db, tid, item_id)
    log_change(db, None, 'template_item', row.id, 'delete', actor_id,
               f'{template_label(db, template_id)}：删除{KIND_NAMES.get(row.kind, "")}「{row.name}」', _snapshot(row), None)
    section_id = row.section_id
    db.delete(row)
    db.flush()
    for index, item in enumerate(db.query(TemplateItem).filter_by(section_id=section_id).order_by(TemplateItem.sort_order, TemplateItem.id)):
        item.sort_order = index
    compile_template(db, tid)


def _copy_blank(db: Session, blank_file_id):
    from app.services.document_requirements import create_file, read_asset
    if not blank_file_id:
        return None
    asset = db.get(DocumentTemplateFile, blank_file_id)
    if asset is None:
        return None
    copied = create_file(db, read_asset(asset), asset.filename, asset.content_type, asset.uploaded_by)
    copied.uploaded_at = asset.uploaded_at
    return copied.id


def _copy_references(db: Session, source_task_id, target_task_id, target_tid):
    from app.services.document_requirements import track_new_file
    for ref in db.query(TemplateDoc).filter_by(task_id=source_task_id).all():
        stored = ref.stored_name
        source = UPLOAD_DIR / ref.stored_name
        if source.is_file():
            stored = f'{uuid4().hex}{os.path.splitext(ref.filename or "")[-1]}'
            destination = UPLOAD_DIR / stored
            if source.is_symlink() or source.resolve().parent != UPLOAD_DIR.resolve() or destination.exists():
                raise HTTPException(409, '来源参考文档路径无效，复制已取消')
            track_new_file(db, destination)
            shutil.copy2(source, destination)
        db.add(TemplateDoc(template_id=target_tid, task_id=target_task_id, filename=ref.filename, stored_name=stored,
                           file_size=ref.file_size, content_type=ref.content_type, note=ref.note, uploaded_by=ref.uploaded_by))


def _clone(db: Session, source: TemplateItem, target_tid, section_id, sort_order, used_codes, step_keys, stage):
    files = []
    for document in source.files or []:
        code = document.get('code') or ''
        if not code or code in used_codes:
            code = _next_code(stage, used_codes)
        used_codes[code] = source.name
        files.append({**document, 'id': str(uuid4()), 'code': code, 'blank_file_id': _copy_blank(db, document.get('blank_file_id'))})
    step_key = None
    if source.per_vehicle:
        step_key = source.step_key if source.step_key and source.step_key not in step_keys else _new_step_key()
        step_keys.add(step_key)
    row = TemplateItem(
        id=str(uuid4()), template_id=target_tid, section_id=section_id, kind=source.kind, name=source.name, note=source.note or '',
        optional=bool(source.optional), per_vehicle=bool(source.per_vehicle), step_key=step_key,
        checks=[{**check, 'id': str(uuid4())} for check in source.checks or []], files=files, quantity=source.quantity,
        unit=source.unit or '', spec=source.spec or '', extra=dict(source.extra or {}), sort_order=sort_order, version=0)
    db.add(row)
    db.flush()
    if source.kind == 'work':
        _copy_references(db, source.id, row.id, target_tid)
    return row


def copy_items(db: Session, template_id, data: CopyIn, actor_id):
    """Copy chosen rows of another template; each lands in a section of the same title, else the chosen/last one."""
    from app.services.document_requirements import lock_templates, recheck_authority
    source_tid, target_tid = tid_of(data.source_template_id), tid_of(template_id)
    if source_tid == target_tid:
        raise HTTPException(400, '请选择另一个模板作为来源')
    lock_templates(db, data.source_template_id, template_id)
    recheck_authority(db, actor_id)
    sources = {row.id: row for row in items_of(db, source_tid)}
    missing = [item_id for item_id in data.item_ids if item_id not in sources]
    if missing:
        raise HTTPException(409, '来源模板内容已变化，请重新选择')
    source_sections = {row.id: row for row in sections_of(db, source_tid)}
    target_sections = sections_of(db, target_tid)
    fallback = _section(db, target_tid, data.section_id) if data.section_id else None
    if fallback is None and not target_sections:
        fallback = TemplateSection(id=str(uuid4()), template_id=target_tid, title='复制的事项', stage_key='6', sort_order=0)
        db.add(fallback)
        db.flush()
        target_sections = [fallback]
    by_title = {row.title: row for row in target_sections}
    used_codes = _codes_in_use(db, target_tid)
    step_keys = {row.step_key for row in items_of(db, target_tid) if row.step_key}
    copied = []
    for item_id in dict.fromkeys(data.item_ids):
        source = sources[item_id]
        source_section = source_sections.get(source.section_id)
        section = fallback or by_title.get(source_section.title if source_section else '') or target_sections[-1]
        position = db.query(TemplateItem).filter_by(section_id=section.id).count()
        copied.append(_clone(db, source, target_tid, section.id, position, used_codes, step_keys, section.stage_key))
    log_change(db, None, 'template', template_id, 'update', actor_id,
               f'{template_label(db, template_id)}：从「{template_label(db, data.source_template_id)}」复制 {len(copied)} 件事：'
               + '、'.join(row.name for row in copied))
    compile_template(db, target_tid)
    return copied


def clear_content(db: Session, tid):
    """Remove a template's rows and sections; the compiled rows follow on the next compile."""
    db.query(TemplateItem).filter(_scope(TemplateItem.template_id, tid)).delete(synchronize_session=False)
    db.query(TemplateSection).filter(_scope(TemplateSection.template_id, tid)).delete(synchronize_session=False)
    db.flush()


def copy_template(db: Session, source_template_id, target_tid):
    """Everything of one template into an empty new one (blank forms and reference files copied)."""
    source_tid = tid_of(source_template_id)
    used_codes, step_keys = {}, set()
    sections = {}
    for index, section in enumerate(sections_of(db, source_tid)):
        sections[section.id] = TemplateSection(id=str(uuid4()), template_id=target_tid, title=section.title,
                                               stage_key=section.stage_key, sort_order=index)
        db.add(sections[section.id])
    db.flush()
    for item in items_of(db, source_tid):
        section = sections.get(item.section_id)
        if section is None:
            continue
        _clone(db, item, target_tid, section.id, item.sort_order or 0, used_codes, step_keys, section.stage_key)
    compile_template(db, target_tid)


# ===== Compiling into the rows projects are generated from =====

def _upsert(db: Session, model, existing: dict, wanted: dict, keep=()):
    for key, values in wanted.items():
        row = existing.get(key)
        if row is None:
            row = model(id=key)
            db.add(row)
        for name, value in values.items():
            if name in keep and key in existing:
                continue
            if getattr(row, name) != value:
                setattr(row, name, value)
    return [row for key, row in existing.items() if key not in wanted]


def compile_template(db: Session, tid):
    """Regenerate this template's phases, tasks, checks, document rules, vehicle steps and procurement rows."""
    db.flush()
    sections = sections_of(db, tid)
    stage_of = {row.id: row.stage_key for row in sections}
    items = items_of(db, tid)
    now = utcnow()

    phases = {row.id: row for row in db.query(Phase).filter(_scope(Phase.template_id, tid), Phase.project_id.is_(None))}
    stale_phases = _upsert(db, Phase, phases, {row.id: {
        'project_id': None, 'template_id': tid, 'name': row.title[:100], 'sort_order': index, 'color': '#1890ff',
        'entry_criteria': '', 'exit_criteria': '', 'stage_key': row.stage_key} for index, row in enumerate(sections)})
    db.flush()

    wanted_tasks, wanted_checks, wanted_docs, wanted_procs, steps = {}, {}, {}, {}, {}
    order = 0
    for position, row in enumerate(items):
        extra = row.extra or {}
        if row.kind == 'work':
            per_vehicle = bool(row.per_vehicle)
            wanted_tasks[row.id] = {
                'project_id': None, 'template_id': tid, 'phase_id': row.section_id,
                'group_label': extra.get('group_label') or '',
                'name': row.name, 'description': row.note or '',
                'quantity_type': 'per_vehicle' if per_vehicle else extra.get('quantity_type') or 'fixed',
                'safety_flag': bool(extra.get('safety_flag')), 'applicable_vehicle_types': list(extra.get('applicable_vehicle_types') or []),
                'sort_order': position, 'reference_docs': [],
                'version': 0, 'source_task_id': None, 'vehicle_step_key': row.step_key if per_vehicle else None}
            for index, check in enumerate(row.checks or []):
                wanted_checks[check['id']] = {
                    'task_id': row.id, 'project_id': None, 'template_id': tid, 'name': check['name'],
                    'description': check.get('description') or '', 'is_safety_critical': bool(check.get('safety')),
                    'is_required': check.get('required', True) is not False, 'is_applicable': True, 'sort_order': index, 'version': 0}
            if per_vehicle and row.step_key and row.step_key not in steps:
                steps[row.step_key] = row.name
        if row.kind == 'purchase':
            wanted_procs[row.id] = {
                'template_id': tid, 'name': row.name, 'unit': row.unit or '件', 'spec': row.spec or '',
                'due_weeks': extra.get('due_weeks') or 0, 'condition': extra.get('condition') or 'default',
                'is_required': not row.optional, 'owner_party': extra.get('owner_party') or 'procurement',
                'risk': extra.get('risk') or 'low', 'sort_order': position}
        for document in row.files or []:
            metadata = dict(document.get('source_metadata') or {})
            metadata['template_item_id'] = row.id
            wanted_docs[document['id']] = {
                'template_id': tid, 'stage_key': stage_of.get(row.section_id, '6'),
                **{key: document.get(key) for key in FILE_RULE_KEYS},
                'template_no': document.get('template_no') or '', 'note': document.get('note') or '',
                'scope': document.get('scope') or 'project', 'is_group': False, 'parent_id': None,
                'required': document.get('required', True) is not False,
                'confidential_default': bool(document.get('confidential_default')),
                'blank_file_id': document.get('blank_file_id'), 'sort_order': order, 'source_metadata': metadata}
            order += 1

    tasks = {row.id: row for row in db.query(Task).filter(_scope(Task.template_id, tid), Task.project_id.is_(None))}
    stale_tasks = _upsert(db, Task, tasks, wanted_tasks, keep=('version',))
    db.flush()
    checks = {row.id: row for row in db.query(CheckItem).filter(_scope(CheckItem.template_id, tid), CheckItem.project_id.is_(None))}
    for row in _upsert(db, CheckItem, checks, wanted_checks, keep=('version',)):
        db.delete(row)
    stale_ids = [row.id for row in stale_tasks]
    if stale_ids:
        db.query(TemplateDoc).filter(TemplateDoc.task_id.in_(stale_ids)).delete(synchronize_session=False)
        for row in stale_tasks:
            db.delete(row)
    db.flush()
    for row in stale_phases:
        db.delete(row)

    documents = {row.id: row for row in db.query(DocumentRequirement).filter(_scope(DocumentRequirement.template_id, tid))}
    for row in documents.values():
        row.parent_id = None
    db.flush()
    # Codes are unique per template: drop removed rules and free changed codes before writing new ones.
    for key in [key for key in documents if key not in wanted_docs]:
        db.delete(documents.pop(key))
    for row in documents.values():
        if wanted_docs[row.id]['code'] != row.code:
            row.code = f'~{row.id}'
    db.flush()
    _upsert(db, DocumentRequirement, documents, wanted_docs)
    for row in documents.values():
        row.updated_at = now
    db.flush()

    key = tid or DEFAULT_TEMPLATE_ID
    current = [(row.key, row.name) for row in db.query(VehicleStep).filter_by(template_id=key).order_by(VehicleStep.sort_order, VehicleStep.key)]
    if current != list(steps.items()):
        db.query(VehicleStep).filter_by(template_id=key).delete(synchronize_session=False)
        db.flush()
        for index, (step, name) in enumerate(steps.items()):
            db.add(VehicleStep(template_id=key, key=step, name=name[:200], sort_order=index))

    procurements = {row.id: row for row in db.query(TemplateProcurementItem).filter(_scope(TemplateProcurementItem.template_id, tid))}
    for row in _upsert(db, TemplateProcurementItem, procurements, wanted_procs):
        db.delete(row)
    if tid is not None:
        template = db.get(Template, tid)
        if template is not None:
            template.updated_at = now
    db.flush()


# ===== Creating a project from a template =====

def creation_scope(db: Session, template_id, optional_item_ids) -> dict:
    """What a new project takes: every required row plus the optional rows chosen for it."""
    tid = tid_of(template_id)
    items = items_of(db, tid)
    optional = {row.id for row in items if row.optional}
    unknown = set(optional_item_ids or []) - optional
    if unknown:
        raise ValueError('所选可选事项已失效或不属于当前模板，请重新读取模板')
    chosen = {row.id for row in items if not row.optional} | set(optional_item_ids or [])
    stage_of = {row.id: row.stage_key for row in sections_of(db, tid)}
    return {
        'work_ids': [row.id for row in items if row.kind == 'work' and row.id in chosen],
        'excluded_requirement_ids': [document['id'] for row in items if row.id not in chosen for document in row.files or []],
        'purchases': [(row, stage_of.get(row.section_id)) for row in items if row.kind == 'purchase' and row.id in chosen],
    }


def add_purchases(db: Session, project, purchases, actor_id) -> int:
    """Purchase rows become the project's procurement records; later-stage purchases have no due date yet."""
    from app.models import ProjectPreparationItem
    from app.services.project_events import planned_event_date
    existing = {name for (name,) in db.query(ProjectPreparationItem.name).filter_by(project_id=project.id, category='procurement')}
    sort_order = db.query(ProjectPreparationItem).filter_by(project_id=project.id).count()
    created = 0
    for row, stage in purchases:
        if row.name in existing:
            continue
        db.add(ProjectPreparationItem(
            project_id=project.id, category='procurement', name=row.name, is_required=not row.optional,
            owner_party=(row.extra or {}).get('owner_party') or 'procurement',
            required_date=planned_event_date(db, project.id) if stage in ('4', '5') else None,
            risk=(row.extra or {}).get('risk') or 'low', note=row.note or '',
            extra={'quantity': row.quantity, 'unit': row.unit, 'spec': row.spec, 'order_status': '未申请',
                   'source': 'template', 'template_item_id': row.id, 'stage_key': stage},
            sort_order=sort_order + created))
        existing.add(row.name)
        created += 1
    if created:
        log_change(db, project.id, 'preparation', project.id, 'create', actor_id, f'从模板带入 {created} 项采购')
    return created


# ===== Excel =====

SHEET_ITEMS, SHEET_FILES = '事项', '文件'
ITEM_COLUMNS = ['段落', '阶段', '类型', '名称', '可选', '每台车', '检查要点', '要交的文件', '数量', '单位', '规格', '说明']
FILE_COLUMNS = ['编号', '名称', '必交', '每台车一份', '什么时候交', '事件', '相隔天数', '星期', '触发情况', '只用于平台',
                '默认保密', '模板编号', '说明']
TIMING_NAMES = {'on_demand': '需要时交', 'weekly': '每周交', 'before_event': '事件之前', 'after_event': '事件之后',
                'after_milestone': '节点完成后', 'on_trigger': '发生情况后', 'lifetime': '项目期间更新'}
EVENT_NAMES = {'internal_kickoff': '内部启动会', 'ship': '发车', 'arrival_all': '全部到场', 'vehicle_arrival': '该车到场',
               'delivery_signed': '到货签收', 'commissioning_done': '调试完工', 'go_live': '上线运行', 'training_done': '培训完成',
               'acceptance': '项目验收', 'handover': '交付售后'}
TRIGGER_NAMES = {'accident': '事故', 'quality': '质量问题', 'member_leave': '人员离开项目'}
PLATFORM_NAMES = {'NDC': 'NDC', 'GRACE': 'GRACE', 'integrated': '集成'}
WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def _yes(value) -> bool:
    return str(value or '').strip() in ('是', '√', '✓', 'Y', 'y', 'yes', 'Yes', 'TRUE', 'true', '1')


def _reverse(mapping: dict, value, label):
    text = str(value or '').strip()
    if not text:
        return None
    for key, name in mapping.items():
        if text in (key, name):
            return key
    raise ValueError(f'{label}「{text}」无法识别，可填：{"、".join(mapping.values())}')


def export_workbook(db: Session, template_id) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    data = tree(db, template_id)
    book = Workbook()
    sheet = book.active
    sheet.title = SHEET_ITEMS
    sheet.append(ITEM_COLUMNS)
    files_sheet = book.create_sheet(SHEET_FILES)
    files_sheet.append(FILE_COLUMNS)
    for section in data['sections']:
        for item in section['items']:
            checks = '\n'.join(('[安全]' if check.get('safety') else '') + ('[选做]' if check.get('required') is False else '') + check['name']
                               for check in item['checks'])
            sheet.append([section['title'], STAGE_NAMES.get(section['stage_key'], '历史待分类'), KIND_NAMES[item['kind']], item['name'],
                          '是' if item['optional'] else '', '是' if item['per_vehicle'] else '', checks,
                          '\n'.join(f"{document['code']} {document['name']}" for document in item['files']),
                          item['quantity'], item['unit'], item['spec'], item['note']])
            for document in item['files']:
                offset = document.get('timing_offset_hours')
                files_sheet.append([
                    document['code'], document['name'], '是' if document.get('required', True) else '否',
                    '是' if document.get('scope') == 'vehicle' else '', TIMING_NAMES.get(document.get('timing_type') or 'on_demand'),
                    EVENT_NAMES.get(document.get('timing_event') or '', ''), None if offset is None else round(offset / 24, 2),
                    WEEKDAY_NAMES[document['timing_weekday'] - 1] if document.get('timing_weekday') else '',
                    TRIGGER_NAMES.get(document.get('trigger_type') or '', ''), PLATFORM_NAMES.get(document.get('platform') or '', ''),
                    '是' if document.get('confidential_default') else '', document.get('template_no') or '', document.get('note') or ''])
    note = book.create_sheet('说明')
    for line in ('一行一件事。「段落」相同的行在同一段落里，段落和行的顺序按表格顺序。',
                 '阶段：内部启动会 / 发车前 / 实施 / 验收 / 交付 / 全项目周期，决定这一段要交的文件在哪个门禁前交齐。',
                 '类型：工作 / 资料 / 采购。每台车、可选填「是」。',
                 '检查要点：一行一个；前面加 [安全] 表示安全项，加 [选做] 表示不是必做。',
                 '要交的文件：一行一个「编号 名称」；编号可不填，导入时自动编号。交付时机等细节在「文件」表按编号填写。',
                 '导入会用表格内容整体替换当前模板；名称和编号相同的事项、文件会保留原有的空白模板和参考文件。'):
        note.append([line])
    for target in (sheet, files_sheet):
        for cell in target[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='EEF2F7')
        target.freeze_panes = 'A2'
    widths = {'A': 16, 'B': 12, 'C': 8, 'D': 22, 'E': 6, 'F': 8, 'G': 36, 'H': 36, 'I': 8, 'J': 8, 'K': 24, 'L': 30}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')
    files_sheet.column_dimensions['B'].width = 30
    note.column_dimensions['A'].width = 110
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _cell(row, index):
    value = row[index] if index < len(row) else None
    return '' if value is None else str(value).strip() if not isinstance(value, (int, float)) else value


def parse_workbook(content: bytes) -> dict:
    """Workbook → {'sections': [{title, stage_key, items: [ItemIn-like dicts]}]}; raises ValueError."""
    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - any unreadable workbook is a user error
        raise ValueError('无法读取 Excel 文件，请使用导出的模板表格') from error
    if SHEET_ITEMS not in book.sheetnames:
        raise ValueError(f'表格中没有「{SHEET_ITEMS}」工作表，请使用导出的模板表格')
    rows = [list(row) for row in book[SHEET_ITEMS].iter_rows(values_only=True)]
    if not rows:
        raise ValueError('「事项」表是空的')
    header = [str(value or '').strip() for value in rows[0]]
    if header[:len(ITEM_COLUMNS)] != ITEM_COLUMNS:
        raise ValueError('「事项」表的列与导出格式不一致，请在导出的表格上修改')
    rules = {}
    if SHEET_FILES in book.sheetnames:
        for number, row in enumerate(list(book[SHEET_FILES].iter_rows(values_only=True))[1:], start=2):
            code = str(_cell(row, 0))
            if not code:
                continue
            try:
                days = _cell(row, 6)
                timing = _reverse(TIMING_NAMES, _cell(row, 4), '什么时候交') or 'on_demand'
                rules[code] = {
                    'code': code, 'name': str(_cell(row, 1)) or code, 'required': str(_cell(row, 2)) != '否',
                    'scope': 'vehicle' if _yes(_cell(row, 3)) else 'project', 'timing_type': timing,
                    'timing_event': _reverse(EVENT_NAMES, _cell(row, 5), '事件'),
                    'timing_offset_hours': None if days in ('', None) else int(round(float(days) * 24)),
                    'timing_weekday': (WEEKDAY_NAMES.index(str(_cell(row, 7))) + 1) if str(_cell(row, 7)) in WEEKDAY_NAMES else None,
                    'trigger_type': _reverse(TRIGGER_NAMES, _cell(row, 8), '触发情况'),
                    'platform': _reverse(PLATFORM_NAMES, _cell(row, 9), '平台'),
                    'confidential_default': _yes(_cell(row, 10)), 'template_no': str(_cell(row, 11)), 'note': str(_cell(row, 12))}
                if rules[code]['timing_type'] == 'lifetime' and not rules[code]['timing_event']:
                    rules[code]['timing_event'] = 'internal_kickoff'
            except (ValueError, TypeError) as error:
                raise ValueError(f'「文件」表第 {number} 行：{error}') from error
    sections, by_title = [], {}
    stage_names = {name: key for key, name in STAGE_NAMES.items()}
    for number, row in enumerate(rows[1:], start=2):
        if not any(value not in (None, '') for value in row):
            continue
        title, name = str(_cell(row, 0)), str(_cell(row, 3))
        if not title or not name:
            raise ValueError(f'「事项」表第 {number} 行：段落和名称都要填写')
        stage_text = str(_cell(row, 1))
        stage = stage_text if stage_text in SECTION_STAGES else stage_names.get(stage_text)
        if stage is None:
            raise ValueError(f'「事项」表第 {number} 行：阶段「{stage_text}」无法识别，可填：{"、".join(STAGE_NAMES[key] for key in STAGE_KEYS)}')
        kind = {'工作': 'work', '资料': 'file', '采购': 'purchase', **{key: key for key in KINDS}}.get(str(_cell(row, 2)))
        if kind is None:
            raise ValueError(f'「事项」表第 {number} 行：类型只能是 工作、资料 或 采购')
        section = by_title.get(title)
        if section is None:
            section = by_title[title] = {'title': title, 'stage_key': stage, 'items': []}
            sections.append(section)
        checks = []
        for line in str(_cell(row, 6)).splitlines():
            text, safety, required = line.strip(), False, True
            while text.startswith(('[安全]', '[选做]')):
                safety = safety or text.startswith('[安全]')
                required = required and not text.startswith('[选做]')
                text = text[4:].strip()
            if text:
                checks.append({'name': text, 'safety': safety, 'required': required})
        files = []
        for line in str(_cell(row, 7)).splitlines():
            text = line.strip()
            if not text:
                continue
            code, _, rest = text.partition(' ')
            if not re.fullmatch(r'[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*', code) or not any(char.isdigit() for char in code):
                code, rest = '', text
            rule = dict(rules.get(code) or {})
            rule.update(code=code, name=rest.strip() or rule.get('name') or code)
            files.append(rule)
        quantity = _cell(row, 8)
        try:
            quantity = None if quantity in ('', None) else float(quantity)
        except (TypeError, ValueError):
            raise ValueError(f'「事项」表第 {number} 行：数量需要填数字')
        section['items'].append({'kind': kind, 'name': name, 'optional': _yes(_cell(row, 4)), 'per_vehicle': _yes(_cell(row, 5)),
                                 'checks': checks, 'files': files, 'quantity': quantity, 'unit': str(_cell(row, 9)),
                                 'spec': str(_cell(row, 10)), 'note': str(_cell(row, 11)), 'row': number})
    if not sections:
        raise ValueError('「事项」表没有任何事项')
    return {'sections': sections}


def import_workbook(db: Session, template_id, content: bytes, actor_id) -> dict:
    """Replace the template with the workbook; rows and files with the same name/code keep their ids and files."""
    try:
        parsed = parse_workbook(content)
    except ValueError as error:
        raise HTTPException(400, str(error))
    tid = lock(db, template_id, actor_id, 'system.template_io.manage')
    from app.services.document_requirements import recheck_authority
    recheck_authority(db, actor_id)
    old_sections = {row.title: row for row in sections_of(db, tid)}
    old_items = {}
    for row in items_of(db, tid):
        old_items.setdefault((row.kind, row.name), row)
    old_files = {document['code']: document for row in old_items.values() for document in row.files or [] if document.get('code')}
    old_checks = {(row.id, check['name']): check['id'] for row in old_items.values() for check in row.checks or []}
    kept_sections, kept_items = set(), set()
    used_codes, total = {}, 0
    explicit = {document['code'] for section in parsed['sections'] for item in section['items'] for document in item['files'] if document['code']}
    for index, section_data in enumerate(parsed['sections']):
        section = old_sections.get(section_data['title']) or TemplateSection(id=str(uuid4()), template_id=tid)
        section.title, section.stage_key, section.sort_order = section_data['title'], section_data['stage_key'], index
        db.add(section)
        db.flush()
        kept_sections.add(section.id)
        for position, data in enumerate(section_data['items']):
            old = old_items.get((data['kind'], data['name']))
            if old is not None and old.id in kept_items:
                old = None
            row = old or TemplateItem(id=str(uuid4()), template_id=tid, checks=[], files=[], extra={}, version=0)
            try:
                body = ItemIn(kind=data['kind'], name=data['name'], note=data['note'], optional=data['optional'], per_vehicle=data['per_vehicle'],
                              checks=[CheckIn(id=old_checks.get((row.id, check['name'])), **check) for check in data['checks']],
                              files=[FileIn(**{key: value for key, value in document.items() if value is not None}) for document in data['files']],
                              quantity=data['quantity'], unit=data['unit'], spec=data['spec'])
            except ValueError as error:
                raise HTTPException(400, f'「事项」表第 {data["row"]} 行：{error}')
            row.section_id, row.sort_order = section.id, position
            row.kind, row.name, row.note, row.optional = body.kind, body.name, body.note, body.optional
            row.per_vehicle = body.per_vehicle
            row.step_key = (row.step_key or _new_step_key()) if row.per_vehicle else None
            _apply_checks(row, body.checks)
            files = []
            for document in body.files:
                values = document.model_dump()
                previous = old_files.get(values['code']) if values['code'] else None
                values['id'] = previous['id'] if previous else str(uuid4())
                values['blank_file_id'] = previous.get('blank_file_id') if previous else None
                values['source_metadata'] = previous.get('source_metadata') if previous else None
                if not values['code']:
                    values['code'] = _next_code(section.stage_key, {**{code: '' for code in explicit}, **used_codes})
                if values['code'] in used_codes:
                    raise HTTPException(400, f'「事项」表第 {data["row"]} 行：文件编号「{values["code"]}」与「{used_codes[values["code"]]}」重复')
                used_codes[values['code']] = row.name
                files.append(values)
            row.files = files
            row.quantity, row.unit, row.spec = body.quantity, body.unit, body.spec
            if old is not None:
                row.version = (row.version or 0) + 1
            db.add(row)
            kept_items.add(row.id)
            total += 1
    db.flush()
    for row in db.query(TemplateItem).filter(_scope(TemplateItem.template_id, tid)):
        if row.id not in kept_items:
            db.delete(row)
    db.flush()
    for row in sections_of(db, tid):
        if row.id not in kept_sections:
            db.delete(row)
    db.flush()
    log_change(db, None, 'template', template_id, 'import', actor_id,
               f'{template_label(db, template_id)}：从 Excel 导入 {len(parsed["sections"])} 个段落、{total} 件事')
    compile_template(db, tid)
    return {'sections': len(parsed['sections']), 'items': total}


# ===== Blank forms of a row's files =====

def _file_entry(db: Session, tid, item_id, file_id):
    row = _item(db, tid, item_id)
    for document in row.files or []:
        if document.get('id') == file_id:
            return row, document
    raise HTTPException(404, '文件不存在或已被删除，请刷新后重试')


def set_blank_file(db: Session, template_id, item_id, file_id, data: bytes, filename, content_type, actor_id):
    from app.services.document_requirements import create_file
    tid = lock(db, template_id, actor_id)
    row, document = _file_entry(db, tid, item_id, file_id)
    asset = create_file(db, data, filename, content_type, actor_id)
    row.files = [{**entry, 'blank_file_id': asset.id} if entry.get('id') == file_id else entry for entry in row.files]
    row.version = (row.version or 0) + 1
    log_change(db, None, 'template_item', row.id, 'update', actor_id,
               f'{template_label(db, template_id)}：上传「{document["code"]} {document["name"]}」的空白模板 {asset.filename}')
    compile_template(db, tid)
    return asset


def clear_blank_file(db: Session, template_id, item_id, file_id, actor_id):
    tid = lock(db, template_id, actor_id)
    row, document = _file_entry(db, tid, item_id, file_id)
    row.files = [{**entry, 'blank_file_id': None} if entry.get('id') == file_id else entry for entry in row.files]
    row.version = (row.version or 0) + 1
    log_change(db, None, 'template_item', row.id, 'update', actor_id,
               f'{template_label(db, template_id)}：移除「{document["code"]} {document["name"]}」的空白模板引用')
    compile_template(db, tid)


def blank_file(db: Session, template_id, item_id, file_id) -> DocumentTemplateFile:
    _, document = _file_entry(db, tid_of(template_id), item_id, file_id)
    asset = db.get(DocumentTemplateFile, document.get('blank_file_id')) if document.get('blank_file_id') else None
    if asset is None:
        raise HTTPException(404, '这份文件还没有空白模板')
    return asset

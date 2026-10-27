"""Excel/JSON import & export for the template and project snapshots.

Excel layout (sheet 1 "实施模板"):
    阶段 | 模块 | 模块类型 | 任务 | 数量规则 | 数量 | 单位 | 标准耗时 | 是否安全 | 检查项 | 必查 | 安全项
Each row = one check item (long format); tasks/modules/phases repeat.

项目Excel默认提供六张交付工作表；完整业务事实通过JSON和项目完整包保全。
"""

import io
import json
import os
from collections import defaultdict
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.models import Phase, Module, Task, CheckItem
from app.services.vehicle_checks import definition_data



def _beautify(ws, title, widths=None):
    """整表美化：标题行（主题蓝底白字合并）+ 表头（深蓝底白字）+ 细边框 + 交替行色 + 列宽。

    约定：调用前先 append 表头与数据；本函数在第 1 行插入标题行，表头随之变第 2 行。
    """
    ncols = max(ws.max_column, 1)
    thin = Side(style="thin", color="FFD9E2F0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.insert_rows(1)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(row=1, column=1, value=title)
    c.font = Font(bold=True, size=13, color="FFFFFF")
    c.fill = PatternFill(start_color="FF1677FF", end_color="FF1677FF", fill_type="solid")
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    for cell in ws[2]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="FF1F4E79", end_color="FF1F4E79", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[2].height = 20

    for row in ws.iter_rows(min_row=3):
        for cell in row:
            cell.border = border
            if cell.row % 2 == 1:
                cell.fill = PatternFill(start_color="FFF2F6FC", end_color="FFF2F6FC", fill_type="solid")

    ws.freeze_panes = "A3"
    if widths:
        for col, w in widths.items():
            ws.column_dimensions[col].width = w
    else:
        # 自动列宽：中文按双倍宽估算
        for col_idx in range(1, ncols + 1):
            letter = get_column_letter(col_idx)
            max_units = 0
            for cell in ws[col_idx]:
                text = str(cell.value or "")
                units = len(text) + sum(1 for ch in text if ord(ch) > 127)
                max_units = max(max_units, units)
            ws.column_dimensions[letter].width = min(max(max_units + 2, 9), 60)


# ===== Export =====

def template_to_excel(db: Session, template_id: str = "default") -> bytes:
    """Export only the selected template, preserving other template libraries."""
    from app.models import Template
    tid = None if template_id == "default" else template_id
    if tid is not None and db.get(Template, tid) is None:
        raise ValueError("模板不存在")
    wb = Workbook()
    ws = wb.active
    ws.title = "实施模板"
    ws.append(["阶段", "模块", "模块类型", "任务", "数量规则", "数量", "单位", "是否安全任务", "检查项", "必查", "安全项"])

    phases = db.query(Phase).filter(Phase.project_id.is_(None), Phase.template_id == tid).order_by(Phase.sort_order).all()
    for ph in phases:
        modules = db.query(Module).filter(Module.project_id.is_(None), Module.phase_id == ph.id).order_by(Module.sort_order).all()
        for m in modules:
            tasks = db.query(Task).filter(Task.project_id.is_(None), Task.module_id == m.id).order_by(Task.sort_order).all()
            for t in tasks:
                items = db.query(CheckItem).filter(CheckItem.project_id.is_(None), CheckItem.task_id == t.id).order_by(CheckItem.sort_order).all()
                if not items:
                    ws.append([ph.name, m.name, m.category, t.name, t.quantity_type,
                               t.target_quantity if t.target_quantity is not None else "", t.unit,
                               "是" if t.safety_flag else "否", "", "", ""])
                for ci in items:
                    ws.append([ph.name, m.name, m.category, t.name, t.quantity_type,
                               t.target_quantity if t.target_quantity is not None else "", t.unit,
                               "是" if t.safety_flag else "否", ci.name,
                               "是" if ci.is_required else "否",
                               "是" if ci.is_safety_critical else "否"])
    _beautify(ws, "AGV 实施模板")
    from app.services.document_requirements import export_bundle
    from app.services.document_requirement_workbook import add_sheets
    add_sheets(wb, export_bundle(db, template_id))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from app.config import MAX_UPLOAD_SIZE
    from fastapi import HTTPException
    if len(buf.getvalue()) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, "模板工作簿超过10MB导入上限，请压缩空白文件后再导出")
    return buf.getvalue()


def project_to_excel(db: Session, project_id: str, actor=None) -> bytes:
    """Six actor-scoped delivery sheets; full operational facts stay in JSON/packages."""
    from app.services.delivery_workbook import build_delivery_workbook
    return build_delivery_workbook(db, project_id, actor=actor)


def _safe_zip_name(name: str) -> str:
    """路径穿越防护：附件名只保留可见安全字符，去掉路径分隔/控制字符，防 ZIP 目录穿越。"""
    import re as _re
    name = _re.sub(r"[/\\\x00-\x1f]", "_", name or "附件")
    name = _re.sub(r"[^\w一-鿿.\-() ]", "_", name)
    return name.strip(" .")[:180] or "附件"


def _project_archive_evidence(db: Session, project, files_meta: list[dict], generated_at: str) -> dict:
    """Read-only handover evidence; never consumed by new-project import/clone."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from app.config import TIMEZONE
    from app.models import AcceptanceRecord, ArchiveChecklist, User
    from app.services.acceptance import acceptance_evidence
    from app.services.project_lifecycle import status_label

    for name in (project.timezone, TIMEZONE, "Asia/Shanghai"):
        try:
            zone = ZoneInfo(name or TIMEZONE)
            break
        except (ZoneInfoNotFoundError, ValueError):
            continue

    def local_time(raw):
        if not raw:
            return ""
        try:
            value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(zone).isoformat()
        except (TypeError, ValueError, OverflowError):
            return ""

    # Read the service-selected IDs first. A concurrently added immutable record
    # must not appear only in a later service read and miss the source-field map.
    selected_evidence = acceptance_evidence(db, project.id)
    original_records = {row.id: row for row in db.query(AcceptanceRecord).filter_by(project_id=project.id).all()}
    checks = db.query(ArchiveChecklist).filter_by(project_id=project.id).order_by(ArchiveChecklist.sort_order, ArchiveChecklist.id).all()
    original_retro = project.retrospective if isinstance(project.retrospective, dict) else (
        {"content": project.retrospective} if isinstance(project.retrospective, str) else {})
    author_id = original_retro.get("author")
    actor_ids = {value for value in (author_id, *(row.done_by for row in checks)) if isinstance(value, str) and value}
    for row in original_records.values():
        actor_ids.update((row.accepted_by, row.created_by))
    actor_ids.discard(None)
    actors = {row.id: row.display_name for row in db.query(User).filter(User.id.in_(actor_ids)).all()}
    files = {row["id"]: row for row in files_meta}

    def attachment_ref(attachment_id):
        if not attachment_id:
            return None
        if attachment_id not in files:
            return {"id": attachment_id, "missing": True, "reason": "attachment_not_in_project_manifest"}
        return dict(files[attachment_id])

    retrospective = {key: original_retro[key] for key in ("content", "success", "problems", "improvements", "author", "written_at") if key in original_retro}
    retrospective["author_name"] = actors.get(author_id, "") if isinstance(author_id, str) else ""
    retrospective["written_at_local"] = local_time(original_retro.get("written_at"))
    records = []
    for evidence in selected_evidence:
        row = original_records[evidence["id"]]
        records.append({
            **evidence,
            "accepted_by_name": evidence["accepted_by_name"] or actors.get(row.accepted_by, ""),
            "created_by": row.created_by,
            "scope_fingerprint": row.scope_fingerprint,
            "created_at_local": local_time(evidence["created_at"]),
            "attachment": attachment_ref(row.attachment_id),
        })
    return {
        "type": "agvpm-project-archive-evidence", "version": 1,
        "read_only": True, "import_supported": False,
        "notice": "只读项目交接记录。新项目导入及克隆不会继承这些验收结论或签字资格；完整系统恢复请使用系统备份。",
        "project": {"id": project.id, "name": project.name, "status": project.status,
                    "status_label": status_label(project.status), "timezone": project.timezone},
        "generated_at": generated_at, "generated_at_local": local_time(generated_at),
        "display_timezone": zone.key,
        "time_basis": "技术时间原值无偏移时按UTC解释；带偏移时保留原偏移。验收日期是项目当地业务日期。",
        "retrospective": retrospective,
        "current_acceptance_id": next((row["id"] for row in records if row["is_effective"]), None),
        "acceptance_records": records,
        "archive_checklist": [{
            "id": row.id, "category": row.category, "item_name": row.item_name,
            "is_required": row.is_required, "is_done": row.is_done,
            "requirements": row.requirements or {}, "done_by": row.done_by,
            "done_by_name": actors.get(row.done_by, ""),
            "done_at": row.done_at.isoformat() if row.done_at else None,
            "done_at_local": local_time(row.done_at.isoformat() if row.done_at else None),
            "attachment_id": row.attachment_id, "attachment": attachment_ref(row.attachment_id),
        } for row in checks],
    }


def _archive_evidence_html(evidence: dict) -> str:
    """Self-contained handover view; technical provenance stays collapsed."""
    from datetime import datetime
    from html import escape
    from urllib.parse import quote
    import json

    def text(value):
        return escape(str(value if value is not None else ""), quote=True)

    def local_time_text(local, raw=None):
        try:
            return datetime.fromisoformat(local).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return "原时间格式未知，可展开查看" if raw else "未记录"

    def raw_details(content):
        return f'<details><summary>原始记录与校验信息</summary><div class="content muted">{content}</div></details>'

    def file_text(item):
        if not item:
            return '<p class="muted">未关联附件</p>'
        label = item.get("name") or "附件名称未记录"
        raw = f'附件ID：{text(item["id"])}<br>包内路径：{text(item.get("archive_path") or "未记录")}'
        if item.get("missing") or not item.get("archive_path"):
            visible = f'{text(label)} · 附件缺失，未包含文件内容'
            raw += f'<br>缺失原因：{text(item.get("reason") or "文件内容不可用")}'
        else:
            href = quote(item["archive_path"], safe="/")
            visible = f'<a href="{text(href)}">{text(label)}</a> · {text(item["size"])} 字节'
            raw += f'<br>SHA-256：{text(item["sha256"])}'
        return f'<div class="file-record"><p>{visible}</p>{raw_details(raw)}</div>'

    def requirement_text(requirements):
        known = []
        if isinstance(requirements, dict):
            for key, label in (("doc_type", "文件格式"), ("version_requirement", "版本要求"), ("notes", "补充说明")):
                if requirements.get(key):
                    known.append(f'{label}：{text(requirements[key])}')
            signoff = requirements.get("signoff_required")
            if isinstance(signoff, bool):
                known.append(f'客户签字：{"需要" if signoff else "不需要"}')
        if known:
            return '<div class="content">' + '<br>'.join(known) + '</div>'
        return '<p class="muted">其他交付要求见原始记录</p>' if requirements else '<p class="muted">无额外要求</p>'

    retro = evidence["retrospective"]
    retro_sections = []
    for key, title in (("content", "复盘原文"), ("success", "成功经验"), ("problems", "问题教训"), ("improvements", "改进建议")):
        if retro.get(key):
            retro_sections.append(f'<h3>{title}</h3><div class="content">{text(retro[key])}</div>')
    retro_html = "".join(retro_sections) or '<p class="muted">尚未填写项目复盘。</p>'
    retro_raw = f'原作者ID：{text(retro.get("author") or "未记录")}<br>原填写时间：{text(retro.get("written_at") or "未记录")}'
    records_html = []
    conclusions = {"accepted": "通过", "conditionally_accepted": "有条件通过", "rejected": "不通过"}
    for row in evidence["acceptance_records"]:
        scope = "当前范围" if row["scope_current"] else ("范围已变更" if row["scope_verified"] else "历史范围未验证")
        title = "当前最新验收" if row["is_effective"] else "历史验收"
        date_state = "" if row["effective_date_reached"] else " · 日期尚未生效"
        raw = f'记录ID：{text(row["id"])}<br>原验收人ID：{text(row["accepted_by"] or "未记录")}<br>原录入人ID：{text(row["created_by"] or "未记录")}<br>原录入时间：{text(row["created_at"] or "未记录")}<br>原范围指纹：{text(row["scope_fingerprint"] or "未记录")}'
        records_html.append(f'''<article><h3>{title} · {text(conclusions.get(row["conclusion"], row["conclusion"]))}</h3>
<p>验收人：{text(row["accepted_by_name"] or "验收人姓名未记录")}<br>验收日期：{text(row["accepted_at"])}<br>{text(scope)}{date_state}</p>
<p>录入人：{text(row["creator_name"] or "原录入人已不存在或未记录")}<br>录入时间：{text(local_time_text(row["created_at_local"], row["created_at"]))}</p>
<div class="content">{text(row["notes"])}</div>{file_text(row["attachment"])}
{raw_details(raw)}</article>''')
    checks_html = []
    for row in evidence["archive_checklist"]:
        raw = f'清单ID：{text(row["id"])}<br>原完成人ID：{text(row["done_by"] or "未记录")}<br>原完成时间：{text(row["done_at"] or "未记录")}<br>原交付要求：{text(json.dumps(row["requirements"], ensure_ascii=False))}'
        checks_html.append(f'''<article><h3>{text(row["category"])} · {text(row["item_name"])}</h3>
<p>{"必需" if row["is_required"] else "可选"} · {"已完成" if row["is_done"] else "未完成"}<br>完成人：{text(row["done_by_name"] or "未记录或原账号已不存在")}<br>完成时间：{text(local_time_text(row["done_at_local"], row["done_at"]))}</p>
{requirement_text(row["requirements"])}{file_text(row["attachment"])}{raw_details(raw)}</article>''')
    project = evidence["project"]
    project_raw = f'项目ID：{text(project["id"])}<br>原状态：{text(project["status"])}<br>项目原时区：{text(project["timezone"] or "未记录")}<br>时间展示时区：{text(evidence["display_timezone"])}<br>原导出时间：{text(evidence["generated_at"])}<br>{text(evidence["time_basis"])}<br><a href="{quote("归档记录.json")}">查看完整归档记录 JSON</a>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{text(project["name"])} · 项目归档记录</title><style>
*{{box-sizing:border-box}}html{{color-scheme:light;background:#fff;color:#17212b}}body{{max-width:1000px;margin:24px auto;padding:16px;font:16px/1.7 system-ui,sans-serif;overflow-wrap:anywhere}}
h1{{font-size:26px}}h2{{font-size:22px;margin-top:32px}}h3{{font-size:18px}}article{{border:1px solid #ccd4de;border-radius:6px;padding:16px;margin:12px 0}}.content{{white-space:pre-wrap;overflow-wrap:anywhere}}.muted{{color:#536273;font-size:14px}}.notice{{border-left:4px solid #466da5;padding:12px;background:#f4f7fb}}a{{color:#174e99}}details{{border-top:1px solid #edf1f5;margin-top:12px}}summary{{cursor:pointer;min-height:44px;padding:8px 0;color:#466da5;font-size:14px}}@media(max-width:480px){{body{{margin:0}}}}@media print{{body{{max-width:none;margin:0}}h2,h3{{break-after:avoid}}article{{break-inside:auto}}}}
</style></head><body><h1>{text(project["name"])} · 项目归档记录</h1>
<p class="notice">{text(evidence["notice"])}<br>“当前最新验收”仅表示导出时的验收记录顺序，不代替全部完成及归档条件。</p>
<p>项目状态：{text(project["status_label"])}<br>导出时间：{text(local_time_text(evidence["generated_at_local"], evidence["generated_at"]))}<br><span class="muted">以下日期与时间按项目当地显示。</span></p>
{raw_details(project_raw)}<h2>项目复盘</h2>
<p>作者：{text(retro["author_name"] or "原作者已不存在或未记录")}<br>填写时间：{text(local_time_text(retro["written_at_local"], retro.get("written_at")))}</p>{retro_html}{raw_details(retro_raw)}
<h2>验收记录（当前与全部历史）</h2>{"".join(records_html) or '<p class="muted">暂无验收记录。</p>'}
<h2>交付资料归档清单</h2>{"".join(checks_html) or '<p class="muted">暂无归档清单。</p>'}
</body></html>'''


def project_package_stream(db: Session, project_id: str, actor=None):
    """HYPE-58：项目整包导出 —— ZIP(项目数据.xlsx + 项目备份.json + files/ + manifest.json)。

    - 附件名做路径穿越防护；重名自动加序号去重（archive_path 唯一）；
    - manifest.json 记录每个文件 SHA-256 与缺失标记；磁盘文件缺失不中断打包；
    - 只读归档记录单独保存验收/复盘证据，不赋予新项目验收资格；
    - Excel为六张交付表；JSON保留完整授权业务事实。
    """
    import hashlib
    import json as stdjson
    import zipfile
    import tempfile
    import stat
    from app.config import UPLOAD_DIR
    from app.models import Attachment, Project
    from app.time_utils import utcnow

    p = db.get(Project, project_id)
    if p is None:
        raise ValueError("项目不存在")

    xlsx = project_to_excel(db, project_id,actor=actor)
    snapshot = project_to_json(db, project_id,actor=actor)
    from app.services.delivery_workbook import visible_delivery_files
    attachments = sorted(visible_delivery_files(db, p, actor).values(), key=lambda row: (row.filename or '', row.id))
    upload_root = UPLOAD_DIR.resolve()

    used_names: set[str] = set()
    files_meta: list[dict] = []
    # Formal originals may be 2 GiB. Spill ZIP output after 8 MiB and copy each
    # input in 1-MiB blocks; the HTTP caller closes this handle after streaming.
    from app.services.document_packages import export_directory
    buf = tempfile.SpooledTemporaryFile(max_size=8*1024*1024,mode='w+b',dir=export_directory())
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("项目数据.xlsx", xlsx)
        zf.writestr("项目备份.json", stdjson.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8"))

        for att in attachments:
            base = _safe_zip_name(att.filename or att.stored_name or "附件")
            arc = base
            n = 1
            while arc in used_names:  # 去重：同名自动加序号
                root, ext = os.path.splitext(base)
                arc = f"{root}-{n}{ext}"
                n += 1
            used_names.add(arc)
            arcname = f"files/{arc}"
            meta = {
                "id": att.id,
                "name": att.filename or "",
                "archive_path": arcname,
                "category": att.category or "",
                "entity_type": att.entity_type or "",
                "uploaded_at": att.uploaded_at.isoformat() if att.uploaded_at else None,
            }
            from app.services.file_retention import removal_record,removal_payload
            if removal_record(att,db):
                meta.update(removal_payload(att),archive_path=None,size=att.file_size,sha256=att.sha256,
                    byte_recovery='历史原字节已按明确授权策略清理，包内只保留原提交元数据和清理凭据')
                files_meta.append(meta)
                continue
            disk = (UPLOAD_DIR / att.stored_name).resolve()
            if upload_root not in disk.parents:  # 路径穿越防护：必须落在 UPLOAD_DIR 内
                meta["missing"] = True
                meta["reason"] = "storage_path_outside_upload_dir"
                files_meta.append(meta)
                continue
            try:
                if (UPLOAD_DIR/att.stored_name).is_symlink():raise OSError('unsafe original')
                descriptor=os.open(disk,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                digest=hashlib.sha256();size=0
                with os.fdopen(descriptor,'rb') as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):raise OSError('unsafe original')
                    with zf.open(arcname,'w',force_zip64=True) as target:
                        for block in iter(lambda:source.read(1024*1024),b''):
                            digest.update(block);size+=len(block);target.write(block)
                meta['size']=size;meta['sha256']=digest.hexdigest()
            except OSError:
                meta["missing"] = True
            files_meta.append(meta)

        generated_at = utcnow().isoformat()
        evidence = _project_archive_evidence(db, p, files_meta, generated_at)
        zf.writestr("归档记录.json", stdjson.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8"))
        zf.writestr("归档记录.html", _archive_evidence_html(evidence).encode("utf-8"))
        manifest = {
            "type": "agvpm-project-package",
            "version": "2.4",
            "project": {"id": p.id, "name": p.name, "status": p.status},
            "generated_at": generated_at,
            "archive_records": {"json": "归档记录.json", "html": "归档记录.html", "read_only": True},
            "file_count": len(files_meta),
            "missing_count": sum(1 for f in files_meta if f.get("missing")),
            "files": files_meta,
        }
        zf.writestr("manifest.json", stdjson.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    buf.seek(0)
    return buf


def project_package_zip(db: Session, project_id: str, actor=None) -> bytes:
    """Small in-process compatibility seam; HTTP uses project_package_stream."""
    with project_package_stream(db,project_id,actor) as package:return package.read()


# ===== Import =====

def template_from_excel(db: Session, data: bytes, template_id: str = "default", actor_id: str | None = None) -> dict:
    """Replace the selected Excel tree without losing unchanged node identities.

    Excel carries only the visible task/check columns. Configuration and reference
    documents outside those columns remain attached to matching existing nodes.
    The caller owns the commit so the import and its audit record are atomic.
    """
    import math
    from app.models import Template, TemplateDoc
    tid = None if template_id == "default" else template_id
    template = db.get(Template, tid) if tid is not None else None
    if tid is not None and template is None:
        raise ValueError("模板不存在")
    from app.services.document_requirement_workbook import check_workbook_size, parse_sheets
    from app.services.document_requirements import replace_bundle
    check_workbook_size(data)
    wb = load_workbook(io.BytesIO(data))
    try:
        documents = parse_sheets(wb)
        ws = wb["实施模板"] if "实施模板" in wb.sheetnames else wb.active
        header = [str(cell.value or "").strip() for cell in ws[2]]
        has_hours = len(header) > 7 and header[7] == "标准耗时"
        parsed = []
        task_values = {}
        for row_number, raw in enumerate(ws.iter_rows(min_row=3, values_only=True), 3):
            if not raw or not any(value not in (None, "") for value in raw):
                continue
            row = list(raw) + [None] * max(0, 12 - len(raw))
            ph_name, mod_name, mod_cat, task_name, qtype = row[:5]
            if not all(isinstance(value, str) and value.strip() for value in (ph_name, mod_name, task_name)):
                raise ValueError(f"第 {row_number} 行缺少阶段、模块或任务名称，未修改现有模板")
            ph_name, mod_name, task_name = (value.strip() for value in (ph_name, mod_name, task_name))
            mod_cat, qtype = mod_cat or "core", qtype or "manual"
            if mod_cat not in ("core", "extra") or qtype not in ("per_vehicle", "manual", "fixed"):
                raise ValueError(f"第 {row_number} 行模块类型或数量规则无效，未修改现有模板")
            qty, unit = row[5:7]
            hours = row[7] if has_hours else None
            safety, ci_name, ci_req, ci_safety = row[8:12] if has_hours else row[7:11]
            def number(value, label):
                if value in (None, ""):
                    return None
                try:
                    result = float(value)
                    if isinstance(value, bool) or not math.isfinite(result) or result < 0:
                        raise ValueError
                    return result
                except (TypeError, ValueError):
                    raise ValueError(f"第 {row_number} 行{label}必须是有限非负数，未修改现有模板") from None
            values = (mod_cat, qtype, number(qty, "数量"), str(unit or "项"), str(safety) == "是", number(hours, "耗时"))
            key = ph_name, mod_name, task_name
            if key in task_values and task_values[key] != values:
                raise ValueError(f"第 {row_number} 行同一任务的重复配置不一致，未修改现有模板")
            task_values[key] = values
            parsed.append((key, values, str(ci_name).strip() if ci_name else "", ci_req, ci_safety))
    finally:
        wb.close()
    if not parsed:
        raise ValueError("文件没有有效任务，未修改现有模板")

    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, actor_id, "system.template_io.manage")
    old = {model: db.query(model).filter(model.project_id.is_(None), model.template_id == tid).all()
           for model in (Phase, Module, Task, CheckItem)}
    def unique_index(rows, key):
        result = {}
        for item in rows:
            identity = key(item)
            if identity in result:
                raise ValueError("当前模板含同层级重名项，Excel 无法安全区分，请在模板编辑器中调整后再导入")
            result[identity] = item
        return result
    old_phases = unique_index(old[Phase], lambda item: item.name)
    old_modules = unique_index(old[Module], lambda item: (item.phase_id, item.name))
    old_tasks = unique_index(old[Task], lambda item: (item.module_id, item.name))
    old_checks = defaultdict(list)
    for item in sorted(old[CheckItem], key=lambda item: item.sort_order or 0):
        old_checks[(item.task_id, item.name)].append(item)

    phase_map, module_map, task_map = {}, {}, {}
    retained = {model: set() for model in old}
    check_orders = defaultdict(int)
    counts = {"phases": 0, "modules": 0, "tasks": 0, "check_items": 0}
    for (ph_name, mod_name, task_name), values, ci_name, ci_req, ci_safety in parsed:
        mod_cat, qtype, qty, unit, safety, hours = values
        if ph_name not in phase_map:
            phase = old_phases.get(ph_name)
            if phase is None:
                phase = Phase(project_id=None, template_id=tid, name=ph_name)
                db.add(phase)
            phase.sort_order = len(phase_map) + 1
            db.flush()
            phase_map[ph_name] = phase
            retained[Phase].add(phase.id)
            counts["phases"] += 1
        phase = phase_map[ph_name]
        mkey = ph_name, mod_name
        if mkey not in module_map:
            module = old_modules.get((phase.id, mod_name))
            if module is None:
                module = Module(project_id=None, template_id=tid, phase_id=phase.id,
                                name=mod_name, is_selected=(mod_cat != "extra"))
                db.add(module)
            module.category = mod_cat
            module.sort_order = sum(key[0] == ph_name for key in module_map) + 1
            db.flush()
            module_map[mkey] = module
            retained[Module].add(module.id)
            counts["modules"] += 1
        module = module_map[mkey]
        tkey = ph_name, mod_name, task_name
        if tkey not in task_map:
            task = old_tasks.get((module.id, task_name))
            if task is None:
                task = Task(project_id=None, template_id=tid, module_id=module.id, name=task_name)
                db.add(task)
            task.quantity_type, task.target_quantity, task.unit, task.safety_flag = qtype, qty, unit, safety
            if qtype != "per_vehicle":
                task.vehicle_step_key = None
            if has_hours:
                task.standard_hours = hours
            task.sort_order = sum(key[:2] == mkey for key in task_map) + 1
            db.flush()
            task_map[tkey] = task
            retained[Task].add(task.id)
            counts["tasks"] += 1
        task = task_map[tkey]
        if ci_name:
            candidates = old_checks[(task.id, ci_name)]
            check = candidates.pop(0) if candidates else CheckItem(
                project_id=None, template_id=tid, task_id=task.id, name=ci_name)
            db.add(check)
            check.is_required = str(ci_req or "是") == "是"
            check.is_safety_critical = str(ci_safety or "否") == "是"
            check.sort_order = check_orders[task.id]
            check_orders[task.id] += 1
            db.flush()
            retained[CheckItem].add(check.id)
            counts["check_items"] += 1

    removed_task_ids = {task.id for task in old[Task]} - retained[Task]
    if removed_task_ids:
        db.query(TemplateDoc).filter(TemplateDoc.task_id.in_(removed_task_ids)).delete(synchronize_session=False)
    for model in (CheckItem, Task, Module, Phase):
        removed_ids = {item.id for item in old[model]} - retained[model]
        if removed_ids:
            db.query(model).filter(model.id.in_(removed_ids)).delete(synchronize_session=False)
    if template is not None:
        template.status = "draft"
    replace_bundle(db, template_id, documents, actor_id, "system.template_io.manage")
    db.flush()
    return {"document_requirements": len(documents[0]) if documents else None, "message": f"模板导入成功：{counts['phases']} 阶段，{counts['modules']} 模块，{counts['tasks']} 任务，{counts['check_items']} 检查项", **counts}


def project_to_json(db: Session, project_id: str, actor=None, include_documents=True) -> dict:
    """Full project snapshot as JSON (template + vehicles + progress)."""
    from app.services.project_events import iso_utc
    from app.models import (
        Project, ProjectEvent, Vehicle, VehicleUnit, VehicleLifecycleEvent,
        ProjectPreparationItem, ArchiveChecklist, ScheduleEntry, DailyProgress, Issue,
        ProjectInventoryItem, ProjectInventoryMovement,
    )
    p = db.get(Project, project_id)
    if p is None:
        raise ValueError("项目不存在")
    from app.models import ProjectSchedulePolicy, TaskDurationOverride, ChangeLog
    policy = db.query(ProjectSchedulePolicy).filter_by(project_id=project_id).first()
    overrides = {row.task_id: row for row in db.query(TaskDurationOverride).filter_by(project_id=project_id).all()}
    snapshot = {
        "type": "agvpm-project",
        "version": "2.4",
        "project": {
            "name": p.name,
            "abbreviation": p.abbreviation,
            "client": p.client,
            "location": p.location,
            "timezone": p.timezone or "Asia/Shanghai",
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "description": p.description,
            "status": p.status,
            "legacy_lifecycle": p.legacy_lifecycle,
            "suspension": p.suspension or {},
            "planned_entry_date": p.planned_entry_date.isoformat() if p.planned_entry_date else None,
            "dispatch_platform": p.dispatch_platform,
            "staffing_notes": p.staffing_notes or "",
            "conditions": {key: key in (p.prep_conditions or []) for key in ("need_wms", "need_charging", "client_server", "new_vehicles", "overseas")},
            "rest_mode": p.rest_mode,
            "rest_days": p.rest_days or [],
            "skip_holidays": bool(p.skip_holidays),
            "client_contacts": p.client_contacts or [],
            "entry_plan": p.entry_plan or {},
        },
        "vehicles": [
            {"vehicle_type": v.vehicle_type, "model_name": v.model_name, "quantity": v.quantity,
             "configuration": v.configuration or {}, "notes": v.notes or "", "sort_order": v.sort_order}
            for v in db.query(Vehicle).filter(Vehicle.project_id == project_id).order_by(Vehicle.sort_order).all()
        ],
        "modules": [],
        "project_events": [{"event_key": e.event_key, "planned_date": e.planned_date.isoformat() if e.planned_date else None,
            "actual_at": iso_utc(e.actual_at),
            "recorded_by": e.recorded_by, "note": e.note or ""}
            for e in db.query(ProjectEvent).filter_by(project_id=project_id).order_by(ProjectEvent.event_key)],
        "vehicle_units": [],
        "preparations": [],
        "inventory_items": [],
        "archive_checklist": [],
        "schedule": [],
        "progress": [],
        "issues": [],
        "planning_schedule": {"duration_scale": policy.duration_scale if policy else None, "task_durations": [], "read_only": True},
    }
    from app.services.inventory_time import inventory_time_basis

    from app.services.work_items import portable_modules
    snapshot['modules'],snapshot['legacy_work_items']=portable_modules(db,project_id)
    for task in db.query(Task).filter_by(project_id=project_id):
        budget=overrides.get(task.id)
        if budget is not None:
            snapshot['planning_schedule']['task_durations'].append({'task_source_id':task.id,'workdays':budget.workdays,
                'baseline_quantity':budget.baseline_quantity,'baseline_unit':budget.baseline_unit,'is_active':bool(budget.is_active)})
    from app.services.legacy_planning_source import snapshot as legacy_planning_snapshot
    from app.services.project_retention import _row
    from app.models import WeeklyPlanCell
    snapshot['legacy_planning_source']=legacy_planning_snapshot(db,project_id)
    snapshot['weekly_plan_source']={'read_only':True,'meaning':'原项目周计划仅供核对，新项目需重新确认范围、负责人和发布',
        'cells':[_row(row) for row in db.query(WeeklyPlanCell).filter_by(project_id=project_id).order_by(WeeklyPlanCell.id)]}
    vehicle_map = {v.id: v for v in db.query(Vehicle).filter_by(project_id=project_id).all()}
    for unit in db.query(VehicleUnit).filter_by(project_id=project_id).order_by(VehicleUnit.asset_code).all():
        _vehicle = vehicle_map.get(unit.vehicle_id)
        snapshot["vehicle_units"].append({
            "source_id": unit.id, "asset_code": unit.asset_code, "serial_number": unit.serial_number,
            "vehicle_type": _vehicle.vehicle_type if _vehicle else "",
            "model_name": _vehicle.model_name if _vehicle else "",
            "fleet_no": unit.fleet_no or "", "current_stage": unit.current_stage, "legacy_current_stage": unit.legacy_current_stage, "current_status": unit.current_status, "location": unit.location,
            "arrived_at": unit.arrived_at.isoformat() if unit.arrived_at else None,
            "warranty_end": unit.warranty_end.isoformat() if unit.warranty_end else None,
            "commissioned_at": unit.commissioned_at.isoformat() if unit.commissioned_at else None, "note": unit.note,
            "events": [{
                "event_type": event.event_type, "event_date": event.event_date.isoformat(), "title": event.title,
                "description": event.description, "stage_after": event.stage_after,
                "status_after": event.status_after, "location_after": event.location_after,
                "fault_part": event.fault_part, "cause": event.cause, "action_taken": event.action_taken,
                "replaced_parts": event.replaced_parts or [], "downtime_hours": event.downtime_hours,
                "verification": event.verification, "handler": event.handler, "is_closed": bool(event.is_closed),
            } for event in db.query(VehicleLifecycleEvent).filter_by(vehicle_unit_id=unit.id).order_by(VehicleLifecycleEvent.event_date).all()],
        })
    for item in db.query(ProjectPreparationItem).filter_by(project_id=project_id).order_by(ProjectPreparationItem.sort_order).all():
        snapshot["preparations"].append({
            "category": item.category, "name": item.name, "is_required": item.is_required,
            "blocks_entry": item.blocks_entry, "status": item.status, "owner_party": item.owner_party,
            "required_date": item.required_date.isoformat() if item.required_date else None,
            "committed_date": item.committed_date.isoformat() if item.committed_date else None,
            "forecast_date": item.forecast_date.isoformat() if item.forecast_date else None,
            "actual_date": item.actual_date.isoformat() if item.actual_date else None,
            "risk": item.risk, "note": item.note, "extra": item.extra or {}, "sort_order": item.sort_order,
        })
    snapshot["archive_checklist"] = [{
        "category": item.category, "item_name": item.item_name, "is_required": item.is_required,
        "is_done": item.is_done, "requirements": item.requirements or {}, "sort_order": item.sort_order,
    } for item in db.query(ArchiveChecklist).filter_by(project_id=project_id).order_by(ArchiveChecklist.sort_order).all()]
    for item in db.query(ProjectInventoryItem).filter_by(project_id=project_id).order_by(ProjectInventoryItem.name).all():
        snapshot["inventory_items"].append({
            "item_code": item.item_code, "name": item.name, "category": item.category,
            "ownership": item.ownership, "tracking_mode": item.tracking_mode,
            "specification": item.specification, "serial_number": item.serial_number,
            "quantity": item.quantity, "minimum_quantity": item.minimum_quantity, "unit": item.unit,
            "status": item.status, "location": item.location, "custodian": item.custodian,
            "supplier": item.supplier,
            "received_date": item.received_date.isoformat() if item.received_date else None,
            "expected_return_date": item.expected_return_date.isoformat() if item.expected_return_date else None,
            "note": item.note, "extra": item.extra or {},
            "movements": [{
                "movement_type": movement.movement_type, "quantity": movement.quantity,
                "balance_after": movement.balance_after, "from_location": movement.from_location,
                "to_location": movement.to_location, "handler": movement.handler,
                "occurred_at": movement.occurred_at.isoformat(), "time_basis": inventory_time_basis(movement), "note": movement.note,
            } for movement in db.query(ProjectInventoryMovement).filter_by(item_id=item.id).order_by(ProjectInventoryMovement.occurred_at).all()],
        })
    task_names = {task.id: task.name for task in db.query(Task).filter_by(project_id=project_id).all()}
    snapshot["schedule"] = [{
        "task_source_id": item.task_id,
        "task_name": task_names.get(item.task_id, ""), "work_date": item.work_date.isoformat(),
        "planned_quantity": item.planned_quantity, "status": item.status, "notes": item.notes,
    } for item in db.query(ScheduleEntry).filter_by(project_id=project_id).order_by(ScheduleEntry.work_date).all()]
    snapshot["progress"] = [{
        "id":item.id,"project_id":item.project_id,"task_source_id": item.task_id,
        "task_name": task_names.get(item.task_id, ""), "work_date": item.work_date.isoformat(),
        "completed_quantity": item.completed_quantity, "note": item.note,
        "user_id":item.user_id,"source":item.source,"client_uuid":item.client_uuid,
        "schedule_entry_id":item.schedule_entry_id,"created_at":iso_utc(item.created_at),
    } for item in db.query(DailyProgress).filter_by(project_id=project_id).order_by(DailyProgress.work_date).all()]
    snapshot["issues"] = [{
        "source_id":item.id,"created_at":item.created_at.isoformat() if item.created_at else None,
        "title": item.title, "description": item.description, "issue_type": item.issue_type,
        "nature":item.nature,
        "source_metadata":item.source_metadata,
        "severity": item.severity, "status": item.status, "resolution": item.resolution, "extra": item.extra or {},
    } for item in db.query(Issue).filter_by(project_id=project_id).order_by(Issue.created_at).all()]
    from app.services.project_documents import export_snapshot
    if include_documents:snapshot.update(export_snapshot(db,p,actor))
    from app.services.vehicle_progress import matrix
    snapshot["vehicle_progress_matrix"] = {**matrix(db, project_id), "read_only": True}
    from app.services.delivery_workbook import execution_evidence
    snapshot['execution_evidence'] = execution_evidence(db, project_id)
    from app.services.field_operations import export_evidence
    snapshot['field_operation_evidence']=export_evidence(db,p,actor)
    if p.portable_unverified_snapshot is not None:
        snapshot['portable_unverified_snapshot'] = p.portable_unverified_snapshot

    return snapshot

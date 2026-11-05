"""Project report forms: 生命周期表 / 质量问题反馈单 / 内部联系单.

面向三个交付物：
- 生命周期表.xlsx：车辆问题履历的扁平表格（导出/导入 → VehicleLifecycleEvent）
- 质量问题反馈单.xlsx：单条质量反馈单据（导出/导入 → Issue）
- 内部联系单.docx：申请物品/服务的 Word 联系单（导出/导入 → ItemApplication）
"""

import hashlib
import io
import re
import zipfile
from datetime import date, datetime
from typing import Optional

from dateutil.parser import parse as parse_datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from sqlalchemy.orm import Session

from app.models import (
    Project, Vehicle, VehicleUnit, VehicleLifecycleEvent, Issue, ItemApplication, Attachment,
)

_ISSUE_TYPES = ("fault", "repair", "maintenance", "inspection", "other")

_QUALITY_TYPE_CN = {
    "hardware": "硬件", "software": "软件", "environment": "环境",
    "process": "流程", "safety": "安全", "other": "其他",
}
_QUALITY_TYPE_EN = {value: key for key, value in _QUALITY_TYPE_CN.items()}


def _beautify(ws, title, widths=None):
    """整表美化：标题行 + 表头 + 细边框 + 交替行色 + 列宽（与 import_export._beautify 同风格）。"""
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


def _parse_loose_date(value) -> Optional[date]:
    """解析生命周期表/质量反馈单中的宽松日期：2023/5/4、2023-05-21 00:00:00、datetime 等。"""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_datetime(text, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None


def _split_multiline(value) -> list[str]:
    """把一个单元格里多行/多问题拆成若干条。

    附件原表常以换行或连续空格分隔同一格内的多条内容（中文不含连续空格，安全）。
    """
    if value is None:
        return []
    text = str(value).replace("\r", "\n")
    return [line.strip() for line in re.split(r"\n+| {2,}", text) if line.strip()]


# ===== 生命周期表 =====

LIFECYCLE_HEADERS = ["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类", "变更内容", "记录人", "记录时间"]
LIFECYCLE_WIDTHS = {"A": 8.8, "B": 15, "C": 18.6, "D": 16.4, "E": 16, "F": 55.8, "G": 15.1, "H": 13.1, "I": 15, "J": 23.3, "K": 8.8, "L": 11.5}
LEGACY_LIFECYCLE_HEADERS = ["序号", "项目名称", "车辆型号", "车辆编号", "车号", "出现过的问题", "问题描述", "解决方法", "记录人", "记录时间", "问题分类"]
_EVENT_CATEGORY = {"fault": "故障", "repair": "维修", "maintenance": "保养", "inspection": "检查", "other": "其他"}


def dotted(value) -> str:
    """Company forms write dates as 2026.5.23."""
    value = _parse_loose_date(value) if not isinstance(value, date) else value
    return f"{value.year}.{value.month}.{value.day}" if value else ""


def _form_date(value) -> Optional[date]:
    """A form date must carry its year; 5.23 alone is not guessed into the current year."""
    if isinstance(value, (date, datetime)):
        return _parse_loose_date(value)
    text = str(value or "").strip()
    if not text or not re.search(r"\d{4}", text):
        return None
    return _parse_loose_date(text)


def lifecycle_columns(project, vehicle, unit, event, users=None) -> list:
    """One vehicle record as the 12 columns of the AGV lifecycle table (sequence number first)."""
    extra = (event.extra or {}) if event else {}
    users = users or {}
    content = ""
    if event:
        title, action = (event.title or "").strip(), (event.action_taken or "").strip()
        content = title if not action or action == title else f"{title}：{action}"
    recorder = (event.handler or users.get(event.operator_id, "")) if event else ""
    recorded = extra.get("recorded_on") or (event.created_at.date() if event and event.created_at else None)
    configuration = (vehicle.configuration or {}) if vehicle else {}
    return [
        None, project.name, project.contract_no or "",
        (vehicle.model_name if vehicle else "") or (unit.model_name if unit else "") or extra.get("model_name", ""),
        str(configuration.get("config_no") or extra.get("config_no") or ""),
        unit.asset_code if unit else "",
        dotted(event.event_date) if event else "",
        (unit.fleet_no if unit else "") or extra.get("fleet_no", ""),
        (extra.get("category") or _EVENT_CATEGORY.get(event.event_type, "")) if event else "",
        content, recorder, dotted(recorded) if event else "",
    ]


def lifecycle_to_excel(db: Session, project_id: str, *, events=None, title=None) -> bytes:
    """项目车辆记录导出为公司「AGV生命周期表」：同一天、同一分类、同一变更的多台车合成一行。"""
    p = db.get(Project, project_id)
    if p is None:
        raise ValueError("项目不存在")
    from app.models import User
    units = {u.id: u for u in db.query(VehicleUnit).filter_by(project_id=project_id).all()}
    vehicles = {v.id: v for v in db.query(Vehicle).filter_by(project_id=project_id).all()}
    if events is None: events = (db.query(VehicleLifecycleEvent)
              .filter(VehicleLifecycleEvent.project_id == project_id,
                      VehicleLifecycleEvent.event_type.in_(_ISSUE_TYPES))
              .order_by(VehicleLifecycleEvent.event_date, VehicleLifecycleEvent.created_at)
              .all())
    operator_ids = {event.operator_id for event in events if event.operator_id}
    users = {u.id: u.display_name for u in db.query(User).filter(User.id.in_(operator_ids))} if operator_ids else {}
    rows, grouped = [], {}
    for event in events:
        unit = units.get(event.vehicle_unit_id)
        vehicle = vehicles.get(unit.vehicle_id) if unit and unit.vehicle_id else None
        columns = lifecycle_columns(p, vehicle, unit, event, users)
        key = tuple(columns[i] for i in (3, 4, 6, 8, 9, 10, 11))
        if key in grouped:
            row = grouped[key]
            row[5] = "、".join(filter(None, [row[5], columns[5]]))
            row[7] = ".".join(filter(None, [row[7], columns[7]]))
            continue
        grouped[key] = columns
        rows.append(columns)

    wb = Workbook()
    ws = wb.active
    ws.title = "AGV生命周期表"
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.merge_cells("A1:L1")
    ws["A1"] = title or "AGV生命周期表"
    ws["A1"].font = Font(name="等线", size=20, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25
    for column, name in enumerate(LIFECYCLE_HEADERS, start=1):
        cell = ws.cell(row=2, column=column, value=name)
        cell.font = Font(name="等线", size=11, bold=True)
        cell.alignment = center
    for index, columns in enumerate(rows, start=1):
        columns[0] = index
        ws.append(columns)
    for row in ws.iter_rows(min_row=1, max_row=max(ws.max_row, 2), max_col=len(LIFECYCLE_HEADERS)):
        for cell in row:
            cell.border = border
            if cell.row > 2:
                cell.font = Font(name="等线", size=11)
                cell.alignment = center
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for column, width in LIFECYCLE_WIDTHS.items():
        ws.column_dimensions[column].width = width
    ws.freeze_panes = "A3"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _unmerge_values(ws):
    """Rows covered by a merged cell carry the merged value (company sheets merge vehicle columns)."""
    for merged in list(ws.merged_cells.ranges):
        value = ws.cell(row=merged.min_row, column=merged.min_col).value
        ws.unmerge_cells(str(merged))
        for row in range(merged.min_row, merged.max_row + 1):
            for column in range(merged.min_col, merged.max_col + 1):
                ws.cell(row=row, column=column, value=value)


def lifecycle_from_excel(db: Session, project_id: str, data: bytes, operator_id: str) -> dict:
    """导入「AGV生命周期表」（公司 12 列）到项目车辆记录。

    新版每行可写多台车（车辆编号用、分隔，车号用 . 分隔），每台车各记一条已完成的变更记录；
    车辆按车辆编号匹配或建档，型号对应车型，空的配置号、项目合同号顺带补上。
    同一 项目+车辆+日期+变更内容 重复导入不会翻倍；日期缺年份或无法解析时明确报错。
    """
    p = db.get(Project, project_id)
    if p is None:
        raise ValueError("项目不存在")
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:
        raise ValueError(f"Excel 解析失败：{exc}") from exc
    ws = wb.active
    _unmerge_values(ws)
    header_row = None
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        vals = [str(c or "").strip() for c in row[:12]]
        if "车辆编号" in vals and "变更内容" in vals:
            header_row = idx
            break
        if idx > 20:
            break
    if header_row is None:
        raise ValueError("未找到生命周期表表头（车辆编号/变更内容），请使用公司 AGV生命周期表 或系统导出的表格")

    vehicle_by_model = {}
    for v in db.query(Vehicle).filter_by(project_id=project_id).all():
        model = (v.model_name or "").strip()
        if model and model not in vehicle_by_model:
            vehicle_by_model[model] = v
    unit_by_code = {u.asset_code: u for u in db.query(VehicleUnit).filter_by(project_id=project_id).all()}
    existing_keys = set()
    for event in db.query(VehicleLifecycleEvent).filter(
            VehicleLifecycleEvent.project_id == project_id,
            VehicleLifecycleEvent.event_type.in_(_ISSUE_TYPES)).all():
        if event.import_key:
            existing_keys.add(event.import_key)
        # A record exported by this system comes back as its title, or "title：action".
        exported = lifecycle_columns(p, None, None, event)[9]
        for text in {event.title.strip(), exported[:200]}:
            existing_keys.add(hashlib.sha1(
                f"{project_id}|{event.vehicle_unit_id}|{event.event_date.isoformat()}|{text}".encode("utf-8")).hexdigest())
    created_units = created_events = skipped_events = 0
    for row_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
        row = list(row) + [None] * 12
        codes = [code for code in re.split(r"[、,，;；/\s]+", str(row[5] or "").strip()) if code]
        content = str(row[9] or "").strip()
        if not codes or not content:
            continue
        contract_no, model_name, config_no = str(row[2] or "").strip(), str(row[3] or "").strip(), str(row[4] or "").strip()
        fleets = [code for code in re.split(r"[.、,，;；/\s]+", str(row[7] or "").strip()) if code]
        category, recorder = str(row[8] or "").strip(), str(row[10] or "").strip()
        event_date, recorded_on = _form_date(row[6]), _form_date(row[11])
        if event_date is None:
            event_date = recorded_on
        if event_date is None:
            raise ValueError(f"第 {row_idx} 行（车辆编号 {codes[0]}，{content[:30]}）调车时间记录与记录时间都缺失或缺年份，"
                             f"请填写为 2026.5.23 或 2026-05-23")
        if contract_no and not p.contract_no:
            p.contract_no = contract_no
        vehicle = vehicle_by_model.get(model_name)
        if vehicle is not None and config_no and not (vehicle.configuration or {}).get("config_no"):
            vehicle.configuration = {**(vehicle.configuration or {}), "config_no": config_no}
        for index, asset_code in enumerate(codes):
            fleet_no = fleets[index] if len(fleets) == len(codes) else ""
            unit = unit_by_code.get(asset_code)
            if unit is None:
                unit = VehicleUnit(project_id=project_id, vehicle_id=vehicle.id if vehicle else None, asset_code=asset_code,
                                   fleet_no=fleet_no, model_name=model_name, current_stage="planned", current_status="normal")
                db.add(unit)
                db.flush()
                unit_by_code[asset_code] = unit
                created_units += 1
            else:
                if model_name and not unit.model_name:
                    unit.model_name = model_name
                if fleet_no and not unit.fleet_no:
                    unit.fleet_no = fleet_no
            title = content[:200]
            import_key = hashlib.sha1(f"{project_id}|{unit.id}|{event_date.isoformat()}|{title}".encode("utf-8")).hexdigest()
            if import_key in existing_keys:
                skipped_events += 1
                continue
            existing_keys.add(import_key)
            db.add(VehicleLifecycleEvent(
                vehicle_unit_id=unit.id, project_id=project_id, event_type="repair", event_date=event_date,
                title=title, action_taken=content, handler=recorder, is_closed=True,
                extra={"category": category, "fleet_no": fleet_no, "model_name": model_name, "config_no": config_no,
                       "recorded_on": recorded_on.isoformat() if recorded_on else ""},
                import_key=import_key, operator_id=operator_id))
            created_events += 1
    db.flush()
    notes = []
    if created_units:
        notes.append(f"新建车辆档案 {created_units} 台")
    if skipped_events:
        notes.append(f"跳过重复记录 {skipped_events} 条")
    return {"message": f"生命周期表导入成功：新增车辆记录 {created_events} 条（{'、'.join(notes) or '车辆均已建档'}）",
            "units": created_units, "events": created_events, "skipped": skipped_events}



# ===== 质量问题反馈单 =====

QUALITY_FORM_VERSIONS = (
    ("A00", "初版建立、设计打印格式"),
    ("A01", "①新增单据编号（需手写）\n②新增涉及数量"),
    ("A02", "①新增门架编号<通过门架钢印获取>\n②新增出厂日期<通过铭牌获取>"),
)
# Photo boxes of the A02 form: (title cell, anchor cell, width px, height px).
_PHOTO_BOXES = (("A22", "A23", 250, 280), ("E22", "E23", 290, 280), ("A39", "A40", 250, 245), ("E39", "E40", 290, 245))


def _image_size(data: bytes):
    """(format, width, height) of a PNG/JPEG/GIF without an imaging library; None for anything else."""
    import struct
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "gif", width, height
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = struct.unpack(">H", data[index + 2:index + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return "jpeg", width, height
            index += 2 + length
    return None


def _form_image(data: bytes, max_width: int, max_height: int):
    """An openpyxl picture from raw bytes (no Pillow), scaled into the box keeping its proportions."""
    from openpyxl.drawing.image import Image as SheetImage
    info = _image_size(data)
    if info is None:
        return None
    fmt, width, height = info
    if not width or not height:
        return None

    class _RawImage(SheetImage):
        def __init__(self):  # noqa: D401 - openpyxl reads ref/format/width/height/anchor and _data()
            self.ref, self.format, self.anchor = None, fmt, "A1"
            scale = min(max_width / width, max_height / height, 1)
            self.width, self.height = int(width * scale), int(height * scale)

        def _data(self):
            return data
    return _RawImage()


def build_quality_form(values: dict, photos=()) -> bytes:
    """「产品质量问题反馈单据」A02 版：单据编号、反馈日期、门架号、数量、出厂日期与四张问题图片。"""
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    label_font, value_font, photo_font = Font(name="宋体", size=12), Font(name="宋体", size=11), Font(name="楷体", size=12)
    label_align = Alignment(horizontal="left", vertical="center")
    value_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "质量反馈单据"
    for cells in ("A1:B3", "C1:I3", "A4:B4", "C4:E4", "F4:G4", "H4:I4", "A5:B7", "C5:E7", "F5:G7", "H5:I7",
                  "A8:C8", "D8:G8", "H8:I8", "A9:C11", "D9:G11", "H9:I11", "A12:B12", "C12:E12", "F12:G12", "H12:I12",
                  "A13:B15", "C13:E15", "F13:G15", "H13:I15", "A16:I16", "A17:I20", "A21:I21",
                  "A22:D22", "E22:I22", "A23:D38", "E23:I38", "A39:D39", "E39:I39", "A40:D53", "E40:I53"):
        ws.merge_cells(cells)
    form_no = str(values.get("form_no") or "").strip()
    ws["A1"] = f"\n  No. {form_no or '__________'}"
    ws["A1"].font = Font(name="Times New Roman", size=11)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws["C1"] = " 产品质量问题反馈单据"
    ws["C1"].font = Font(name="黑体", size=20)
    ws["C1"].alignment = Alignment(horizontal="left", vertical="center")
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    labels = {"A4": ("问题类型", " ", "Type"), "C4": ("项目", " ", "Project"), "F4": ("反馈日期", " ", "Date"), "H4": ("反馈人", " ", "Name"),
              "A8": ("车型", " ", "Model"), "D8": ("车辆编号", " ", "No."), "H8": ("问题来源", " ", "From"),
              "A12": ("问题部件", " ", "Parts"), "C12": ("门架号", "", "Elevating Frame Number"), "F12": ("数量", " ", "Amount"),
              "H12": ("出厂日期", " ", "Factory Date"), "A16": ("问题简述（或现象）", "", "Description")}
    for ref, (chinese, gap, english) in labels.items():
        # Chinese in 楷体 12, English in small italics, as printed on the company form.
        blocks = [TextBlock(InlineFont(rFont="楷体", sz=12), chinese)]
        if gap:
            blocks.append(TextBlock(InlineFont(rFont="宋体", sz=12), gap))
        blocks.append(TextBlock(InlineFont(rFont="宋体", sz=10, i=True), english))
        ws[ref] = CellRichText(*blocks)
        ws[ref].font, ws[ref].alignment = label_font, label_align
    ws["H12"].alignment = Alignment(horizontal="center", vertical="center")
    feedback = _parse_loose_date(values.get("feedback_date"))
    factory = _parse_loose_date(values.get("factory_date"))
    quantity = values.get("quantity")
    entries = {"A5": values.get("issue_type", ""), "C5": values.get("project", ""), "F5": dotted(feedback) if feedback else "",
               "H5": values.get("reporter", ""), "A9": values.get("model", ""), "D9": values.get("vehicle_no", ""),
               "H9": values.get("source", ""), "A13": values.get("part", ""), "C13": values.get("frame_no", ""),
               "F13": quantity if quantity not in (None, "") else None, "H13": factory, "A17": values.get("description", "")}
    for ref, value in entries.items():
        ws[ref] = value if value != "" else None
        ws[ref].font, ws[ref].alignment = value_font, value_align
    ws["F13"].number_format = 'General\\ "台"'
    ws["H13"].number_format = "mm-dd-yy"
    for ref, text in (("A22", "问题图片（一）"), ("E22", "问题图片（二）"), ("A39", "问题图片（三）"), ("E39", "问题图片（四）")):
        ws[ref] = text
        ws[ref].font, ws[ref].alignment = photo_font, label_align
    for row in ws.iter_rows(min_row=4, max_row=53, max_col=9):
        for cell in row:
            if cell.row != 21:
                cell.border = border
    placed = 0
    for data in photos:
        if placed >= len(_PHOTO_BOXES):
            break
        _, anchor, width, height = _PHOTO_BOXES[placed]
        image = _form_image(data, width, height)
        if image is None:
            continue
        image.anchor = anchor
        ws.add_image(image)
        placed += 1
    for column, width in {"A": 10.58, "B": 10.58, "C": 10.58, "D": 10.58, "E": 10.58, "F": 5.75, "G": 10.58, "H": 10.58, "I": 10.58}.items():
        ws.column_dimensions[column].width = width
    heights = {1: 14.25, 2: 14.25, 3: 14.25, 4: 24, 8: 24, 12: 24, 16: 24, 20: 66, 21: 5.25, 22: 24, 39: 24}
    ws.sheet_format.defaultRowHeight = 14
    for row in range(1, 54):
        ws.row_dimensions[row].height = heights.get(row, 14)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = "A1:I53"
    ws.oddHeader.left.text = "HCZN-JY-2026-010  A/02"
    ws.oddHeader.left.font, ws.oddHeader.left.size = "Times New Roman,常规", 10
    ws.oddFooter.left.text = "Product Quality Feedback Document"
    ws.oddFooter.left.font, ws.oddFooter.left.size = "Times New Roman,常规", 8
    ws.page_margins.left = ws.page_margins.right = 0.7
    ws.page_margins.top = ws.page_margins.bottom = 0.75
    ws.page_margins.header = ws.page_margins.footer = 0.3
    history = wb.create_sheet("版本管理")
    history.sheet_state = "hidden"  # kept with the form, not printed (as on the company form)
    history.append(["版本号", "更新记录"])
    for version, note in QUALITY_FORM_VERSIONS:
        history.append([version, note])
    for cell in history[1]:
        cell.font = Font(name="黑体", size=12)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in history.iter_rows(min_row=2):
        row[0].font, row[1].font = Font(name="宋体", size=10), Font(name="宋体", size=10)
        row[0].alignment = Alignment(horizontal="center", vertical="center")
        row[1].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    history.column_dimensions["A"].width, history.column_dimensions["B"].width = 22.8, 107.2
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _photo_bytes(db: Session, project, assets, user) -> list:
    """Image files the requester may read, in upload order; damaged or unreadable files are left out."""
    from app.services.project_documents import can_read_file, validate_file
    result = []
    for asset in assets:
        if asset is None or not (asset.content_type or "").startswith("image/"):
            continue
        if user is not None and not can_read_file(user, project, asset):
            continue
        try:
            result.append(validate_file(asset).read_bytes())
        except Exception:  # noqa: BLE001 - a missing original only leaves its photo box empty
            continue
    return result


def _unit_for(db: Session, project_id: str, asset_code: str):
    if not asset_code:
        return None
    return db.query(VehicleUnit).filter_by(project_id=project_id, asset_code=asset_code).first()


def quality_form_to_excel(db: Session, project_id: str, issue_id: str, user=None) -> bytes:
    """把一条项目问题导出为公司「产品质量问题反馈单据」A02 版（照片取问题附件里的图片）。"""
    issue = db.get(Issue, issue_id)
    if issue is None or issue.project_id != project_id:
        raise ValueError("问题不存在")
    p = db.get(Project, project_id)
    extra = issue.extra or {}
    vehicle_no = str(extra.get("vehicle_no", "")).strip()
    unit = _unit_for(db, project_id, vehicle_no)
    vehicle = db.get(Vehicle, unit.vehicle_id) if unit and unit.vehicle_id else None
    feedback = _parse_loose_date(extra.get("feedback_date", "")) or (issue.created_at.date() if issue.created_at else None)
    values = {
        "form_no": extra.get("form_no", ""),
        "issue_type": _QUALITY_TYPE_CN.get(issue.issue_type or "", issue.issue_type or ""),
        "project": extra.get("project_name") or (p.name if p else ""), "feedback_date": feedback,
        "reporter": extra.get("reporter_name", ""),
        "model": extra.get("vehicle_model") or (vehicle.model_name if vehicle else "") or (unit.model_name if unit else ""),
        "vehicle_no": vehicle_no, "source": extra.get("source", ""), "part": extra.get("part", ""),
        "frame_no": extra.get("frame_no") or (unit.frame_no if unit else ""),
        "quantity": extra.get("quantity") if extra.get("quantity") not in (None, "") else (1 if vehicle_no else None),
        "factory_date": extra.get("factory_date") or (unit.factory_date if unit else None),
        "description": issue.description or issue.title or "",
    }
    assets = db.query(Attachment).filter_by(project_id=project_id, entity_type="issue", entity_id=issue.id).order_by(
        Attachment.uploaded_at, Attachment.id).all()
    return build_quality_form(values, _photo_bytes(db, p, assets, user))


def vehicle_quality_form_to_excel(db: Session, project_id: str, event_id: str, user=None) -> bytes:
    """把一条车辆问题导出为「产品质量问题反馈单据」：车型、车辆编号、门架号、出厂日期取自这台车。"""
    from app.models import User
    event = db.get(VehicleLifecycleEvent, event_id)
    if event is None or event.project_id != project_id or event.event_type not in _ISSUE_TYPES:
        raise ValueError("车辆问题不存在")
    p = db.get(Project, project_id)
    unit = db.get(VehicleUnit, event.vehicle_unit_id)
    vehicle = db.get(Vehicle, unit.vehicle_id) if unit and unit.vehicle_id else None
    extra = event.extra or {}
    operator = db.get(User, event.operator_id) if event.operator_id else None
    title, description = (event.title or "").strip(), (event.description or "").strip()
    part = event.fault_part or next((row.get("name") for row in event.replaced_parts or [] if isinstance(row, dict) and row.get("name")), "")
    values = {
        "form_no": extra.get("form_no", ""), "issue_type": extra.get("issue_type") or "硬件", "project": p.name,
        "feedback_date": event.event_date, "reporter": event.handler or (operator.display_name if operator else ""),
        "model": (vehicle.model_name if vehicle else "") or (unit.model_name if unit else "") or extra.get("model_name", ""),
        "vehicle_no": unit.asset_code if unit else "", "source": extra.get("source") or "项目现场", "part": part,
        "frame_no": unit.frame_no if unit else "", "quantity": extra.get("quantity") or 1,
        "factory_date": unit.factory_date if unit else None,
        "description": description if not title or description.startswith(title) else f"{title}\n{description}".strip(),
    }
    assets = [db.get(Attachment, event.attachment_id)] if event.attachment_id else []
    return build_quality_form(values, _photo_bytes(db, p, assets, user))


def _form_cell(ws, row: int, col: int) -> str:
    value = ws.cell(row=row, column=col).value
    if isinstance(value, (datetime, date)):
        return value
    return str(value).strip() if value is not None else ""


def quality_form_from_excel(db: Session, project_id: str, data: bytes, operator_id: str) -> dict:
    """导入「产品质量问题反馈单据」（公司 A02 版）为一条项目问题（Issue）。

    车辆编号对应到本项目车辆时，表上的门架号、出厂日期补到这台车的档案（档案已有值时不覆盖）。
    """
    p = db.get(Project, project_id)
    if p is None:
        raise ValueError("项目不存在")
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:
        raise ValueError(f"Excel 解析失败：{exc}") from exc
    ws = wb.worksheets[0]
    cell = lambda row, col: _form_cell(ws, row, col)
    title_text = f"{cell(1, 1)} {cell(1, 3)}"
    if "质量问题反馈" not in title_text or "反馈日期" not in str(cell(4, 6)) or "门架" not in str(cell(12, 3)):
        raise ValueError("不是公司质量问题反馈单（A02 版）：标题、反馈日期或门架号栏缺失")
    fields = {"issue_type": cell(5, 1), "project_name": cell(5, 3), "feedback_date": cell(5, 6), "reporter_name": cell(5, 8),
              "vehicle_model": cell(9, 1), "vehicle_no": cell(9, 4), "source": cell(9, 8), "part": cell(13, 1),
              "frame_no": cell(13, 3), "quantity": cell(13, 6), "factory_date": cell(13, 8)}
    number = re.search(r"No\.\s*([^\s_][^\s]*)", str(cell(1, 1)))
    fields["form_no"] = number.group(1) if number else ""
    description = "\n".join(str(cell(row, 1)) for row in range(17, 21) if cell(row, 1) not in (None, "")).strip()
    vehicle_no, part = str(fields["vehicle_no"]), str(fields["part"])
    if not (description or part or vehicle_no):
        raise ValueError("质量问题反馈单内容为空：问题简述、问题部件与车辆编号均未填写")
    feedback = _parse_loose_date(fields["feedback_date"])
    date_label = "反馈日期"
    if not fields["feedback_date"]:
        raise ValueError(f"质量问题反馈单缺少{date_label}，请填写后再导入")
    if feedback is None:
        raise ValueError(f"{date_label}无法解析：「{fields['feedback_date']}」，请填写为 2026.10.9 或 2026-10-09")
    factory = _parse_loose_date(fields["factory_date"]) if fields["factory_date"] not in ("", None) else None
    if fields["factory_date"] not in ("", None) and factory is None:
        raise ValueError(f"出厂日期无法解析：「{fields['factory_date']}」，请填写为 2026-03-27")
    quantity = fields["quantity"]
    if quantity not in ("", None):
        try:
            quantity = float(str(quantity).replace("台", "").strip())
            quantity = int(quantity) if quantity == int(quantity) else quantity
        except ValueError:
            raise ValueError(f"数量需要填数字：「{fields['quantity']}」")
    issue_type_cn = str(fields["issue_type"])
    issue_type = {"硬件": "hardware", "软件": "software"}.get(issue_type_cn) or _QUALITY_TYPE_EN.get(issue_type_cn, "other")
    title = description[:60] or f"质量反馈：{part or vehicle_no or '未填写部件'}"
    extra = {
        "project_name": str(fields["project_name"]) or p.name, "reporter_name": str(fields["reporter_name"]),
        "vehicle_model": str(fields["vehicle_model"]), "vehicle_no": vehicle_no, "source": str(fields["source"]), "part": part,
        "feedback_date": feedback.isoformat(), "form_no": str(fields["form_no"]), "frame_no": str(fields["frame_no"]),
        "quantity": quantity if quantity not in ("", None) else "", "factory_date": factory.isoformat() if factory else "",
    }
    issue = Issue(project_id=project_id, title=title, description=description, issue_type=issue_type, severity="medium",
                  status="open", nature="quality", reporter_id=operator_id, extra=extra)
    db.add(issue)
    db.flush()
    unit = _unit_for(db, project_id, vehicle_no)
    filled = []
    if unit is not None:
        if extra["frame_no"] and not unit.frame_no:
            unit.frame_no = extra["frame_no"]; filled.append("门架号")
        if factory and not unit.factory_date:
            unit.factory_date = factory; filled.append("出厂日期")
    from app.services.document_triggers import issue_event
    issue_event(db, p, issue, operator_id)
    suffix = f"，并补充车辆 {vehicle_no} 的{'、'.join(filled)}" if filled else ""
    return {"message": f"质量问题反馈单已导入为问题「{title}」{suffix}", "id": issue.id}


# ===== 内部联系单（物品申请） =====

def item_application_to_docx(db: Session, project_id: str, app_id: str) -> bytes:
    """把一条物品申请记录生成「内部联系单」Word 文档。"""
    from docx import Document
    from docx.shared import Pt,RGBColor

    p = db.get(Project, project_id)
    app = db.get(ItemApplication, app_id)
    if app is None or app.project_id != project_id:
        raise ValueError("联系单不存在")

    doc = Document()
    # Keep the existing contact form fields and order, with enough room for
    # ordinary multi-line requests and the signature block on the same page.
    doc.styles['Normal'].font.size=Pt(11)
    doc.styles['Normal'].paragraph_format.space_after=Pt(4)
    doc.styles['Title'].font.color.rgb=RGBColor(0,0,0)
    for style in doc.styles:
        for border in style.element.xpath('./w:pPr/w:pBdr'):
            border.getparent().remove(border)
    title = doc.add_paragraph(style='Title')
    title.paragraph_format.space_after=Pt(12)
    title.paragraph_format.keep_with_next=True
    title.alignment = 1  # center
    run = title.add_run(f"内部联系单——{p.name if p else ''}")
    run.bold = True
    run.font.size = Pt(16)

    fields = [
        ("申请事项", app.title or ""),
        ("申请物品/服务", app.item_name or ""),
        ("需求", app.requirement or ""),
        ("原因", app.reason or ""),
        ("图号", app.drawing_no or ""),
        ("合同号", app.contract_no or ""),
        ("金额", app.amount or ""),
        ("申请人", app.applicant or ""),
        ("审批人", app.approver or ""),
    ]
    for label, value in fields:
        para = doc.add_paragraph()
        para.add_run(f"{label}：").bold = True
        para.add_run(str(value))

    para = doc.add_paragraph()
    para.add_run(f"申请部门：{app.department or ''}").bold = True
    if app.apply_date:
        doc.add_paragraph(f"申请日期：{app.apply_date.isoformat()}")
    signature=doc.add_paragraph("项目技术部")
    signature.paragraph_format.space_before=Pt(10)
    signature.paragraph_format.keep_with_next=True
    doc.add_paragraph("日期：")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def item_application_from_docx(db: Session, project_id: str, data: bytes, operator_id: str) -> dict:
    """解析「内部联系单」Word 文档为一条物品申请记录。

    按段落文本匹配字段标签（申请事项/申请物品服务/需求/原因/图号/合同号/金额/申请人/审批人/申请部门/申请日期），
    与 item_application_to_docx 生成版式一一对应，支持系统生成 → 回灌；
    对无完整标签的旧版本文档，回退到「需要…，」/「共计…元」/独立日期段解析。
    """
    p = db.get(Project, project_id)
    if p is None:
        raise ValueError("项目不存在")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Word 解析失败：{exc}") from exc

    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    texts = []
    for para in paragraphs:
        pieces = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", para)
        line = "".join(pieces).strip()
        if line:
            texts.append(line)

    def pick(label: str) -> str:
        for line in texts:
            match = re.match(rf"^{re.escape(label)}\s*[:：]\s*(.*)$", line)
            if match:
                return match.group(1).strip()
        return ""

    requirement = pick("需求")
    reason = pick("原因")
    drawing_no = pick("图号")
    contract_no = pick("合同号")
    applicant = pick("申请人")
    approver = pick("审批人")
    department = pick("申请部门") or pick("部门")
    title = pick("申请事项")
    item_name = pick("申请物品/服务")
    amount = pick("金额")

    project_name = ""
    apply_date = _parse_loose_date(pick("申请日期"))
    standalone: list[str] = []
    for line in texts:
        m = re.match(r"^内部联系单[\s\-—–:：]*(.*)$", line)
        if m and not project_name:
            project_name = m.group(1).strip()
            continue
        if re.match(r"^(需求|原因|图号|合同号|申请人|审批人|申请部门|部门|申请事项|申请物品/服务|金额|申请日期|日期)\s*[:：]", line):
            continue
        m = re.match(r"^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})$", line)
        if m:
            if apply_date is None:
                apply_date = _parse_loose_date(m.group(1))
            continue
        standalone.append(line)
    if not department and standalone:
        # 独立段落（如「项目技术部」）作为申请部门
        department = standalone[0]

    # 回退链：标签缺失时按需求文本推断物品与金额（兼容旧版/手工版式）
    if not item_name:
        item_match = re.search(r"需要\s*([^，。]+?)\s*，", requirement)
        if item_match:
            # 去掉「需要」后常见的动作前缀：需要使用吊车 → 吊车
            candidate = re.sub(r"^(使用|调用|租用|采购|申请|用)+", "", item_match.group(1)).strip()
            item_name = candidate
    if not amount:
        amount_match = re.search(r"共计\s*([\d.]+)\s*元|([\d.]+)\s*元", requirement)
        if amount_match:
            amount = f"{amount_match.group(1) or amount_match.group(2)}元"
    if not item_name:
        item_name = requirement[:40]
    if not title:
        title = requirement or (standalone[0] if standalone else "")

    app = ItemApplication(
        project_id=project_id, title=title[:300], item_name=item_name,
        requirement=requirement, reason=reason, drawing_no=drawing_no,
        contract_no=contract_no, amount=amount, applicant=applicant,
        approver=approver, department=department, apply_date=apply_date,
        status="pending", created_by=operator_id,
    )
    db.add(app)
    db.flush()
    return {
        "message": f"内部联系单已导入为物品申请「{title or requirement[:40]}」",
        "id": app.id,
        "title": app.title,
        "project_name": project_name or p.name,
    }

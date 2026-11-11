"""Excel in and out: the whole project, the company's lifecycle table, the lists, a template."""
import io
import re
from datetime import date, datetime

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app import models, records
from app.records import KINDS
from app.services.change_log import log_change

MAX_ROWS = 5000
LIFECYCLE_HEADERS = ["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类",
                     "变更内容", "记录人", "记录时间"]
LIFECYCLE_WIDTHS = [8.8, 15, 18.6, 16.4, 16, 55.8, 15.1, 13.1, 15, 23.3, 8.8, 11.5]
TEMPLATE_SHEETS = {"work": ("工作", ("阶段", "工作内容")), "document": ("资料", ("资料名称",)),
                   "step": ("车辆环节", ("环节",)), "item": ("物品", ("名称", "规格", "数量", "单位"))}
_TICKS = {"✓", "√", "✔", "是", "y", "yes", "1", "true", "完成", "已完成", "已到", "做完"}
_DATE = re.compile(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})")
_BAD = object()  # a cell that could not be read; its row is skipped and reported
_THIN = Side(style="thin", color="FFD5DDE6")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def dotted(value) -> str:
    """Company forms write dates as 2026.5.23."""
    return f"{value.year}.{value.month}.{value.day}" if value else ""


def loose_date(value):
    """2026.5.23, 2026-05-23, 2026/5/4, or an Excel date. A date without its year is not guessed."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = _DATE.search(str(value or ""))
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _number(value):
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _save(workbook: Workbook) -> bytes:
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"  # text beginning with "=" stays text, never a formula
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _sheet(workbook: Workbook, title: str, headers, rows, widths=None):
    sheet = workbook.create_sheet(title)
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = PatternFill("solid", start_color="FF2F5F8F", end_color="FF2F5F8F")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in sheet.iter_rows(min_row=1, max_col=len(headers)):
        for cell in row:
            cell.border = _BORDER
            if cell.row > 1:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index in range(1, len(headers) + 1):
        sheet.column_dimensions[get_column_letter(index)].width = (widths or {}).get(index, 16)
    sheet.freeze_panes = "A2"
    return sheet


def _day(value) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat() if value else ""


def export_project(db: Session, project: models.Project) -> bytes:
    from app.routers.projects import _live_rows
    people = {user.id: user.display_name for user in db.query(models.User)}
    rows = {key: _live_rows(db, key, project.id) for key in records.PROJECT_KINDS}
    vehicles = {row.id: row for row in rows["vehicles"]}
    marks = {(mark.vehicle_id, mark.step_id) for mark in db.query(models.VehicleMark).filter_by(project_id=project.id)}
    files = {}
    for row in db.query(models.File).filter_by(project_id=project.id, deleted_at=None).order_by(models.File.created_at):
        files.setdefault((row.owner_kind, row.owner_id), []).append(row.filename)
    workbook = Workbook()
    workbook.remove(workbook.active)
    steps = rows["steps"]
    _sheet(workbook, "车辆", ["车辆编号", "车号", "型号", "配置号", *[step.name for step in steps], "备注"],
           [[v.vehicle_no, v.fleet_no, v.model, v.config_no, *["✓" if (v.id, step.id) in marks else "" for step in steps], v.note]
            for v in rows["vehicles"]], {1: 22, 5 + len(steps): 30})
    _sheet(workbook, "车辆记录", ["车辆编号", "车号", "调车时间记录", "分类", "变更内容", "记录人", "记录时间"],
           [[vehicles[r.vehicle_id].vehicle_no, vehicles[r.vehicle_id].fleet_no, _day(r.happened_on), r.category, r.content,
             r.recorded_by_name, _day(r.recorded_on)] for r in rows["vehicle-records"] if r.vehicle_id in vehicles],
           {1: 22, 5: 50})
    _sheet(workbook, "工作", ["阶段", "工作内容", "做完", "完成人", "完成日期", "备注"],
           [[w.stage, w.name, "✓" if w.done else "", people.get(w.done_by, ""), _day(w.done_at), w.note] for w in rows["work"]],
           {2: 44, 6: 30})
    _sheet(workbook, "问题", ["问题描述", "关联车辆", "状态", "处理结果", "上报人", "上报日期", "关闭人", "关闭日期", "附件"],
           [[i.description, vehicles[i.vehicle_id].vehicle_no if i.vehicle_id in vehicles else "", "已关" if i.is_closed else "没关",
             i.resolution, people.get(i.created_by, ""), _day(i.created_at), people.get(i.closed_by, ""), _day(i.closed_at),
             "\n".join(files.get(("issue", i.id), []))] for i in rows["issues"]], {1: 50, 4: 40, 9: 30})
    _sheet(workbook, "资料", ["资料名称", "状态", "文件", "备注"],
           [[d.name, "已交" if files.get(("document", d.id)) else "没交", "\n".join(files.get(("document", d.id), [])), d.note]
            for d in rows["documents"]] + [["（其他文件）", "", name, ""] for name in files.get(("other", None), [])],
           {1: 36, 3: 50, 4: 30})
    _sheet(workbook, "物品", ["名称", "规格", "数量", "单位", "到了没", "备注"],
           [[i.name, i.spec, _number(i.quantity), i.unit, "✓" if i.arrived else "", i.note] for i in rows["items"]],
           {1: 30, 2: 26, 6: 30})
    return _save(workbook)


def export_lifecycle(db: Session, project: models.Project) -> bytes:
    """The company's 12-column table. The same record on several vehicles becomes one line."""
    from app.routers.projects import _live_rows
    vehicles = _live_rows(db, "vehicles", project.id)
    by_vehicle = {}
    for record in _live_rows(db, "vehicle-records", project.id):
        by_vehicle.setdefault(record.vehicle_id, []).append(record)
    lines, grouped = [], {}
    for vehicle in vehicles:
        for record in by_vehicle.get(vehicle.id) or [None]:
            columns = [None, project.name, project.contract_no, vehicle.model, vehicle.config_no, vehicle.vehicle_no,
                       dotted(record.happened_on) if record else "", vehicle.fleet_no,
                       record.category if record else "", record.content if record else "",
                       record.recorded_by_name if record else "", dotted(record.recorded_on) if record else ""]
            key = tuple(columns[i] for i in (3, 4, 6, 8, 9, 10, 11)) if record else None
            if key is not None and key in grouped:
                line = grouped[key]
                line[5] = "、".join(filter(None, [line[5], columns[5]]))
                line[7] = ".".join(filter(None, [line[7], columns[7]]))
                continue
            if key is not None:
                grouped[key] = columns
            lines.append(columns)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "AGV生命周期表"
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.merge_cells("A1:L1")
    sheet["A1"] = "AGV生命周期表"
    sheet["A1"].font = Font(name="等线", size=20, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 25
    for column, name in enumerate(LIFECYCLE_HEADERS, start=1):
        cell = sheet.cell(row=2, column=column, value=name)
        cell.font = Font(name="等线", size=11, bold=True)
    for number, columns in enumerate(lines, start=1):
        columns[0] = number
        sheet.append(columns)
    for row in sheet.iter_rows(min_row=1, max_row=max(sheet.max_row, 2), max_col=len(LIFECYCLE_HEADERS)):
        for cell in row:
            cell.border = border
            if cell.row > 1:
                cell.alignment = center
            if cell.row > 2:
                cell.font = Font(name="等线", size=11)
    for index, width in enumerate(LIFECYCLE_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A3"
    return _save(workbook)


def export_template(db: Session, template: models.Template) -> bytes:
    from app.routers.templates import template_rows
    rows = template_rows(db, template.id)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for kind, (title, headers) in TEMPLATE_SHEETS.items():
        names = {"work": ("stage", "name"), "document": ("name",), "step": ("name",), "item": ("name", "spec", "quantity", "unit")}[kind]
        _sheet(workbook, title, headers, [[_number(getattr(row, name)) for name in names] for row in rows if row.kind == kind],
               {1: 26, 2: 40})
    return _save(workbook)


# ---- reading ----

def _open(data: bytes):
    try:
        return load_workbook(io.BytesIO(data), data_only=True)
    except Exception:
        raise HTTPException(400, "这个文件打不开，请确认是 .xlsx 格式的 Excel 文件") from None


def _table(sheet, required):
    """Rows of a sheet as dicts keyed by header text. The header row is the first one that has every required header."""
    for merged in list(sheet.merged_cells.ranges):  # a merged cell speaks for every row it covers
        value = sheet.cell(row=merged.min_row, column=merged.min_col).value
        sheet.unmerge_cells(str(merged))
        for row in range(merged.min_row, merged.max_row + 1):
            for column in range(merged.min_col, merged.max_col + 1):
                sheet.cell(row=row, column=column, value=value)
    header_row = headers = None
    for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        names = [_text(cell) for cell in row]
        if all(name in names for name in required):
            header_row, headers = index, names
            break
        if index >= 20:
            break
    if headers is None:
        return None
    result = []
    for index, row in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
        if len(result) >= MAX_ROWS:
            raise HTTPException(400, f"一次最多导入 {MAX_ROWS} 行")
        values = {name: row[position] for position, name in enumerate(headers) if name and position < len(row)}
        if any(_text(value) for value in values.values()):
            result.append((index, values))
    return headers, result


def _need(sheet, required, what):
    table = _table(sheet, required)
    if table is None:
        raise HTTPException(400, f"没有找到表头（{'、'.join(required)}），请使用{what}")
    return table


class _Import:
    def __init__(self, db: Session, user, project: models.Project):
        self.db, self.user, self.project = db, user, project
        self.counts, self.problems, self.models_seen = {}, [], set()

    def count(self, label: str, amount: int = 1):
        self.counts[label] = self.counts.get(label, 0) + amount

    def value(self, kind_key: str, name: str, raw, line: int):
        """A cleaned cell, or _BAD after noting the problem."""
        spec = KINDS[kind_key].fields[name]
        try:
            return records.clean(spec, raw if spec.type == "number" else _text(raw))
        except HTTPException as error:
            self.problems.append(f"第 {line} 行：{error.detail}")
            return _BAD

    def order(self, kind_key: str) -> int:
        return records._next_order(self.db, KINDS[kind_key], self.project.id)

    def result(self) -> dict:
        known = {name for (name,) in self.db.query(models.VehicleType.name)}
        return {"counts": [{"label": label, "count": count} for label, count in self.counts.items()],
                "problems": self.problems[:50], "problem_count": len(self.problems),
                "unknown_models": sorted(self.models_seen - known)}


def _vehicle(job: _Import, existing: dict, line: int, number, fleet="", model="", config="", note=""):
    """Find the vehicle by its number or add it; fill only what is still empty."""
    if not _text(number):
        return None
    number = job.value("vehicles", "vehicle_no", number, line)
    if number is _BAD:
        return None
    values = {"fleet_no": fleet, "model": model, "config_no": config, "note": note}
    cleaned = {name: job.value("vehicles", name, raw, line) for name, raw in values.items()}
    if any(value is _BAD for value in cleaned.values()):
        return None
    if cleaned["model"]:
        job.models_seen.add(cleaned["model"])
    vehicle = existing.get(number)
    if vehicle is None:
        vehicle = models.Vehicle(id=models.gen_uuid(), project_id=job.project.id, created_by=job.user.id, vehicle_no=number,
                                 sort_order=job.order("vehicles"), **cleaned)
        job.db.add(vehicle)
        job.db.flush()
        existing[number] = vehicle
        job.count("新增车辆")
        return vehicle
    filled = False
    for name, value in cleaned.items():
        if value and not getattr(vehicle, name):
            setattr(vehicle, name, value)
            filled = True
    if filled:
        job.count("补全已有车辆")
    return vehicle


def _import_vehicles(job: _Import, sheet):
    headers, rows = _need(sheet, ["车辆编号"], "系统导出的车辆表")
    db, project = job.db, job.project
    existing = {row.vehicle_no: row for row in db.query(models.Vehicle).filter_by(project_id=project.id, deleted_at=None)}
    steps = {step.name: step for step in db.query(models.ProjectStep).filter_by(project_id=project.id, deleted_at=None)}
    marks = {(mark.vehicle_id, mark.step_id) for mark in db.query(models.VehicleMark).filter_by(project_id=project.id)}
    for line, row in rows:
        vehicle = _vehicle(job, existing, line, row.get("车辆编号"), row.get("车号"), row.get("型号"), row.get("配置号"), row.get("备注"))
        if vehicle is None:
            continue
        for name, step in steps.items():
            if name in headers and _text(row.get(name)).lower() in _TICKS and (vehicle.id, step.id) not in marks:
                db.add(models.VehicleMark(project_id=project.id, vehicle_id=vehicle.id, step_id=step.id, done_by=job.user.id))
                marks.add((vehicle.id, step.id))
                job.count("新增环节打勾")


def _import_lifecycle(job: _Import, sheet):
    _, rows = _need(sheet, ["车辆编号", "变更内容"], "公司的 AGV 生命周期表或系统导出的生命周期表")
    db, project = job.db, job.project
    existing = {row.vehicle_no: row for row in db.query(models.Vehicle).filter_by(project_id=project.id, deleted_at=None)}
    seen = {(r.vehicle_id, r.category, r.content, r.happened_on, r.recorded_on)
            for r in db.query(models.VehicleRecord).filter_by(project_id=project.id, deleted_at=None)}
    for line, row in rows:
        codes = [code for code in re.split(r"[、,，;；/\s]+", _text(row.get("车辆编号"))) if code]
        fleets = [code for code in re.split(r"[.、,，;；/\s]+", _text(row.get("车号"))) if code]
        if not codes:
            continue
        contract = _text(row.get("项目合同号"))
        if contract and not project.contract_no:
            project.contract_no = contract[:100]
        content = job.value("vehicle-records", "content", row.get("变更内容"), line) if _text(row.get("变更内容")) else ""
        category = job.value("vehicle-records", "category", row.get("分类"), line)
        recorder = job.value("vehicle-records", "recorded_by_name", row.get("记录人"), line)
        if _BAD in (content, category, recorder):
            continue
        happened, recorded = loose_date(row.get("调车时间记录")), loose_date(row.get("记录时间"))
        for index, code in enumerate(codes):
            vehicle = _vehicle(job, existing, line, code, fleets[index] if len(fleets) == len(codes) else "",
                               row.get("型号"), row.get("配置号"))
            if vehicle is None or not content:
                continue
            key = (vehicle.id, category, content, happened, recorded)
            if key in seen:
                job.count("跳过重复记录")
                continue
            seen.add(key)
            db.add(models.VehicleRecord(project_id=project.id, vehicle_id=vehicle.id, created_by=job.user.id, category=category,
                                        content=content, recorded_by_name=recorder, happened_on=happened, recorded_on=recorded))
            job.count("新增车辆记录")


def _import_list(kind_key: str, columns: dict, match: tuple, source: str):
    """An importer for a plain list: columns maps header -> field; rows already present (by match) are skipped."""
    required = [header for header, name in columns.items() if KINDS[kind_key].fields[name].required]

    def run(job: _Import, sheet):
        kind = KINDS[kind_key]
        _, rows = _need(sheet, required, source)
        present = {tuple(getattr(row, name) for name in match)
                   for row in job.db.query(kind.model).filter_by(project_id=job.project.id, deleted_at=None)}
        position = job.order(kind_key)
        for line, row in rows:
            if not _text(row.get(required[0])):
                continue  # a line without its name is not a row
            values = {name: job.value(kind_key, name, row.get(header), line) for header, name in columns.items()}
            if any(value is _BAD for value in values.values()):
                continue
            key = tuple(values[name] for name in match)
            if key in present:
                job.count(f"跳过已有{kind.label}")
                continue
            present.add(key)
            job.db.add(kind.model(project_id=job.project.id, created_by=job.user.id, sort_order=position, **values))
            position += 1
            job.count(f"新增{kind.label}")
    return run


IMPORTERS = {
    "lifecycle": ("生命周期表", _import_lifecycle),
    "vehicles": ("车辆", _import_vehicles),
    "work": ("工作", _import_list("work", {"阶段": "stage", "工作内容": "name", "备注": "note"}, ("stage", "name"), "系统导出的工作表")),
    "documents": ("资料清单", _import_list("documents", {"资料名称": "name", "备注": "note"}, ("name",), "系统导出的资料表")),
    "items": ("物品", _import_list("items", {"名称": "name", "规格": "spec", "数量": "quantity", "单位": "unit", "备注": "note"},
                                 ("name", "spec"), "系统导出的物品表")),
}
_SHEET_NAMES = {"lifecycle": ("AGV生命周期表", "生命周期表"), "vehicles": ("车辆",), "work": ("工作",),
                "documents": ("资料",), "items": ("物品",)}


def import_project(db: Session, user, project: models.Project, what: str, data: bytes, *, preview: bool) -> dict:
    """Read the file into the project. A preview does everything and then undoes it, so its numbers are exact."""
    label, run = IMPORTERS[what]
    workbook = _open(data)
    sheet = next((workbook[name] for name in _SHEET_NAMES[what] if name in workbook.sheetnames), workbook.active)
    job = _Import(db, user, project)
    run(job, sheet)
    db.flush()
    result = job.result()
    if preview:
        db.rollback()
        return {**result, "preview": True}
    if job.counts:
        log_change(db, project.id, "project", project.id, "import", user, f"导入{label}", new_value=job.counts,
                   row_label=project.name)
        records.bump(db, models.Project, project.id)
    db.commit()
    return {**result, "preview": False}


def import_template(db: Session, user, template: models.Template, data: bytes, *, preview: bool) -> dict:
    workbook = _open(data)
    kind, counts, problems = KINDS["rows"], {}, []
    present = {(row.kind, row.stage, row.name) for row in db.query(models.TemplateRow).filter_by(template_id=template.id, deleted_at=None)}
    position = records._next_order(db, kind, template.id)
    fields = {"阶段": "stage", "工作内容": "name", "资料名称": "name", "环节": "name", "名称": "name", "规格": "spec",
              "数量": "quantity", "单位": "unit"}
    found = False
    for list_kind, (title, headers) in TEMPLATE_SHEETS.items():
        if title not in workbook.sheetnames:
            continue
        table = _table(workbook[title], [headers[-1] if list_kind == "work" else headers[0]])
        if table is None:
            continue
        found = True
        for line, row in table[1]:
            values = {}
            try:
                for header in headers:
                    spec = kind.fields[fields[header]]
                    values[fields[header]] = records.clean(spec, row.get(header) if spec.type == "number" else _text(row.get(header)))
            except HTTPException as error:
                problems.append(f"{title} 第 {line} 行：{error.detail}")
                continue
            key = (list_kind, values.get("stage", ""), values["name"])
            if key in present:
                counts[f"跳过已有{title}"] = counts.get(f"跳过已有{title}", 0) + 1
                continue
            present.add(key)
            db.add(models.TemplateRow(template_id=template.id, created_by=user.id, kind=list_kind, sort_order=position, **values))
            position += 1
            counts[f"新增{title}"] = counts.get(f"新增{title}", 0) + 1
    if not found:
        raise HTTPException(400, "没有找到“工作、资料、车辆环节、物品”这几张表，请使用系统导出的模板文件")
    db.flush()
    result = {"counts": [{"label": label, "count": count} for label, count in counts.items()],
              "problems": problems[:50], "problem_count": len(problems), "unknown_models": [], "preview": preview}
    if preview:
        db.rollback()
        return result
    if counts:
        log_change(db, None, "template", template.id, "import", user, "导入模板内容", new_value=counts, row_label=template.name)
        records.bump(db, models.Template, template.id)
    db.commit()
    return result

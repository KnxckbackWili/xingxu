"""Frozen legacy repair, executed once by the T01 revision, never on startup."""

from typing import Optional
from sqlalchemy import text

from sqlalchemy.orm import Session

from migrations.v243_schema import *  # noqa: F403

_is_sqlite = True

PREP_PHASE_MODULES = [
    ("mod-16", "项目准备", ["项目实施范围冻结", "现场布局图", "点位表", "客户系统接口文档（WMS/MES）",
                            "验收标准确认", "车辆交付", "调度系统项目配置", "现场施工完成", "网络检查",
                            "实施人员安排", "入场手续"]),
    ("mod-17", "WMS 接口", ["接口协议确认", "测试环境提供", "测试账号提供", "网络连通检查", "联调计划确认"]),
    ("mod-18", "自动充电", ["充电设备交付", "充电区域施工", "电源条件确认", "充电通讯测试条件"]),
    ("mod-19", "客户服务器", ["服务器配置确认", "操作系统准备", "网络端口开放", "远程访问方式确认"]),
    ("mod-20", "新造车辆", ["设计冻结", "首车完成", "厂内测试通过", "发货", "到场确认"]),
    ("mod-21", "海外项目", ["发运和清关计划", "人员签证/邀请函", "入场手续（海外）", "当地网络和通信条件", "现场交通住宿安排"]),
]

TEMPLATE_PREP_ITEMS = [
    # (name, category, required, blocks, party, risk, condition)
    ("项目实施范围冻结", "scope", True, True, "project", "low", "default"),
    ("现场布局图", "scope", True, False, "client", "medium", "default"),
    ("点位表", "scope", True, True, "client", "high", "default"),
    ("客户系统接口文档（WMS/MES）", "scope", False, False, "client", "medium", "default"),
    ("验收标准确认", "scope", True, False, "client", "low", "default"),
    ("车辆交付", "vehicle", True, True, "production", "high", "default"),
    ("调度系统项目配置", "software", True, False, "software", "high", "default"),
    ("现场施工完成", "site", True, True, "client", "high", "default"),
    ("网络检查", "site", True, True, "client", "high", "default"),
    ("实施人员安排", "site", True, False, "project", "medium", "default"),
    ("入场手续", "site", True, True, "project", "medium", "default"),
    # 条件组：need_wms
    ("接口协议确认", "scope", True, True, "client", "high", "need_wms"),
    ("测试环境提供", "scope", True, False, "client", "high", "need_wms"),
    ("测试账号提供", "scope", False, False, "client", "medium", "need_wms"),
    ("网络连通检查", "site", True, True, "client", "high", "need_wms"),
    ("联调计划确认", "software", True, False, "software", "medium", "need_wms"),
    # 条件组：need_charging
    ("充电设备交付", "vehicle", True, True, "procurement", "high", "need_charging"),
    ("充电区域施工", "site", True, True, "client", "high", "need_charging"),
    ("电源条件确认", "site", True, False, "client", "medium", "need_charging"),
    ("充电通讯测试条件", "software", False, False, "software", "low", "need_charging"),
    # 条件组：client_server
    ("服务器配置确认", "scope", True, False, "client", "high", "client_server"),
    ("操作系统准备", "scope", True, False, "client", "medium", "client_server"),
    ("网络端口开放", "site", True, True, "client", "high", "client_server"),
    ("远程访问方式确认", "scope", False, False, "client", "low", "client_server"),
    # 条件组：new_vehicles
    ("设计冻结", "vehicle", True, False, "production", "medium", "new_vehicles"),
    ("首车完成", "vehicle", True, False, "production", "high", "new_vehicles"),
    ("厂内测试通过", "vehicle", True, True, "production", "high", "new_vehicles"),
    ("发货", "vehicle", True, True, "production", "high", "new_vehicles"),
    ("到场确认", "vehicle", True, True, "production", "high", "new_vehicles"),
    # 条件组：overseas
    ("发运和清关计划", "scope", True, True, "project", "high", "overseas"),
    ("人员签证/邀请函", "site", True, True, "project", "high", "overseas"),
    ("入场手续（海外）", "site", True, False, "client", "medium", "overseas"),
    ("当地网络和通信条件", "site", True, False, "client", "medium", "overseas"),
    ("现场交通住宿安排", "site", False, False, "project", "low", "overseas"),
]

DEFAULT_ITEMS = [
    ("设计资料", "项目设计方案", True),
    ("设计资料", "电气与网络布置图", True),
    ("设计资料", "系统配置表", True),
    ("测试记录", "单车调试测试记录", True),
    ("测试记录", "系统联调测试记录", True),
    ("测试记录", "压力测试记录（48小时）", True),
    ("测试记录", "试运行记录（7天）", True),
    ("问题汇总", "问题汇总表及整改记录", True),
    ("培训资料", "操作培训记录", True),
    ("培训资料", "维护培训记录", True),
    ("验收文件", "初验报告", True),
    ("验收文件", "终验报告（客户签字）", True),
    ("验收文件", "备件与工具移交记录", False),
]

def seed_template_preparations(db):
    """默认模板准备项（幂等：仅当默认模板无准备项时创建）。"""
    from migrations.v243_schema import TemplatePreparationItem
    existing = db.query(TemplatePreparationItem).filter(TemplatePreparationItem.template_id.is_(None)).count()
    if existing > 0:
        return
    for i, (name, cat, req, blocks, party, risk, cond) in enumerate(TEMPLATE_PREP_ITEMS):
        db.add(TemplatePreparationItem(
            template_id=None, name=name, category=cat, is_required=req,
            blocks_entry=blocks, owner_party=party, risk=risk, condition=cond, sort_order=i,
        ))
    db.flush()

def seed_team_templates(db):
    """预置团队模板（幂等：仅当没有任何模板时创建）。"""
    from migrations.v243_schema import TeamTemplate
    if db.query(TeamTemplate).count() > 0:
        return
    PRESET = [
        {
            "name": "标准实施团队",
            "description": "常规 AGV 项目：PM + 组长 + 技术 + 2 名实施",
            "roles": {"pm": 1, "lead": 1, "technician": 1, "worker": 2},
        },
        {
            "name": "快速响应团队",
            "description": "小项目/售后：组长 + 1 名实施",
            "roles": {"lead": 1, "worker": 1},
        },
        {
            "name": "复杂集成团队",
            "description": "多车型/外设项目：PM + 组长 + 技术 + 3 名实施 + 实习",
            "roles": {"pm": 1, "lead": 1, "technician": 1, "worker": 3, "intern": 1},
        },
    ]
    for preset in PRESET:
        db.add(TeamTemplate(name=preset["name"], description=preset["description"], roles=preset["roles"]))

def ensure_checklist_seeded(db: Session, project_id: str) -> bool:
    """若项目尚无归档项则播种默认 13 项（幂等）。返回是否本次播种。

    v1.2.1：播种从「GET 首次访问时」改为「创建项目时 + 迁移补齐 + 显式 initialize」，
    GET 只读端点不再有写副作用。
    """
    has = db.query(ArchiveChecklist).filter(ArchiveChecklist.project_id == project_id).first()
    if has:
        return False
    for i, (cat, name, req) in enumerate(DEFAULT_ITEMS):
        db.add(ArchiveChecklist(
            project_id=project_id, category=cat, item_name=name,
            is_required=req, sort_order=i,
        ))
    db.flush()
    return True

def _normalize_legacy_vehicle_types(db):
    """HYPE-63：历史遗留车型字符串归一化（SQLite 与 PG 都走这条）。

    custom / 自定义 曾分别代表「其他/定制」，迁移为字典规范名「其他/定制」；
    其余字典外历史值原样保留（现场仍可显示与编辑），不丢数据。
    """
    from sqlalchemy import text
    db.execute(text(
        "UPDATE vehicles SET vehicle_type = '其他/定制' "
        "WHERE vehicle_type IN ('custom', '自定义')"
    ))
    from migrations.v243_schema import Task as _VehicleTask
    _legacy_map = {"custom": "其他/定制", "自定义": "其他/定制"}
    for _vtask in db.query(_VehicleTask).filter(_VehicleTask.applicable_vehicle_types.isnot(None)).all():
        _vtypes = _vtask.applicable_vehicle_types or []
        _new = [_legacy_map.get(v, v) for v in _vtypes]
        if _new != _vtypes:
            _vtask.applicable_vehicle_types = _new

def migrate_legacy_data(db):
    """Frozen legacy data repairs; schema alignment has already completed."""
    from sqlalchemy import text as _text
    _dup_issue = db.execute(_text('SELECT project_id, client_uuid FROM issues WHERE client_uuid IS NOT NULL GROUP BY project_id, client_uuid HAVING COUNT(*) > 1 LIMIT 1')).fetchone()
    if _dup_issue is not None:
        import logging
        logging.getLogger(__name__).error('issues 表存在重复 (project_id, client_uuid)=%s/%s，无法加唯一约束；请人工合并后重启。', _dup_issue[0], _dup_issue[1])
        raise RuntimeError('issues 存在重复 client_uuid，拒绝静默删除数据创建唯一索引')
    from sqlalchemy import text
    _normalize_legacy_vehicle_types(db)
    if not _is_sqlite:
        return
    from sqlalchemy import text
    _ver = db.execute(text('PRAGMA user_version')).scalar() or 0
    if _ver < 2:
        db.execute(text('UPDATE tasks SET standard_hours = NULL WHERE project_id IS NULL'))
        db.execute(text('PRAGMA user_version = 2'))
    seed_template_preparations(db)
    from migrations.v243_schema import Phase as _Ph, Module as _Mod, Task as _Task
    _fk_was_on = db.execute(text('PRAGMA foreign_keys')).scalar()
    if _fk_was_on:
        db.execute(text('PRAGMA foreign_keys=OFF'))
    _mis_mod = db.query(_Mod).filter(_Mod.project_id.is_(None), _Mod.id == 'mod-18', _Mod.name == '自动充电').first()
    _prep_ph2 = db.query(_Ph).filter(_Ph.project_id.is_(None), _Ph.name == '项目准备').first()
    if _mis_mod is not None and (_prep_ph2 is None or _mis_mod.phase_id != _prep_ph2.id):
        db.execute(text("UPDATE modules SET id = 'mod-15' WHERE id = 'mod-18' AND name = '自动充电'"))
        db.execute(text("UPDATE tasks SET module_id = 'mod-15' WHERE module_id = 'mod-18' AND project_id IS NULL"))
    try:
        for mid, mname, _tasks in PREP_PHASE_MODULES:
            if _prep_ph2 is None:
                break
            m_existing = db.query(_Mod).filter(_Mod.project_id.is_(None), _Mod.phase_id == _prep_ph2.id, _Mod.name == mname).first()
            if m_existing is not None and m_existing.id != mid:
                params = {'new_id': mid, 'old_id': m_existing.id}
                db.execute(text('UPDATE modules SET id = :new_id WHERE id = :old_id'), params)
                db.execute(text('UPDATE tasks SET module_id = :new_id WHERE module_id = :old_id'), params)
    finally:
        if _fk_was_on:
            db.execute(text('PRAGMA foreign_keys=ON'))
    _entry_ph = db.query(_Ph).filter(_Ph.project_id.is_(None), _Ph.name == '进场准备').first()
    _prep_phase = db.query(_Ph).filter(_Ph.project_id.is_(None), _Ph.name == '项目准备').first()
    if _prep_phase is not None and _entry_ph is not None and (_prep_phase.sort_order > _entry_ph.sort_order):
        _tmp_sort = _prep_phase.sort_order
        _prep_phase.sort_order = _entry_ph.sort_order
        _entry_ph.sort_order = _tmp_sort
        db.flush()
    _has_phases = db.query(_Ph).filter(_Ph.project_id.is_(None)).count() > 0
    if _prep_phase is None and _has_phases:
        for ph in db.query(_Ph).filter(_Ph.project_id.is_(None), _Ph.sort_order >= 2).all():
            ph.sort_order = (ph.sort_order or 0) + 1
        _prep_phase = _Ph(project_id=None, name='项目准备', sort_order=1, color='#1677ff', entry_criteria='准备清单确认', exit_criteria='必需准备项完成')
        db.add(_prep_phase)
        db.flush()
        _prep_tid = _prep_phase.id
        for mid, mname, tasks in PREP_PHASE_MODULES:
            m = _Mod(id=mid, project_id=None, phase_id=_prep_tid, name=mname, category='core' if mname == '项目准备' else 'extra', is_selected=mname == '项目准备', sort_order=1)
            db.add(m)
            db.flush()
            for i, tname in enumerate(tasks, 1):
                db.add(_Task(project_id=None, template_id=None, module_id=m.id, name=tname, quantity_type='manual', target_quantity=1, unit='项', sort_order=i))
        db.flush()
    seed_team_templates(db)
    db.execute(text("UPDATE users SET role = 'pm' WHERE role = 'sub_pm'"))
    from migrations.v243_schema import Project as ProjectModel
    for pj in db.query(ProjectModel).all():
        ensure_checklist_seeded(db, pj.id)
    from migrations.v243_schema import Module as _ProjMod
    _null_phase_mods = db.query(_ProjMod).filter(_ProjMod.project_id.isnot(None), _ProjMod.phase_id.is_(None)).all()
    if _null_phase_mods:
        _tpl_by_name = {}
        for _tm in db.query(_ProjMod).filter(_ProjMod.project_id.is_(None)).all():
            _cur = _tpl_by_name.get(_tm.name)
            if _cur is None or (_cur.template_id is not None and _tm.template_id is None):
                _tpl_by_name[_tm.name] = _tm
        _fixed = 0
        for _pm in _null_phase_mods:
            _tpl = _tpl_by_name.get(_pm.name)
            if _tpl is not None and _tpl.phase_id:
                _pm.phase_id = _tpl.phase_id
                _fixed += 1
        if _fixed:
            db.flush()
    db.flush()
def detach_project_phases(db: Session):
    """幂等迁移旧项目的模板阶段引用，避免编辑/删除模板影响进行中的项目。"""
    modules = db.query(Module).join(Phase, Phase.id == Module.phase_id).filter(
        Module.project_id.isnot(None), Phase.project_id.is_(None)).all()
    for module in modules:
        source = db.get(Phase, module.phase_id)
        phase = db.query(Phase).filter(Phase.project_id == module.project_id, Phase.name == source.name).first()
        if phase is None:
            phase = Phase(project_id=module.project_id, name=source.name, sort_order=source.sort_order,
                          color=source.color, entry_criteria=source.entry_criteria, exit_criteria=source.exit_criteria)
            db.add(phase)
            db.flush()
        if not module.source_module_id:
            source_module = db.query(Module).filter(Module.project_id.is_(None), Module.phase_id == source.id,
                                                     Module.name == module.name).first()
            if source_module:
                module.source_module_id = source_module.id
        module.phase_id = phase.id
    db.flush()

def log_change(
    db: Session,
    project_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    operator_id: Optional[str],
    detail: str,
    old_value=None,
    new_value=None,
):
    """Write a single change-log entry. Call inside a transaction."""
    db.add(ChangeLog(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        operator_id=operator_id,
        detail=detail,
        old_value=old_value,
        new_value=new_value,
    ))

def migrate_scope_preparations(db):
    marker = 'scope-preparation-v1'
    if db.query(ChangeLog.id).filter_by(entity_type='migration', entity_id=marker).first():
        return
    # Bootstrap known legacy modules once; subsequent renames and explicit edits are preserved.
    for module in db.query(Module).filter(Module.project_id.is_(None)).all():
        phase = db.get(Phase, module.phase_id)
        if not phase or phase.name == '项目准备' or module.preparation_conditions:
            continue
        if module.name == '自动充电':
            module.preparation_conditions = ['need_charging']
        elif module.name in ('WMS 接口', 'WMS/MES 接口', 'WMS/MES 对接'):
            module.preparation_conditions = ['need_wms']

    preset_names = ('标准 AGV 实施模板', '潜伏式简版模板', '叉车重载项目模板', '多车型集成模板')
    template_ids = [None] + [t.id for t in db.query(Template).filter(Template.name.in_(preset_names)).all()]
    for tid in template_ids:
        # Add an optional, real execution module, not a second preparation checkbox.
        phase = db.query(Phase).filter_by(project_id=None, template_id=tid, name='系统联调').first()
        if not phase:
            continue
        modules = db.query(Module).filter_by(project_id=None, template_id=tid).all()
        if not any('need_wms' in (m.preparation_conditions or []) for m in modules):
            module = Module(template_id=tid, phase_id=phase.id, name='WMS/MES 对接', category='extra',
                            is_selected=False, sort_order=max((m.sort_order or 0 for m in modules), default=0) + 1,
                            preparation_conditions=['need_wms'],
                            description='客户业务系统与 AGV 调度系统对接，含数据映射、业务联调和异常恢复。')
            db.add(module); db.flush()
            for order, (name, check) in enumerate([
                ('业务接口与数据映射', '接口字段、鉴权及状态映射确认'),
                ('业务订单闭环联调', '下发、执行、完成反馈全流程通过'),
                ('接口异常恢复验证', '超时重试、断线恢复及重复订单处理通过'),
            ], 1):
                task = Task(template_id=tid, module_id=module.id, name=name, quantity_type='fixed',
                            target_quantity=1, unit='项', sort_order=order)
                db.add(task); db.flush()
                db.add(CheckItem(template_id=tid, task_id=task.id, name=check, is_required=True, sort_order=1))
        # This document is relevant only when integration is selected.
        for prep in db.query(TemplatePreparationItem).filter_by(template_id=tid, name='客户系统接口文档（WMS/MES）', condition='default').all():
            prep.condition = 'need_wms'
    log_change(db, None, 'migration', marker, 'update', None,
               '实施范围关联准备事项；预置方案补充可选 WMS/MES 对接工作')
    db.flush()


def migrate_shared_data(db):
    """Cross-database backfills formerly stranded below the SQLite-only return."""
    db.execute(text("UPDATE users SET role = 'pm' WHERE role = 'sub_pm'"))
    valid_users = {row[0] for row in db.query(User.id).all()}
    for project in db.query(Project).all():
        existing = {row[0] for row in db.query(ProjectMember.user_id).filter_by(project_id=project.id)}
        members = set(project.members or [])
        members.update(uid for uid in (project.manager, project.technical_manager) if uid)
        members.update(g['user_id'] for g in (project.co_managers or []) if g.get('user_id'))
        for uid in sorted(members - existing):
            if uid in valid_users:
                db.add(ProjectMember(project_id=project.id, user_id=uid, role='member'))
            else:
                log_change(db, project.id, 'migration', 't01-missing-member', 'review', None,
                           f'保留项目原始成员引用 {uid}；账号不存在，未伪造关系，请核对')
    # Existing detached project phases stay unchanged; only missing links are repaired.
    template_modules = db.query(Module).filter(Module.project_id.is_(None)).all()
    by_name = {}
    for module in template_modules:
        current = by_name.get(module.name)
        if current is None or current.template_id is not None and module.template_id is None:
            by_name[module.name] = module
    for module in db.query(Module).filter(Module.project_id.isnot(None), Module.phase_id.is_(None)):
        source = by_name.get(module.name)
        if source is not None and source.phase_id:
            module.phase_id = source.phase_id
    db.flush()

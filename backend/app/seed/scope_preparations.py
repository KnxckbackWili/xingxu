"""One-time upgrade of built-in scope/preparation links. Never rewrites project work."""
from app.models import ChangeLog, Module, Phase, Task, CheckItem, Template
from app.services.change_log import log_change


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
                task = Task(template_id=tid, module_id=module.id, phase_id=phase.id, group_label=module.name, scope_conditions=["need_wms"], name=name, quantity_type='fixed',
                            target_quantity=1, unit='项', sort_order=order)
                db.add(task); db.flush()
                db.add(CheckItem(template_id=tid, task_id=task.id, name=check, is_required=True, sort_order=1))
    log_change(db, None, 'migration', marker, 'update', None,
               '实施范围关联准备事项；预置方案补充可选 WMS/MES 对接工作')
    db.flush()

"""项目使用模板的来源及快照。模板提供起点，现场计划拥有自己的阶段。"""
from sqlalchemy.orm import Session
from app.models import Project, Phase, Module, Task, Template


def project_template_info(db: Session, project: Project) -> dict:
    template_id = project.template_id
    if not template_id:
        # 兼容旧项目：只有来源唯一时才推断，不能把自定义项目默认为系统模板。
        sources = db.query(Task.template_id).filter(Task.id.in_(
            db.query(Task.source_task_id).filter(Task.project_id == project.id, Task.source_task_id.isnot(None))
        )).distinct().all()
        if len(sources) == 1:
            template_id = sources[0][0] or 'default'
    meta = db.get(Template, template_id) if template_id and template_id != 'default' else None
    return {
        'id': template_id,
        'name': '系统默认模板' if template_id == 'default' else meta.name if meta else '来源模板已删除' if template_id else '未记录来源模板',
        'version': project.template_version or None,
        'available': template_id == 'default' or meta is not None,
    }


def detach_project_phases(db: Session):
    """幂等迁移旧项目的模板阶段引用，避免编辑/删除模板影响进行中的项目。"""
    modules = db.query(Module).join(Phase, Phase.id == Module.phase_id).filter(
        Module.project_id.isnot(None), Phase.project_id.is_(None)).all()
    for module in modules:
        source = db.get(Phase, module.phase_id)
        phase = db.query(Phase).filter(Phase.project_id == module.project_id, Phase.name == source.name).first()
        if phase is None:
            phase = Phase(project_id=module.project_id, name=source.name, sort_order=source.sort_order,
                          color=source.color, entry_criteria=source.entry_criteria, exit_criteria=source.exit_criteria, stage_key=source.stage_key)
            db.add(phase)
            db.flush()
        if not module.source_module_id:
            source_module = db.query(Module).filter(Module.project_id.is_(None), Module.phase_id == source.id,
                                                     Module.name == module.name).first()
            if source_module:
                module.source_module_id = source_module.id
        module.phase_id = phase.id
    db.flush()

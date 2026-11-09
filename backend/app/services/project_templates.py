"""项目使用模板的来源。模板提供起点，现场计划拥有自己的阶段。"""
from sqlalchemy.orm import Session
from app.models import Project, Template


def project_template_info(db: Session, project: Project) -> dict:
    template_id = project.template_id
    meta = db.get(Template, template_id) if template_id and template_id != 'default' else None
    return {
        'id': template_id,
        'name': '通用模板' if template_id == 'default' else meta.name if meta else '来源模板已删除' if template_id else '未记录来源模板',
        'version': project.template_version or None,
        'available': template_id == 'default' or meta is not None,
    }

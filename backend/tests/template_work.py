"""Work rows of the built-in template by name, for tests that used to pick the seeded modules mod-01….

The built-in template is now sections of one-row items (migration g3a93b000001); each old module maps
to the merged row that covers the same work.
"""
from app.db import SessionLocal
from app.models import TemplateItem

LEGACY_MODULES = {
    'mod-01': ('场地勘测',), 'mod-02': ('到场点检',), 'mod-03': ('单车调试',), 'mod-04': ('地图与站点',),
    'mod-05': ('服务器与网络部署',), 'mod-06': ('系统联调',), 'mod-07': ('上线运行',), 'mod-08': ('操作与维护培训', '最终验收'),
    'mod-11': ('电梯/自动门对接',), 'mod-12': ('电梯/自动门对接',), 'mod-13': ('PLC 对接',), 'mod-15': ('系统联调',), 'mod-16': (),
}


def default_items(kind=None) -> dict:
    """{name: id} of the built-in template's rows (optionally of one kind)."""
    with SessionLocal() as db:
        query = db.query(TemplateItem).filter(TemplateItem.template_id.is_(None))
        if kind:
            query = query.filter(TemplateItem.kind == kind)
        return {row.name: row.id for row in query}


def default_work(*modules) -> list:
    """Task ids (= row ids) of the built-in work rows replacing the given old module ids, or row names."""
    rows = default_items('work')
    names = [name for module in modules for name in LEGACY_MODULES.get(module, (module,))]
    return list(dict.fromkeys(rows[name] for name in names))


def upload_template_blank(client, headers, code, files, template_id='default'):
    """Attach a blank form to the template file with this code (through the template row that holds it)."""
    tree = client.get(f'/api/templates/{template_id}/items', headers=headers)
    assert tree.status_code == 200, tree.text
    item, document = next((item, document) for section in tree.json()['sections'] for item in section['items']
                           for document in item['files'] if document['code'] == code)
    return client.post(f"/api/templates/{template_id}/items/{item['id']}/files/{document['id']}/blank", headers=headers, files=files)

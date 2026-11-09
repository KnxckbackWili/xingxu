"""The built-in general template: about twenty rows that carry every company document.

Document rules (timing, scope, confidentiality) come from the company document list in
company_documents.json, matched by code.
"""
import json
from pathlib import Path
from uuid import uuid4

# (section, stage, rows); rows are (kind, name, spec). Checks are (name, safety critical).
DEFAULT_CONTENT = [
    ('启动准备', '4', [
        ('work', '内部启动会', {'note': '确认项目风险、人员、定版流程和采购清单', 'files': ['4.1', '4.2', '4.3', '4.4', '4.5']}),
        ('purchase', 'AGV 本体', {'unit': '台', 'spec': '按合同型号与配置'}),
        ('purchase', '自动充电桩', {'unit': '台', 'spec': '按车辆 1:1 选型，含安装底座'}),
    ]),
    ('发车前', '5', [
        ('file', '发车与进场资料', {'files': ['5.1.1', '5.1.2', '5.1.3', '5.1.4', '5.1.5', '5.2.1', '5.2.2', '5.3', '5.4']}),
        ('work', '场地勘测', {'checks': [('场地尺寸与平整度测量', False), ('通道宽度与转弯半径确认', False),
                                     ('网络覆盖与带宽测试', False), ('安全围栏与警示标识检查', True),
                                     ('施工方案各节点签字确认', False)]}),
        ('purchase', '网络设备', {'unit': '套', 'spec': '工业路由器、千兆交换机、网线（按现场需要）', 'optional': True}),
        ('purchase', '安全围栏', {'unit': '米', 'spec': '铝合金围栏 1.2m 高，含立柱', 'optional': True}),
    ]),
    ('到货与单车调试', '6', [
        ('work', '到场点检', {'per_vehicle': True, 'step': 'arrival_inspection',
                           'checks': [('外观检查无损伤', False), ('核对设备清单与配件', False), ('电池电压与充电器功能', True)],
                           'files': ['6.1', '6.10.1']}),
        ('work', '单车调试', {'per_vehicle': True, 'step': 'single_commissioning',
                           'checks': [('机械与导航调试，到点精度≤30mm', False), ('安全激光与停车距离验证', True),
                                      ('额定载荷与过载保护测试', True), ('急停、触边与失速保护', True), ('车辆参数与程序备份', False)],
                           'files': ['6.11.2a', '6.11.2.1', '6.11.2.2', '6.11.2b', '6.10.2']}),
    ]),
    ('系统部署与联调', '6', [
        ('work', '服务器与网络部署', {'checks': [('服务器上架与系统安装', False), ('调度系统与数据库部署', False),
                                            ('防火墙、VLAN 与远程访问', False), ('自动备份与恢复测试', False)],
                                 'files': ['6.11.6a', '6.11.6b', '6.11.6c', '6.11.1a', '6.11.1b']}),
        ('work', '地图与站点', {'checks': [('建图并验证地图精度', False), ('工位与充电站点设置', False),
                                       ('路径规划与交通管制区域', False), ('地图文件备份（本地+云端）', False)],
                             'files': ['6.11.3a', '6.11.3b', '6.11.4']}),
        ('work', '系统联调', {'per_vehicle': True, 'step': 'system_integration',
                           'checks': [('多车任务分配与交通管制', False), ('任务创建→执行→完成全流程', False),
                                      ('断网恢复与故障接管', True), ('紧急情况全系统停止', True), ('满载吞吐与响应延迟达标', False)]}),
        ('work', 'WMS/MES 对接', {'optional': True, 'checks': [('接口字段、鉴权及状态映射确认', False),
                                                            ('下发、执行、完成反馈全流程通过', False),
                                                            ('超时重试、断线恢复及重复订单处理通过', False)]}),
        ('work', '电梯/自动门对接', {'optional': True, 'checks': [('设备安装与信号对接', False), ('联动联调通过', False)]}),
        ('work', 'PLC 对接', {'optional': True, 'checks': [('PLC 信号对接', False), ('联调通过', False)], 'files': ['6.11.5']}),
    ]),
    ('试运行', '6', [
        ('work', '上线运行', {'per_vehicle': True, 'step': 'go_live',
                           'checks': [('连续运行≥7天无重大故障', False), ('异常统计、整改与复测', True), ('试运行报告与运行数据归档', False)],
                           'files': ['6.10.3', '6.11.8']}),
        ('purchase', '备件（坏件更换）', {'unit': '件', 'spec': '现场损坏需更换的零部件，按实际填写', 'optional': True}),
    ]),
    ('培训与验收', '7', [
        ('work', '操作与维护培训', {'checks': [('操作、维护手册交付', False), ('操作与维护人员实操考核', False)], 'files': ['6.10.4']}),
        ('work', '最终验收', {'checks': [('验收标准逐项确认', False), ('客户签字验收', False), ('全部项目文档归档', False)], 'files': ['7.1']}),
    ]),
    ('交付', '8', [
        ('file', '交付资料', {'files': ['8.1', '8.2', '8.3', '8.4']}),
    ]),
    ('过程记录', '6', [
        ('file', '每周资料', {'files': ['6.2', '6.3', '6.4', '6.5', '6.11.7', '6.11.9']}),
        ('file', '发生时提交', {'files': ['6.6', '6.7', '6.8.1', '6.8.2', '6.9.1', '6.9.2', '6.9.3']}),
    ]),
    ('全程记录', '9', [
        ('file', '全程更新资料', {'files': ['9.1', '9.2']}),
    ]),
]

FILE_KEYS = ('code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours',
             'timing_weekday', 'trigger_type', 'confidential_default', 'note')


def company_documents() -> dict:
    """The company's document list by code (groups left out)."""
    rows = json.loads((Path(__file__).with_name('company_documents.json')).read_text(encoding='utf-8'))
    return {row['code']: row for row in rows if not row.get('is_group')}


def seed_default_template(db):
    """Give an installation without the built-in template its merged general template (idempotent)."""
    from app.models import TemplateItem, TemplateSection
    from app.services.template_items import compile_template
    if db.query(TemplateSection.id).filter(TemplateSection.template_id.is_(None)).first() is not None:
        return False
    rules = company_documents()
    for section_index, (title, stage, rows) in enumerate(DEFAULT_CONTENT):
        section = TemplateSection(id=str(uuid4()), template_id=None, title=title, stage_key=stage, sort_order=section_index)
        db.add(section)
        db.flush()
        for position, (kind, name, spec) in enumerate(rows):
            files = [{**{key: rules[code].get(key) for key in FILE_KEYS}, 'id': str(uuid4()),
                      'scope': rules[code].get('scope') or 'project', 'template_no': rules[code].get('template_no') or '',
                      'note': rules[code].get('note') or '', 'blank_file_id': None, 'source_metadata': None}
                     for code in spec.get('files', []) if code in rules]
            db.add(TemplateItem(
                id=str(uuid4()), template_id=None, section_id=section.id, kind=kind, name=name, note=spec.get('note', ''),
                optional=spec.get('optional', False), per_vehicle=spec.get('per_vehicle', False), step_key=spec.get('step'),
                checks=[{'id': str(uuid4()), 'name': check, 'description': '', 'required': True, 'safety': safety}
                        for check, safety in spec.get('checks', [])],
                files=files, quantity=None, unit=spec.get('unit', ''), spec=spec.get('spec', ''), extra={},
                sort_order=position, version=0))
    db.flush()
    compile_template(db, None)
    return True

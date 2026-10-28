"""The single stage backbone of templates and projects.

Templates and projects are organised by the company document stages 4–9. Work groups
(phases), document requirements, procurement and vehicle work all hang off these
stages, and the lifecycle gates already read the same numbering (stage 4/5 before
execution, stage 6 sign-offs before acceptance, 4–9 before completion/archive).

This module has no app imports so models and migrations-adjacent code can use it.
"""

STAGES = (
    ('4', '内部启动会'),
    ('5', '发车前'),
    ('6', '实施'),
    ('7', '验收'),
    ('8', '交付'),
    ('9', '全项目周期'),
)
STAGE_KEYS = tuple(key for key, _ in STAGES)
STAGE_NAMES = dict(STAGES)
DEFAULT_WORK_STAGE = '6'

# Former work phases of the default template and their place on the backbone.
PHASE_STAGE_BY_NAME = {
    '项目准备': '4',
    '进场准备': '5',
    '到货检查': '6', '单车调试': '6', '地图与站点': '6', '系统部署': '6',
    '系统联调': '6', '联调工作': '6', '试运行': '6', '试运行工作': '6', '现场追加工作': '6',
    '培训验收': '7',
}


def infer_phase_stage(name: str | None) -> str:
    return PHASE_STAGE_BY_NAME.get((name or '').strip(), DEFAULT_WORK_STAGE)


def stage_order(key: str | None) -> int:
    return STAGE_KEYS.index(key) if key in STAGE_KEYS else len(STAGE_KEYS)

"""One allowlist for retained read-only Agent grants; old rows stay as evidence."""
SCOPE_OPTIONS = [
    ('projects:read','项目列表与详情'), ('issues:read','问题列表'),
    ('inventory:read','现场物品'), ('dashboard:read','项目组合概览'),
    ('templates:read','资料模板与车辆环节'), ('team:read','项目团队'),
    ('vehicles:read','车辆资料与进度表'), ('files:read','资料清单、本周待交与文件目录'),
    ('activity:read','项目动态'),
]
ACTIVE_SCOPES = frozenset(scope for scope,_ in SCOPE_OPTIONS)
DEFAULT_SCOPES = [scope for scope,_ in SCOPE_OPTIONS]

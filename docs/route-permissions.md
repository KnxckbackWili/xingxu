# 路由权限声明

系统级显式禁止和资源权限共同生效。每个写接口必须在路由处声明权限；启动自检在数据库迁移和调度器启动前执行。新接口没有声明会拒绝启动，遗漏自检的独立应用中，未声明的会话接口也会拒绝执行。URL 名称不参与权限选择。

普通操作在 FastAPI 路由装饰器下声明动作，同时保留认证依赖和处理器内的资源、角色及生命周期检查：

```python
@router.post("/templates")
@route_permission("system.templates.manage")
def create_template(user: User = Depends(require_admin)):
    ...
```

多个 key 表示每项都需要。`require_project_capability(...)` 依赖同样构成声明，包含嵌套依赖；处理器仍按项目实际关系校验。普通权限声明的写接口必须包含 `get_current_user` 认证依赖，避免只有元数据却匿名可写。

同一接口承载不同动作时，使用 `route_permission_contextual(..., reason=...)` 列明可能使用的权限，处理器在解析真实资源和每个动作后逐项校验。例如资料提交与审核、项目成员字段与资料字段、混合离线操作；它不是把不同权限合并为 AND，也不为处理器授予权限。资料审核仍不能自审，离线操作仍逐项刷新账号和授权。

公开登录、当前账号会话、只读业务候选字典和只能真实管理员执行的操作，可使用 `route_permission_exempt(reason)` 说明独立校验依据。不要以此省略普通业务操作的权限检查。Agent HTTP/MCP 使用专用令牌认证，明确声明独立协议边界；工具调用逐次校验账号、scope、系统动作与资源范围。

自检覆盖 FastAPI 0.141 的懒加载及嵌套 include、隐藏的 Starlette 写路由和 ASGI 挂载边界。新增挂载应用必须明确认证边界，不能借 mount 绕过写接口检查。升级 FastAPI 时必须运行 `test_system_permissions.py` 中的嵌套扫描负测试。

验证包括：全部生产写接口声明、未知 key、无说明豁免、缺认证声明、未声明新写接口、隐藏路由及嵌套挂载拒绝；原系统权限授予/撤销、项目隔离、成员授权和业务角色回归。

# 路由权限声明

每个写接口必须在路由处声明动作；启动自检在数据库迁移和调度器启动前执行，缺声明、未知动作或无说明豁免都会拒绝启动。URL 名称不参与权限选择。

```python
@router.post("/templates")
@route_permission("system.templates.manage")
def create_template(user: User = Depends(require_admin)):
    ...
```

动作清单在 `app/services/system_permissions.py`。`has_permission(user, key)` 的规则只有一条：账号启用时，系统管理员可做全部动作，员工可做 `ADMIN_ONLY` 以外的动作。`get_current_user` 会按声明逐项校验。

- 多个 key 表示每项都需要。`require_project_capability(...)` 依赖同样构成声明；处理器仍按项目、生命周期和版本校验。
- 同一接口承载不同动作时用 `route_permission_contextual(..., reason=...)`，处理器在解析真实资源后逐项校验，例如混合离线同步。
- 登录、当前账号会话和只能系统管理员执行的操作可用 `route_permission_exempt(reason)` 写明独立校验依据，不能用来省略普通业务检查。
- 普通权限声明的写接口必须包含 `get_current_user` 认证依赖。

自检覆盖懒加载及嵌套 include、隐藏的 Starlette 写路由和 ASGI 挂载边界；新增挂载应用必须明确认证边界。

## 版本号（乐观锁）

项目基本信息、问题、工作项、资料状态与关键事件的编辑请求必须携带读取时的 `version`。缺少版本号返回 428（`require_client_version`），版本不符返回 409。车辆到场批量登记例外：各批次只改所选车辆并在项目锁内重算全部到场，版本号可选。

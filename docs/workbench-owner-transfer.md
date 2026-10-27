# 工作台事实与负责人更换

T50 后端把日常项目读模型集中在 `app.services.workbench`，不重新计算日数量、工时、人员负荷或自动排程。导航、工作台折叠统计和项目设置使用这些接口。

## 当前事实接口

- `GET /api/projects`：保留现有列表/分页形式，为每个可见项目补充 `vehicle_progress`、`document_attention` 和 `next_signoff`，只要求 `project.read`，不额外要求工作台权限。
- `GET /api/dashboard/overview`：要求 `workspace.view`，返回项目当前事实、顶层 `this_week_documents` 和 `weekly_plan`；不再返回人员工时、混单位数量或治理申请。
- `GET /api/dashboard/statistics`：独立要求 `insights.view`，即使没有 `workspace.view` 也可读本人的可见项目聚合。返回项目/状态计数、车辆进度、待交/逾期资料计数和未闭环问题计数，不返回项目名、资料名、原文件、人员日程或工时。

车辆字段直接沿用 T30 matrix.summary：`target`、`completed`、`identified_completed`、`unidentified_completed`、`quantity_unknown`、`fleet_quantity_unknown`、`unregistered_quantity`、`percent`；列表增加 `progress_known = !quantity_unknown`。统计保留目标、完成、未知状态及未辨识完成数量。未知分母时百分比为 `null`，旧米/项等数量不混入车辆分母。

资料字段沿用 T23 时区/期限来源和 T26 当前可见性：`this_week`、`this_week_count`、`overdue`、`overdue_count`、`estimated_past_due_count`、`on_demand`、`owner_warnings`、`period_key`、`timezone`、`as_of`。列表项附 `project_id`、`project_name`、`timezone`、`url`。非运行项目没有当前待交义务。`next_signoff` 是按 6.10.1–6.10.4 顺序筛出的首张适用、未交且当前账号可见签单；有授权的保密资料元数据读取会审计。

问题计数复用一个批量投影：普通 Issue 的 `closed`/`cancelled` 为已闭环，`resolved` 仍待最终关闭；车辆问题中心的故障/维修/保养/检查/其他事件以 `is_closed` 为准。严重计数包含 high/critical Issue 和当前 fault/stopped 车辆的未闭环事件。计数接口不回传问题文字。

T40 未接入前，`weekly_plan_attention` 明确返回 `{state: "unavailable", count: null, items: null, reason: "本周计划尚未读取"}`。T40 应替换该接缝，不能用零项冒充成功读取。所有项目/工作台响应（包括拒绝响应）设为 `Cache-Control: private, no-store`，总览不使用跨授权变化的资料名 TTL 缓存。

## 直接更换负责人

先调用 `GET /api/projects/{id}/transfer-preview`，取得：

```json
{
  "project_id": "…", "version": 1,
  "current_manager": {"id": "…", "name": "…"},
  "candidates": [{"id": "…", "name": "…"}],
  "removed": [{"user_id": "…", "name": "…", "documents": []}],
  "warning": "…", "rule_warning": "…"
}
```

再调用 `POST /api/projects/{id}/transfer`：

```json
{
  "target_manager_id": "…",
  "reason": "填写至少五个字的具体更换理由",
  "version": 1,
  "member_removal_confirmations": ["确实离场的人员ID"]
}
```

当前负责人或启用的管理员还必须具有 `project.update` 和 `project.manage_members`。接收人必须是当前启用且有项目查看/维护权限的 PM。项目锁后按账号策略编辑器同一 User 锚点顺序加锁，重新读取 actor、token version、角色、操作权限及接收人状态；项目版本不符返回 409。归档和未修复历史生命周期项目保持只读。

离场确认必须精确匹配预览，缺失/多余确认均拒绝。仅真实离场成员触发 T24 的 6.7 资料；仍有明确技术负责人/协管等角色的前负责人可以保留成员资格，但不再获得“当前 manager”隐式保密阅读权。自定义保密留存标题在预览和 409 中按 T26 隐去。更换、离场事件、成员同步、审计和通知在同一事务提交，审计失败全部回滚。成功响应为项目对象并补 `viewer_retains_access`，前端据此决定是否仍可留在当前项目。

普通 `PUT /api/projects/{id}` 一律拒绝 `manager_id` 字段，管理员同样须走直接更换入口，不能省略理由、版本或离场确认。

## 退役与历史保全

原治理申请创建、列表、预览、审批和撤回接口认证后返回 410，不读取/改写历史申请。旧决策视图也不再输出治理申请或待审批计数。`system.governance.review` 从当前可编辑权限目录和前端权限常量移除，原账号 overrides 原值留存但不产生权限；保存其它当前权限时保留未知历史键，旧编辑器只可提交已有且未变化的退役值，不能新增或改变它。

`ProjectGovernanceRequest` 原表不删除、不改写，项目永久删除时原非 FK 历史行仍留存；完整记录进入 T12/#85 私有加密项目备份，普通项目保留快照不再公开这些记录。系统备份原有覆盖保持不变。

本任务未引入迁移。T40 后续应把 `member_handover` 旧已确认日程约束接到真实周计划/当前工作；本次没有自动重分配或删除旧日程行。

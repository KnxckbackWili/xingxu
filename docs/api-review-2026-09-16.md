# 接口与流程审查 · 2026-09-16

> 本文引用的 QA 回执描述历史时点，原件已[归档](evidence-archive.md)；当前 v3 操作请从[文档入口](index.md)开始。

## 覆盖与结论

共盘点 244 个业务 API 操作。240 个需登录操作全部执行了匿名请求检查，均拒绝访问；另外 4 个是登录、刷新、退出和公开角色说明。
全部 40 个带 project_id 的 GET 操作还使用未加入该项目的现场账号检查，未返回项目数据。参数必填校验导致的 422 单独接受，因此这不是每个操作全部权限分支的穷举。

完整后端回归 646 项通过；完整前端回归 220 项通过。之后补充有限数值校验并对相关路由补跑回归（见后文最终验证）。

本清单证明接口注册与上述边界检查的覆盖，不等于所有接口在任意输入、并发或真实外部服务下均正确。MCP 挂载、WebSocket、真实 AI 服务、消息渠道、PostgreSQL 多进程并发与生产 NAS 环境不在此次逐接口请求检查范围内。

## 本轮修复

1. 创建项目、车型、初始任务与审计同事务提交；失败回滚。新增创建凭证表，按用户与请求键去重，同键不同内容拒绝。复制的模板资料在创建失败时清理。旧客户端只建项目的请求保持兼容。
2. 模板切换使用请求序号防止旧响应覆盖新选择；加载或失败时禁止创建。模块 ID 必须全部属于所选模板，拒绝静默部分生成。
3. 任务生成与状态切换改为明确的请求模型，错误类型返回校验错误。数量字段禁止无穷和 NaN。
4. 撤回填报检查当前项目可见性与归档状态，并记录审计。记录列表返回项目当地日期与可撤回标记；前端按后端规则显示入口。
5. 填报记录切换月份防止过期响应，撤回后保留筛选，加载失败可重试；合计按单位分开，注明最多显示 200 条。
6. 解决问题失败保留方案，成功后才关闭；作废要求真实原因。
7. 创建弹窗的车型行按手机卡片分组，保留明确字段标签和固定可见的提交区；记录页筛选与任务标题允许换行。普通交付提醒不再一律标红为紧急。

## 部署与限制

新增 project_creation_receipts 表由现有 init_db / create_all 创建；没有修改旧表列。部署必须同时更新前后端并重启服务，旧前端仍可使用旧的分步接口。此次仅修改并验证本地环境，未部署生产。
创建去重键保存在当前页面内存，跨刷新后的新请求不保证与先前请求去重；返回成功结果前会重新验证项目可见性。并发唯一约束与异常恢复已实现，未在真实 PostgreSQL 多进程下压测。
跨页面持久草稿、附件上传响应丢失后的服务端去重、全站时间戳统一仍是后续工作，未在本轮宣称完成。

## 接口清单

“登录”列是路由依赖静态盘点，项目级能力可能在处理函数内部继续校验。

| 路由模块 | 操作数 |
|---|---:|
| ai_internal | 4 |
| ai_memory | 3 |
| ai_projects | 13 |
| archive | 3 |
| archives | 3 |
| attachments | 4 |
| auth | 5 |
| availability | 6 |
| change_sets | 6 |
| codex | 1 |
| dashboard | 11 |
| feedback | 4 |
| inbox | 7 |
| incidents | 6 |
| insights | 13 |
| inventory | 8 |
| io_routes | 9 |
| issues | 7 |
| logs | 1 |
| notification_channels | 4 |
| notifications | 5 |
| org | 5 |
| preparations | 10 |
| progress | 3 |
| projects | 16 |
| report_forms | 11 |
| reports | 1 |
| schedules | 10 |
| system | 5 |
| tasks | 8 |
| team_templates | 5 |
| templates | 23 |
| users | 5 |
| vehicle_lifecycle | 6 |
| vehicle_types | 5 |
| worker | 8 |

| 方法 | 路径 | 登录依赖 | 处理函数 |
|---|---|---|---|
| GET | `/api/ai-projects/capabilities` | 有 | `app.routers.ai_projects.get_capabilities` |
| POST | `/api/ai-projects/chat` | 有 | `app.routers.ai_projects.chat` |
| GET | `/api/ai-projects/chat/sessions` | 有 | `app.routers.ai_projects.get_chat_session_list` |
| DELETE | `/api/ai-projects/chat/sessions/{session_id}` | 有 | `app.routers.ai_projects.remove_chat_session` |
| GET | `/api/ai-projects/chat/sessions/{session_id}` | 有 | `app.routers.ai_projects.get_chat_session` |
| POST | `/api/ai-projects/chat/stream` | 有 | `app.routers.ai_projects.chat_stream` |
| POST | `/api/ai-projects/extract` | 有 | `app.routers.ai_projects.extract_documents` |
| POST | `/api/ai-projects/organize` | 有 | `app.routers.ai_projects.organize` |
| POST | `/api/ai-projects/organize/jobs` | 有 | `app.routers.ai_projects.create_organize_job` |
| GET | `/api/ai-projects/organize/jobs/{job_id}` | 有 | `app.routers.ai_projects.get_organize_job` |
| GET | `/api/ai-projects/skill-bundle` | 有 | `app.routers.ai_projects.download_skill` |
| GET | `/api/ai-projects/status` | 有 | `app.routers.ai_projects.get_status` |
| POST | `/api/ai-projects/test-connection` | 有 | `app.routers.ai_projects.check_connection` |
| POST | `/api/ai/codex/chat` | 有 | `app.routers.codex.codex_chat` |
| GET | `/api/ai/internal/tokens` | 有 | `app.routers.ai_internal.list_tokens` |
| POST | `/api/ai/internal/tokens` | 有 | `app.routers.ai_internal.create_token` |
| DELETE | `/api/ai/internal/tokens/{token_id}` | 有 | `app.routers.ai_internal.revoke_token` |
| PUT | `/api/ai/internal/tokens/{token_id}` | 有 | `app.routers.ai_internal.update_token` |
| GET | `/api/ai/memory` | 有 | `app.routers.ai_memory.list_memories` |
| POST | `/api/ai/memory` | 有 | `app.routers.ai_memory.create_memory` |
| DELETE | `/api/ai/memory/{memory_id}` | 有 | `app.routers.ai_memory.delete_memory` |
| GET | `/api/archives/projects` | 有 | `app.routers.archives.list_project_archives` |
| GET | `/api/archives/projects/{project_id}` | 有 | `app.routers.archives.get_project_archive` |
| GET | `/api/archives/projects/{project_id}/verify` | 有 | `app.routers.archives.verify_project_archive` |
| DELETE | `/api/attachments/{attachment_id}` | 有 | `app.routers.attachments.delete_attachment` |
| GET | `/api/attachments/{attachment_id}/download` | 有 | `app.routers.attachments.download_attachment` |
| POST | `/api/auth/login` | 公开/会话入口 | `app.routers.auth.login` |
| POST | `/api/auth/logout` | 公开/会话入口 | `app.routers.auth.logout` |
| GET | `/api/auth/me` | 有 | `app.routers.auth.me` |
| PUT | `/api/auth/password` | 有 | `app.routers.auth.change_password` |
| POST | `/api/auth/refresh` | 公开/会话入口 | `app.routers.auth.refresh_token` |
| GET | `/api/dashboard/assignment-pool` | 有 | `app.routers.dashboard.assignment_pool` |
| GET | `/api/dashboard/decision-view` | 有 | `app.routers.dashboard.decision_view` |
| GET | `/api/dashboard/issues` | 有 | `app.routers.dashboard.scope_issues` |
| GET | `/api/dashboard/metrics` | 有 | `app.routers.dashboard.management_metrics` |
| GET | `/api/dashboard/overdue` | 有 | `app.routers.dashboard.overdue_projects` |
| GET | `/api/dashboard/overview` | 有 | `app.routers.dashboard.portfolio_overview` |
| GET | `/api/dashboard/people-overview` | 有 | `app.routers.dashboard.people_overview` |
| GET | `/api/dashboard/people-plan` | 有 | `app.routers.insights.people_plan` |
| POST | `/api/dashboard/people-plan/self` | 有 | `app.routers.insights.create_my_plan_entry` |
| PUT | `/api/dashboard/people-plan/{entry_id}/self` | 有 | `app.routers.insights.update_my_plan_entry` |
| GET | `/api/dashboard/people-summary` | 有 | `app.routers.dashboard.people_summary` |
| GET | `/api/dashboard/people-workload` | 有 | `app.routers.dashboard.people_workload` |
| GET | `/api/dashboard/personal-events` | 有 | `app.routers.insights.list_personal_events` |
| POST | `/api/dashboard/personal-events` | 有 | `app.routers.insights.create_personal_event` |
| DELETE | `/api/dashboard/personal-events/{event_id}` | 有 | `app.routers.insights.delete_personal_event` |
| PUT | `/api/dashboard/personal-events/{event_id}` | 有 | `app.routers.insights.update_personal_event` |
| GET | `/api/dashboard/stats` | 有 | `app.routers.dashboard.unified_stats` |
| GET | `/api/dashboard/team-schedule` | 有 | `app.routers.insights.team_schedule` |
| GET | `/api/dashboard/trend` | 有 | `app.routers.dashboard.portfolio_trend` |
| GET | `/api/dashboard/workload` | 有 | `app.routers.insights.global_workload` |
| GET | `/api/feedback` | 有 | `app.routers.feedback.list_feedback` |
| POST | `/api/feedback` | 有 | `app.routers.feedback.create_feedback` |
| GET | `/api/feedback/{feedback_id}` | 有 | `app.routers.feedback.get_feedback` |
| PATCH | `/api/feedback/{feedback_id}/status` | 有 | `app.routers.feedback.update_feedback_status` |
| GET | `/api/inbox/documents` | 有 | `app.routers.inbox.list_documents` |
| POST | `/api/inbox/documents` | 有 | `app.routers.inbox.upload_documents` |
| POST | `/api/inbox/documents/organize/jobs` | 有 | `app.routers.inbox.create_organize_job` |
| GET | `/api/inbox/documents/organize/jobs/{job_id}` | 有 | `app.routers.inbox.get_organize_job` |
| DELETE | `/api/inbox/documents/{doc_id}` | 有 | `app.routers.inbox.delete_document` |
| POST | `/api/inbox/documents/{doc_id}/archive` | 有 | `app.routers.inbox.archive_document` |
| GET | `/api/inbox/documents/{doc_id}/download` | 有 | `app.routers.inbox.download_document` |
| GET | `/api/inventory` | 有 | `app.routers.inventory.global_inventory` |
| DELETE | `/api/issues/{issue_id}` | 有 | `app.routers.issues.delete_issue` |
| PUT | `/api/issues/{issue_id}` | 有 | `app.routers.issues.update_issue` |
| POST | `/api/issues/{issue_id}/reopen` | 有 | `app.routers.issues.reopen_issue` |
| GET | `/api/north-star` | 有 | `app.routers.insights.north_star_metric` |
| GET | `/api/notification-channels` | 有 | `app.routers.notification_channels.get_channels` |
| DELETE | `/api/notification-channels/dingtalk` | 有 | `app.routers.notification_channels.disable_dingtalk` |
| PUT | `/api/notification-channels/dingtalk` | 有 | `app.routers.notification_channels.put_dingtalk` |
| POST | `/api/notification-channels/dingtalk/test` | 有 | `app.routers.notification_channels.test_dingtalk` |
| GET | `/api/notifications` | 有 | `app.routers.notifications.list_notifications` |
| POST | `/api/notifications/read-all` | 有 | `app.routers.notifications.mark_all_read` |
| POST | `/api/notifications/read-batch` | 有 | `app.routers.notifications.mark_batch_read` |
| GET | `/api/notifications/unread-count` | 有 | `app.routers.notifications.unread_count` |
| POST | `/api/notifications/{notification_id}/read` | 有 | `app.routers.notifications.mark_read` |
| GET | `/api/org/groups` | 有 | `app.routers.org.list_groups` |
| POST | `/api/org/groups` | 有 | `app.routers.org.create_group` |
| DELETE | `/api/org/groups/{group_id}` | 有 | `app.routers.org.delete_group` |
| PUT | `/api/org/groups/{group_id}` | 有 | `app.routers.org.update_group` |
| GET | `/api/org/roles` | 有 | `app.routers.org.list_roles` |
| GET | `/api/projects` | 有 | `app.routers.projects.list_projects` |
| POST | `/api/projects` | 有 | `app.routers.projects.create_project` |
| GET | `/api/projects/governance/requests` | 有 | `app.routers.projects.list_governance_requests` |
| POST | `/api/projects/governance/requests/{request_id}/review` | 有 | `app.routers.projects.review_governance_request` |
| POST | `/api/projects/import/json` | 有 | `app.routers.io_routes.import_project_json` |
| POST | `/api/projects/import/preview` | 有 | `app.routers.io_routes.preview_quick_import` |
| GET | `/api/projects/import/template` | 有 | `app.routers.io_routes.download_quick_import_template` |
| DELETE | `/api/projects/{project_id}` | 有 | `app.routers.projects.delete_project` |
| GET | `/api/projects/{project_id}` | 有 | `app.routers.projects.get_project` |
| PUT | `/api/projects/{project_id}` | 有 | `app.routers.projects.update_project` |
| GET | `/api/projects/{project_id}/acceptance` | 有 | `app.routers.projects.list_acceptance` |
| POST | `/api/projects/{project_id}/acceptance` | 有 | `app.routers.projects.create_acceptance` |
| GET | `/api/projects/{project_id}/archive-checklist` | 有 | `app.routers.archive.get_checklist` |
| POST | `/api/projects/{project_id}/archive-checklist/initialize` | 有 | `app.routers.archive.initialize_checklist` |
| PUT | `/api/projects/{project_id}/archive-checklist/{item_id}` | 有 | `app.routers.archive.update_item` |
| GET | `/api/projects/{project_id}/attachments` | 有 | `app.routers.attachments.list_attachments` |
| POST | `/api/projects/{project_id}/attachments` | 有 | `app.routers.attachments.upload_attachment` |
| GET | `/api/projects/{project_id}/change-sets` | 有 | `app.routers.change_sets.list_change_sets` |
| POST | `/api/projects/{project_id}/change-sets/propose` | 有 | `app.routers.change_sets.propose` |
| GET | `/api/projects/{project_id}/change-sets/{change_set_id}` | 有 | `app.routers.change_sets.detail` |
| POST | `/api/projects/{project_id}/change-sets/{change_set_id}/cancel` | 有 | `app.routers.change_sets.cancel` |
| POST | `/api/projects/{project_id}/change-sets/{change_set_id}/merge` | 有 | `app.routers.change_sets.merge` |
| POST | `/api/projects/{project_id}/change-sets/{change_set_id}/rollback` | 有 | `app.routers.change_sets.rollback` |
| PUT | `/api/projects/{project_id}/check-items/{cid}` | 有 | `app.routers.tasks.update_check_item` |
| POST | `/api/projects/{project_id}/clone` | 有 | `app.routers.io_routes.clone_project` |
| GET | `/api/projects/{project_id}/current-phase` | 有 | `app.routers.insights.current_phase` |
| GET | `/api/projects/{project_id}/export/excel` | 有 | `app.routers.io_routes.export_project_excel` |
| GET | `/api/projects/{project_id}/export/json` | 有 | `app.routers.io_routes.export_project_json` |
| GET | `/api/projects/{project_id}/export/lifecycle` | 有 | `app.routers.report_forms.export_lifecycle` |
| GET | `/api/projects/{project_id}/export/package` | 有 | `app.routers.io_routes.export_project_package` |
| POST | `/api/projects/{project_id}/governance-requests` | 有 | `app.routers.projects.create_governance_request` |
| POST | `/api/projects/{project_id}/import/item-application` | 有 | `app.routers.report_forms.import_item_application` |
| POST | `/api/projects/{project_id}/import/lifecycle` | 有 | `app.routers.report_forms.import_lifecycle` |
| POST | `/api/projects/{project_id}/import/quality-form` | 有 | `app.routers.report_forms.import_quality_form` |
| GET | `/api/projects/{project_id}/incidents` | 有 | `app.routers.incidents.list_incidents` |
| POST | `/api/projects/{project_id}/incidents` | 有 | `app.routers.incidents.create_incident` |
| GET | `/api/projects/{project_id}/incidents/{incident_id}` | 有 | `app.routers.incidents.get_incident` |
| POST | `/api/projects/{project_id}/incidents/{incident_id}/block` | 有 | `app.routers.incidents.update_blocked_tasks` |
| POST | `/api/projects/{project_id}/incidents/{incident_id}/postpone` | 有 | `app.routers.incidents.postpone_schedule` |
| POST | `/api/projects/{project_id}/incidents/{incident_id}/status` | 有 | `app.routers.incidents.change_status` |
| GET | `/api/projects/{project_id}/inventory` | 有 | `app.routers.inventory.project_inventory` |
| POST | `/api/projects/{project_id}/inventory` | 有 | `app.routers.inventory.create_item` |
| POST | `/api/projects/{project_id}/inventory/import` | 有 | `app.routers.inventory.import_items` |
| DELETE | `/api/projects/{project_id}/inventory/{item_id}` | 有 | `app.routers.inventory.delete_item` |
| PUT | `/api/projects/{project_id}/inventory/{item_id}` | 有 | `app.routers.inventory.update_item` |
| GET | `/api/projects/{project_id}/inventory/{item_id}/movements` | 有 | `app.routers.inventory.list_movements` |
| POST | `/api/projects/{project_id}/inventory/{item_id}/movements` | 有 | `app.routers.inventory.create_movement` |
| GET | `/api/projects/{project_id}/issues` | 有 | `app.routers.issues.list_issues` |
| POST | `/api/projects/{project_id}/issues` | 有 | `app.routers.issues.create_issue` |
| POST | `/api/projects/{project_id}/issues/import` | 有 | `app.routers.issues.import_issues` |
| GET | `/api/projects/{project_id}/issues/{issue_id}/export/quality-form` | 有 | `app.routers.report_forms.export_quality_form` |
| GET | `/api/projects/{project_id}/item-applications` | 有 | `app.routers.report_forms.list_item_applications` |
| POST | `/api/projects/{project_id}/item-applications` | 有 | `app.routers.report_forms.create_item_application` |
| DELETE | `/api/projects/{project_id}/item-applications/{app_id}` | 有 | `app.routers.report_forms.delete_item_application` |
| GET | `/api/projects/{project_id}/item-applications/{app_id}` | 有 | `app.routers.report_forms.get_item_application` |
| PUT | `/api/projects/{project_id}/item-applications/{app_id}` | 有 | `app.routers.report_forms.update_item_application` |
| GET | `/api/projects/{project_id}/item-applications/{app_id}/export` | 有 | `app.routers.report_forms.export_item_application` |
| GET | `/api/projects/{project_id}/logs` | 有 | `app.routers.logs.list_logs` |
| GET | `/api/projects/{project_id}/modules` | 有 | `app.routers.tasks.list_modules` |
| GET | `/api/projects/{project_id}/overdue` | 有 | `app.routers.insights.overdue_tasks` |
| GET | `/api/projects/{project_id}/overview` | 有 | `app.routers.progress.project_overview` |
| GET | `/api/projects/{project_id}/preparations` | 有 | `app.routers.preparations.list_preparations` |
| POST | `/api/projects/{project_id}/preparations` | 有 | `app.routers.preparations.create_item` |
| POST | `/api/projects/{project_id}/preparations/confirm-ready` | 有 | `app.routers.preparations.confirm_ready` |
| POST | `/api/projects/{project_id}/preparations/import-procurements` | 有 | `app.routers.preparations.import_procurements` |
| POST | `/api/projects/{project_id}/preparations/review` | 有 | `app.routers.preparations.review_manifest` |
| POST | `/api/projects/{project_id}/preparations/review/confirm` | 有 | `app.routers.preparations.review_confirm` |
| GET | `/api/projects/{project_id}/preparations/reviews` | 有 | `app.routers.preparations.list_reviews` |
| POST | `/api/projects/{project_id}/preparations/seed` | 有 | `app.routers.preparations.seed_items` |
| DELETE | `/api/projects/{project_id}/preparations/{item_id}` | 有 | `app.routers.preparations.delete_item` |
| PUT | `/api/projects/{project_id}/preparations/{item_id}` | 有 | `app.routers.preparations.update_item` |
| GET | `/api/projects/{project_id}/progress` | 有 | `app.routers.progress.progress` |
| GET | `/api/projects/{project_id}/progress/timeline` | 有 | `app.routers.progress.timeline` |
| GET | `/api/projects/{project_id}/report` | 有 | `app.routers.reports.project_report` |
| GET | `/api/projects/{project_id}/schedule` | 有 | `app.routers.schedules.list_schedule` |
| POST | `/api/projects/{project_id}/schedule/apply-suggestions` | 有 | `app.routers.schedules.apply_suggestions` |
| POST | `/api/projects/{project_id}/schedule/confirm` | 有 | `app.routers.schedules.confirm_schedule` |
| POST | `/api/projects/{project_id}/schedule/generate` | 有 | `app.routers.schedules.generate` |
| GET | `/api/projects/{project_id}/schedule/preview` | 有 | `app.routers.schedules.preview_schedule` |
| POST | `/api/projects/{project_id}/schedule/reschedule` | 有 | `app.routers.schedules.reschedule` |
| GET | `/api/projects/{project_id}/schedule/reschedule-preview` | 有 | `app.routers.schedules.reschedule_preview` |
| POST | `/api/projects/{project_id}/status` | 有 | `app.routers.projects.change_status` |
| POST | `/api/projects/{project_id}/tasks` | 有 | `app.routers.tasks.create_single_task` |
| POST | `/api/projects/{project_id}/tasks/generate` | 有 | `app.routers.tasks.generate_tasks` |
| PUT | `/api/projects/{project_id}/tasks/{task_id}` | 有 | `app.routers.tasks.update_task` |
| POST | `/api/projects/{project_id}/tasks/{task_id}/deliverables` | 有 | `app.routers.tasks.update_task_deliverables` |
| GET | `/api/projects/{project_id}/tasks/{task_id}/reference-docs/{idx}/download` | 有 | `app.routers.tasks.download_task_reference_doc` |
| POST | `/api/projects/{project_id}/team-template` | 有 | `app.routers.projects.apply_team_template` |
| GET | `/api/projects/{project_id}/tree` | 有 | `app.routers.tasks.get_project_tree` |
| GET | `/api/projects/{project_id}/vehicle-issues` | 有 | `app.routers.issues.list_vehicle_issues` |
| GET | `/api/projects/{project_id}/vehicle-units` | 有 | `app.routers.vehicle_lifecycle.list_units` |
| POST | `/api/projects/{project_id}/vehicle-units` | 有 | `app.routers.vehicle_lifecycle.create_unit` |
| GET | `/api/projects/{project_id}/vehicle-units/{unit_id}` | 有 | `app.routers.vehicle_lifecycle.get_unit` |
| PUT | `/api/projects/{project_id}/vehicle-units/{unit_id}` | 有 | `app.routers.vehicle_lifecycle.update_unit` |
| POST | `/api/projects/{project_id}/vehicle-units/{unit_id}/events` | 有 | `app.routers.vehicle_lifecycle.create_event` |
| PUT | `/api/projects/{project_id}/vehicle-units/{unit_id}/events/{event_id}` | 有 | `app.routers.vehicle_lifecycle.update_event` |
| GET | `/api/projects/{project_id}/vehicles` | 有 | `app.routers.projects.list_vehicles` |
| POST | `/api/projects/{project_id}/vehicles` | 有 | `app.routers.projects.add_vehicle` |
| DELETE | `/api/projects/{project_id}/vehicles/{vehicle_id}` | 有 | `app.routers.projects.delete_vehicle` |
| PUT | `/api/projects/{project_id}/vehicles/{vehicle_id}` | 有 | `app.routers.projects.update_vehicle` |
| GET | `/api/schedule/assignment-check` | 有 | `app.routers.schedules.assignment_check` |
| GET | `/api/schedule/calendar` | 有 | `app.routers.schedules.calendar` |
| PUT | `/api/schedule/{entry_id}` | 有 | `app.routers.schedules.update_entry` |
| GET | `/api/system/backups` | 有 | `app.routers.system.list_backups` |
| POST | `/api/system/backups` | 有 | `app.routers.system.create_system_backup` |
| DELETE | `/api/system/backups/{filename}` | 有 | `app.routers.system.delete_backup` |
| GET | `/api/system/backups/{filename}` | 有 | `app.routers.system.download_backup` |
| POST | `/api/system/restore` | 有 | `app.routers.system.stage_restore` |
| GET | `/api/team-templates` | 有 | `app.routers.team_templates.list_templates` |
| POST | `/api/team-templates` | 有 | `app.routers.team_templates.create_template` |
| GET | `/api/team-templates/roles` | 公开/会话入口 | `app.routers.team_templates.plan_roles` |
| DELETE | `/api/team-templates/{template_id}` | 有 | `app.routers.team_templates.delete_template` |
| PUT | `/api/team-templates/{template_id}` | 有 | `app.routers.team_templates.update_template` |
| GET | `/api/templates` | 有 | `app.routers.templates.list_templates` |
| POST | `/api/templates` | 有 | `app.routers.templates.create_template` |
| GET | `/api/templates/export/excel` | 有 | `app.routers.io_routes.export_template_excel` |
| GET | `/api/templates/export/json` | 有 | `app.routers.templates.export_default_template_json` |
| POST | `/api/templates/import/excel` | 有 | `app.routers.io_routes.import_template_excel` |
| GET | `/api/templates/tree` | 有 | `app.routers.templates.get_default_template_tree` |
| DELETE | `/api/templates/{template_id}` | 有 | `app.routers.templates.delete_template` |
| PUT | `/api/templates/{template_id}` | 有 | `app.routers.templates.rename_template` |
| GET | `/api/templates/{template_id}/export/json` | 有 | `app.routers.templates.export_template_json` |
| POST | `/api/templates/{template_id}/import/json` | 有 | `app.routers.templates.import_template_json` |
| GET | `/api/templates/{template_id}/preparations` | 有 | `app.routers.templates.list_template_preparations` |
| POST | `/api/templates/{template_id}/preparations` | 有 | `app.routers.templates.create_template_preparation` |
| DELETE | `/api/templates/{template_id}/preparations/{item_id}` | 有 | `app.routers.templates.delete_template_preparation` |
| PUT | `/api/templates/{template_id}/preparations/{item_id}` | 有 | `app.routers.templates.update_template_preparation` |
| GET | `/api/templates/{template_id}/procurements` | 有 | `app.routers.templates.list_template_procurements` |
| POST | `/api/templates/{template_id}/procurements` | 有 | `app.routers.templates.create_template_procurement` |
| DELETE | `/api/templates/{template_id}/procurements/{item_id}` | 有 | `app.routers.templates.delete_template_procurement` |
| PUT | `/api/templates/{template_id}/procurements/{item_id}` | 有 | `app.routers.templates.update_template_procurement` |
| POST | `/api/templates/{template_id}/publish` | 有 | `app.routers.templates.publish_template` |
| GET | `/api/templates/{template_id}/tasks/{task_id}/reference-docs` | 有 | `app.routers.templates.list_template_task_docs` |
| POST | `/api/templates/{template_id}/tasks/{task_id}/reference-docs` | 有 | `app.routers.templates.upload_template_task_doc` |
| DELETE | `/api/templates/{template_id}/tasks/{task_id}/reference-docs/{doc_id}` | 有 | `app.routers.templates.delete_template_task_doc` |
| GET | `/api/templates/{template_id}/tasks/{task_id}/reference-docs/{doc_id}/download` | 有 | `app.routers.templates.download_template_task_doc` |
| GET | `/api/templates/{template_id}/tree` | 有 | `app.routers.templates.get_template_tree` |
| PUT | `/api/templates/{template_id}/tree` | 有 | `app.routers.templates.replace_template_tree` |
| GET | `/api/users` | 有 | `app.routers.users.list_users` |
| POST | `/api/users` | 有 | `app.routers.users.create_user` |
| GET | `/api/users/all-active` | 有 | `app.routers.users.list_active_users` |
| DELETE | `/api/users/{user_id}` | 有 | `app.routers.users.delete_user` |
| PUT | `/api/users/{user_id}` | 有 | `app.routers.users.update_user` |
| GET | `/api/users/{user_id}/skills` | 有 | `app.routers.availability.get_skills` |
| PUT | `/api/users/{user_id}/skills` | 有 | `app.routers.availability.update_skills` |
| GET | `/api/users/{user_id}/unavailability` | 有 | `app.routers.availability.list_unavailability` |
| POST | `/api/users/{user_id}/unavailability` | 有 | `app.routers.availability.create_unavailability` |
| DELETE | `/api/users/{user_id}/unavailability/{unavail_id}` | 有 | `app.routers.availability.delete_unavailability` |
| PUT | `/api/users/{user_id}/unavailability/{unavail_id}` | 有 | `app.routers.availability.update_unavailability` |
| GET | `/api/vehicle-types` | 有 | `app.routers.vehicle_types.list_enabled_vehicle_types` |
| POST | `/api/vehicle-types` | 有 | `app.routers.vehicle_types.create_vehicle_type` |
| GET | `/api/vehicle-types/all` | 有 | `app.routers.vehicle_types.list_all_vehicle_types` |
| PUT | `/api/vehicle-types/reorder` | 有 | `app.routers.vehicle_types.reorder_vehicle_types` |
| PUT | `/api/vehicle-types/{vehicle_type_id}` | 有 | `app.routers.vehicle_types.update_vehicle_type` |
| GET | `/api/worker/overdue` | 有 | `app.routers.insights.worker_overdue_tasks` |
| GET | `/api/worker/records` | 有 | `app.routers.worker.my_records` |
| POST | `/api/worker/reports` | 有 | `app.routers.worker.submit_report` |
| POST | `/api/worker/reports/adjust` | 有 | `app.routers.worker.adjust_report` |
| DELETE | `/api/worker/reports/{report_id}` | 有 | `app.routers.worker.delete_my_report` |
| POST | `/api/worker/sync` | 有 | `app.routers.worker.batch_sync` |
| POST | `/api/worker/tasks/{task_id}/complete` | 有 | `app.routers.worker.manual_complete_task` |
| POST | `/api/worker/tasks/{task_id}/reopen` | 有 | `app.routers.worker.manual_reopen_task` |
| GET | `/api/worker/today` | 有 | `app.routers.worker.today_tasks` |

## 最终验证记录

- 后端全量 646 项通过；随后对新增数值校验及相关接口补跑 79 项，全部通过；请求指纹规范化后再次运行接口专项 15 项通过。
- 前端全量 220 项通过；最后字段标签/空态调整后，相关页面补跑 3 项通过。
- TypeScript 检查与生产构建通过。
- 浏览器以项目经理身份完成一次创建：1 个车型、执行任务与检查项随项目创建成功，自动进入项目总览。
- 390×844 手机视口检查创建弹窗：车型行分组、车型/型号/台数标签及提交区可见，文档宽度与视口均为 390，无横向溢出。
- 手机截图：[车型录入](evidence-archive.md "原路径：docs/screenshots/review-2026-09-15/create-vehicles-mobile.png；SHA256：ece4845d5212869d85d7b9326df7219a8366f7b841f79ff76dc3f926321d135b")。

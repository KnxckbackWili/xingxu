# 第六轮系统、身份、模板、导入与 AI 工作流复核

> 历史 QA 记录：接口、测试名和结果按当时源码保留，不作为 3.0.0 当前操作说明。原测试现按功能归入 模板/项目往返、备份恢复、账号与 AI 作业等功能模块；旧行为的保留、迁移或退役见[测试整理记录](test-organization-plan.md)。历史通过数量不代表新功能已复验或已部署。

范围：隔离副本、本地 SQLite/API、故障注入和模拟提供商。没有生产访问、真实 AI/通知服务调用、提交或推送。不是仅按接口是否存在验收；每个领域都追踪用户前一步如何影响后一步。

## 已复现并修复

1. **管理员交接失去系统控制权**：唯一管理员能将自己降为普通人员；有接替人后，接替人也能停用自己，最终无人能管理账号。账号修改在稳定账号行上串行，保留至少一个启用管理员；等待锁后重新验证操作者身份。新增两个独立会话同时退出管理员角色的回归。
2. **模板编辑改变身份**：普通树保存重建参考文档 ID，已有下载链接失效、上传人/时间丢失；旧客户端部分保存重建缺省阶段的全部 ID；按 ID 改名仍按旧名称回填，9 阶段变 10 阶段。保留节点和文档身份、保留上传元数据，按真实 ID 区分改名、移动及省略。
3. **模板删除/复制错误恢复**：来源已删除仍创建空模板；删除模板留下准备与采购定义；参考文件先删除、审计失败后数据库回滚却无法恢复文件。不存在来源拒绝创建，删除清理子定义，文件仅在数据库成功提交后清理。
4. **通知集成契约**：钉钉签名已 URL 编码后又被 query 构造二次编码。接收端单次解码后的值与 HMAC 不相等；修复为一次编码。提供商异常响应/异常对象可回显凭据，日志改用安全错误类别。所有验证使用模拟 HTTP，不发通知。
5. **导入预检不是真正保护**：字符串 NaN/Infinity 通过非负检查，布尔值和小数车辆数被接受或截断。统一拒绝非有限数量，车辆数必须确为正整数；预检与提交使用同一验证。
6. **JSON 定义往返丢失**：项目时区、阶段进入/退出条件、模块说明/准备条件、任务车型适用性/依赖、检查描述丢失。保留这些计划定义，依赖按导入任务新 ID 重连，拒绝不存在/循环依赖。显式的逐车数量覆盖不因往返被改成车辆总数。
7. **复制项目丢失施工口径**：现场时区、说明、休息设置、准备条件、车辆配置丢失；非法日期报 500，反向日期被写入。复制保留计划背景，执行状态仍从原有的 draft 初始状态开始，日期写入前验证。
8. **新项目伪带原项目交付审批**：JSON 原样复制 attachment_id/submitted_by/reviewed_by/accepted，形成跨项目证据与原账号身份。按明确的新项目导入边界只复制交付要求，状态改待提交，预检与导入返回可见警告。二进制文件及账号不通过 JSON 导入。
9. **收集箱晚返回破坏归档文件**：AI 调用中用户将文件归档，晚返回把 archived 改回 organized，后续收集箱删除销毁已归档项目附件共用的文件。归档按项目→文档顺序锁定；分类写回重新校验文档当前状态；删除检查实际附件引用并在提交后清理文件；同目标重试返回同一个附件。
10. **收集箱 AI 越权输入与预算旁路**：候选项目使用全库名称，未按上传者可见范围过滤；排队期间身份/角色变化及预算耗尽未检查。现在绑定 job owner、只读其文档和可见项目，执行前校验当前账号/角色/预算并计量；禁用/降级账号的排队任务不会启动提供商。
11. **AI 隐藏写工具边界**：普通聊天/SSE 可调度未展示的 MCP 合并/回退工具；模型自选 project_id 绕过用户所选项目；失败的排程预览残留写入被后续工具提交；调用期间账号停用后仍可写草稿。限定聊天工具白名单与用户选中项目、每步刷新身份，预览成功/失败都回滚。
12. **AI 作业/桥接后续状态**：查询过期作业仍返回结果，晚返回覆写已完成/失败状态；排队权限与预算不重新核对，Codex bridge 未使用共享预算。终态不可被迟到更新覆写，读取执行 TTL；队列执行前重新鉴权/检查预算；桥接与通用聊天共用限额与记账。
13. **真实项目执行计划工具无法读取**：工具读不存在的 Task.completed，且只查模板阶段。改为真实填报聚合与项目实际阶段映射；覆盖有任务/填报的聊天工具及 HTTP Agent 调用。

14. **上传失败留下未归属文件**：收集箱第一份上传成功、后续空文件失败时，数据库回滚但第一份磁盘文件残留；模板参考上传在审计失败时也残留文件。两条上传链记录本次写入的唯一文件，失败回滚并清理，只影响本请求产生的文件。

15. **Excel 与实际进度矛盾**：任务表/甘特着色忽略必需与安全检查，手动完成可显示 100%/绿色；项目概览按任务简单平均，与系统按数量加权的进度不同。统一使用实际进度函数，甘特“今天”使用项目时区；不改变生命周期推进规则。
16. **直接变更集 API 锁后未重新授权**：PM 在请求初次鉴权后被降级、停用，或项目刚软删除，提出/合并/回退/取消仍使用旧权限。四类服务操作统一先锁项目、刷新用户与项目可见性、再检验当前能力；SQLite 也用实际写锁，不能仅依靠其忽略的 SELECT FOR UPDATE。
17. **物理清理的不可变归档缺证据**：旧代码复用新项目 JSON 导出，丢弃验收原记录/准备评审/检查状态及更多结构化证据，校验哈希通过也不代表内容完整。新增独立 `agvpm-project-retention` 格式，明确列入项目成员、车辆/事件、库存/出入库/领料、阶段/模块/任务/检查、日程/报工、问题/突发事件/处置、附件、验收/归档清单、变更集/治理申请、准备事项/评审。保留原始 ID、日期、签字与审阅身份。排除账号凭据、AI Token、私人 AI 会话/记忆。
18. **归档文件所有权与个人日程清理阻塞**：保留附件/参考文件的存储名、来源记录和 SHA-256，文件仍归不可变归档所有，收集箱/模板/普通附件删除与运维孤儿扫描均不能删它。新增归档文件下载，仅既有 admin/director 权限，先校验归档再校验文件，缺失/损坏/非法路径明确拒绝。个人临时日程是仅本人可读，不能扩散到管理归档；存在这类日程时只延后其项目清理、返回无私人内容的 blocked 计数，其余项目继续。本人在软删除后仍可查看、删除或改挂项目，清理后下次可正常 purge。

19. **启动迁移向连接池泄漏关闭的外键约束**：迁移在 Session 连接 A 上关闭 FK，commit 把 A 归还连接池，finally 可能取出 B 并只恢复 B。两个真实连接的独立观察为 `[1,1] → [1,0]`，使后续普通删除缺少级联/完整性保护。迁移现在绑定一个显式 checkout 的连接，成功提交或失败回滚后在同一物理连接恢复 FK=ON 并读回验证，然后才归还连接池。恢复设置自身失败则 invalidate 该连接并让启动失败，不吞掉错误。新增成功、迁移异常、commit 异常、恢复异常四种回归，检查同一物理句柄、事务回滚、两连接 FK 状态及无 checked-out 泄漏。

## 业务契约仍需决定，未擅自改变

- 新的不可变归档是业务审计留存，JSON 中不嵌入文件二进制，不能替代系统完整备份。文件当前由服务端保留并可校验下载，存储损坏仍需系统完整备份恢复。旧归档已遗漏/删除的历史不会被新版本凭空补回。
- JSON 界面承诺“结构化快照创建新项目”且排除文件、账号，但后端旧测试明确允许恢复 completed/archived。它不携带验收/准备评审/审计历史、检查状态、已下达身份与报工-日程关联；因此不能称为完整恢复。建议将“新项目导入”回到可检查的初始态，或另设真正完整恢复模式。当前保留终态兼容行为，已列入待业务确认项。
- 通知已发送到个人收件箱后，撤销项目成员是否也删除历史通知/AI 聊天中的历史内容，是信息保留策略；没有擅自删用户历史。
- 通知同时配置多个渠道时，现行语义为任一成功即送达，而不是全部渠道成功。单 scheduler 部署下已测重试/退避，未宣称多 scheduler 跨进程恰好一次外发。
- 禁用账号的安全需求与进行中项目负责人/执行人交接的冲突未擅自改成禁止停用；项目人员移除本身已有交接检查。
- 模板整树编辑缺少全域强制版本：本轮修复稳定身份，不声称排除了两个长期开着的编辑页覆盖彼此的修改。
- org 创建/更新/删除、feedback 创建/处理状态的既有代码没有 ChangeLog，与仓库“全部写操作审计”约定有差距；没有批量扩展系统事件审计策略。
- 模板 draft/published 目前主要是版本标签；项目向导仍可选择草稿。是否强制仅发布版可用于新项目，属于需要统一的产品契约。
- 同名收集箱文件的 AI 结果仍按文件名匹配；目前为私人空间内分类歧义，需产品选择明确的文件 ID 契约或逐文件分类。

## 验证记录

- 第一批原代码：6 项失败；修复后与原模板/账号回归共 14 passed
- 第二批原代码：10 项新增失败；修复后与通知、Excel、JSON 全流程共 85 passed
- 第三批定位：时区/定义、company 准备责任方、克隆日期/计划背景缺失；回归中纠正了一项新增测试误把原有 draft 初态写成 planning 的预期，没有改变业务初态
- 第四批原代码：交付外部身份、收集箱删除故障、归档晚返回、不可见项目名 4 项失败
- AI 分项新增 24 条；修复前复现 19 个失败检查，关联 AI/Agent 回归 91 passed；后续真实项目工具测试另加
- 本范围广回归：220 passed（账号/模板/通知/JSON/备份/组织/团队/收集箱/反馈/字典），186.27 秒
- 最新系统+AI+收集箱+参考资料+Round5 系统回归：92 passed，75.97 秒
- 新增真实任务读取+显式数量/依赖校验：4 passed；真实任务工具修复后第一次新测试用了错误 HTTP 工具名称 get_execution_plan，已按目录修正为 tasks_tree，没有改变 API 命名
- 新发现兼容性回归已纠正：既有字符串交付要求（如 ["验收报告"]）仍可 JSON 往返，导入规范化为待提交要求对象；外部证据/审核身份仍清除
- 最终整合相关回归见下方最终记录；隔离环境脚本为仓库外 test-env/run-pytest.sh
- 未运行真实 PostgreSQL 并发、真实云提供商、Docker/NAS 断电恢复；API 回归不等同于浏览器视觉验收

## 领域覆盖与断言

| 领域 | 已追踪的业务链 | 当前证据 |
|---|---|---|
| auth/users | 登录、刷新、改密、重置、停用/再启用、角色变更、管理员交接、过期会话 | 既有 auth/cookie/system-round5 + 新并发退休回归 |
| org/team | 大组→小组→负责人换组→成员移动/删除；团队定岗角色合法性 | org/team_templates 既有回归与代码追踪；同层重名/大组归属拒绝 |
| templates | 创建/复制→参考上传→编辑/部分保存→发布→生成项目→删除来源 | 新稳定身份、失败回滚、旧引用下载；既有项目快照/Excel一致性 |
| io | Excel 双向、JSON 预检→导入、项目 JSON/Excel/ZIP、新项目复制 | 新定义/数字/依赖/证据契约；既有打包与附件缺失清单 |
| system | 完整备份→下载→非法包拒绝→有效包待恢复→替换失败回滚 | Round5 故障/路径/完整性/并发 staging + backup/governance 回归 |
| notification settings | 保存/掩码→测试→启停→排队→失败/重试 | 新 HMAC 接收端验证、错误不泄密；既有 env 优先、SSRF、outbox |
| AI/Agent | 绑定 token→scope撤销→工具执行；用户选项目→多轮/流式→失败/撤权；排队/过期 | 模拟提供商/API/MCP；当前授权和终态断言 |
| inbox | 多文件上传→私人读取→AI→归档→删除/重试/迟到回调 | 新状态/身份/引用生命周期 + 既有私密隔离 |
| feedback/logs | 普通用户提交→管理角色处理→按项目读审计 | 既有 feedback 角色矩阵；logs 当前可见性源码追踪 |
| vehicle_types | 管理字典→使用→重命名/停用/排序 | 既有 vehicle_types、引用保护和原子拒绝回归 |

## 最终交叉验证补充

- 直接 REST 变更集新增 12 项撤权/停用/软删除交错全部通过；同批 Excel 安全门禁回归通过（13 passed）
- 清理→不可变归档→授权下载→共享收集箱删除→文件篡改拒绝→归档篡改拒绝，及私人日程只阻塞本项目/本人解除阻塞：2 passed
- 既有 change_sets/archive/governance 共 31 passed；旧 purge/哈希/管理范围回归 1 passed（这些发生在最后交叉修复前，最终批再次完整跑相关文件）
- 早期整合系统/AI/IO 回归 105 passed；后续档案关系/非法路径/旧归档文件边界 5 passed。最终 owned 批次 317 passed、0 failed，288.51 秒；其加载于 11:40 冻结版本，11:42 唯一关系兼容修复另跑 5 passed，个人日程解除阻塞另跑 1 passed
- 11:42:25.84 UTC 冻结后独立组合复测发现启动迁移连接池 FK 缺陷，旧冻结点已撤销。修复后当前源码/测试冻结为 2026-10-01 11:51:14.54 UTC；新冻结后重新运行全库测试。本文不是全库测试结果替代品
- 归档和变更集另由独立覆盖复核交叉审查；前端没有把所有保留 API 作为人机工作流入口，见总覆盖表，不把 API 可用等同于导航可达

## 本范围完整 HTTP 操作清单

以下清单来自 AST 枚举，共 20 个路由文件、116 个 HTTP 操作，目的为防止接口遗落；不将枚举本身当作执行验证。

### auth.py（5 个操作）
- `POST /api/auth/login` → `login`
- `POST /api/auth/refresh` → `refresh_token`
- `POST /api/auth/logout` → `logout`
- `GET /api/auth/me` → `me`
- `PUT /api/auth/password` → `change_password`

### users.py（5 个操作）
- `GET /api/users` → `list_users`
- `POST /api/users` → `create_user`
- `PUT /api/users/{user_id}` → `update_user`
- `DELETE /api/users/{user_id}` → `delete_user`
- `GET /api/users/all-active` → `list_active_users`

### org.py（5 个操作）
- `GET /api/org/groups` → `list_groups`
- `POST /api/org/groups` → `create_group`
- `PUT /api/org/groups/{group_id}` → `update_group`
- `DELETE /api/org/groups/{group_id}` → `delete_group`
- `GET /api/org/roles` → `list_roles`

### team_templates.py（5 个操作）
- `GET /api/team-templates` → `list_templates`
- `POST /api/team-templates` → `create_template`
- `PUT /api/team-templates/{template_id}` → `update_template`
- `DELETE /api/team-templates/{template_id}` → `delete_template`
- `GET /api/team-templates/roles` → `plan_roles`

### templates.py（23 个操作）
- `GET /api/templates` → `list_templates`
- `POST /api/templates` → `create_template`
- `PUT /api/templates/{template_id}` → `rename_template`
- `POST /api/templates/{template_id}/publish` → `publish_template`
- `DELETE /api/templates/{template_id}` → `delete_template`
- `GET /api/templates/tree` → `get_default_template_tree`
- `GET /api/templates/export/json` → `export_default_template_json`
- `GET /api/templates/{template_id}/tree` → `get_template_tree`
- `PUT /api/templates/{template_id}/tree` → `replace_template_tree`
- `GET /api/templates/{template_id}/export/json` → `export_template_json`
- `POST /api/templates/{template_id}/import/json` → `import_template_json`
- `GET /api/templates/{template_id}/procurements` → `list_template_procurements`
- `POST /api/templates/{template_id}/procurements` → `create_template_procurement`
- `PUT /api/templates/{template_id}/procurements/{item_id}` → `update_template_procurement`
- `DELETE /api/templates/{template_id}/procurements/{item_id}` → `delete_template_procurement`
- `GET /api/templates/{template_id}/tasks/{task_id}/reference-docs` → `list_template_task_docs`
- `POST /api/templates/{template_id}/tasks/{task_id}/reference-docs` → `upload_template_task_doc`
- `DELETE /api/templates/{template_id}/tasks/{task_id}/reference-docs/{doc_id}` → `delete_template_task_doc`
- `GET /api/templates/{template_id}/tasks/{task_id}/reference-docs/{doc_id}/download` → `download_template_task_doc`
- `GET /api/templates/{template_id}/preparations` → `list_template_preparations`
- `POST /api/templates/{template_id}/preparations` → `create_template_preparation`
- `PUT /api/templates/{template_id}/preparations/{item_id}` → `update_template_preparation`
- `DELETE /api/templates/{template_id}/preparations/{item_id}` → `delete_template_preparation`

### io_routes.py（9 个操作）
- `GET /api/projects/import/template` → `download_quick_import_template`
- `POST /api/projects/import/preview` → `preview_quick_import`
- `GET /api/templates/export/excel` → `export_template_excel`
- `POST /api/templates/import/excel` → `import_template_excel`
- `GET /api/projects/{project_id}/export/excel` → `export_project_excel`
- `GET /api/projects/{project_id}/export/json` → `export_project_json`
- `GET /api/projects/{project_id}/export/package` → `export_project_package`
- `POST /api/projects/import/json` → `import_project_json`
- `POST /api/projects/{project_id}/clone` → `clone_project`

### system.py（5 个操作）
- `GET /api/system/backups` → `list_backups`
- `POST /api/system/backups` → `create_system_backup`
- `GET /api/system/backups/{filename}` → `download_backup`
- `DELETE /api/system/backups/{filename}` → `delete_backup`
- `POST /api/system/restore` → `stage_restore`

### vehicle_types.py（5 个操作）
- `GET /api/vehicle-types` → `list_enabled_vehicle_types`
- `GET /api/vehicle-types/all` → `list_all_vehicle_types`
- `POST /api/vehicle-types` → `create_vehicle_type`
- `PUT /api/vehicle-types/reorder` → `reorder_vehicle_types`
- `PUT /api/vehicle-types/{vehicle_type_id}` → `update_vehicle_type`

### notifications.py（5 个操作）
- `GET /api/notifications` → `list_notifications`
- `GET /api/notifications/unread-count` → `unread_count`
- `POST /api/notifications/{notification_id}/read` → `mark_read`
- `POST /api/notifications/read-all` → `mark_all_read`
- `POST /api/notifications/read-batch` → `mark_batch_read`

### notification_channels.py（4 个操作）
- `GET /api/notification-channels` → `get_channels`
- `PUT /api/notification-channels/dingtalk` → `put_dingtalk`
- `DELETE /api/notification-channels/dingtalk` → `disable_dingtalk`
- `POST /api/notification-channels/dingtalk/test` → `test_dingtalk`

### agent.py（2 个操作）
- `GET /api/agent/tools` → `list_agent_tools`
- `POST /api/agent/tools/{name}` → `call_agent_tool`

### ai_internal.py（4 个操作）
- `GET /api/ai/internal/tokens` → `list_tokens`
- `POST /api/ai/internal/tokens` → `create_token`
- `PUT /api/ai/internal/tokens/{token_id}` → `update_token`
- `DELETE /api/ai/internal/tokens/{token_id}` → `revoke_token`

### ai_memory.py（3 个操作）
- `GET /api/ai/memory` → `list_memories`
- `POST /api/ai/memory` → `create_memory`
- `DELETE /api/ai/memory/{memory_id}` → `delete_memory`

### ai_projects.py（13 个操作）
- `GET /api/ai-projects/status` → `get_status`
- `GET /api/ai-projects/capabilities` → `get_capabilities`
- `POST /api/ai-projects/chat` → `chat`
- `POST /api/ai-projects/chat/stream` → `chat_stream`
- `GET /api/ai-projects/chat/sessions` → `get_chat_session_list`
- `GET /api/ai-projects/chat/sessions/{session_id}` → `get_chat_session`
- `DELETE /api/ai-projects/chat/sessions/{session_id}` → `remove_chat_session`
- `POST /api/ai-projects/extract` → `extract_documents`
- `POST /api/ai-projects/organize` → `organize`
- `POST /api/ai-projects/organize/jobs` → `create_organize_job`
- `GET /api/ai-projects/organize/jobs/{job_id}` → `get_organize_job`
- `POST /api/ai-projects/test-connection` → `check_connection`
- `GET /api/ai-projects/skill-bundle` → `download_skill`

### codex.py（1 个操作）
- `POST /api/ai/codex/chat` → `codex_chat`

### inbox.py（7 个操作）
- `POST /api/inbox/documents` → `upload_documents`
- `GET /api/inbox/documents` → `list_documents`
- `GET /api/inbox/documents/{doc_id}/download` → `download_document`
- `DELETE /api/inbox/documents/{doc_id}` → `delete_document`
- `POST /api/inbox/documents/{doc_id}/archive` → `archive_document`
- `POST /api/inbox/documents/organize/jobs` → `create_organize_job`
- `GET /api/inbox/documents/organize/jobs/{job_id}` → `get_organize_job`

### feedback.py（4 个操作）
- `POST /api/feedback` → `create_feedback`
- `GET /api/feedback` → `list_feedback`
- `GET /api/feedback/{feedback_id}` → `get_feedback`
- `PATCH /api/feedback/{feedback_id}/status` → `update_feedback_status`

### logs.py（1 个操作）
- `GET /api/projects/{project_id}/logs` → `list_logs`

### change_sets.py（6 个操作）
- `POST /api/projects/{project_id}/change-sets/propose` → `propose`
- `GET /api/projects/{project_id}/change-sets` → `list_change_sets`
- `GET /api/projects/{project_id}/change-sets/{change_set_id}` → `detail`
- `POST /api/projects/{project_id}/change-sets/{change_set_id}/merge` → `merge`
- `POST /api/projects/{project_id}/change-sets/{change_set_id}/rollback` → `rollback`
- `POST /api/projects/{project_id}/change-sets/{change_set_id}/cancel` → `cancel`

### archives.py（4 个操作）
- `GET /api/archives/projects` → `list_project_archives`
- `GET /api/archives/projects/{project_id}` → `get_project_archive`
- `GET /api/archives/projects/{project_id}/verify` → `verify_project_archive`
- `GET /api/archives/projects/{project_id}/files/{stored_name}` → `download_retained_file`

## 最终状态

- 系统/AI 与文件交叉回归：317 passed（日志 `round6-system-final-owned.log`）
- 最后关系兼容、文件路径与旧归档边界：5 passed（`round6-system-legacy-final.log`）；私人日程解除阻塞：1 passed（`round6-system-private-final.log`）
- 新增本报告回归文件 `backend/tests/test_system_workflow_round6.py`，新增 AI 专项 `backend/tests/test_ai_system_round6.py`
- 最终源码编译检查与 `git diff --check` 通过
- 连接池 FK 修复前 3 failed（`round6-system-pool-fk-before.log`）；修复后四种故障/成功路径 4 passed（`round6-system-pool-fk-focused.log`），与保留证据组合 6 passed（`round6-system-pool-fk-after.log`）
- 新冻结后的系统/启动/迁移/模板/日程/报告/车型 8 文件整合回归：138 passed、0 failed，127.51 秒（`round6-system-pool-fk-regression.log`）
- 独立复核最终 9 项组合 probe 全部通过，9.65 秒：真实 OFF/ON 句柄相同、两个连接 FK 均为 1，物理级联删除与原验收证据留存并存、撤权变更集拒绝、私人日程仅阻塞其项目
- 全库最终测试在 11:51:14.54 UTC 新冻结之后运行；不把多个重叠分项测试数量相加冒充独立覆盖
- 没有生产写入、实际删除生产项目/文件、真实外部模型/通知调用、提交或推送

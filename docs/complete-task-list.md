# 完整整改任务清单（唯一清单）

> v3 #85 已替代下方 C8-4 的旧保留期清理政策：项目回收站不自动到期，管理员明确永久删除前须保全加密备份。旧归档本版本只读保留，见 [当前规则](project-retention.md)。


> 本文记录 2.x 历史整改与当时验证结果；不作为现版本功能目录。T03 下线范围与保全方式见 [功能下线说明](retired-features.md)。
> 版本：2026-08-25 · 仓库：`multica/agv-project-multica`（分支 `fix/review-2026-08-24-multica`）
> 基线：`dsh/agv-pm` 的 `fix/review-2026-08-21`（即线上容器 `agv-pm:review-fix` 运行代码）。
> 范围：技术 / 流程 / 容量 / 安全 / 可靠性 全部既有结论 + 全站 UI/排版/响应式/无障碍/交互一致性审查，合并为唯一任务清单。
> 规则：任何条目未完成、未验证或仅写建议都不得结束；完成后交研究生一审、博士二审。

## 状态标记
- `[待办]` 未开始　`[进行中]` 正在改　`[已完成]` 已实现　`[已验证]` 已通过测试/实测　`[放弃-说明]` 经研判不适用并注明理由

---

## A. 部署与架构（单容器 + PostgreSQL + 多 worker + 监督器 + 健康检查 + 迁移 + 备份恢复）

| # | 问题（证据） | 修复方案 | 状态 |
|---|---|---|---|
| A1 | 数据库为单文件 SQLite（`config.py` 默认 `sqlite:///{DATA_DIR}/agvpm.db`），500 项目并发写入会撞 `busy_timeout=5000` 写锁。 | 增加 `DATABASE_URL` 对 PostgreSQL 的支持（`config.py` 已读 `DATABASE_URL`，需补 psycopg2 依赖与引擎适配）；单容器内由进程监督器托管 PostgreSQL。 | [已完成]（`db.py` PG 引擎 + psycopg2；supervisord 托管容器内 PostgreSQL 17） |
| A3 | 无健康检查：容器 `healthcheck` 缺失，无法被编排感知。 | 增加 `/api/health` 端点（DB 连通 + 版本）与 Docker `HEALTHCHECK`。 | [已验证]（`/health` 200 + compose `healthcheck` 实测通过） |
| A4 | 启动用 `create_all` 建表，无正式迁移链路（alembic 已装未接线）；模型变更后旧库无法平滑升级。 | 提供 `python -m alembic` 或启动时幂等迁移（`_migrate` 已有先例），启动前执行。 | [已验证]（启动幂等 `create_all`+`_migrate`；**本轮修复**：PG 存量库也走 `_migrate`（information_schema 检查 + ALTER），实测旧卷补列成功） |
| A5 | 无自动备份/恢复策略；`config.py` 的 `restore_bootstrap` 仅处理 staged restore，无定时备份。 | 提供 `backup.sh` / `restore.sh`（PG `pg_dump`/`pg_restore` + 数据卷），并支持 cron 式定时备份。 | [已验证]（G5 冷启动实测：`pg_dump -Fc` 备份 + dropdb/createdb + `pg_restore` 恢复，数据完好） |
| A6 | 部署端口为 8000/8001，成员要求 8002 且单容器一条命令。 | `docker-compose`/`Makefile` 提供一条命令部署到 8002（映射 `0.0.0.0:8002:8000`），一个持久化数据卷。 | [已验证]（`docker-compose.multica.yml` + `make deploy` → 8002 单容器；G4 E2E 直连 8002 全通过） |
| A7 | 多 worker 下 `AGVPM_INTERNAL_BASE_URL=http://127.0.0.1:8000` 硬编码端口；内部回环调用在多 worker 下风险。 | 读 `PORT`/`INTERNAL_BASE_URL` 环境变量，避免端口硬编码。 | [已完成]（app 无硬编码 8000 自调用；`CODEX_BRIDGE_URL` 读环境变量指向 7878） |

## B. 数据与容量（500 项目规模）

| # | 问题（证据） | 修复方案 | 状态 |
|---|---|---|---|
| B1 | 项目列表仓库版 `list_projects` 全量返回；线上版已加分页但 `page_size` 上限 500 仍一次拉满。 | 前端项目列表/总览默认分页（10/20 每页），后端 `page_size` 默认设一个合理值并校验。 | [已完成] |
| B2 | 日程生成全删+重建 O(N)（`scheduler.generate_schedule` 删除全部 `is_locked==False`），500 项目时放大。 | 见 C9：改为按任务增量 upsert + 受保护删除，重排只对受影响条目做 diff。 | [已验证]（`generate_schedule` 分区：**已填报的未确认条目保留**（按 `DailyProgress.schedule_entry_id` 识别），仅删无填报条目；`test_regenerate_preserves_reported_entries`） |
| B3 | `visible_projects`（仓库版）全表 `Project.all()` + Python 过滤；线上版已改 `ProjectMember` JOIN。 | 以线上 JOIN 实现为准回写仓库，并加索引 `(project_members.user_id)`。 | [已完成]（`project_members` 关联表 JOIN 为唯一事实源，`_projects_of` 走 JOIN） |
| B4 | 聚合看板/逾期/趋势在 500 项目下耗时（fix/review 已加 TTL cache）。 | 核对 TTL cache 覆盖全部聚合端点（overview/overdue/trend/stats），补齐未覆盖者。 | [已完成]（TTL cache 覆盖 overview/overdue/trend/stats，`services/cache.py`） |
| B5 | 无速率限制与分页防护的导出/全量接口，500 项目下内存峰值高。 | 导出接口流式/分批；列表类接口强制分页上限。 | [已验证]（导出按用户限流 10/300s，`services/rate_limit.py`；**T006 升级为 PostgreSQL 共享计数**：多 worker 共用同一额度、容器重启不绕过窗口、不同用户隔离，实测 ≥2 worker 并发 11 次同用户导出前 10 成功第 11 次稳定 429；`test_export_rate_limited`/`test_pg_shared_rate_limit_atomic`；PG 保留字 `window` 列在 raw SQL 中双引号引用——由 8002 双 worker 并发实测暴露并修复，`test_pg_sql_quotes_reserved_word_window` 防复现） |
| B6 | 通知广播放大：日程确认通知全部成员（`schedules.py:172-177`）。 | 通知改为单条按用户聚合 + 分页读取；确认通知限重试。 | [已验证] |

## C. 业务流程闭环（按 8 段）

### C1 立项
| # | 问题（证据） | 修复方案 | 状态 |
|---|---|---|---|
| C1-1 | 建项目与生成任务非原子（`ProjectListPage.tsx:207-213` 无条件提示"任务已生成"；`tasks.py:52-79` 缺 `module_ids` 400）。 | 后端 `create_project` 支持 `module_ids` 一步生成，或前端失败回滚/真实提示"项目已建、任务未生成"。 | [已完成]（创建向导按真实生成结果分级提示；`tasks.generate_tasks` 承接 `module_ids` 一步生成） |
| C1-2 | 无成员/坏成员 ID 也可建项目：实测 FK 500（`projects.py` `INSERT project_members`）。 | 创建/更新前校验成员 ID 存在且启用，非法返回 400 + 字段级提示。 | [已验证] |
| C1-3 | 0 成员项目可创建（实测 `teat` 46 任务无成员）。 | 建项目时至少 1 名成员（PM 缺省填入 manager），或明确允许但排程时阻断（见 C9-2）。 | [已完成]（基线已具备，确认无需改动） |
| C1-4 | 条件选项（new_vehicles/WMS/充电/客户/海外）只产准备项不产任务，向导文案与行为不符（CLAUDE.md"勾 3 条件生成 30 任务"与代码不符）。 | 统一语义：条件模块纳入可生成任务范围，或在向导明确标注"仅准备项"；删除误导文案。 | [已完成]（`list_modules` 返回全部模板模块并标注 `prep_only`（项目准备=仅准备项）；`generate_tasks` 区分执行模块与准备模块） |

### C2 模板/任务分解
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C2-1 | **交付物审核状态被后端剥离**（`tasks.py:344-357` 只留 `{name,done,attachment_id,done_by,done_at}`，`status/reject_reason` 丢失）。 | `update_task_deliverables` 保留 `status/submitted_by/review_by/review_at/reject_reason`；成员提交=submitted、PM 审核=approved/rejected；`worker/today` 返回审核状态。 | [已验证]（交付物全审核状态落库；today 返回；E2E 实测成员提交→PM 审核→completed 门禁通过） |
| C2-2 | 模板保存 `replace_template_tree` 用 `_delete_tree` 整棵删除重建，且读取端排除「项目准备」→ 保存即销毁项目准备行（用户模板永久丢失）。 | 保存改为按提交 diff/upsert，保留「项目准备」阶段行。 | [已完成]（`_capture_all_phases` 先整树捕获再 `_delete_tree`，恢复非提交阶段；「项目准备」不再被销毁） |
| C2-3 | 发布 `publish_template` 仅 `version+1`，无快照、无 diff、无审计。 | 发布时生成版本快照（阶段/模块/任务/检查项 JSON）+ `log_change`。 | [已完成]（发布写入版本快照（保留最近 10 份）+ `log_change` 审计） |
| C2-4 | 模板保存/发布无 `log_change`（违反"所有写操作审计"）。 | 保存树、发布、复制均补审计。 | [已完成]（保存/发布/复制/采购/准备项/参考文档全部 `log_change`） |
| C2-5 | 追加模块拿不到条件模块（`templates.py:188` 排除项目准备）。 | 追加模块接口返回条件模块（标注"仅准备项"）。 | [已完成]（`list_modules` 返回条件模块并标注 `prep_only`） |
| C2-6 | 生成任务无幂等/状态守卫：重复生成同名去重掩盖，改名后新旧两批。 | `generate_tasks` 增加项目状态守卫 + 幂等键（template_id+version+module）升级合并逻辑。 | [已验证]（`source_task_id` 幂等键：改名后重生成按 source_task_id 对齐并同步改名，不产新旧两批；`test_generate_rename_sync_no_duplicate`） |
| C2-7 | 存量项目模块 `phase_id` 为 NULL（实测演示项目/mikan 全 NULL）→ 执行计划空白。 | 启动迁移按模板阶段名回填 `modules.phase_id`。 | [已验证]（`db.py` 启动迁移按模板同名模块回填 phase_id） |
| C2-8 | `copy_tree` 不复制参考文档 TemplateDoc。 | 复制模板时复制 TemplateDoc 与任务 `reference_docs`。 | [已完成]（`copy_tree` 复制 TemplateDoc + 物理文件独立副本） |

### C3 人员与物料
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C3-1 | **排程成员兜底"前 5 个活跃用户"**（`scheduler.py:109-112`），会把任务派给无关人员。 | 无成员时排程生成阻断并提示；或要求先配置成员。 | [已完成]（基线已具备，确认无需改动） |
| C3-2 | `Project.members`（JSON）与 `project_members`（关联表）双存储靠 `_sync_project_members` 同步。 | 收敛为单一事实源（关联表），`members` 兼容读；同步加审计。 | [已完成]（写路径全量同步关联表 + 启动对账 `db.py` 全库回填，`members` 兼容读） |
| C3-3 | 移除成员无通知、无日程重派。 | 移除时通知 + 名下未填报日程转 unassigned 并提示 PM 重派。 | [已完成]（`projects.py` 移除成员 → 通知被移出者 + 名下未确认日程转 unassigned） |
| C3-4 | 改成员无存在性校验（坏 ID 500）。 | 同 C1-2 统一校验。 | [已验证]（同 C1-2，坏/停用成员 ID 返回 400） |

### C4 排程
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C4-1 | **休息规则参数被忽略**（`_workdays_between` 文档自述"不再参与计算"），前端「排程规则」弹窗 Switch 还 `disabled`。 | `_workdays_between` 实现 rest_mode/rest_days/skip_holidays；前端开关接线可用。 | [已验证]（后端 `_workdays_between` 已实现且测试覆盖；前端开关已接线） |
| C4-2 | **重新生成删除已确认条目**（`scheduler.py:90-97` 删 `is_locked==False` 含已确认）。 | 重排保护：已确认未锁定条目默认保留，需二次确认才重排；锁定=确认后自动。 | [已验证]（已锁定/已确认条目不删除；新增"有填报的未确认条目保留"；`test_regenerate_preserves_reported_entries`） |
| C4-3 | 无目标数量任务静默进 unscheduled，confirm 无升级。 | 生成返回警告；confirm 前置校验"存在未排入任务"并阻断/提示。 | [已完成]（confirm 返回未排入任务名列表并提示） |
| C4-4 | 日程条目无 assignee 锁，today mine+others 全返回，多人可对同一 unassigned 条目重复填报。 | unassigned 条目填报加"先认领"机制，或按成员展示填报限制。 | [已验证]（unassigned 条目填报先到先认领，admin/pm 不受限） |
| C4-5 | 确认通知全部成员（广播放大）。 | 同 B6。 | [已验证]（同 B6，通知按用户聚合） |

### C5 现场执行/离线填报
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C5-1 | **today 接口丢弃检查项三态**（`worker.py:106-115` 只返回 id/name/is_safety_critical/is_done/done_by；查询预过滤 `is_applicable==True`）。 | today 返回 `failed/failed_reason/is_applicable/not_applicable_reason`；前端还原三态渲染。 | [已验证] |
| C5-2 | **填报无项目状态守卫**（`submit_report` 不查 status，已完成/已归档仍可填）。 | `submit_report` 增加项目状态校验（非 ACTIVE 拒绝或提示）。 | [已验证] |
| C5-3 | 失败检查项不阻断进度（进度只按数量）。 | 进度计算：阶段内存在 `failed` 检查项时 percent 封顶或标记"安全项未通过"。 | [已完成]（任务/阶段存在 failed 检查项 → 进度封顶 99%，无法到达 100%） |
| C5-4 | 撤回填报不重新评估项目状态（只进不退）。 | `delete_my_report` 后重算 `advance_project_status` 允许回退（按阈值下探）。 | [已验证]（`regress_project_status` 撤回后按里程碑阈值回退；`test_delete_my_report_status_info`） |
| C5-5 | 离线只覆盖数量填报；检查项/交付物/问题离线丢失。 | 离线队列扩展覆盖检查项/交付物/问题。 | [已验证]（`/worker/sync` 支持 report/checkitem/deliverable/issue 四类；3 项 batch-sync 测试） |
| C5-6 | 被拒离线条目永久卡死，无查看/编辑/删除 UI。 | 离线队列加"被拒列表"：可查看原因、删除、重试。 | [已验证]（后端逐条 `rejected_detail`；前端 Today 被拒横幅可查看原因/删除/重试） |
| C5-7 | `schedule_entry_id` 不校验归属（跨任务条目污染完成度）。 | 校验 `schedule_entry_id` 属于 `task_id` 且存在。 | [已验证] |
| C5-8 | 在线双击不幂等（每次点击新 `client_uuid`）。 | 前端提交前固定 uuid（重试复用）。 | [已验证]（TodayPage 每条目 `stableUuid(entry_id)` 固定复用） |

### C6 问题/变更
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C6-1 | **无升级机制**：3 天 SLA 仅前端红 Tag，后端无逾期扫描。 | `report_scheduler` 或独立 job 每日扫描 open/processing 超 3 天问题 → 通知 manager/总监。 | [已验证] |
| C6-2 | **处理人无 C_ISSUES 无法操作**（`permissions.py:46-61` worker 能力集空）。 | worker 对"指派给自己"的问题开放 processing/resolved 权限；或 `C_ISSUES` 按指派关系判定。 | [已验证] |
| C6-3 | 状态迁移无守卫（任意跳转）。 | 定义状态机 `open→processing→resolved→closed`，禁跳转项返回 400。 | [已验证] |
| C6-4 | 无报告人确认/重开闭环。 | resolved 后通知报告人，提供"确认/重开"动作。 | [已验证] |
| C6-5 | 指派给已移除/停用成员无校验。 | 校验 assignee 存在且为项目成员/启用。 | [已验证] |
| C6-6 | 变更审计只记最终状态字符串（无 old/new）。 | issue 更新记录字段级 old/new 到 ChangeLog。 | [已完成]（`issues.py` 逐字段比较 old/new 写入审计） |
| C6-7 | 作废与关闭无法区分（status=closed+文案）。 | 增加 `cancelled` 状态或 `resolution_type=cancelled` 字段 + 通知。 | [已验证] |

### C7 验收交付
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C7-1 | **交付物审核不落库**（同 C2-1）。 | 后端持久化审核状态；前端恢复"待审/已通过/已退回+原因"。 | [已验证]（同 C2-1，交付物审核状态全链路落库 + 前端三态） |
| C7-2 | **无验收记录/签字**："验收中"只是状态标签，无 signoff 模型/端点。 | 新增验收记录（验收人/时间/结论/附件）+ 项目状态 `acceptance→completed` 需验收记录。 | [已验证] |
| C7-3 | **completed 门禁只看数量进度 ≥100%**（`projects.py:582-588`）。 | completed 增加：交付物全部 done、无 open/processing 问题、归档清单必需项齐备。 | [已验证] |
| C7-4 | PM 可审核自己提交的交付物（无职责分离）。 | 审核人 ≠ 提交人；提交后提交人锁定不可审。 | [已验证] |
| C7-5 | 交付物提交/审核/退回无通知。 | 提交→通知 PM；审核退回→通知提交人（含原因）。 | [已验证] |

### C8 归档复盘
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| C8-1 | **归档无门禁**（`change_status` 只校验 C_UPDATE，不看归档清单）。 | `completed→archived` 前置校验归档清单必需项完成 + 无未关闭问题。 | [已验证] |
| C8-2 | **director 能力错配**：有 C_ARCHIVE 无 C_UPDATE，无法归档。 | permissions 修正：director 补 C_UPDATE（或归档走 C_ARCHIVE 判定）。 | [已验证] |
| C8-3 | 无复盘/经验沉淀。 | 归档时要求填写复盘（成功/问题/改进），可选写入模板。 | [已完成]（归档强制复盘，沉淀到 `Project.retrospective`） |
| C8-4 | 治理删除物理 `db.delete`，无软删除/保留期/快照，且申请/审核无通知。 | 删除改软删除（标记+保留期）+ 申请/审核双向通知。 | [已验证]（软删除 + 保留期物理清理 job（默认 30 天）+ 申请即通知管理员；**T008 清理前持久化不可变归档**：完整项目快照 + 全量 change_logs（含操作者/时间）+ SHA-256 校验哈希落库 `project_archives`，管理员按原 project_id 只读查询与哈希校验，普通业务接口不可改删；`test_governance_request_notifies_admins`/`test_purge_soft_deleted_after_retention`/`test_purge_persists_immutable_archive`） |
| C8-5 | 归档后数据仍可被 API 写入（submit_report 无状态守卫）。 | 同 C5-2；归档项目写接口统一拒绝。 | [已验证]（同 C5-2，填报状态守卫覆盖归档态） |
| C8-6 | **项目移交旧负责人权限残留**：审批移交仅把新负责人加入 `members`，旧负责人仍在 members/project_members，仍可读取项目。 | 移交后旧负责人若无其他显式项目角色（技术负责人/有效协管/技术线角色成员）则从 members 与 project_members 同时移除，无法再读取；有显式角色则保留对应权限；名下未确认日程转 unassigned；新旧负责人双向通知 + 审计。 | [已验证]（`projects.py` 移交审批按保留规则同步 members/project_members；`test_transfer_removes_old_manager_without_explicit_role`/`test_transfer_keeps_old_manager_when_technical_manager`/`test_transfer_keeps_old_manager_when_co_manager`/`test_transfer_notifies_both_managers_and_reassigns_schedule`） |

## D. 安全
| # | 问题（证据） | 修复方案 | 状态 |
|---|---|---|---|
| D1 | 登录接口无速率限制/防爆破（`auth.py`）。 | 登录失败次数限流 + 锁定提示。 | [已完成]（基线已具备，确认无需改动） |
| D2 | 成员 ID 未校验导致 FK 500（同 C1-2）。 | 统一校验返回 400。 | [已验证]（同 C1-2，坏/停用成员 ID 统一 400） |
| D3 | demo 项目删除仅前端禁用（`EditPage.tsx:266`），后端无 `is_demo` 守卫。 | `create_governance_request`/`review` 增加 `is_demo` 拒绝。 | [已完成]（治理删除对 `is_demo` 项目后端拒绝） |
| D4 | `project_governance_requests` 审批人角色校验弱。 | 审批人强制 admin/director。 | [已完成]（审批人强制 admin/director） |
| D5 | 审计缺口：模板保存/发布/状态迁移无 `log_change`。 | 见 C2-4/C6-6；补全写操作审计。 | [已验证]（模板保存/发布/复制 + issue 字段级 old/new 均补审计） |
| D6 | 前端 9 处 `aria-label`（全站），图标按钮无 alt/可访问名。 | 全站图标按钮补 `aria-label`/title。 | [已完成]（全局导航/主题切换/通知铃等图标按钮补 `aria-label`；round-5 补 Select/Progress/滚动容器语义，见 H2） |

## E. 可靠性
| # | 问题 | 修复方案 | 状态 |
|---|---|---|---|
| E1 | 无健康检查端点与容器 HEALTHCHECK。 | 见 A3。 | [已验证]（见 A3：`/health` + Docker `HEALTHCHECK`） |
| E2 | 启动 `create_all` 无迁移版本追踪；损坏库无法恢复。 | 见 A4/A5；启动前自动备份一次再迁移。 | [已验证]（`_backup_before_migrate` 启动迁移前自动备份，保留最近 20 份） |
| E3 | 调度器（scheduler/report_scheduler）无自愈（进程崩溃无重启补偿）。 | 调度任务加"上次运行成功水位"，重启补跑遗漏。 | [已验证] |
| E4 | 数据库连接池/重连策略仅 SQLite 参数。 | PG 引擎补 pool_pre_ping + 重连。 | [已验证]（PG 引擎 `pool_pre_ping`/`pool_recycle`；G5 冷启动实测） |
| E5 | 导出大项目内存峰值高。 | 见 B5。 | [已完成]（导出限流 B5 + 填报流水 >10 万行自动周聚合降内存） |

## F. 前端 UI/排版/响应式/无障碍/交互一致性
| # | 问题（证据） | 修复方案 | 状态 |
|---|---|---|---|
| F1 | 硬编码颜色遍布页面（`MessagesPage.tsx:164-171`、`ProjectListPage.tsx:471`、`DataAccessPage.tsx:29-31` 等），与主题 token 不一致。 | 收敛到 theme token/constants（status/roles/issues 单一事实源），颜色统一。 | [已完成]（新增 constants/theme.ts 语义 token，已收敛评审点名的 MessagesPage/ProjectListPage/DataAccessPage/LoginPage） |
| F2 | 硬编码 `fontSize` 散落（`LoginPage.tsx:82`、`MessagesPage.tsx:184-227` 等 11-13px 混用）。 | 收敛为字号 token（caption/body/small）。 | [已完成]（同上，字号统一走 FONT token） |
| F3 | 「排程规则」Switch 为 `disabled` 死配置（`SchedulePage.tsx:599`）。 | 接线真实生效（对应 C4-1）。 | [已验证]（排程规则弹窗改为真实编辑：休息模式/跳过节假日/手动休息日，存项目字段） |
| F4 | 全站仅 9 处 `aria-label`；图标按钮无可访问名；无焦点可见性处理。 | 补 `aria-label`/`role`/焦点环；表单错误 `aria-describedby`。 | [已完成]（全局导航开关/主题切换/通知铃均已补 aria-label；内容按钮自带可见文字；round-5 全量补齐 Select combobox/Progress/横向滚动容器可访问名，见 H2） |
| F5 | 响应式只靠 AntD 栅格（xs/md），无断点专项；今日页 44px 触控按钮未全覆盖。 | 移动端专项走查：Today/日程/问题页触控目标 ≥44px、表格横向滚动。 | [已完成]（Today 44px 触控基线已具备；全站宽表补 scroll={{x}} 横向滚动） |
| F6 | 交互一致性：确认弹窗/危险操作/空态/加载态/错误态在各页不一致。 | 统一 `Modal.confirm` 危险操作文案、空态插画/文案、骨架屏、错误重试。 | [已完成]（EmptyState 空态 30 处、危险操作 Modal.confirm、骨架屏基线已具备） |
| F7 | 项目状态机前端展示与后端十态不一致（历史遗留 `closed` 等）。 | 前端状态定义统一引 `constants/status.ts`，删除内联分叉。 | [已验证]（DashboardPage 状态筛选取代硬编码旧态 → STATUS_OPTIONS；问题状态补 cancelled 与后端 C6-7 一致） |
| F8 | 新建向导文案误导"任务已生成"（`ProjectListPage.tsx:213`）。 | 文案按真实结果分派（对 C1-1）。 | [已完成]（基线已具备：创建向导按真实生成结果分级提示） |
| F9 | 表格列宽/对齐/单位/Tag 语义在各页不统一。 | 页面走查统一列宽策略与数字对齐。 | [已完成]（为 10+ 宽表补横向滚动，表格列宽/数字对齐基线已统一） |
| F10 | PWA 离线状态提示不一致（今日页离线队列 vs 其他页）。 | 离线提示组件全局统一。 | [已完成]（基线已具备：Today 离线队列+同步 UI、退出登录未同步警告） |

## G. 测试与验收
| # | 事项 | 状态 |
|---|---|---|
| G1 | 后端 pytest 全量回归（当前 fix/review 基线）。 | [已验证]（**240 passed**，含 round-3 5 项、round-4（T006-T008）8 项与 round-5（T018-T021）5 项） |
| G2 | 新增针对 C2-1/C4-1/C4-2/C5-1/C5-2/C6-3/C7-3/C8-1 的单元/接口测试。 | [已完成]（round-2 新增 13 项接口测试覆盖 C6-3/C7-3/C8-1/C5-2 等；C4-1 已有 test_schedules 覆盖；round-3 再补 B2/C2-6/C8-4/B5 5 项） |
| G3 | 前端 `npm run build` 通过 + TypeScript 无错。 | [已验证]（`tsc -b && vite build` 退出 0） |
| G4 | 8002 端到端烟测（登录→建项目→生成任务→排程→确认→填报→问题→交付→归档）。 | [已验证]（E2E 直连 `127.0.0.1:8002`，**144 步全通过**：planning→ready→executing→pilot→acceptance→completed→archived，含问题闭环与交付物审核） |
| G5 | 单容器冷启动：全新数据卷 → 迁移 → 种子 → 健康检查通过 → 备份 → 恢复验证。 | [已验证]（一次性容器冷启动：health OK（~15s）→ 种子 4 用户/45 阶段/400 任务 → `pg_dump -Fc` 备份 → dropdb/createdb + `pg_restore` 恢复 → 数据完好 → 清理，不碰生产 8002） |
| G6 | 全站无障碍与对比度扫描（T019/T020，WCAG 2.1 AA）。 | [已验证]（150 次角色×路由 axe 扫描（wcag2a/2aa）**0 critical/serious**，label / aria-progressbar-name / aria-hidden-focus / scrollable-region-focusable 全部归零；**450 视口单元（150 路由×3 视口）100% 通过**，无横向溢出；对比度全站 ≥4.5:1（大字/UI 组件 ≥3:1），2332 个 color-contrast 节点归零；状态含义不再仅靠颜色传达） |

---

## H. 二审第三轮（T018–T022，2026-08-25）
| # | 问题（证据） | 修复方案 | 状态 |
|---|---|---|---|
| H1 (T018) | **dashboard stats 在 PostgreSQL 下崩溃**：`dashboard.py` 用 `.group_by(DailyProgress.user_id, User.display_name)`，PG 严格 GROUP BY 要求 select 列全出现在分组（SQLite 宽松模式不报）。 | GROUP BY 补 `User.role`/聚合函数对齐 select 列表；新增 PG 回归测试。 | [已验证]（真实 PG 端点 `/api/dashboard/stats` 200 且 workload 含 `现场工程师A`；旧 SQL 在 PG 上以 `column "u.display_name" must appear in the GROUP BY clause` 复现失败，修复后通过；`pg_stats_regression.py` 防复现） |
| H2 (T019) | **全站可访问语义缺失**：AntD Select combobox 搜索框无可访问名称（placeholder 不算 name）、`<Progress>` 无名称（aria-progressbar-name）、`.ant-table-measure-row` aria-hidden+tabindex=-1（aria-hidden-focus 4 节点）、横向滚动 `.ant-table-content` 不可聚焦（scrollable-region-focusable 2 节点）。 | 源码层为 Inputs/Selects/search boxes/Progress 补 aria-label；全局 MutationObserver 兜底（`utils/a11y.ts` 幂等补 label，随 DOM 变化自动修补）；measure-row CSS `visibility:hidden;height:0`；table-content 补 `tabindex=0 + role=region + aria-label`。 | [已验证]（150 次扫描 label/aria-progressbar-name/aria-hidden-focus/scrollable-region-focusable 全部归零） |
| H3 (T020) | **对比度不达 WCAG 2.1 AA**：次级文本 `.ant-typography-secondary`、彩色 Tag、KPI/日历/状态色多处 <4.5:1（1.64~4.15），150 次扫描 2332 个 color-contrast serious 节点。 | 收敛颜色：theme token `colorTextSecondary/colorTextDescription/colorTextTertiary` → 灰阶 ≥4.5:1；Tag 主色（cyan/green/gold/orange/volcano/success）与状态色（红/绿/蓝/橙）整体上调至 AA（大字号 ≥3:1）；状态含义同时保留文字/图标，不只靠颜色。 | [已验证]（150 次扫描 2332→0 serious；对比度全部 ≥4.5:1（大字 ≥3:1）） |
| H4 (T021) | **people/AI 路由与接口权限不一致**：technician 访问 `/pm/people` 时 `GET /api/dashboard/assignment-pool` 返回空候选池（人页像断链）；非管理员访问 `/pm/ai` 把 403 渲染成"AI 未配置"。 | 路由 `NAV_ACCESS` 与后端接口 allow-set 对齐：assignment-pool 对 technician 返回真实候选；AI `/status` 对所有登录角色开放，AI 能力校验放具体操作端点；前端 403 与"未配置"文案区分。 | [已验证]（technician `GET /api/dashboard/assignment-pool` → 200 且候选池非空；pm/technician `GET /api/ai-projects/status` → 200 `available:true`，不再以 403 冒充"未配置"） |
| H5 (T022) | 合并 T018-T021 全量回归 + 重建 8002 单容器 + 提交最终 SHA。 | 合并提交，重建容器，pytest + 前端 build + E2E + 视口扫描 + axe 扫描全绿后推送。 | [已验证]（240 passed；`tsc -b && vite build` 退出 0；E2E 144 步全通过；450 视口 100%；150 axe 扫描 0 critical/serious；清单无 [待办]；唯一运行容器 agv-pm-8002，`/health` 200；T018-T021 修复 4 笔 + 本清单更新已推送） |
| H6 (T023) | **8002 经 NPM 反代外网不可达**（用户实测：npm 反代理外网访问不行）。 | 复现并定位：端口发布 `0.0.0.0:8002→8000`、uvicorn 监听 `0.0.0.0:8000`、`TRUSTED_HOSTS=*` 均正常；缺**代理头信任**（uvicorn 无 `--proxy-headers`）与 **SSE 缓冲规避**（流式响应无 `X-Accel-Buffering: no`，nginx/NPM 默认 `proxy_buffering on` 会整段缓冲、流式挂起）。修复：`docker/supervisord.conf` uvicorn 加 `--proxy-headers`；`ai_projects.py` SSE 加 `X-Accel-Buffering: no`；Dockerfile/compose 提供 `FORWARDED_ALLOW_IPS`/`NO_PROXY` 兜底（T024 起默认不信任任意来源）。 | [已验证]（重建后全量 pytest 通过；`t023_npm_test.py` 基线 12 PASS/1 FAIL（SSE 头缺失）→ 修复后 **13 PASS/0 FAIL**；模拟 NPM 反代容器→宿主机 8002 实测页面加载/深链刷新/登录/登录后 API/SSE 流式全 200，SSE 带 `X-Accel-Buffering: no`；局域网 IP `192.168.1.136:8002`/`192.168.1.42:8002` 直连 200；`/health` 200；唯一运行容器 agv-pm-8002） |
| H7 (T024) | **代理头默认信任任意来源 + 独立仓库不可读**（二审：`--forwarded-allow-ips *` 下局域网客户端可伪造 X-Forwarded-For 污染登录审计 IP、绕过登录限流；独立仓库 `multica/agv-project-multica` 需恢复可访问）。 | 默认不信任任意来源：`FORWARDED_ALLOW_IPS` 默认空 → supervisord 条件传参，uvicorn 仅回环可信；显式配置 NPM 可信地址/网段才信任。新增 `backend/tests/test_proxy_security.py` 3 项回归（默认伪造头无效 / 轮换伪造头无法绕过登录限流 / 可信网段转发头生效）与 `docs/scripts/t024_proxy_security_test.py` 运行时验证。恢复独立仓库 `multica/agv-project-multica`：remote 加用户名认证、注册进 workspace 仓库 registry、分支 `fix/review-2026-08-24-multica` 含 `49953b6`，Multica 项目资源绑定该独立仓库。 | [已验证]（全量 **243 passed**（240+3）；`t023_npm_test.py` **13 PASS/0 FAIL** 不回退；运行时默认模式 uvicorn 无 `--forwarded-allow-ips`、伪造头访问日志记录真实对端（修复前 `*` 记录伪造 IP）；可信模式显式配置后转发头生效；独立仓库全新克隆 `fix/review-2026-08-24-multica` = `49953b6`，项目资源已绑定独立仓库） |
| H8 (T025) | **登录失败限流是进程内 `_login_failures`**（二审：`WEB_CONCURRENCY=2` 多 worker 各记各的，全局额度放大为 worker 数×单进程额度；容器重启即绕过窗口；不同 worker 无法共享登录失败计数）。 | 复用 T006 共享桶设计改 PostgreSQL 原子共享计数：新增 `login_failure_buckets` 表（`key`=真实客户端IP:用户名，固定窗口桶 + `UPDATE ... WHERE count < :limit RETURNING` 原子递增，PG 行锁保证并发下恰好 `limit` 次成功）；仅统计失败、成功登录清空该 key；不新增 Redis/任何容器；保留现有阈值（8 次）、窗口（15 分钟）、成功登录清理及 T024 可信代理后的真实客户端 IP 语义（key 用 `request.client.host`）。SQLite/单进程保留原内存路径，测试与本地行为不变。 | [已验证]（全量 **246 passed**（243+3，新增 `test_login_limit_t025.py`：PG 路径第 9 次 429/不同 key 隔离/成功清空/窗口滚动重置/`window` 保留字双引号防复现，内存路径不回退）；真实部署 8002 单容器 `t025_login_limit_test.py` **10 PASS/0 FAIL**：uvicorn `--workers 2` 确认 master+2 worker 子进程、顺序 9 次失败登录前 8 次 401 第 9 次 429（跨 worker 全局累计，第 9 次 429 必由共享落库达成）、不同账号隔离（PG 两 key 计数 {8,1}）、`docker restart` 后同一账号仍 429（窗口未被绕过）、重启后另一账号仍 401（隔离保持）；重建后 `t023_npm_test.py` **13 PASS/0 FAIL**、`t024_proxy_security_test.py` **6 PASS/0 FAIL** 不回退；唯一运行容器 agv-pm-8002 `/health` 200） |
| H9 (HYPE-24) | **`Invalid host header`（400）**：HYPE-19 把 `docker/.env` 的 `TRUSTED_HOSTS` 收口为静态精确 IP 白名单，Starlette `TrustedHostMiddleware` 只做精确/`*.domain` 匹配，无法表达"整个局域网网段"——反代域名访问、DHCP 换 IP、新增网卡/VPN 接口都会命中 400。 | 自研 `backend/app/middleware.py` `TrustedHostsMiddleware`：保留 Starlette 精确 + `*.domain` 语义，新增 **IP 网段（CIDR）** 条目（如 `192.168.1.0/24`）；未命中仍 400，**Host 校验不放开**。`main.py` 换用该中间件；`.env.example`/`docs/deployment.md` 补充配置示例。部署侧需把 `docker/.env` 的精确 LAN IP 收敛为网段并补上反代域名后重建容器。 | [已验证]（全量 **269 passed**（246+8 新增 `test_trusted_hosts.py`，另含 `test_proxy_security.py`/`test_security.py` 7 项不回退）；隔离回归 8 项全过：精确匹配/子域通配/CIDR 命中与未命中/带端口 Host/IPv6 字面量/未知 Host 仍 400/`*` 显式放行/真实部署白名单对比；临时端口 8100 实跑验证：`TRUSTED_HOSTS=...,192.168.1.0/24` 下局域网任意 IP（含未逐条列出的 `192.168.1.100`）与 `192.168.1.136:8002` 均 200，`192.168.2.5`/`10.0.0.7`/`agv.example.com` 仍 400；运行中 8002 容器复现 `Host=192.168.1.100`/`agv.example.com` → 400。**已部署（2026-08-26）**：以 `deploy/hype24-8c8149f` 重建 8002 容器（镜像 `agv-pm-multica:2.1.0` = `8c8149f` 代码），`docker/.env` TRUSTED_HOSTS 收敛为 `127.0.0.1,localhost,HUAWEI-Harmony-mini.local,HUAWEI-Harmony-mini,192.168.1.0/24`；未确认真实反代域名，未写入任何域名白名单；回滚镜像 `agv-pm-multica:2.1.0-pre-hype24` 与 `docker/.env.pre-hype24-*` 已留存。部署后验收：容器 healthy、`/health` 200、页面/API 正常；白名单精确主机与局域网任意 IP（含此前 400 的 `192.168.1.100`/`192.168.1.200`）全部 200；网段外 `192.168.2.5`/`10.0.0.7` 与未知/示例域名仍 400） |

---

## 优先级汇总（实施顺序）
1. **P0（本轮必须实现+验证）**：C2-1/C7-1 交付物审核持久化；C4-2 重排保护；C4-1 休息规则；C3-1 排程无成员阻断；C5-1 today 三态；C5-2 填报状态守卫；C6-3 问题状态机；C7-3/C8-1 完成/归档门禁；C2-7 phase_id 迁移；A1-A7 单容器 PG 部署；D1 登录限流。—— **全部 [已验证]**
2. **P1（本轮尽量）**：C6-1 升级；C6-2 worker 处理权限；C7-2 验收记录；C8-2 director 权限；F1/F3/F8 前端一致性高发项。—— **全部 [已验证]**
3. **P2（记录在案，后续迭代）**：C2-2/2-3/2-4 模板保存与发布；C3-2 单一事实源；C5-5/5-6 离线扩展；C6-6/6-7 审计与作废；C8-3 复盘；D2/D3/D4 安全补强；B/B4-B6 容量优化；F2/F4-F7/F9/F10 前端专项。—— **本轮已全部实现并验证，无一遗留**

> 说明：应主实施者要求"清单中任何条目未完成、未验证或仅写建议都不得结束"，原 P2 项也已在本轮全部实现、测试与部署验证，任务清单已无 [待办] 项。
> 二审补充整改（T006-T008）已合并回清单：B5 导出限流改 PostgreSQL 共享计数、C8-4 清理前持久化不可变归档、C8-6 移交旧负责人权限残留；round-4 新增 8 项回归测试（含 PG 保留字 `window` 双引号修复防复现用例），全量 235 项通过。
> 二审第三轮（T018-T022）已合并回清单：H1-H4（dashboard PG GROUP BY / 全站可访问语义 / WCAG 2.1 AA 对比度 / people-AI 路由权限对齐）新增 5 项回归测试，全量 240 项通过；G6 记录 150 次 axe 扫描 0 critical/serious 与 450 视口单元 100% 通过。
> 二审第三轮补充（T023，NPM 反代 8002 外网不可达）已合并回清单：H6 修复代理头信任与 SSE 缓冲规避，重建后全量 240 项通过；NPM 反代与局域网直连全链路实测通过（见 docs/deployment.md「Nginx Proxy Manager（NPM）反代 8002」）。
> 二审第四轮（T024，代理头默认信任任意来源 + 独立仓库不可读）已合并回清单：H7 将 `FORWARDED_ALLOW_IPS` 改为默认不信任任意来源、显式配置 NPM 可信地址/网段；新增 `test_proxy_security.py` 3 项安全回归（默认伪造头无效/轮换伪造头无法绕过登录限流/可信网段转发头生效），全量 243 项通过；运行时默认模式 uvicorn 无 `--forwarded-allow-ips`、伪造头访问日志记录真实对端；恢复独立仓库 `multica/agv-project-multica`（分支 `fix/review-2026-08-24-multica` = `49953b6`），项目资源绑定独立仓库。
> 二审第五轮（T025，登录失败限流进程内计数）已合并回清单：H8 复用 T006 共享桶设计将登录失败限流改为 PostgreSQL 原子共享计数（新增 `login_failure_buckets` 表，`UPDATE ... WHERE count < :limit RETURNING` 原子递增），保留阈值/窗口/成功登录清理/可信代理后真实客户端 IP 语义；新增 3 项回归测试，全量 246 项通过；真实部署多 worker + 容器重启运行时回归 10/10 通过（跨 worker 第 9 次 429、重启不能绕过窗口、账号隔离）；NPM 13 链与代理安全 6 项不回退；唯一运行容器 agv-pm-8002 `/health` 200。

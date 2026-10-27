# 系统全景与整理报告（2026-08 全系统梳理）

> 本文档是全系统梳理的正式成果：页面地图、接口地图、数据模型、问题清单、修复记录与遗留决策。
> 维护建议：随功能迭代同步更新；新增路由/页面时在此登记。
> **注意**：本文为历史整理报告，部分页面/接口/统计已变化。当前权威入口：CLAUDE.md（当前状态）、docs/page-map.md（v1.12 页面清单）、docs/data-visibility.md（数据边界）与实际代码。

## 1. 系统概览

| 项 | 值 |
|---|---|
| 架构 | FastAPI 0.115 + SQLAlchemy 2.0 + SQLite(WAL) ｜ React 18 + AntD 5 + Vite + PWA |
| 部署 | Docker 单容器（docker/docker-compose.yml），端口 8000，NAS 目标 |
| 规模（当前实测） | 前端 90 源文件 ｜ 后端 29 路由模块 / 146 端点 / 36 表 / 26 服务 ｜ 测试 255 用例全绿（pytest）＋ vitest 21 用例全绿 ｜ CI 门禁 scripts/ci.sh（.gitea/workflows/ci.yml） |
| 角色 | admin / director / lead / pm / technician / worker / intern（7 级） |
| 版本 | 2.1.2（前端版本号从 package.json 注入，单一事实源） |

## 2. 页面地图

### PM 端（/pm，需管理端角色；侧边栏按「工作台/团队/分析/系统」分组且随角色增减：admin 11 项、director 9 项、pm/lead/technician 8 项、worker 5 项）
| 路由 | 页面 | 核心接口 |
|---|---|---|
| /pm/dashboard | 数据总览：风险指标带(RAG)+逾期/未解决内联 Top5+项目状态表(分页10/页) | /dashboard/overview, overdue, issues |
| /pm/projects | 项目列表+创建向导（选模板→填信息→生成任务） | /projects, /templates, tasks/generate |
| /pm/ai | 统一 AI 助手：建档/排程/物品/问题/交接，项目能力校验 | /ai-projects 系列 |
| /pm/inventory | 物品总览：跨项目物品/去向的盘点视图 | 现场信息/物品相关接口 |
| /pm/people | 人员管理：按人安排/按项目/排班日历 3 Tab | /users/all-active, /projects, /dashboard/people-plan |
| /pm/stats | 信息统计：KPI+趋势折线+状态分布 | /dashboard/stats, trend, overview |
| /pm/messages | 消息通知（分页+未读过滤+批量已读） | /notifications 系列 |
| /pm/governance | 项目治理（admin/director only） | 治理相关接口 |
| /pm/notification-channels | 通知渠道（admin only，钉钉配置/测试，加密存储） | /notification-channels 系列 |
| /pm/templates | 模板中心：9阶段21模块80任务74检查项树形编辑 | /templates 系列 |
| /pm/users | 用户账号管理（按系统权限授权） | /users |

### 项目内（/pm/projects/:id/:tab，8 Tab）
总览 / 准备提醒 / 执行计划 / 项目日程 / 现场信息（现场车辆、物品与去向、现场交接 3 个内页）/ 问题关注 / 交付与验收 / 项目动态；AI 功能统一从侧边栏进入。

### Worker 端（/worker，需现场端角色，底部导航：今日/日程/问题/我的；消息在顶栏铃铛）
今日任务(离线填报+检查项+交付物+问题上报) / 我的日程(未来两周按日分组) / 问题关注(我上报及协管项目待关注) / 我的(我的记录+个人统计两个 Tab，`/worker/records`、`/worker/stats` 旧路由重定向到此) / 消息(`/worker/messages`，顶栏铃铛入口，与 PM 消息通知页同组件)

## 3. 接口地图（当前 146 端点，下表为历史节选；完整清单以 `/openapi.json` 为准）

| 模块 | 端点 | 权限 |
|---|---|---|
| auth | login / refresh / me / password | 公开 / 公开 / 登录 / 登录 |
| users | CRUD 4 个（admin）+ all-active（登录，下拉用） | admin / 登录 |
| projects | 列表+详情+CRUD+状态流转+车型 4 个 | 读=登录+可见性 / 写=pm |
| templates | 列表+树+导出+导入（10 个） | 读=登录 / 写=pm |
| tasks | modules / generate / tree / 单任务 / deliverables / check-items | 读=登录+可见性 / 写=pm / 打勾=worker |
| schedules | generate / 列表 / PUT 调整 / confirm / calendar | generate&confirm&调整=pm / 读=登录+可见性 |
| worker | today / reports(幂等+超额拦截) / sync(离线) / records / 撤回 | 登录+成员校验 |
| progress | 进度树 / 计划vs实际 | 登录+可见性 |
| issues | 列表 / 上报(成员校验) / 更新 / 删除 | 读=登录+可见性 / 写=pm |
| io_routes | 项目 Excel(13 sheet)/完整 JSON / AI 快捷导入 / 克隆 / 模板 Excel | 读=登录+可见性 / 写=pm |
| attachments | 列表 / 上传(成员) / 下载(按附件所属项目校验) / 删除 | 见左 |
| notifications | 列表 / 未读数 / 已读 3 种 | 登录（本人数据） |
| dashboard | overview / overdue / issues / stats / trend / people-overview | 登录+角色范围 |
| reports | 项目周/月报 | 登录+可见性 |
| insights | 项目逾期 / worker逾期 / people-plan / workload / current-phase | 登录 |
| archive | 清单(首次自动播种) / 更新 | 读=登录+可见性 / 写=pm |
| org | 组树 / 组 CRUD / roles | 读=登录 / 写=admin |

## 4. 数据模型（当前 36 表；完整清单 = 下述 17 表 + 19 张新增表，以 `information_schema.tables` 为准）

迁移机制：Alembic 版本化迁移与 db.py `_migrate()` + `ensure_column()`（PRAGMA table_info + ALTER TABLE 幂等，18 项列迁移）并存——新库由 Alembic 基线建表并维护 `alembic_version`，存量库仍由 `_migrate()` 兜底补列，另有 `PRAGMA user_version` 守卫（v1.2 耗时清理只跑一次）。

## 5. 2026-08 整理：已修复问题

### 安全（5 项）
1. **SECRET_KEY 硬编码** → env 优先，否则持久化 `data/secret.key`（chmod 600，重启不失效；NAS 部署拷贝该文件或设 env）
2. **跨项目越权读取**（系统性）→ 新增 `scope.ensure_project_visible(db, pid, user)`，11 个读端点统一收紧：logs / io_routes 导出 / schedules 列表 / progress / issues 列表 / insights overdue / reports / archive / attachments 列表 + **下载按附件所属项目校验**。worker 只能读自己参与的项目
3. **前端路由零角色守卫** → ProtectedRoute 加 `allow` 参数：/pm 需管理端角色，/worker 需现场端角色；删除 /worker/users 死路由（worker 此前 URL 直达可看全部账号）
4. **templates 5 个 GET 端点无鉴权** → 补 get_current_user
5. **项目可见性统一校验** → 未被指定或未参与的账号返回 404，避免泄露项目存在性

### 功能（9 项）
1. verify.sh 附件上传依赖第 7 步才生成的导出文件（干净环境必失败中断）→ 改用独立占位图片；步骤编号统一 x/9
2. MessagesPage「加载更多」失效（items.length 依赖导致 useEffect 循环重跑重置分页）→ itemsRef 跟踪已加载数
3. 孤儿页面 ImportExportPage.tsx（与 ExportPage 重复，无路由引用）→ 删除
4. api/index.ts 5 个死函数（userApi.remove / projectApi.remove / changeStatus / logs / orgApi.roles）→ 删除
5. 6 处未使用 import（PmLayout/ProjectListPage/ExportPage/HistoryPage/TodayPage）+ NotificationBell loading 死分支接线
6. AssignPage「按项目」进度 Tag 死 UI（列表接口不返回 percent）→ 删除
7. RecordsPage 撤回日期判定用 UTC（东八区晚 8 点后差一天）→ 改本地时区
8. ProjectLayout 非法 tab 静默空白 → 兜底回「项目总览」
9. 5 个页面 load 无 catch（StatsPage/PeoplePlanPage/HistoryPage/RecordsPage/IssuesPage）→ 补错误提示；前端版本号改从 package.json import

## 6. 权限矩阵（v1.2.1 能力型权限）

项目级能力：`project.update`(核心资料/车型/状态/删附件) / `manage_members` / `manage_plan`(任务) / `manage_schedule` / `manage_issues` / `export` / `archive` / `delete`。
判定：admin/director=全量可见；项目经理仅自己负责项目；技术经理/技术工程师需被指定为技术负责人；实施工程师仅被加入的项目。
项目不可见→404（不泄露存在性）；可见但无能力→403。实现：`app/services/permissions.py`（require_project_capability dependency + authorize_project）。

| 角色 | update/members/delete/archive | plan/schedule | issues | export | 说明 |
|---|---|---|---|---|---|
| admin / director | ✅ | ✅ | ✅ | ✅ | 全项目 |
| pm（负责人） | ✅ | ✅ | ✅ | ✅ | 自己负责的项目 |
| 技术负责人 | ❌ | ✅ | ✅ | ✅ | 仅限被指定项目，不能改核心资料/成员 |
| lead（负责人） | ❌ | ✅ | ✅ | ❌ | 现场执行管理 |
| technician/worker/intern | ❌（只读） | ❌ | ❌ | ❌ | 填报走 /worker、/deliverables、check-item 打勾 |

## 7. 遗留决策项（v1.2.1 后剩余）

| 项 | 现状 | 建议 |
|---|---|---|
| 已实现未接线端点（核实后） | 团队模板全套 / 模板 Excel/JSON 导入导出 / 日程月历汇总 / people-overview / workload / current-phase / 项目删除 / org.roles（**改密码已接线** v1.2.1；**用户删除**核实=前端只有停用无硬删除，后端 DELETE 保留 admin 用） | 团队模板按评审第二批接线；硬删除不接 UI |
| 乐观锁（并发修改保护） | **已实现**：projects/tasks/schedule_entries/issues 带 version 列，`services/optimistic.py` bump_version → 409 | 扩展到其余写端点（团队模板/准备项/审批等） |
| project_members 正规化 | **已实现**：project_members 关系表已落地（projects.members JSON 仍为兼容层） | 存量数据已在启动迁移时回填 |
| 备份恢复闭环 | 系统界面完整备份/恢复 + `docker/scripts/backup.sh` | NAS 再配置异机快照与定期恢复演练 |
| 项目时区 | 全系统 Asia/Shanghai 硬编码 | 多地区现场（俄/越）时再按项目时区 |
| refresh token 失效 | 已由 token_version 在改密/禁用后统一失效 | 后续评估 HttpOnly Cookie + CSRF |
| CORS | 默认同源关闭，`CORS_ORIGINS` 可显式开启 | 保持生产空值 |

## 8. 维护备忘

- 后端开发：`cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000`
- 测试：`cd backend && .venv/bin/python -m pytest tests/ -q`（255 用例）；前端 `cd frontend && npm test`（vitest 21 用例）；一键门禁 `bash scripts/ci.sh`
- 构建部署：项目根 `docker compose --env-file .env -f docker/docker-compose.yml up -d --build`（Docker 内部构建前端）
- 部署验证：项目根 `bash docker/scripts/verify.sh`（9/9，独立端口 8090 验证）
- 改安全相关：新读端点一律用 `ensure_project_visible`（404 不泄露）；新写端点一律用 `require_project_capability`/`authorize_project`（403），不直接用 `require_pm`
- 写操作一律 `log_change()` 审计（约定不变）

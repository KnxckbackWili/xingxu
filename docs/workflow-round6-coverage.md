# 第六轮：独立业务闭环与全功能覆盖矩阵

> 历史 QA 记录：接口、测试名和结果按当时源码保留，不作为 3.0.0 当前操作说明。原测试现按功能归入 `test_legacy_schedule_preservation.py` 及周计划替代测试；旧行为的保留、迁移或退役见[测试整理记录](test-organization-plan.md)。历史通过数量不代表新功能已复验或已部署。

审查日期：2026-10-01（UTC）。起始代码：`ea97dcb4a610d46aad2b2ac3b8afb0634a11e05d`。本报告记录产品逻辑交叉复核与证据；本轮未操作生产数据，并补正了当前流程说明和附件清理 SOP。**最终清单按 2026-10-01 11:51 UTC 的源码重新提取**；发现时证据与修复后结果在下文分别列出。最终全量后端运行由综合验证记录负责，不能把本报告定向测试代替它。

专题证据：[生命周期](workflow-round6-lifecycle.md)、[现场执行](workflow-round6-field.md)、[系统与导入](workflow-round6-system.md)、[人员与预览](workflow-round6-availability.md)、[前端与浏览器边界](workflow-round6-browser.md)。本文负责完整清单和跨领域一致性，专题报告负责具体复现/修复；不把重叠测试数量相加。

## 结论与判定标准

“页面可打开”“测试为绿”“接口有权限控制”不是业务闭环完成。必须能解释：谁发起、谁执行、何时算完成、失败后谁处理、历史如何保留，以及同一事实在不同页面是否表达同一结论。

本轮独立盘点得到：

- `frontend/src/pages` 有 **55 个非测试 TSX 组件**。其中包括页签、嵌入面板和布局，不能宣称 55 个独立页面全部完成浏览器验收
- `backend/app/routers` 有 **37 个含 HTTP 操作的模块、256 个 HTTP 操作**；加 `/health` 为 257。另有 `/api/ai/mcp/` 挂载协议，不在 HTTP 装饰器计数内
- 正常主链、权限、取消/重试、离线、导入/导出、归档、移交及后台运维均进入本矩阵；仍存在**业务定义未定、页面入口缺失和恢复语义不完整**三种不同问题
- 不应把旧轮次的 924/405 个测试结果复制为本轮结果，也不应把当前规则被测试固定下来称为业务已正确

### 证据标记

- **S**：本轮源码/路由/调用关系核查。能证明当前实现，不等于真实点击或故障测试
- **P1–P3**：本轮独立合成数据库/API/服务观察，见下文。断言用于确认现状，不表示赞同现状
- **T**：本轮重跑指定已有用例；仅覆盖用例断言到的分支。具体清单与结果见“本轮实际执行”
- **R5**：第五轮报告或已有回归文件提供的背景证据，本报告没有用它替代本轮执行
- **B**：真实浏览器验收。本报告不把源码、jsdom、API、静态构建标为 B；本轮实际尝试结果：云浏览器 `ERR_BLOCKED_BY_CLIENT`，本机 Chromium Unix socket `EPERM`，允许的工具级升级后仍受阻，真实截图/旅程为 0，不再绕过环境限制
- **未验**：需要外部环境、人工产品决策或尚未执行的组合；不能推断通过

## 一、已复现的业务矛盾及需要明确的选择

### D1：项目阶段由“写入次数”而非真实阶段事实决定

**来源**：`services/status_flow.py:advance_project_status/regress_project_status`，`services/progress.py:project_progress_tree`。

**P3 实际结果**：两个项目都为 100% 且数据相同，一个仅评估一次变为 `commissioning`，另一个评估三次变为 `acceptance`；从 `acceptance` 把完成量一次撤回到 0%，一次回退后仍为 `pilot`。直接服务探针用于隔离规则本身，不声称所有 API 都恰好调用相同次数。

**人的问题**：甲把工作一次录入、乙分三次录入，项目不该因此分别是“系统联调”和“验收中”。数量分母还把“100 个地图点”和“1 套安全验证”相加，100 个点完成后可显示约 99%，并不证明已经试运行。

可选定义：

1. **建议**：80/90/95% 仅作进度提示，阶段由对应工作/必要质量证据完成后人工确认；改进度不自动宣称已试运行
2. 若坚持纯进度状态，改用清晰的“进度区间”标签并按一次计算到达确定区间，不冒充业务里程碑；还需规定撤回时是否降级
3. 保留现状会保留同事实不同状态，不能称为逻辑收敛

需决定：真实阶段负责人、进入/退出证据、是否允许例外、撤回影响。不是简单把阈值由 80 改为 85 能解决。

### D2：历史通过是否能覆盖后来不通过

**来源**：`routers/projects.py:change_status` 完成门禁查询任意 `conclusion='accepted'`。

**P2 实际结果**：9 月 29 日通过、9 月 30 日不通过、任务 100%，仍能标记 `completed`。

可选定义：

1. **建议**：最新有效“同范围/同版本”验收决定是否允许完成；后来拒绝立即使旧通过不能满足完成条件
2. 分批/分范围验收：每个车辆批次、子系统或合同范围各有有效结果，全部必需范围通过才完成
3. 历史通过永远有效：必须明确后来的“不通过”仅是无门禁效力的补充记录，避免界面误导

注意：仅按 `accepted_at` 日期取最大仍不够；同日多轮、补录旧日期、撤销/替代关系、扩范围后旧验收的有效性需定义。保留历史记录，不删除旧通过。

### D3：进场评审与实际进入执行是两套门禁

**来源**：`routers/preparations.py:_summary/_review_manifest/confirm_review`，`routers/projects.py:change_status`。

**P1 实际结果**：新建待进场项目有 6 个未完成阻塞项、无已确认准备评审；`POST /status {status:executing}` 省略 `confirm_warnings` 仍返回 200 并进入执行。代码明确将省略值用于旧客户端兼容。

另一个矛盾：普通 `ready` 评审把所有未完成项列入 `unmet`，包含非必需且不阻塞的可选项；而状态流转警告只看阻塞/逾期，高风险未逾期、预计延期、评审失效并不等价。

可选定义：

1. **建议**：统一入口，只认可当前快照的“就绪”或明确风险确认；普通就绪需要必需/阻塞项通过，可选项保留提醒
2. 风险进场必须记录每项责任人、补齐期限、批准人/理由；与安全条件区别处理，哪些永不允许豁免必须由业务方确认
3. 如果保持软提醒，就明确它不是强制门禁；API、前端和评审页都要用同一说明，不能只有页面要求确认

例子：可选的住宿安排未完成不应与安全围栏未通过采用同样的正常进场规则。不能用“全部标成不适用”替代真正的例外决定。

### D4：检查项的“通过”究竟覆盖谁

**来源**：`models.CheckItem` 只有 `task_id/project_id` 与一个检查状态；`DailyProgress` 同样没有车辆/批次检查归属。`VehicleUnit` 有独立履历，但未成为检查项结果维度。

现状：10 台车辆的同一“急停测试”任务只有一组检查状态；一次勾选不能表达 9 台通过、1 台失败，也不能回答“车辆 A-007 谁在什么时候做过哪次测试”。

可选定义：

1. **建议**：检查模板可选择项目级/任务级/批次级/逐车级；安全关键或交付合同要求逐车的项生成逐车结果，其余沿用共享检查
2. 任务级只保留总体确认，但必须提示“已代表全部车辆核对”并提供外部逐车证据附件；这不能等价于结构化逐车追踪
3. 逐批检验需明确批次清单、抽样规则、失败重检与更换车辆后的失效规则

这是模型能力缺口，不应通过把 task 目标数量改为 10 就声称完成逐车质量闭环。

### D5：一次下达的范围与重复下达语义

**来源**：`routers/schedules.py:confirm_schedule` 和 `apply_suggestions`。

现状：确认接口无日期/任务/人员范围参数，选择全项目非“项目准备”日程；每次调用都递增发布版本并通知成员。AI 应用一个任务的建议并带 `confirm=true` 会复用同一个全项目发布入口。未安排任务只是返回提示，缺执行人也不是普遍的硬门禁。

例子：经理在本周日历检查 A 的 3 条日程，另有下月 B 的 20 条草稿；点击下达并不意味着只下达可见 3 条。重复点击/超时重试还可能发出新的版本与通知，虽然没有新业务变化。

可选定义：

1. 保留全项目一次下达，但按钮与确认预览必须列明全部新增条目、日期跨度、人员和异常
2. **分批作业建议**：显式选择范围、预览固定候选 ID/version、只发布该批；未分配可作为公共待领工作与不可执行草稿两类，而不是含混的空执行人
3. 幂等命令标识/无变化不重复通知属于重复动作完整性；发布粒度本身仍须业务确定

### D6：一件、24 小时、三天，计划为何是 1/0/0

**来源**：`services/scheduler.py`，`tests/test_round5_scheduler_integrity.py:test_long_single_unit_split_policy_remains_unchanged`，`pages/worker/TodayPage.tsx`。

现状：任务目标 1、标准耗时 24 小时，可生成三天数量 **1/0/0**。今日任务以 `planned_quantity - completed_today` 显示剩余；0 数量日期并无清晰的工时占用对象。

人的例子：整机联调需三天，第一天完成安装但整机尚不能算一套交付；“全完成”按钮按件数却可把 1 全报在第一天，后两天则显示计划 0。现有用例有意保护现状，不能把该用例绿灯当为合理体验。

可选定义：

1. **建议**：交付数量仍为整数；独立记录每天计划/实际工时与持续占用，最终一天才确认该件完成；日历以工时显示人力负荷
2. 可拆分工程量的任务允许小数（0.33/0.33/0.34），但单位必须表达可拆分量，不能强行把安全测试“一次”拆碎
3. 显式拆成安装/调试/验证三个可验收子任务，代价是计划维护量增加

### D7：提交、批准、可选交付物的完成口径不一致

发现时源码：提交把 `done=true` 用于 `submitted` 和 `approved`；项目完成门禁只读 `done` 且遍历所有具名交付物；交接摘要却把 `required && status!='approved'` 列为待办。

所以发现时可能出现“必需文件待批准，但项目可完成”和“可选附件未交，项目不可完成”。

**11:19 UTC 更新**：生命周期审查已修复 `required=false` 可选项误阻塞，并将字符串形式的必需交付按未交付处理；该修复的最终复测由生命周期/综合报告提供。**submitted 是否必须 approved 才能完成仍未改变，是待确认的业务规则**。 后续交叉复查还复现了“已完成后退回必需交付仍能归档”；生命周期审查已提取统一必需交付校验，并在完成与归档两处复用，独立正向探针确认退回后归档返回 400。合理不变量应为同一套必需/批准规则供完成、归档、交接、概览共同使用；若业务允许免审核提交，也应显式选择并统一。

### D8：数据迁移副本不能同时冒充完整恢复与新项目

发现时源码：JSON 保留项目 `status` 和部分进度，但没有验收、准备评审、全部审计、检查执行状态/执行身份、日程与报工关联、附件字节等完整历史；导入创建新 ID 并由导入账号承接部分历史身份。ZIP 包带附件文件，但页面未提供 ZIP 恢复操作。

人的例子：项目已完成，导出 JSON 再导入后仍是“已完成”，但找不到当时验收；或计划量/进度已存在、检查却回到待查。系统审查负责更细的安全定义字段损失和实际回放。

**第六轮局部更新**：系统审查补齐时区、模块/阶段定义、任务适用车型、依赖及检查描述；外项目交付证据/审核身份重置并在预检明确提醒。独立往返复验确认人工 per-vehicle 目标 17 在车数 3 时仍保留 17。终态项目的完整历史恢复合同尚未改变，因此不能将这些字段修复称为完整恢复。

可选定义：

1. **建议**：名称与产品入口分成“复制项目定义”“导入外部项目数据”“完整系统恢复”三类，用户明确知道历史/权限/附件处理方式
2. 若要可验证项目级恢复，需可移植 ID 映射、范围/版本、签字/审计、附件哈希与缺失校验；不能仅将 JSON 字段补全几项就承诺完整恢复
3. 完整实例备份走系统备份/数据库恢复；恢复过程和外部通知的副作用单独验证

### D9：留存的接口与承诺的网页闭环不一致

发现时全源检索：

- `/pm/ai`、`/pm/ai-assistant` 均重定向项目列表；当前网页入口为管理员 `/pm/ai-tokens`，是外部 Agent 接入配置，不是聊天页
- `ChangeSetPanel` 组件只有测试导入，实际页面没有挂载；已有 Agent 提案不能按旧文档描述在网页看到/审核。写 scope 的接口仍可调用，不等于普通人有审核入口
- `/pm/inbox` 路由保留，但主菜单及工作区刻意排除，需已知链接；不能用“页面测试通过”证明新用户能发现它
- 突发状况 API 与 dashboard 未关闭计数仍在，`/projects/:id/incidents` 却被旧路由解析成首页；普通用户缺少专门关闭旧 incident 的网页路径
- 物理清理后的 `/archives/projects` 查询/校验 API 没有相应网页入口；治理页展示申请结果不等于可以读完整归档快照

这些应分别决定恢复入口或正式声明为兼容/API/运维能力，不能同时宣称“已下线”及“所有普通用户可闭环”。已列为待确认的产品入口范围。

## 后段交叉复核：不能以“政策未定”解释的实现缺陷

以下是在责任范围交叉检查中新增的确定缺陷。系统审查已修复或以保留隐私的方式处理，本报告在收束源码上进行只读复核：

1. **变更集合并使用锁前权限**：请求最初以 PM 负责人鉴权，另一会话在项目锁边界把同一账号降为 worker；REST 合并仍 200 并实际更改项目。探针并未伪造请求身份，而是模拟真实角色撤销与在途请求交错。**已修复**：变更集所有写动作统一 SQLite/PostgreSQL 可用的项目优先写锁，锁后刷新账号、可见性与能力；同一探针现在返回 403，不再写入
2. **保留期归档丢失验收原始证据**：给验收记录写唯一备注，正常 soft-delete 超 31 天后 purge；原验收行被级联删除、备注在快照与日志均不存在，校验 API 仍返回 `match=true`。**已修复**：专门 `agvpm-project-retention` 快照按明确业务表白名单保存原记录/身份/状态，并保留共享模板阶段、旧任务检查关系；验收备注和原记录现在可在快照找到。校验哈希只验证已包含内容，不能单凭哈希证明未来所有数据类型都完整
3. **个人临时日程阻塞整批清理**：通过正常 API 添加 PersonalEvent 后项目进入保留期清理，因 FK 无 cascade 且 purge 未处理，返回 `FOREIGN KEY constraint failed` 并回滚。**保守处理**：个人临时日程仍只属本人，不复制到管理员可见档案、不擅自删除；仅该项目延后清理并计入通用 blocked 数，其他项目可正常清理。本人在项目软删除后仍能查阅/删除/改挂自己的事件。若本人不清理，项目会继续保留，不能承诺 30 天后一律清掉
4. **旧字符串交付定义无法导回自身导出**：收紧导入校验时，只接受 dict，却仍原样导出系统支持的字符串交付要求。**已修复**：系统审查加入兼容归一化与往返回归；新项目证据重置规则不因此放松
5. **迁移恢复了错误连接的外键开关**：组合探针出现 Project 已删但 AcceptanceRecord 仍在，不能用单条重跑绿灯掩盖。独立复现为两个池连接最初均 FK=1，真实 `init_db()` 后变为 [1,0]；SQL 物理连接追踪证明 OFF 在连接 A、ON 在连接 B。**已修复并独立组合复验**：迁移固定同一 checkout 连接，提交/失败回滚后在同一连接恢复并验证 FK；不能恢复则 invalidate，禁止危险连接回池。再次追踪 OFF/ON 为同一连接，两连接均为 1，正常级联删除恢复。

**文件链也已接通**：`binary_files.manifest` 记录文件名、来源、可用性、大小与 SHA-256；归档文件读接口核对 manifest、路径、归档与文件哈希。附件/收集箱/模板删除均尊重归档所有权，清理 SOP 的候选查询也排除此引用。文件字节仍在 uploads，不嵌入 JSON，磁盘损坏仍须完整系统备份。旧归档的缺失历史不能凭修复代码补造。

## 仍需区别对待的其他边界

系统审查补充了以下现行边界，不能合并成一句“其余均通过”：

- 账号停用立即阻止登录，但当前进行中工作不自动交接；这是安全撤权与业务责任的配合问题。推荐保持立即撤权，并让管理者看到尚无人接管的工作，不能为等交接而延缓安全停用
- 撤销项目访问后，已发到个人收件箱/历史聊天的旧内容是否保留属于数据留存选择；没有在本轮擅自删除历史
- 同时配置多个通知渠道时，任一成功可被记为送达；若要求每个渠道都收到，须另定逐渠道结果与重试。当前没有真实外发证据
- 模板整树和部分库存/车辆长开编辑缺少全域强制乐观版本，不能声称已消除旧表单覆盖；这是技术完整性缺口，不应伪装为已完成验收
- 同名收集箱文件的 AI 结果仍按文件名关联，分类歧义尚未解决；稳定文件 ID 或逐文件分类才可把每个结果对应到正确输入。与同名项目不自动猜目标是两个不同问题
- 维修事件复发后再安排仍复用原已报满任务，不能继续报同样数量；当前可用独立临时返工工作并注明原问题。产品应明确每轮新维修任务或每次复发新事件，不能把旧实绩清零来伪造下一轮进度
- 历史周期报告的项目百分比仍是当前状态，期初按当前范围与历史量重算；当前没有过去每一轮范围/检查的快照。报告不能被当作精确历史签字证明
- 周容量固定 40h、全部人员不可用时自动排程的降级策略、终态项目遗留未来安排是否继续占容量仍待统一；本轮补齐冲突时间范围与隐私并不解决这些定义

## 二、从人的目标出发的端到端验收故事

| ID | 完整旅程与角色 | 预条件/关键事实 | 成功必须建立的事实 | 异常与恢复路径 | 本轮证据/剩余风险 |
|---|---|---|---|---|---|
| J01 | 管理员首次启用 → 个人演示 → 建真实项目 | 新实例、账号有效；演示只属本人 | 演示不混入正式统计/通知；真实项目可在正确时区找到 | 首登失败、停用、退出登录再进、误删演示后不反复生成 | S；T private_demo；真实安装/邮件未验 |
| J02 | PM 选模板 → 配置车辆/目标 → 准备/采购 → 安排成员 → 排程 → 下达 → 现场执行 | 负责人、模板版本、人工目标、执行人/工期 | 任务不重复；准备不重复进入施工；成员收到可执行任务 | 目标漏填、0 车、跨日、无可用人、草稿未下达；补齐后续做 | S；T project_template_flow/e2e_closure；D3/D5/D6 |
| J03 | 一部分工作执行后改工期/重排/取消/改派 | 已下达、已报工、取消、锁定混合 | 已发生历史保留；剩余量不重复；原人改派后能解释去向 | 旧页面 409、重排已删草稿、项目中途归档；刷新复核再重做 | S；T scheduler_integrity；多人 PostgreSQL 竞争未验 |
| J04 | 工人断网填数量/检查/交付/问题 → 重连 → 再次离线 | 曾在线读取、账号绑定、缓存/队列可用 | 同 UUID 只落一次；被拒数据保留并可修正；不同账号不混队列 | 撤权、版本冲突、浏览器关闭、账号切换、HTTP 已成功但应答丢失 | S + R5 queue/useOfflineSync；真实 Service Worker/手机操作仍未验证 |
| J05 | 10 台车分批调试 → 单车失败 → 维修 → 复检 | 车辆台账、任务数量、检查范围明确 | 能回答每台车每次质量结论及执行/审核人 | 一台失败不能被其他车勾选覆盖；换车、补量、N/A/安全项处理 | S；模型 D4 未决，现实现仅任务级 |
| J06 | 上报问题/车辆故障 → 领修/处理 → 关闭 → 复发重开 | 谁上报、影响哪车/任务、照片证据 | 项目问题与车辆当前异常一致；维修任务不重复生成 | 重复点击、误关、跨项目附件、停工期间、完成/归档后复发 | S；R5 field + vehicle_issue；完成后处理规则需清晰 |
| J07 | 交付提交 → 退回 → 更换证据 → 他人审核 → 验收 → 完成 → 归档 | 必需项、最新有效签字、未结问题已清 | 同一“完成”规则贯穿交接/概览/项目门禁；资料与签字可追溯 | 最新验收拒绝、项目扩范围、附件变更、撤回进度、恢复项目 | S；P2/P3；D2/D7，归档恢复亦需复核 |
| J08 | 原 PM 移交 → 新 PM 接管 → 原人离开 | 申请/审批身份、待交接工作及成员权限 | 谁还欠什么有明确主人；老账号失权不丢历史 | 未交接的已下达工作阻止移除；审批冲突、撤回、拒绝可恢复 | S；T governance_tracking；长表单及多人审批由其他审查复测 |
| J09 | 导出/移交另实例 → 导入 → 校验继续执行 | 是定义复制还是历史恢复须先选 | 数量、时区、依赖、证据和状态不会静默改变含义 | 同名任务、缺附件、无原成员、格式错误、过期模板、重复上传 | S；T io/report_forms；D8，不承诺完整项目恢复 |
| J10 | 管理员备份 → 故障 → 恢复 → 验证登录/附件/任务 | SQLite/PostgreSQL 路径不同，备份可读 | 完整数据库+文件+密钥一致；失败回滚到原状态 | 包损坏、路径穿越、容量不足、中途终止、并发备份、启动失败 | S+R5 system；真实 NAS/容器/断电/PostgreSQL 未验 |
| J11 | 外部 Agent 查询 → 提案 → 人审核 → 合并 → 撤销 | token 绑定账号/独立写 scopes；可见项目 | 最小授权；新基线不能被旧草稿覆盖；用户知道何时写库 | token 过期/停用、403/404、旧基线 409、已归档、重放 | S；R5 agent/change_sets；D9 人工入口缺失待处理 |
| J12 | 海外工地现场日期 → 今日任务 → 修正 → 周报/导出/审计 | 每项目时区、本地工作日期/UTC 操作时间不同 | 今天与逾期一致；真实完成量/人工完成状态分开 | 跨午夜、夏令时、回填、撤回、已删除/演示项目过滤 | S；T e2e_closure/my_calendar；跨区真实设备显示未验 |

## 三、逐功能覆盖矩阵

表内测试名省略 `backend/tests/` 或 `frontend/src/` 前缀。T 只用于本轮确实选入重跑清单的文件；其余明确写 R5/测试定位。S 包括确认实际入口、处理函数和关联数据，不表示逐行证明整个模块的全部实现。每一行都包含可操作的失败恢复目标，不因当前有测试而删除风险；各责任人修复后的终态证据须与综合报告对照。

### 账号、全局导航与个人执行

| 功能/页面或入口 | 用户目标与预条件 | 失败/恢复必须覆盖 | 本轮证据 | 剩余风险 |
|---|---|---|---|---|
| 登录、刷新会话、退出；LoginPage | 活跃账号进入正确角色工作区；尊重安全 next 地址 | 密码错、接口 5xx、旧 me 晚到、重复点、退出后刷新/另一标签页 | S App/auth/client；R5 auth.test/LoginPage.test | cookie/SameSite/真实会话跨域未验 |
| 改密；ChangePasswordModal | 自己更新凭据并回到可登录状态 | 旧密码错误、弱密码、已过期会话、旧 token 不应复活 | S auth.py；R5 test_auth/admin_rotation | 真实密码管理器/表单交互未验 |
| PM/worker 布局、403/404、旧链接 | 有权者能发现功能；无权 URL 明确拒绝 | 404 项目/无权限、后退前进、抽屉关闭、错误路由不默默变成其他业务 | S App/projectNav/pmMenu；R5 App/nav tests | D9；未知项目 tab 回首页可能掩盖坏链接 |
| 今日任务 TodayPage | 看本地今天已下达安排，按本次新增量报工 | 重复提交、0 数量、超目标、另一人已填、过期安排/撤权 | S worker.py；T e2e_closure；R5 TodayPage/field | D6；整条日报上限和任务累计上限须解释清晰 |
| 统一工作详情 WorkDetailHost/WorkContextPanel | 从列表/日历进入同任务，查安排、记录、剩余并填报 | 快速切任务、关闭保留草稿、重试保持 UUID、账户切换 | S；T test_work_workspace | 内嵌与页面两套表单长期保持一致 |
| 检查三态、必需/安全、不适用原因 | 区分通过/失败/不适用；安全项不可豁免 | 状态互转、过期版本、误勾、更换结果、离线冲突 | S task/check/model；R5 test_checkitem_tristate/field | D4；单个“通过”代表任务而非每辆车 |
| 手动完成/重新打开、数量修正 | 管理人员能纠正，且不伪造真实工作量 | 小数余量、同 UUID 重放、已完成项目、失败后再试 | S worker.py/progress.py；R5 manual_complete/float_residue | 状态完成与实际报工不同，报表要同时解释 |
| 我的记录 RecordsPage | 找到自己的历史并授权撤回 | 已删除/归档项目、撤回使质量/进度回退、记录不属本人 | S worker.records/withdraw；T e2e_closure；R5 RecordsPage | D1 回退只一步；分页/长历史浏览器未验 |
| 我的统计 WorkerStats / MyPage | 本人统计不泄露公司范围；记录/统计页签可达 | 空数据、加载失败、演示/已删排除、日期边界 | S；R5 WorkerStats/RecordsPage | 标签页状态/打印未验 |
| 我的项目 WorkerProjects/WorkerProjectDetail | 工人能从个人入口查看项目完整上下文 | 退出项目、深链接旧项目、非成员、只读状态 | S worker routes + project capabilities；R5 worker pages | 多角色授予能力后控制是否即时刷新 |
| 我的日程 WorkerSchedule，PM editable | 看个人跨项目日期并做允许的本人调整 | 改别人的、已填报/已结束、过期版本、跨月、休假冲突 | S；T test_my_calendar_self_edit | 触屏拖拽/键盘替代需 B |
| 现场问题 WorkerIssues | 看自己可见项目的问题，含已解决再重开 | 无可见项目、空筛选、误关闭后恢复、不同项目归属 | S；R5 WorkerIssues/test_completion_issue_review | 部分用户可能只通过通知进入旧上下文 |
| 离线缓存与四类队列 | 无网继续记录，联网有明确成功/被拒状态 | 浏览器重开、账号切换、错序依赖、队列 retry/remove、磁盘满 | S offline/*/sw.js；R5 相关 Hook/queue | 未证明浏览器持久性、安装 PWA、系统清理缓存后的恢复 |

### 项目建立、计划、人员与准备

| 功能/页面或入口 | 用户目标与预条件 | 失败/恢复必须覆盖 | 本轮证据 | 剩余风险 |
|---|---|---|---|---|
| 项目列表搜索/筛选/新建 | 新项目具备名称日期时区/模板/责任者；清楚下一步 | 重名、日期倒置、快速双建、取消后重新打开、导入返回 | S ProjectList/projects；T project_template_flow/private_demo | 角色创建边界与共享范围逐组合未穷举 |
| 个人演示/删除演示 | 练习数据本人可见，不发给同事、不计正式统计 | 删后刷新、重登、其他 admin 读写、软删后清理 | S personal_demos；T test_private_demo | 演示数据仍有权限分工，不能当管理员操作模拟器 |
| 项目首页/下一步/启动清单 | 一眼知道项目欠什么，能去正确页补齐 | 无车/无任务/缺目标/成员不足/未下达；失败不是空 | S Overview/projectWorkflow；R5 Overview/Startup tests | D1/D3/D7；“清单齐备”不等于已实际进场 |
| 开工安排 StartupPage/StartupWork | 连续录目标→人员→排程→进场 | 未保存离开、后台已变、部分失败、回退步骤不丢内容 | S；R5 StartupWork/StartupPage tests | 全局导航、浏览器后退是否同样拦未保存需 B |
| 项目资料 EditPage、联系人/入场计划 | 改客户地点日期/时区，不误改权限 | 旧 version 409、日期变化后日程不自动偷改、归档只读 | S projects/EditPage；R5 EditPage/optimistic | 改时区后历史日期解释需要产品定义 |
| 车型数量/适用车型/车型字典 | 按真实车数生成适用任务目标 | 0/负/未知车型、改数量低于实绩、字典改名、已有手动目标 | S projects/vehicle_types/generate_tasks；T project_template_flow | 车型汇总与独立车辆台账数量不自动等同 |
| 项目任务生成/追加/编辑/依赖 | 模板快照生成执行结构；追加工作进入同一执行系统 | 重生成不重复；模板改名、循环依赖、已有实绩时删除/改目标 | S tasks/generate_tasks/work_assignment；T project_template_flow/work_workspace | 历史模板变更不能悄悄重写已发生事实 |
| 目标人工填写/单位/标准耗时 | 施工量与耗时有不同含义 | 缺目标不生成假 0；小数、负值、单位切换、不足工期 | S scheduler/effort/StartupWork；T round5_scheduler | D1/D6；异单位总量不等于真实阶段完成度 |
| 任务参考文件、交付要求编辑 | 施工前能读对资料，不能误把参考当交付 | 过期预览、跨项目附件、同名交付、已批准附件替换 | S tasks/attachments/TaskPlan；R5 references/field | 实际文件安全扫描、版本版次治理未验 |
| 准备清单/五分类/责任方/四日期 | 区分采购跟进、客户条件与施工，形成进场决定 | 任务/阶段跨项目引用、延期、需求数量变更、责任人停用 | S preparations；T readiness/project_template_flow | 外部责任方不是已分派系统账号，通知责任不能臆测 |
| 常用采购显式带入/采购数量规格 | 只选本项目需采购的项目，避免模板自动采购 | 重复导入、无效 ID、单位/数量变化、旧已就绪失效 | S preparations/import-procurements；T project_template_flow | 只是跟进清单，无采购审批/下单/收货自动闭环 |
| 准备评审/正常/风险/不进场/历史 | 评审具体快照，保留理由与未完项 | 旧 token、新增/恶化风险、改日期、同名项、清单为空 | S；T test_readiness_confirmation；P1 | D3；业务安全不可豁免条件未定义 |
| 团队成员/协管/定岗/成员能力 | 成员看全项目，操作按本项目授权 | 撤人前交接、授权旧版本、协管过期、不能转授权/删项目 | S Team/MemberPermissions/permissions；R5 member_permissions | 全角色×能力×状态组合仍需分层验收 |
| 团队模板保存/应用/重用 | 快速套用成员配置且不覆盖未交接责任 | 模板成员停用、他人模板、覆盖/合并模式、归档中修改 | S team_templates；R5 test_team_templates | 应用成功不代表人员日期容量可用 |
| 人员安排/AssignPage/StaffingBoard | 跨项目看容量、挑合适成员、安排具体工作 | 部分批量写失败刷新、409、同名人、不可用期间 | S PeoplePlan/Assign；R5 people/work_assignment | 成员加入与日程分派不是同一操作，应持续区分 |
| 不可用时段/个人日程/团队日程 | 登记请假出差、不把冲突隐去 | 重叠日期、错人、删除后容量恢复、项目不可见信息隔离 | S availability/TeamSchedule；T my_calendar | 手工覆盖冲突是否需要额外确认未统一说明 |

### 排程、现场协同、交付与历史

| 功能/页面或入口 | 用户目标与预条件 | 失败/恢复必须覆盖 | 本轮证据 | 剩余风险 |
|---|---|---|---|---|
| 自动排程/预览/规则保存 | 依据目标、依赖、技能/负荷、周末规则生成草稿 | 无人/无工时/工期不足、预览失败不确认、旧预览被新请求替代 | S schedules/scheduler；T round5_scheduler | 排程优化不代表真实工期承诺；D6 |
| 甘特/日历/月视图/拖动/锁定 | 在正确粒度改整任务或单日安排 | 锁定、已报工、已下达、跨月、误拖、409 刷新 | S Schedule/Gantt；R5 schedule tests | B 需验证触屏、可访问操作、打印分页 |
| 下达/通知/未分配/未排入 | 把确切计划送到执行者 | 空计划、重复调用、全项目隐含范围、无负责人、漏任务 | S confirm_schedule；T status_flow | D5；发布版本可增而内容无变化 |
| AI 排程建议/匹配/发布 | 只应用本项目唯一任务/有效成员 | 同名歧义、过期草稿、保留已下达/锁定/实际历史 | S apply_suggestions；R5 round5 lifecycle | D5，局部建议触发全项目下达 |
| 取消/已结束历史/剩余量/重排 | 取消未做计划不当作完成，不占据剩余量 | 已取消但部分完成、锁定取消、旧草稿删除、历史顺序 | S scheduler/progress；T round5_scheduler | 所有统计维度都要排除取消计划而保留实绩 |
| 停工/恢复 | 说明原因、停止执行、恢复原阶段 | 重复暂停、非法恢复、停工时排程/问题/交付写边界 | S project_lifecycle/status；R5 suspension | 停工期间哪些准备/补证允许写需文档统一 |
| 突发状况/影响任务/顺延/关闭 | 突发影响有主人、安排与复盘 | 已锁/下达历史保护；关闭要理由；旧 incident 如何找回 | S incidents/dashboard；R5 incidents | D9，无专门人用入口；不能称全站闭环 |
| 项目问题分类/照片/解决/重开 | 记录问题、谁处理谁负责、解除影响 | 附件失败保留文本、重复上报、分类专属字段、旧状态冲突 | S Issues/issues；R5 issue_categories/workflow | 项目问题与旧 incident 两种模型共存 |
| 现场车辆创建/编辑/阶段/故障履历 | 按车编号保留真实状态与维修轨迹 | 重复编号、开故障后改正常、最后故障关闭、跨项目事件 | S VehicleLifecycle/vehicle_lifecycle；T report_forms | 长编辑表单缺通用强制版本，D4 |
| 车辆故障一键安排维修 | 故障成为一条可执行工作，完成后可复核 | 重复点击不重复任务、改派、验收失败重开、故障仍未关 | S vehicle_lifecycle/work_assignment；R5 vehicle_issue | 工作量完成不自动等于车辆无故障 |
| 物品台账/物权/保管人/库存流水 | 知道东西在哪里、谁持有、剩多少 | 并发领料、负库存、同 UUID、部分出库、异地收料、删除有历史物品 | S Inventory/inventory；本轮 field 报告补十进制/幂等/位置一致性 | 整表旧编辑覆盖；单行仅一处余额，部分移库须先拆分；跨项目“调拨”不是原子转移流程 |
| 物品总览/低库存/去向 | 跨可见项目找物品、缺口和待归还 | 已删/演示过滤、项目权限、加载失败不显示空台账 | S InventoryOverview/dashboard；R5 overview | 汇总看得到不代表拥有写权限 |
| 物品申请单 CRUD/DOCX 往返 | 保存申请、导出给相关方并回导 | 格式错、重复导入、归档只读、删除后历史 | S report_forms/Inventory；T test_report_forms | 这是申请记录，不是已授权采购/审批/入库 |
| 生命周期 XLSX 往返 | 导出车辆履历，修改后按已知规则回导 | 表头变、车辆/事件匹配、同名、日期、并发/重复导入 | S report_forms/VehicleLifecycle；T test_report_forms | 文件导入非事务合并工具，字段缺失语义需清楚 |
| 质量问题单 XLSX 导出/回导 | 以原版表单交流问题证据 | 错项目、文件坏、重复问题、附件关联/文字提取失败 | S report_forms/Issues；T test_report_forms | Excel 版式/打印需独立视觉验证 |
| 现场交接/客户联系人/入场安排 | 到现场知道找谁、何时、怎样进入 | 主要联系人唯一、清空/旧版本、私密信息可见范围 | S SiteHandover/projects；R5 SiteHandover | 项目共享不是个人通讯录；导出泄露范围须告知 |
| 项目文件上传/预览/下载/删除 | 证据属于当前项目，能找到并打开 | 超限/危险文件、上传并发、文件缺失、跨项目引用、删除被引用 | S Files/attachments；R5 file safety/Files | 真实杀毒、浏览器 MIME/大文件内存未验 |
| 交付清单/上传/审核/退回再交 | 提交者与审核者分开，替换附件后重审 | 整表保留未变项；同名/删改要求；旧 version；上传后切任务 | S tasks/Delivery；R5 field/Delivery | D7；需求必需性与完成门禁一致性待最终复测 |
| 验收签字/结论/附件 | 记录真正批准范围/签字人及时间 | 拒绝后再验、同日轮次、补录、错误附件、范围变化 | S Archive/projects；P2 | D2；当前只是录入姓名，不是电子签名认证 |
| 完成/恢复/归档/复盘/归档清单 | 质量/交付/问题齐备后结束；历史仍可查 | 未达量、检查未过、未关问题、复盘为空、恢复后修改 | S projects/archive；T status_flow | D1/D2/D7；恢复到 completed 也要考虑有效门禁 |
| 项目动态 History/Activity | 查谁何时改了什么，不能把审计当撤销功能 | 时间/操作筛选、旧项目响应、空与失败、删除后访问 | S logs/History/Activity；R5 History | 不可见/已软删项目的后续查档需 D9 运维入口 |
| 周/月报告、计划/实际曲线、个人/公司统计 | 同一事实聚合一致，周期和累计不同 | 时区、取消量、人工完成、负修正、演示/已删排除 | S reports/progress/insights/Stats；T e2e_closure | 异单位相加与工时估算的解释；导出打印未验 |
| 消息中心/通知铃/单条全已读/上下文跳转 | 接收可执行提醒并回到正确记录 | 失效项目、被撤权、重复通知、切账号、未读变化 | S notifications/notifyNav/Messages；T notification_filters | 外部渠道送达不同于站内落库；D5 重复下达 |

### 导入导出、系统管理与后台能力

| 功能/页面或入口 | 用户目标与预条件 | 失败/恢复必须覆盖 | 本轮证据 | 剩余风险 |
|---|---|---|---|---|
| 快捷 JSON 模板/预检/新建 | 从外部结构化定义建立项目，预检再确认 | malformed JSON、非法成员注入、无目标、同名任务、重复提交 | S io_routes/ProjectList；T test_io | D8，项目历史与定义不能混称备份 |
| 项目 JSON/Excel/ZIP 导出 | 下载可解释的快照/附件集合 | export 能力、文件名、权限变化、缺附件、超长历史 | S import_export/Export；T test_io | D8；ZIP 不是已实现的一键项目恢复 |
| 项目克隆 | 复制结构到新日期，保留原项目且不复制实绩 | 同名、日期倒置、旧模板/自定义模块、重复点击 | S io_routes/Export；T test_io | 与 JSON 导入的历史处理口径差异须明确 |
| 甘特 PDF/报告下载 | 可交付打印或文件 | 弹窗被阻止、当前视图不符、分页/中文字体/图表截断 | S Export/Report | 仅 window.open + 浏览器打印；未经 B/打印验收 |
| 模板中心/多模板/阶段模块任务检查 | 管理以后项目的来源，不改已交付项目事实 | 模板选错、重复/重命名、归档/激活、适用车型、删除引用 | S templates/TemplateEditor；T project_template_flow | 模板变更影响后建项目，现项目更新政策需明确 |
| 模板准备项/常用采购库 | 分开管理准备提醒与可选采购 | 条件触发、必需/阻塞含义、改单位、复制模板 | S TemplatePreps/Procurements；T project_template_flow | D3；采购库不是采购执行 |
| 模板 JSON/Excel 导入导出/参考资料 | 可定制模板并理解匹配规则 | 跨模板复制、同层重名、改名视为新增、失败原子性 | S import_export/templates；R5 template_excel/system | Excel 不包含所有元数据/二进制资料；手工重命名非身份重命名 |
| 用户管理/技能/角色/停用启用 | 管理有效人员，不留下旧会话越权 | 最后 admin、原用户名、同名显示、资料/技能部分失败 | S users/Users；R5 users/system round5 | 账号停用后其项目/日程责任仍需交接，不应只隐藏 |
| 组织小组/批量人员调整 | 管理团队结构与可发现候选人 | 树层级、重复、部分成功、成员不可用、旧响应 | S org/Users/Assign；R5 org/Users | 组织成员变动不自动完成项目级工作交接 |
| 车型管理 | 统一字典并保留历史引用 | 停用在用车型、重复名字、快速切换/重复提交 | S vehicle_types/VehicleTypes；R5 vehicle_types | 旧自由文本/导入映射可能继续存在 |
| 移交申请/审批/拒绝/撤回 | 有可追溯结果，原任务有人接手 | 新负责人不合格、工作没交接、并发处理、老申请过期 | S Governance/projects；T governance_tracking | 原 PM 可见性变化/项目成员边界组合未穷举 |
| 删除申请/软删/保留/物理清理归档 | 知道消失范围及如何查留存证据 | 拒绝/撤回、未交接、保留期、清理失败、归档哈希不符 | S + T governance_tracking；本轮独立实际 purge/验收留存/私人事件探针；system 专题回归 | D9 无完整查档网页；个人事件使该项目延后；没有生产计划任务运行证据 |
| 备份列表/创建/下载/删除/准备恢复 | 保存完整实例，按支持路径恢复 | 损坏包、版本/数据库类型不符、并发、失败回滚、重启 | S SystemBackup/system/backup_safety；R5 system | SQLite 网页恢复与 PostgreSQL 脚本不同；真实 NAS 未验 |
| 通知渠道保存/测试/定时日报周报 | 正确接收方看到正确范围，不泄露秘密 | 空凭据保留旧值、配置冲突、发送失败、重试、时区/重复发送 | S notification_channels/report_scheduler；R5 channels/scheduler | 无真实外部提供商送达证据 |
| 外部 Agent token/MCP/HTTP | 仅绑定账号可见范围，独立写 scope | 超期/停用、无 scope、撤成员、跨项目、token 只显示一次 | S ai_internal/agent/ai_mcp/AiTokens；R5 agent/ai_permissions | 真实 Agent 客户端/SSO/网络未验；不许把配置页称聊天页 |
| AI 问答/排程/整理后台任务/流/预算 | 后端保留接口安全失败、有状态可查 | provider 错误、预算、job 取消/过期、丢流尾、cookie 身份 | S ai_projects/codex/ai_jobs；R5 ai_chat/budget/stream_tail | 无网页聊天入口；真实外部 AI 未验 |
| AI 记忆/变更草稿/合并/回退/取消 | 白名单修改可审阅、旧基线不可覆盖、回退不越过新改动 | 两个草稿、归档、重复合并、权限撤销、过期 version | S ai_memory/change_sets/ChangeSetPanel；R5 change_sets | D9 人工面板缺挂载；scope 放行即有实际写能力 |
| 文档收集箱上传/整理/归项目/下载/删 | AI 建议目标，用户确认后进入正确项目 | 同名项目不自动猜、选错/过期、轮询切账号、归档后刷新失败 | S Inbox/inbox；R5 test_inbox/InboxPage | D9 不可发现；真实 AI 内容质量与文件隐私未验 |
| 反馈提交/列表/处理状态 | 用户报告产品问题并看到处理结果 | 附件失败、内容为空、重复提交、无权查看其他反馈 | S feedback/Feedback；R5 feedback/FeedbackPage | 系统反馈与项目问题不同，避免错入口 |
| 健康检查/迁移/部署/更新回滚/静态服务 | 部署后可登录、深链接/资源可用、失败回滚 | 数据版本迁移失败、反向代理、压缩/PWA、限流/CORS/hosts | S main/migrations/docker scripts；R5 deploy/static/auth scan | 真实 Docker/PostgreSQL/NAS 故障恢复未验 |

## 四、页面/路由完整清单

### 全局 URL

- 公开：`/login`；`/` 重定向登录；未知顶层路径显示 NotFoundPage
- PM 工作区：`/pm` 按角色落地；`/pm/projects`、`/pm/dashboard`、`/pm/inventory`、`/pm/my-schedule`、`/pm/team-schedule`、`/pm/people`、`/pm/templates`、`/pm/stats`、`/pm/messages`、`/pm/governance`、`/pm/backups`、`/pm/users`、`/pm/ai-tokens`、`/pm/notification-channels`、`/pm/vehicle-types`、`/pm/feedback`、`/pm/inbox`
- PM 旧链接：`/pm/ai`、`/pm/ai-assistant` → `/pm/projects`；`/pm/progress` → `/pm/dashboard`
- 现场工作区：`/worker` → `/worker/today`；`today`、`schedule`、`issues`、`projects`、`projects/:projectId`、`my`、`messages`、`feedback`
- 现场旧链接：`/worker/records`、`/worker/stats` → `/worker/my`；两者都打开合并页，而非保证选择旧页签

### 项目 URL（前缀 `/pm/projects/:projectId`）

`/` 与 `/overview` 首页；`/start` 开工安排（step=work/people/schedule/entry）；`/preparation` 准备；`/plan` 任务（task/tab/focus 查询）；`/tasks` 旧任务别名；`/schedule` 日程（view=gantt）；`/vehicles`、`/inventory`、`/handover` 现场信息子项；`/issues`（report=1 上报）；`/team` 团队；`/delivery`、`/files`、`/archive` 交付子项；`/activity`、`/history`、`/reports` 历史/报告；`/edit` 设置；`/export` 导出。

路由接受任意 `:tab`，未识别值由 `resolveProjectNav` 退回首页，包括已下线 incidents。该行为不是专用页面存在的证据。

### 55 个页面目录组件（含独立页面、子组件与布局）

- `.`：`FeedbackPage.tsx`、`ForbiddenPage.tsx`、`LoginPage.tsx`、`MessagesPage.tsx`、`NotFoundPage.tsx`、`StatsPage.tsx`

- `pm`：`AiTokensPage.tsx`、`AssignPage.tsx`、`DashboardPage.tsx`、`GovernancePage.tsx`、`InboxPage.tsx`、`InventoryOverviewPage.tsx`、`NotificationChannelsPage.tsx`、`PeoplePlanPage.tsx`、`ProjectListPage.tsx`、`StaffingBoard.tsx`、`SystemBackupPanel.tsx`、`TeamSchedulePage.tsx`、`TemplateEditorPage.tsx`、`TemplatePrepsTab.tsx`、`TemplateProcurementsTab.tsx`、`UsersPage.tsx`、`VehicleTypesPage.tsx`

- `pm/project`：`ActivityPage.tsx`、`ArchivePage.tsx`、`DeliveryPage.tsx`、`EditPage.tsx`、`ExportPage.tsx`、`FilesPage.tsx`、`GanttView.tsx`、`HistoryPage.tsx`、`InventoryPage.tsx`、`IssuesPage.tsx`、`MemberPermissions.tsx`、`OverviewPage.tsx`、`PreparationPage.tsx`、`ProjectLayout.tsx`、`ProjectMenu.tsx`、`ReportPage.tsx`、`SchedulePage.tsx`、`SiteHandoverPage.tsx`、`SiteInformationPage.tsx`、`StartupPage.tsx`、`StartupWork.tsx`、`TaskPlanPage.tsx`、`TeamPage.tsx`、`VehicleLifecyclePage.tsx`

- `worker`：`MyPage.tsx`、`RecordsPage.tsx`、`TodayPage.tsx`、`WorkerIssuesPage.tsx`、`WorkerProjectDetailPage.tsx`、`WorkerProjectsPage.tsx`、`WorkerSchedulePage.tsx`、`WorkerStats.tsx`


## 五、路由核对领域与逐接口清单

核对领域缩写：**L** 生命周期；**F** 现场执行；**S** 系统工具；**B** 真实浏览器；**C** 跨领域语义与功能入口。领域映射用于查阅证据，不代表每个写入口的全部权限/并发组合已验证。

| 路由模块 | 实质业务领域/交叉核对 | 功能证据要求 |
|---|---|---|
| projects / preparations / schedules / progress / team_templates | L；C 核对进场/阶段/验收/发布定义 | 从建立到恢复/移交完整状态机，失败原子性、历史保护 |
| tasks | L 任务结构/目标；F 检查/交付/执行；C 比较完成与交接规则 | 目标/质量/交付不能只靠 percent 互相替代 |
| worker / issues / vehicle_lifecycle / inventory / attachments | F；L 核对完成阻塞 | 实际填报、修正、报修、物品流水、证据与并发 |
| archive | L；F 核对交付证据 | 归档清单不能代替验收门禁 |
| availability / report_forms / reports / dashboard / insights | L；F 核对车辆/库存表单 | 日期/可见性/往返完整性/统计分母，需业务用例 |
| auth / users / org / templates / vehicle_types / io_routes | S；L 核对项目复制后可继续执行 | 停用会话、模板身份、导入语义，不能只测未认证 401 |
| system / archives | S；C 后段独立复核 archives 原 3 接口/新增文件接口及实际 purge | 恢复前校验、重启后应用、失败回滚；结构化证据不随 purge 丢失，个人日程不得阻塞其他项目的保留期清理 |
| ai_projects / ai_internal / ai_memory / codex / agent / change_sets | S；C 独立复核 change_sets 6 个 REST 操作与人工入口 | 绑定身份/scope/版本、草稿与真实写分离、请求重试及等待期间撤权 |
| notifications / notification_channels | S；L 核对发布/周期触发 | 正确收件人/上下文/去重；外部送达单独验 |
| inbox / feedback / logs | S；C 核对可发现性 | 同名目标、账号切换、审核历史和反馈处理闭环 |
| incidents | L（项目影响/恢复）+ F（任务阻塞）；C 已报入口缺口 | 已有 incident 能被人找到、处理并关闭 |
| App / 全部页面及导航 / PWA | B；对应后端责任人处理发现 | 真实页面交互证据，与 API/组件测试分别记录 |

下列列表由本轮 AST 提取，覆盖 37 个路由模块的 256 个 HTTP 操作。列出接口不表示每个接口已穷举所有角色、状态和输入；上方矩阵说明相应完整业务责任和证据级别。`main.py` 的 `/health` 与 MCP mount 另计。

### `agent.py`（2）

- `GET /api/agent/tools` → `list_agent_tools`
- `POST /api/agent/tools/{name}` → `call_agent_tool`

### `ai_internal.py`（4）

- `GET /api/ai/internal/tokens` → `list_tokens`
- `POST /api/ai/internal/tokens` → `create_token`
- `PUT /api/ai/internal/tokens/{token_id}` → `update_token`
- `DELETE /api/ai/internal/tokens/{token_id}` → `revoke_token`

### `ai_memory.py`（3）

- `GET /api/ai/memory` → `list_memories`
- `POST /api/ai/memory` → `create_memory`
- `DELETE /api/ai/memory/{memory_id}` → `delete_memory`

### `ai_projects.py`（13）

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

### `archive.py`（3）

- `GET /api/projects/{project_id}/archive-checklist` → `get_checklist`
- `POST /api/projects/{project_id}/archive-checklist/initialize` → `initialize_checklist`
- `PUT /api/projects/{project_id}/archive-checklist/{item_id}` → `update_item`

### `archives.py`（4）

- `GET /api/archives/projects` → `list_project_archives`
- `GET /api/archives/projects/{project_id}` → `get_project_archive`
- `GET /api/archives/projects/{project_id}/verify` → `verify_project_archive`
- `GET /api/archives/projects/{project_id}/files/{stored_name}` → `download_retained_file`

### `attachments.py`（4）

- `GET /api/projects/{project_id}/attachments` → `list_attachments`
- `POST /api/projects/{project_id}/attachments` → `upload_attachment`
- `GET /api/attachments/{attachment_id}/download` → `download_attachment`
- `DELETE /api/attachments/{attachment_id}` → `delete_attachment`

### `auth.py`（5）

- `POST /api/auth/login` → `login`
- `POST /api/auth/refresh` → `refresh_token`
- `POST /api/auth/logout` → `logout`
- `GET /api/auth/me` → `me`
- `PUT /api/auth/password` → `change_password`

### `availability.py`（6）

- `GET /api/users/{user_id}/unavailability` → `list_unavailability`
- `POST /api/users/{user_id}/unavailability` → `create_unavailability`
- `PUT /api/users/{user_id}/unavailability/{unavail_id}` → `update_unavailability`
- `DELETE /api/users/{user_id}/unavailability/{unavail_id}` → `delete_unavailability`
- `GET /api/users/{user_id}/skills` → `get_skills`
- `PUT /api/users/{user_id}/skills` → `update_skills`

### `change_sets.py`（6）

- `POST /api/projects/{project_id}/change-sets/propose` → `propose`
- `GET /api/projects/{project_id}/change-sets` → `list_change_sets`
- `GET /api/projects/{project_id}/change-sets/{change_set_id}` → `detail`
- `POST /api/projects/{project_id}/change-sets/{change_set_id}/merge` → `merge`
- `POST /api/projects/{project_id}/change-sets/{change_set_id}/rollback` → `rollback`
- `POST /api/projects/{project_id}/change-sets/{change_set_id}/cancel` → `cancel`

### `codex.py`（1）

- `POST /api/ai/codex/chat` → `codex_chat`

### `dashboard.py`（11）

- `GET /api/dashboard/assignment-pool` → `assignment_pool`
- `GET /api/dashboard/trend` → `portfolio_trend`
- `GET /api/dashboard/metrics` → `management_metrics`
- `GET /api/dashboard/people-workload` → `people_workload`
- `GET /api/dashboard/people-overview` → `people_overview`
- `GET /api/dashboard/people-summary` → `people_summary`
- `GET /api/dashboard/stats` → `unified_stats`
- `GET /api/dashboard/issues` → `scope_issues`
- `GET /api/dashboard/overview` → `portfolio_overview`
- `GET /api/dashboard/overdue` → `overdue_projects`
- `GET /api/dashboard/decision-view` → `decision_view`

### `feedback.py`（4）

- `POST /api/feedback` → `create_feedback`
- `GET /api/feedback` → `list_feedback`
- `GET /api/feedback/{feedback_id}` → `get_feedback`
- `PATCH /api/feedback/{feedback_id}/status` → `update_feedback_status`

### `inbox.py`（7）

- `POST /api/inbox/documents` → `upload_documents`
- `GET /api/inbox/documents` → `list_documents`
- `GET /api/inbox/documents/{doc_id}/download` → `download_document`
- `DELETE /api/inbox/documents/{doc_id}` → `delete_document`
- `POST /api/inbox/documents/{doc_id}/archive` → `archive_document`
- `POST /api/inbox/documents/organize/jobs` → `create_organize_job`
- `GET /api/inbox/documents/organize/jobs/{job_id}` → `get_organize_job`

### `incidents.py`（6）

- `POST /api/projects/{project_id}/incidents` → `create_incident`
- `GET /api/projects/{project_id}/incidents` → `list_incidents`
- `GET /api/projects/{project_id}/incidents/{incident_id}` → `get_incident`
- `POST /api/projects/{project_id}/incidents/{incident_id}/postpone` → `postpone_schedule`
- `POST /api/projects/{project_id}/incidents/{incident_id}/block` → `update_blocked_tasks`
- `POST /api/projects/{project_id}/incidents/{incident_id}/status` → `change_status`

### `insights.py`（14）

- `POST /api/dashboard/people-plan/self` → `create_my_plan_entry`
- `GET /api/dashboard/personal-events` → `list_personal_events`
- `POST /api/dashboard/personal-events` → `create_personal_event`
- `PUT /api/dashboard/personal-events/{event_id}` → `update_personal_event`
- `DELETE /api/dashboard/personal-events/{event_id}` → `delete_personal_event`
- `GET /api/dashboard/team-schedule` → `team_schedule`
- `GET /api/projects/{project_id}/overdue` → `overdue_tasks`
- `GET /api/worker/overdue` → `worker_overdue_tasks`
- `GET /api/dashboard/people-plan` → `people_plan`
- `PUT /api/dashboard/people-plan/{entry_id}/self` → `update_my_plan_entry`
- `GET /api/dashboard/workload` → `global_workload`
- `GET /api/projects/{project_id}/current-phase` → `current_phase`
- `GET /api/north-star` → `north_star_metric`
- `GET /api/dashboard/staffing` → `staffing_board`

### `inventory.py`（8）

- `GET /api/inventory` → `global_inventory`
- `GET /api/projects/{project_id}/inventory` → `project_inventory`
- `POST /api/projects/{project_id}/inventory` → `create_item`
- `POST /api/projects/{project_id}/inventory/import` → `import_items`
- `PUT /api/projects/{project_id}/inventory/{item_id}` → `update_item`
- `DELETE /api/projects/{project_id}/inventory/{item_id}` → `delete_item`
- `GET /api/projects/{project_id}/inventory/{item_id}/movements` → `list_movements`
- `POST /api/projects/{project_id}/inventory/{item_id}/movements` → `create_movement`

### `io_routes.py`（9）

- `GET /api/projects/import/template` → `download_quick_import_template`
- `POST /api/projects/import/preview` → `preview_quick_import`
- `GET /api/templates/export/excel` → `export_template_excel`
- `POST /api/templates/import/excel` → `import_template_excel`
- `GET /api/projects/{project_id}/export/excel` → `export_project_excel`
- `GET /api/projects/{project_id}/export/json` → `export_project_json`
- `GET /api/projects/{project_id}/export/package` → `export_project_package`
- `POST /api/projects/import/json` → `import_project_json`
- `POST /api/projects/{project_id}/clone` → `clone_project`

### `issues.py`（8）

- `GET /api/projects/{project_id}/issues` → `list_issues`
- `GET /api/projects/{project_id}/issue-assignees` → `issue_assignees`
- `GET /api/projects/{project_id}/vehicle-issues` → `list_vehicle_issues`
- `POST /api/projects/{project_id}/issues` → `create_issue`
- `POST /api/projects/{project_id}/issues/import` → `import_issues`
- `PUT /api/issues/{issue_id}` → `update_issue`
- `POST /api/issues/{issue_id}/reopen` → `reopen_issue`
- `DELETE /api/issues/{issue_id}` → `delete_issue`

### `logs.py`（1）

- `GET /api/projects/{project_id}/logs` → `list_logs`

### `notification_channels.py`（4）

- `GET /api/notification-channels` → `get_channels`
- `PUT /api/notification-channels/dingtalk` → `put_dingtalk`
- `DELETE /api/notification-channels/dingtalk` → `disable_dingtalk`
- `POST /api/notification-channels/dingtalk/test` → `test_dingtalk`

### `notifications.py`（5）

- `GET /api/notifications` → `list_notifications`
- `GET /api/notifications/unread-count` → `unread_count`
- `POST /api/notifications/{notification_id}/read` → `mark_read`
- `POST /api/notifications/read-all` → `mark_all_read`
- `POST /api/notifications/read-batch` → `mark_batch_read`

### `org.py`（5）

- `GET /api/org/groups` → `list_groups`
- `POST /api/org/groups` → `create_group`
- `PUT /api/org/groups/{group_id}` → `update_group`
- `DELETE /api/org/groups/{group_id}` → `delete_group`
- `GET /api/org/roles` → `list_roles`

### `preparations.py`（10）

- `POST /api/projects/{project_id}/preparations/import-procurements` → `import_procurements`
- `GET /api/projects/{project_id}/preparations` → `list_preparations`
- `POST /api/projects/{project_id}/preparations` → `create_item`
- `PUT /api/projects/{project_id}/preparations/{item_id}` → `update_item`
- `DELETE /api/projects/{project_id}/preparations/{item_id}` → `delete_item`
- `POST /api/projects/{project_id}/preparations/seed` → `seed_items`
- `POST /api/projects/{project_id}/preparations/confirm-ready` → `confirm_ready`
- `POST /api/projects/{project_id}/preparations/review` → `review_manifest`
- `POST /api/projects/{project_id}/preparations/review/confirm` → `review_confirm`
- `GET /api/projects/{project_id}/preparations/reviews` → `list_reviews`

### `progress.py`（3）

- `GET /api/projects/{project_id}/progress` → `progress`
- `GET /api/projects/{project_id}/progress/timeline` → `timeline`
- `GET /api/projects/{project_id}/overview` → `project_overview`

### `projects.py`（18）

- `GET /api/projects` → `list_projects`
- `POST /api/projects` → `create_project`
- `GET /api/projects/{project_id}` → `get_project`
- `GET /api/projects/{project_id}/people` → `project_people`
- `PUT /api/projects/{project_id}` → `update_project`
- `POST /api/projects/{project_id}/team-template` → `apply_team_template`
- `DELETE /api/projects/{project_id}` → `delete_project`
- `POST /api/projects/{project_id}/governance-requests` → `create_governance_request`
- `GET /api/projects/governance/requests` → `list_governance_requests`
- `POST /api/projects/governance/requests/{request_id}/review` → `review_governance_request`
- `POST /api/projects/governance/requests/{request_id}/withdraw` → `withdraw_governance_request`
- `POST /api/projects/{project_id}/status` → `change_status`
- `POST /api/projects/{project_id}/acceptance` → `create_acceptance`
- `GET /api/projects/{project_id}/acceptance` → `list_acceptance`
- `GET /api/projects/{project_id}/vehicles` → `list_vehicles`
- `POST /api/projects/{project_id}/vehicles` → `add_vehicle`
- `PUT /api/projects/{project_id}/vehicles/{vehicle_id}` → `update_vehicle`
- `DELETE /api/projects/{project_id}/vehicles/{vehicle_id}` → `delete_vehicle`

### `report_forms.py`（11）

- `GET /api/projects/{project_id}/export/lifecycle` → `export_lifecycle`
- `POST /api/projects/{project_id}/import/lifecycle` → `import_lifecycle`
- `GET /api/projects/{project_id}/issues/{issue_id}/export/quality-form` → `export_quality_form`
- `POST /api/projects/{project_id}/import/quality-form` → `import_quality_form`
- `GET /api/projects/{project_id}/item-applications` → `list_item_applications`
- `POST /api/projects/{project_id}/item-applications` → `create_item_application`
- `GET /api/projects/{project_id}/item-applications/{app_id}` → `get_item_application`
- `PUT /api/projects/{project_id}/item-applications/{app_id}` → `update_item_application`
- `DELETE /api/projects/{project_id}/item-applications/{app_id}` → `delete_item_application`
- `GET /api/projects/{project_id}/item-applications/{app_id}/export` → `export_item_application`
- `POST /api/projects/{project_id}/import/item-application` → `import_item_application`

### `reports.py`（1）

- `GET /api/projects/{project_id}/report` → `project_report`

### `schedules.py`（11）

- `POST /api/projects/{project_id}/schedule/generate` → `generate`
- `GET /api/projects/{project_id}/schedule` → `list_schedule`
- `PUT /api/schedule/{entry_id}` → `update_entry`
- `POST /api/projects/{project_id}/schedule/confirm` → `confirm_schedule`
- `POST /api/projects/{project_id}/schedule/apply-suggestions` → `apply_suggestions`
- `GET /api/projects/{project_id}/schedule/preview` → `preview_schedule`
- `GET /api/projects/{project_id}/schedule/reschedule-preview` → `reschedule_preview`
- `POST /api/projects/{project_id}/schedule/reschedule` → `reschedule`
- `GET /api/schedule/assignment-check` → `assignment_check`
- `GET /api/schedule/calendar` → `calendar`
- `POST /api/projects/{project_id}/schedule/manual` → `create_manual_assignment`

### `system.py`（5）

- `GET /api/system/backups` → `list_backups`
- `POST /api/system/backups` → `create_system_backup`
- `GET /api/system/backups/{filename}` → `download_backup`
- `DELETE /api/system/backups/{filename}` → `delete_backup`
- `POST /api/system/restore` → `stage_restore`

### `tasks.py`（11）

- `GET /api/projects/{project_id}/modules` → `list_modules`
- `POST /api/projects/{project_id}/tasks/generate` → `generate_tasks`
- `GET /api/projects/{project_id}/tree` → `get_project_tree`
- `GET /api/projects/{project_id}/handover-summary` → `handover_summary`
- `GET /api/projects/{project_id}/tasks/{task_id}/workspace` → `task_workspace`
- `POST /api/projects/{project_id}/tasks` → `create_single_task`
- `PUT /api/projects/{project_id}/tasks/{task_id}` → `update_task`
- `PUT /api/projects/{project_id}/task-targets` → `update_task_targets`
- `POST /api/projects/{project_id}/tasks/{task_id}/deliverables` → `update_task_deliverables`
- `PUT /api/projects/{project_id}/check-items/{cid}` → `update_check_item`
- `GET /api/projects/{project_id}/tasks/{task_id}/reference-docs/{idx}/download` → `download_task_reference_doc`

### `team_templates.py`（5）

- `GET /api/team-templates` → `list_templates`
- `POST /api/team-templates` → `create_template`
- `PUT /api/team-templates/{template_id}` → `update_template`
- `DELETE /api/team-templates/{template_id}` → `delete_template`
- `GET /api/team-templates/roles` → `plan_roles`

### `templates.py`（23）

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

### `users.py`（5）

- `GET /api/users` → `list_users`
- `POST /api/users` → `create_user`
- `PUT /api/users/{user_id}` → `update_user`
- `DELETE /api/users/{user_id}` → `delete_user`
- `GET /api/users/all-active` → `list_active_users`

### `vehicle_lifecycle.py`（7）

- `GET /api/projects/{project_id}/vehicle-units` → `list_units`
- `POST /api/projects/{project_id}/vehicle-units` → `create_unit`
- `GET /api/projects/{project_id}/vehicle-units/{unit_id}` → `get_unit`
- `PUT /api/projects/{project_id}/vehicle-units/{unit_id}` → `update_unit`
- `POST /api/projects/{project_id}/vehicle-units/{unit_id}/events` → `create_event`
- `PUT /api/projects/{project_id}/vehicle-units/{unit_id}/events/{event_id}` → `update_event`
- `POST /api/projects/{project_id}/vehicle-units/{unit_id}/events/{event_id}/schedule` → `schedule_repair`

### `vehicle_types.py`（5）

- `GET /api/vehicle-types` → `list_enabled_vehicle_types`
- `GET /api/vehicle-types/all` → `list_all_vehicle_types`
- `POST /api/vehicle-types` → `create_vehicle_type`
- `PUT /api/vehicle-types/reorder` → `reorder_vehicle_types`
- `PUT /api/vehicle-types/{vehicle_type_id}` → `update_vehicle_type`

### `worker.py`（8）

- `GET /api/worker/today` → `today_tasks`
- `POST /api/worker/reports` → `submit_report`
- `POST /api/worker/reports/adjust` → `adjust_report`
- `POST /api/worker/tasks/{task_id}/complete` → `manual_complete_task`
- `POST /api/worker/tasks/{task_id}/reopen` → `manual_reopen_task`
- `POST /api/worker/sync` → `batch_sync`
- `DELETE /api/worker/reports/{report_id}` → `delete_my_report`
- `GET /api/worker/records` → `my_records`


## 六、本轮实际执行与不可替代项

### 独立观测探针

命令：隔离 API 场景测试，禁用缓存与外部服务

初始策略观测结果：**3 passed**。每条使用隔离临时 SQLite 数据和合成账号/项目，不接触生产，不调用真实外部服务。独立脚本与终端日志保存在当前审查环境临时目录，关键输入/输出已完整转录在 D1–D3，不把临时路径当永久交付物。

- P1：6 blockers、entry_confirmed=false；省略 confirm_warnings 后 status=executing、requires_confirmation=false
- P2：accepted(2026-09-29) + rejected(2026-09-30)；完成操作返回 status=completed
- P3：相同 100% 数据；1 次评估=commissioning、3 次评估=acceptance；撤到 0% 后 1 次回退=pilot

这些“通过”意味着确实复现了待决定行为，不意味着业务规则正确。

### 修复交叉核验

- 归档旁路：先建立有效完成项目，再通过真实交付接口退回必需交付；修复前归档 200，修复后 400 并明确提示必需交付未完成/已退回
- 逐车任务定义往返：车数 3、人工任务目标 17，导出后新建导入仍保留 17；与“修改实际车数才重新计算”的既有语义一致
- 锁中撤权：PM 请求已入站、另一连接撤去其角色能力后，变更集合并现在返回 403
- 留存证据：项目清理后原验收行正确级联删除，原验收备注/身份在独立留存快照中可查，归档校验通过
- 私人日程：仅有私人日程的项目计 blocked=1 保留，另一个可清理项目 purged=1；本人仍能访问该私人事项，不把备注搬入管理员档案
- 迁移连接：真实 init_db 的 FK OFF/ON 使用同一物理连接，两个池连接从 [1,1] 回到 [1,1]；组合清理不再留下孤儿验收行

**最后独立组合：9 passed、0 failed、0 skipped，9.65 秒**。其中 3 条仍是 D1–D3 未改政策的观察，6 条是上述修复的正向验证，不能混称“9 个业务矛盾全部解决”。此前组合确有 7 passed/1 failed；没有忽略它，而是据此进一步定位并修复迁移外键连接泄漏，再完整重跑。永久回归由系统/现场/生命周期测试文件保存。该 9 条不与 104 条已有文件回放合计为全站测试数。

### 本轮定向重放

选择以下已有文件重跑，覆盖主链和容易被遗漏的副链：

`test_e2e_closure.py`、`test_status_flow.py`、`test_readiness_confirmation.py`、`test_round5_scheduler_integrity.py`、`test_project_template_flow.py`、`test_report_forms.py`、`test_io.py`、`test_private_demo.py`、`test_governance_tracking.py`、`test_my_calendar_self_edit.py`、`test_notification_filters.py`、`test_work_workspace.py`。

结果：**104 passed，0 failed，0 skipped，103.08 秒**（Python 3.12，隔离 SQLite，12 个指定文件；存在 1318 条依赖/SQLite datetime 弃用警告）。这是本轮开始快照上的定向回放，不能替代其他人员后续源码修复后的最终全量重跑。

### 前端最终已执行证据（来自前端审查记录）

前端已在收束代码重跑 **80 个测试文件、435 个测试通过**，TypeScript/Vite/PWA 生产构建通过，前后 206 个源码/资源/配置文件哈希未漂移。详细日志与哈希见 [前端审查记录](workflow-round6-browser.md)。这些是组件、路由器与构建证据，真实浏览器仍为 **0 页面、0 旅程、0 截图**。

### 最终发布前应保留的验收边界

1. 全量后端、前端、类型检查、生产构建需针对最终共享代码再运行，不能合计各人的重复子集
2. 浏览器证据应注明使用的桌面/手机视口、账号、日期、网络模式、是否真实 Service Worker；模拟 hook 不是离线现场验收
3. PostgreSQL 真实竞争/死锁、数据库迁移、Docker 更新回滚、NAS 中断恢复必须分别验证；SQLite 通过不覆盖它们
4. 外部 AI/通知服务真实配置、失败/费用/送达与第三方副作用没有本轮实际连接证据
5. 文档补正可以消除错误承诺，不能代替 D1–D8 的产品决策或缺失功能；应按“已修复复测 / 明确保留政策 / 未验证”三类交付
6. 本矩阵覆盖功能清单与关键人类场景，不声称数学证明“每一个可能流程永不出错”。所有并发、角色、生命周期、网络、导入版本的笛卡尔积不可用一个总通过数替代

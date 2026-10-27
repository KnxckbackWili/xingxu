# 管理端全局网页验收与修复清单（2026-10-05）

> 本文引用的 QA 回执描述历史时点，原件已[归档](evidence-archive.md)；当前 v3 操作请从[文档入口](index.md)开始。

## 环境与范围

- 隔离演示环境：`http://localhost:15173`；真实 Chromium 网页操作，TaskSpace 3 / p2。最终生产构建由root在隔离后端 `http://localhost:18000` 实际网页复核。
- 管理员演示账号；浏览器时区 Asia/Shanghai。
- 桌面 1440 × 1000 与手机 390 × 844；未修改生产数据。
- 本文覆盖登录、全站布局、项目列表、人员安排、我的日程、团队日程、物品总览、统计、消息与反馈，以及现场车辆、物品与去向、现场交接。其他项目内业务、系统设置、现场端由其他验收清单覆盖。
- 页面打开与流程闭环分开记录；数据为空、只有单页数据时，不据此宣称分页或大量数据性能已经通过。

原轮次主验收总表为61项实际网页问题；本文原记录UI-01至UI-12及负责或协同的项目/现场问题，末尾已追加UI13–UI16索引，当前主表累计68项。编号与[主验收清单](browser-audit-2026-10-05.md)对应，未将源码候选或专项断言当作网页发现。

## 已复现并修复

|编号|问题与网页证据|原因与修改|网页回归|
|---|---|---|---|
|UI-01|管理员提交反馈后，输入框已清空但下方仍“暂无反馈”；浏览器刷新才出现。证据：`qa-feedback-before.png`。|提交成功后没有重新加载管理列表。现在清除旧状态筛选、回第一页并刷新。|手机端再次提交“UI-01修复回归：管理员反馈立即可见”，无需刷新直接出现，共2条；状态更新“已处理”成功。证据：`qa-feedback-after.png`。|
|UI-02|反馈提交时间显示 `2026/10/4 19:05:30`，浏览器上海当前时间为 `2026-10-05 03:07`，少8小时并跨天。|后端UTC审计时间省略时区，页面按本地解析。统一 `formatDateTime` 把无时区ISO日期时间按UTC解释；日期-only保持日历语义，显式时区保持原语义；反馈列表与详情使用统一格式。|原记录显示 `2026-10-05 03:05`，新记录 `03:07`、状态更新 `03:08` 与浏览器当地时间一致。证据：`qa-feedback-detail-mobile.png`。时区边界测试通过。|
|UI-03|我的日程新增个人临时事项后，日格/详情2条，但页头仍1项、底栏仍1条。证据：`qa-my-schedule-count-before.png`。|页头与底栏只计算项目排程，漏个人事项。统一计算两类日程。|页头、日格、底栏与详情均2；个人事项编辑成功，删除后均回1。证据：`qa-my-schedule-count-after.png`。|
|UI-04|项目卡片模式Tab序列跳过全部正式项目，直接到“删除我的演示”；正式卡片内0个可聚焦元素。“进入项目”仅是文字。|保留整卡鼠标入口，把“进入项目”改为有项目名的原生按钮。表格已有可键盘访问“查看”按钮，经反证无需修改。|聚焦“进入项目：网页验收-业务闭环”后Enter成功进入项目。|
|UI-05|消息中心打开未读问题通知后，列表已读但顶部铃铛仍显示1，直到定时刷新。证据：`qa-messages-mobile-detail.png`。|读操作只更新消息列表本地状态；铃铛操作也未刷新消息中心。成功后发出带来源的共享事件，双方即时刷新，中心忽略自身事件避免双请求；序号防止旧读取覆盖新状态。|新通知打开后已读状态同步；“全部已读”后铃铛即时消失。回归同时有其他代理新通知产生，按实际未读记录核对数量。证据：`qa-messages-immediate-read-after.png`。批量选择2条后未读4→2；铃铛全部已读后中心标题600→400、徽标data-show true→false；切未读为空。反向回归使用隔离库2条受控通知样本，生成通知流程另由现场端实测。|
|UI-06|通知正文显示“严重程度：medium · 上报人：user-worker-001”，泄漏内部枚举/用户ID。|新系统通知生成为中文严重度/姓名；旧系统字段仅按固定前缀/后缀兼容，不替换用户自由文字。|新通知显示“高 · 上报人：现场工程师A”，旧通知显示“中 · 上报人：现场工程师A”；通知日期03:31正确。现场端也确认姓名/严重度。|
|UI-07|手机车辆页面主操作36px、车型配置/问题履历27px、子导航32px；文件页上传/下载/删除亦27px（根代理网页测量）。|项目工作区与全局关键按钮缺少手机触控尺寸。添加仅手机生效的44px最小触控规则，覆盖PM按钮、Select筛选、区域导航、分段选项、搜索、弹窗确认及局部表格翻页。|车辆重新测量主要按钮/导航/履历均44px，页面scrollWidth与innerWidth均390；库存录入/流水入口可正常使用。全局新建项目、进入9张项目卡片、状态/进度筛选、添加日程、提交反馈均网页实测44px，宽度382/390或390/390无横溢；文件页由根代理复核。|
|UI-08|车辆已关闭故障→网页导出生命周期表→原样导入，未关闭数量从0变1；同日期/同标题出现新待处理事件，原已关闭事件仍在。原导出：`qa-vehicle-lifecycle.xlsx`。|去重只识别具有import_key的导入事件，遗漏手工录入事件。现在同时按项目/车辆/日期/标题匹配全部现有问题，保留原故障的关闭状态、维修与验证内容。|网页新建QA-UI-002已关闭故障→导出→连续原样导入，都新增0/跳过重复3，仍0未关闭，该车仅1条已关闭记录且验证保留。证据：`qa-vehicle-lifecycle-after.xlsx`、`qa-vehicle-lifecycle-after-mobile.png`。首次复现产生的QA副本已关闭，保留取证，不删除原记录。|
|UI-09|物品列表提供“物品分类”筛选，显示“未填写编号和规格”，但新建/编辑弹窗均没有分类、编号、规格输入；手工建工具只能归“其他”。|表单只保留少量字段，其余后端已支持的字段固定沿用旧值。增设可选折叠信息区，包含分类/编号/规格/序列号/管理方式/来源/到场与归还日期/库存关注数量，常用字段仍直接可见。|网页编辑QA测距仪为工具，编号QA-TOOL-001、规格QA-LDM-100、关注数量1；工具筛选可找到记录；领用后余1触发“需要关注1”。再次打开编辑核对到场/预计归还日期、分类编号规格与最低库存已持久化。|
|UI-10|上海03:47建立物品，历史初始盘点却显示10-04 19:47，发生时间框为10-05 03:49，少8小时。|初始流水UTC，手工流水提交无时区本地字符串，混合存储/解析。新网页提交ISO时间点，后端aware输入转换UTC naive并记录nullable time_basis。无标记旧服务端盘点/数量调整按确定的UTC来源显示；旧人工无时区保留原墙钟并标“旧记录未注明时区”，不猜测迁移。SQLite/PG共享补列不设SQL默认，JSON导出导入保留来源及aware归一化；不同basis同UUID重试拒绝。历史按展示时刻排序，避免混合旧值挤到最前。|原盘点显示10-05 03:47，新领用流水显示10-05 03:51，与填写时间一致；排序新→旧，结余由2→1。后端等价+08/Z重试仅扣一次。隔离旧NULL fixture：原手工03:10仍显示03:10并提示来源；原UTC盘点19:00显示上海03:00；实际新网页流水04:24显示正确，顺序04:24→03:10→03:00。证据：qa-inventory-time-browser-evidence.txt。受控样本只写隔离库，未猜测修改生产历史。|
|UI-11|现场端问题指派/重开通知“前往处理”跳今日页，未打开对应问题；交付审核同样缺少任务上下文。现场端代理真实网页复现。|共享导航全部现场角色走今日页兜底，遗漏entity_id。issue_*进入问题页并聚焦ID；交付通知进入可见项目并聚焦任务的交付页签；补齐中文类型标签。|现场端代理网页：重开通知进入worker/issues?issue_id并自动打开原问题；审核通知进入worker/projects/:id?task_id&tab=deliverables，自动打开“设备开箱照片已通过”。页内解析由现场端代理补齐，详见其清单。|
|UI-12|root实际网页选择月报后，报告类型combobox的辅助名称仍为“周报”；已核对实际outerHTML。|报告类型Select没有显式固定label；App安装的a11y兜底首次用选中项“周报”赋aria-label，后续已有label即跳过，因此切月报仍保留旧名称。补aria-label="报告类型"；不改类型选择、业务请求或全局命名策略，已确认不是ego写入属性。|既有ReportPage6项、TypeScript与差异格式检查通过。root最新生产index-DlYd9NZL.js在390深色实际聚焦报告类型，ArrowDown/Enter选择月报，日期/月报标题正确，DOM辅助名称始终“报告类型”，body宽390。[修复前](evidence-archive.md "原路径：docs/qa-report-type-keyboard-before.txt；SHA256：1c3e74e815fc2adfcb1262552aa6717be741b60fa214a33dc89df0967ce813a7")、[修复后](evidence-archive.md "原路径：docs/qa-report-type-keyboard-after.txt；SHA256：3f7ff5c827ef24c2d01b77a185dda66ed8a4c6722a0a5426bbf50a9681f3a585")。|

## 已完成的真实网页检查

|区域|完成操作与结果|限制|
|---|---|---|
|登录|空表单显示用户名/密码缺项；错误用户名密码保持登录页并提示错误；手机布局无横向溢出；管理员会话可复用。|记住登录状态长期过期未等待真实时长。|
|全局布局|手机导航Drawer打开，能进入现场资产；桌面侧栏展开/收起；主题切换及恢复；区域页签可达；反馈Drawer手机满宽；页面横向滚动宽度核查。|未以色彩喜好重设计。|
|项目列表|卡片/表格切换并记住选择；搜索不存在项目显示清空筛选入口，清空恢复2项目；表格“查看”可聚焦；卡片键盘进入修复。|初始2项目，最终回归9张手机卡片；没有足够数据验证大数据分页性能。|
|人员安排|默认人员日程能看到主项目7条排程；新增“UI全局回归-临时现场核查”给管理员并下达；在本人/团队日程均同步且锁定；人员看板手机卡片无页面横溢。|该现场工作保留在隔离主测试项目中供跨模块核验。|
|人员不可用|手机：登记PM未来一天不可用→看板近期安排出现→管理时段编辑原因→确认取消→时段消失。|测试记录已清理。|
|我的日程|手机：新增个人事项（归属项目）→当天详情出现→编辑标题→删除确认→计数及详情更新；管理员现场工作锁定展示。|未修改他人的项目任务。|
|团队日程|手机日格打开当天详情：工程师A任务、管理员新增工作、下达/锁定/计划/完成/备注均展示。|只读页面无编辑入口，符合范围。|
|统计|手机四页签可切换，7天趋势刷新，真实1条填报显示完成量1/样本1/估算8h，任务效率搜索无结果/清空恢复。|仅单项目、单填报样本，不将图表展示视为统计全部数学边界验收。|
|物品总览|先验空态，演示生成后2物品；不存在物品搜索为空，清空恢复；桌面项目链接进入对应项目物品页；手机卡片有归属/分类/状态/位置/保管人。正式项目工具新建/分类/领用/低库存已网页验证。|已验证超量拦截、领用、退回现场、整体归还物主、重新收货：2→1→2→0→2，状态在现场→已归还→在现场、关注1→0正确。|
|消息|真实新/旧问题通知列表与详情、类型中文/姓名/严重度、时间、全部已读与铃铛同步；现场通知准确问题/交付跳转由现场端代理回归。|批量和铃铛反向已读同步已网页通过，未等待轮询。|
|反馈|新增→即时列表→详情→状态改已处理；手机表格可局部横滚，详情满宽且无页面横溢。|系统反馈审计日志需全局审计入口再核验。|
|现场车辆|手机批量建QA-UI-001/002→记录故障与位置→给管理员下达1h维修→工作详情执行1/1→维修验证→关闭；返回台账正常/0遗留。导出下载及重复导入闭环。|QA记录保留；未清除原记录。|
|现场物品|手机建立测距仪2台→编辑分类/编号/规格/日期/关注数量→工具筛选；超量领用3台被拦截且库存不变；领用1台后余1，剩余库存位置/保管人不被发放去向覆盖；初始/新流水本地时间正确。|退回/归还/再次收货闭环已通过；QA申请新建已批准→Word导出下载→重新导入字段一致（导入按待审批规则）→编辑标题/备注保存。保留QA记录，不清除原记录。|
|现场交接|手机新建主联系人、保存入场手续/劳保/安全/车辆/网络/备注→整页刷新回读6字段；桌面编辑联系人电话/职责→删除确认→空态恢复。交接摘要真实展示19未完工作、3问题、0车辆故障、6待验收资料。|仅删除本次QA联系人；原进场安排由后端合并保留。|

## 自动化补充验证

- `TZ=Asia/Shanghai npm test -- src/pages/FeedbackPage.test.tsx src/utils/date.test.ts`：2文件，8测试通过。
- 日期工具检查面：通知、通知铃、项目审计、附件上传、准备评审/确认、验收录入时间均来自后端 `utcnow()`；纯验收日期等日期-only不改。
- 前端反馈/日期/铃铛/通知导航focused：4文件25测试通过；后续库存/通知导航focused：2文件19测试通过。
- 最新前端 Messages/Bell/Inventory 3文件19通过；Bell补充失败读操作与读取并发的Spinner回归5项通过。
- 后端消息/问题分类：14通过；生命周期表导入导出：25通过（含手工已关闭事件反复导出导入不重建）；库存：6通过（含等价时区重试不重复扣减、NULL旧数据兼容、basis语义冲突409）；独立迁移/库存/IO合计30通过，含SQLite真旧表、PG补列mock、+08/Z/-04 JSON归一化。没有连接真实生产PG。

## 截图索引

- `qa-login-mobile.png`、`qa-dashboard-empty-mobile.png`、`qa-dashboard-mobile.png`
- `qa-project-list-mobile.png`、`qa-project-list-desktop.png`
- `qa-people-overview-mobile.png`、`qa-my-schedule-mobile.png`、`qa-team-schedule-mobile.png`
- `qa-my-schedule-count-before.png`、`qa-my-schedule-count-after.png`
- `qa-stats-mobile.png`、`qa-inventory-desktop.png`、`qa-mobile-global-nav.png`、`qa-messages-dark-mobile.png`
- `qa-feedback-before.png`、`qa-feedback-after.png`、`qa-feedback-detail-mobile.png`

## 可复核下载与文本证据

- qa-item-application.docx：网页真实导出后作为网页导入回读样本。
- qa-inventory-time-browser-evidence.txt：旧NULL墙钟/旧盘点UTC/新网页UTC同屏及排序的真实网页语义快照。截图工具在此轮Page.captureScreenshot超时，保留成功语义证据，未伪造截图。

验收数据说明：修复迭代中，QA测距仪4笔人工流水已由新网页以ISO UTC提交，但当时尚未增加time_basis列。隔离库依据该轮已记录的实际输入为这4笔补充UTC来源标记；没有按时间差猜测任何历史或生产记录。旧NULL兼容样本仍保持NULL，以验证旧人工墙钟保留。

## 发布只读验证（2.1.2）

- 本机Docker CLI 29.8.1的Compose软链指向已不存在的OrbStack.app，原检查失败属于工具环境，不是Compose文件错误。未修改机器配置或仓库发布脚本。
- 官方来源：[Docker Compose文档](https://docs.docker.com/compose/install/standalone/)、[docker/compose v5.6.0发布页](https://github.com/docker/compose/releases/tag/v5.6.0)。临时darwin-aarch64资产放在 `/tmp/agv-release-compose-v5.6.0/cli-plugins/docker-compose`。执行前SHA256同时匹配官方资产 `.sha256` 与GitHub API asset digest：`bd714a42b46e51757fc1121085b3096b9064e3f80d3ca5a991e33f44df4f43c9`。
- 原样执行 `DOCKER_CONFIG=/tmp/agv-release-compose-v5.6.0 FAST=1 bash docker/scripts/release-check.sh`，退出0并返回 `Release checks passed for v2.1.2`。临时DOCKER_CONFIG仅作用于本次命令。
- 基线 `.env.example` + `docker/docker-compose.yml`，正式 `docker/.env.example` + `docker/docker-compose.multica.yml`，演练 `docker/.env.example` + `docker/docker-compose.drill.yml` 分别执行相同 `docker compose --env-file ... -f ... config --quiet`，全部退出0。只解析配置，不连接生产或启动容器。
- JSON精确核对frontend package、lock顶层、lock根包、backend APP_VERSION默认、Dockerfile ARG均2.1.2；主Compose与两个变体默认版本也已统一2.1.2。登录页从frontend/version.ts读取package版本。
- docker/scripts及docker目录共14个shell脚本逐文件执行 `bash -n`，全部通过；`git diff --check`通过。
- FAST验证覆盖版本、差异格式、脚本语法与Compose解析，未以此宣称Docker镜像构建、实际容器启动、生产PG、现场硬件或网络部署通过。前后端完整测试、生产构建和依赖审计由主验收报告记录。


## 最终网页闭环补充：P01 / P04 / P12

全部步骤使用同一TaskSpace 3的p2，独占串行执行。localhost管理员与pm.localhost项目经理保持各自会话；仅新建隔离副本，主业务项目未改动，已归档收尾项目仅只读查看。

|问题|真实网页步骤与最终结果|隔离样本与证据|
|---|---|---|
|P04 两个JSON复用入口|项目列表快捷导入与项目内导入均上传原始现场实施JSON：原样预检拒绝，确认创建按钮禁用；明确“按草稿重新预检”后提示新项目从草稿开始并重新验证通过。分别取消后整页刷新，项目数保持8和9不变；损坏JSON在两个入口均拒绝，不创建。随后分别重选原文件、重新预检、确认创建，两个独立新项目网页读回草稿及20项任务。快捷入口损坏JSON原误提示网络异常，已改为有效JSON格式说明，网页回归通过。|快捷导入新草稿 `bc1bb5cd-2c2d-4afc-bd23-08cbe6c7cc31`；项目内导入新草稿 `abcb70aa-57b7-479d-9e41-54b066f7ab98`。 [完整网页语义证据](evidence-archive.md "原路径：docs/qa-import-schedule-final-evidence.txt；SHA256：57a496f4ee93eee4026e6450cadc2fa8e74198477fa7232cc8917c16728c9bc4")。|
|P04 网页克隆|在第二份新草稿的导出页实际打开克隆表单，填写新名称及10/05—10/06周期并确认；整页刷新读回独立草稿、20项任务、0%进度、无日程。项目列表搜索读回填写的周期，原副本未修改。|`QA-P04-网页克隆完整副本`：`e37c420e-7bf0-4ad4-87a0-82bee6fb70fc`，同上证据。|
|P01 超周期下达|新建10/05单日项目，网页方案显示17项标准工作。两个培训目标未填时仅生成15条；在本隔离项目网页补两个培训目标各1人，重新预检明确15→17并生成17条至10/21。整页刷新仍显示16条超期提醒及0下达。390px手机点击确认并下达再次弹出超周期核对，返回调整取消，刷新仍17条/0下达；再次明确继续后17条全下达，整页刷新读回17/17且超期提醒仍在，周期仍10/05单日。Popover门户原27px按钮已并入UI07触控规则，实际回归两个按钮44px、页面scrollWidth390。|`QA-P01-单日超期下达复核`：`83a17ac4-1808-4638-837d-dd8b03284579`，17任务及17条下达记录保留；同上证据。|
|P12 未登录深链丢失目标|root先实际复现PM退出后报告深链只到/login、登录回dashboard。ProtectedRoute现在把pathname/search/hash一并编码进next，登录页保留既有角色与无权守卫，并拒绝反斜杠/控制字符危险目标。实际PM退出→带qa查询和main-content片段报告深链→登录，完整回原报告URL。再退出→备份管理深链→PM登录，仍在同一query/hash目标显示403。另危险反斜杠next实际登录返回同源PM工作台，没有离站。|[登录回跳/403/危险next网页语义证据](evidence-archive.md "原路径：docs/qa-login-next-final-evidence.txt；SHA256：5de84ca4c30601e7f5ca0b8988f3bdc76ed98d2721c4cd7e19f611c970ad18ee")。|

原备份 `/Users/knxckbackwili/Documents/agvm/audit-artifacts/project.json` 验收前后SHA256均为 `500a3e3860cc34f7ca5c65936ef3e9b597d99ec2fbac13cee3cf08276b8fcbaa`，JSON源状态仍 `executing`，20项任务没有手工编辑；两个草稿副本转换只用于导入请求。初始8个项目，最终12个，新增恰为两个导入、一克隆、一单日排程项目。

补充专项：App/LoginPage/ProjectListPage共3文件31项通过，覆盖深链path/query/hash保留、登录后角色边界、内部next、外域/反斜杠/控制字符/登录回圈拒绝、损坏JSON不请求导入API；TypeScript与差异格式检查通过。手机排版采用实际DOM尺寸与成功语义快照；本轮ego的Page.captureScreenshot再次超时，没有声称生成截图。

P14已归档复盘查看：收尾项目overview“查看项目复盘→”实际跳archive后只见验收/历史记录，未显示已保存复盘，[修复前网页证据](evidence-archive.md "原路径：docs/qa-archive-retrospective-before.txt；SHA256：475fcd75fe2bbdb36d92894d1b79846cdd79012b38f99c35a91a2e8d43e57909")。runtime补有权项目详情DTO与只读复盘卡片，主清单已实际通过管理员入口/刷新及worker手机成员回读：原完整内容、作者系统管理员、当地05:58保留，13项归档checkbox仍禁用。[成员最终网页证据](evidence-archive.md "原路径：docs/qa-worker-demo-progress-after.txt；SHA256：345c0dfba8c179fc68e9e7d8aecf2577118f58e8b7b34a223078bc9e4fb87057")。我独立源码复核确认可见性检查在返回前、列表/克隆不带复盘、旧结构和缺失作者安全回退，未扩大写入权限。

## 最后同族修复与串行网页复核

此轮由root/现场端代理在各自独占网页窗口复现并回归，我负责下列源码与专项验证，未并行操作浏览器。

|编号|网页发现及最小修复|真实网页回归与证据|
|---|---|---|
|W15 今日页迟到保存覆盖新项目|个人演示保存的成功响应被受控延迟后，SPA切到正式今日页；释放旧响应会把正式开箱1台、线缆2米替换成演示提示/任务。以项目与账号变化的scope generation隔离读取、保存、检查项迟到响应；A→B→A也属于新scope。旧操作仍释放业务锁，但不清除新草稿、不启动旧查询、不覆盖新状态。|现场端代理重复相同“演示保存hold200→SPA正式两行→release”步骤后仍保留正式URL及两项正式工作，无演示提示；练习新增报工已网页撤回。[修复前](evidence-archive.md "原路径：docs/qa-worker-today-race-before.txt；SHA256：39b748479e7857b3bb8203780d10fb6cdec1123a847b89402d4f916d466739f0")、[修复后](evidence-archive.md "原路径：docs/qa-worker-today-race-after.txt；SHA256：21d3fdda8dbc7628d537a2bd323b3378cba99a4546aa35c038318fc64e38264f")。Today专项26项通过，包含晚到读取、A→B→A、检查项成功/409、卸载后响应。|
|W16 账户菜单键盘与弹窗回焦|PM与现场端账户按钮默认仅hover打开，Enter/Space不能访问。改为原生button点击触发、controlled open及aria状态，Escape关闭并回焦。root继续网页发现密码Modal关闭后焦点落BODY，因此增加可选afterClose，并在真实关闭动画之后回焦账户按钮；密码/会话/离线退出原规则保留。|root实际PM Enter/Space打开、菜单Escape回焦；密码Escape关闭后回焦账户。现场端密码Escape与取消均实际回焦。原始红证：[PM](evidence-archive.md "原路径：docs/qa-pm-account-keyboard-before.txt；SHA256：e5a56f942e7d85c2f6ece742ce1747cfaae15fe7eaaa5051c9d1a7edaddd02ad")、[现场端](evidence-archive.md "原路径：docs/qa-worker-account-keyboard-before.txt；SHA256：64ac627d08fcd7f71fecfa4aaaec7bd98118e250750de3335112071845950eda")。真实AntD Modal的PM/现场 × Escape/取消4项与菜单3项，共3文件7项通过；jsdom只模拟动画完成事件，最终原生键盘结果以root网页复核为准。|
|P15 项目历史系统枚举裸显|变更记录裸显问题状态resolved/processing/closed、严重度low、物品流水transfer/receive等。formatAuditDetail只整条匹配3种系统固定格式与已知枚举；标题、物品名称中的英文及自由文本/未知格式原样，审计存储不改。HistoryPage与概况最近动态共用。|root实际/history展开46条、/activity及最近动态均显示状态中文、严重度低/中与物品收货/转移/归还/退回/领用中文。[修复前](evidence-archive.md "原路径：docs/qa-project-history-final.txt；SHA256：2ba8896a2d6d270acdb179fbad83fcf4d8acdd83659952c67aa19dc2431bedc3")、[修复后](evidence-archive.md "原路径：docs/qa-project-history-after.txt；SHA256：3b5a258ee30b46dedd9120f53c90b9f92bbaa42a09ffc60be405189bbbd03251")。固定格式/自由文本边界与两页集成3文件49项通过；TypeScript与差异格式检查通过。|
|P16 项目设置未保存内容丢失|原说明输入后路由离开无提示；另同页切协管并实际授权会触发父重载而丢失未保存说明。基本信息与未提交协管选择统一计脏；路由与受控内部Tabs提供留守/明确放弃，放弃实际恢复已保存信息、重置协管选择。成功落库后清脏、失败保留；保存期间基本字段/Tabs禁用并防重复提交。路由确认接管已有Tab确认，旧决策失效。|coverage实际URL留/弃/保存后离开、内部Tab留守/放弃、协管未提交选择重置均绿；再次实际授权/撤销后说明保留已保存QA值。[原路由红证](evidence-archive.md "原路径：docs/qa-admin-project-unsaved-before.txt；SHA256：8c5557d83a8836f3f1a51e3afe40420116c5e4d953cc1850210174f31115f94a")、[同页重载红证](evidence-archive.md "原路径：docs/qa-admin-project-unsaved-tab-before.txt；SHA256：eec9897a9eadbb9ee919231af82d423cf75e83538b0d435083ba2a65d1c95fdc")、[最终网页回归](evidence-archive.md "原路径：docs/qa-admin-project-unsaved-after.txt；SHA256：a9557d36c9bafc91b4f7ceaa51108eef6197a563e3ab63abee0085076421b8cb")。Edit/hook/Startup3文件24项与TypeScript/差异格式通过。单组件同项目回填保护不被宣称跨父卸载保留。|
|P17 总览卡片混合物理单位|最后生产构建实测主项目10%旁仍显示无单位4/40。后端透出已有quantities_by_unit，桌面/手机两处经formatQuantities按单位显示；旧DTO缺字段明确提示，不猜单位。数量另起可换行一行，原百分比/legacy字段/项目范围不改。|root以最新生产index-BMpNQYt4.js实际1440桌面及390浅/深回归：仍10%，数量分别1/18台、1/8项、0/4人、2/10米，body宽390无整页溢出。[修复前](evidence-archive.md "原路径：docs/qa-dashboard-quantity-before.txt；SHA256：986a1b65b50bde9deb98ec76e65342e59c009fc712ab40c8271798a5b0fcfb66")、[修复后](evidence-archive.md "原路径：docs/qa-dashboard-quantity-after.txt；SHA256：c2964f2d69d96bfd9a13fc9212c0ed0a5b2fb10d23bde4fea6921772d0807c90")。前端双端混单位/旧DTO/空数组与既有Dashboard、quantities共2文件17项通过；后端Dashboard9项通过，含新增混单位/空项目/负修正/既有percent与scope兼容。|
|P18 推荐归档包遗漏验收与复盘|root实际下载归档ZIP确认只含原JSON、15Sheet Excel及附件，没有已保存验收结论和复盘。runtime负责只读归档记录JSON/HTML；导出页说明增加“归档记录（验收与复盘）”，原13+2Sheet说明及导入/克隆政策不改。|root最新网页实际下载29850B ZIP：完整5份归档记录/13项验收清单、2PDF附件字节精确一致，原项目JSON不变；HTML手机body390、桌面body1000，无整页溢出，23个历史详情默认折叠；摘要、JSON及PDF真实链接可用。[修复前](evidence-archive.md "原路径：docs/qa-archive-package-evidence-before.txt；SHA256：96e02143f6fbe084536cd2ace95b6f0feafcf45998f61c8dce472ec5fe9b629a")、[包内容复核](evidence-archive.md "原路径：docs/qa-archive-package-evidence-after.txt；SHA256：8fc7cd6bea6a097e5d13cc96a379541bad9055ee6dfe68bea39604e0ac8e99f5")、[HTML网页](evidence-archive.md "原路径：docs/qa-archive-package-html-after.txt；SHA256：b51dff8fec7d4839806dbe6c967ae58a70e69e22378214be86d23ff0f4822590")、[详情与链接](evidence-archive.md "原路径：docs/qa-archive-package-details-after.txt；SHA256：1bd742659bd258977b5924913d8be3ba567b61ec5d07a34863eff02c2d082abc")。ExportPage既有4项及后端IO19+sidecar7共26项通过；TypeScript与差异格式检查通过。|
|P19 甘特图PDF打印混入操作且内容截断|root实际从导出入口横向打印两页，项目操作/筛选/密度控件进入PDF，长维修名称截断、续页缺日期表头。保留原屏幕甘特图，增加打印专用HTML表格：完整名称、项目周期/排程范围/筛选说明、人员/状态、按日期比例的时间条与图例；thead重复、任务行不拆、named page局部A4横向及白底打印规则，报告P13规则不改。|Gantt/Schedule2文件16项通过，覆盖跨年范围、同名不同ID、含首尾日期的条长/偏移、长名称、取消/今日标记、最多7个均匀刻度保留首末、真实零日程保留生成入口、list/calendar/error不套打印空态及屏幕任务入口/密度控制；TypeScript与差异格式检查通过。root生产index-BxjRxsUi.js最终实测桌面与390深色PDF各547240B/3页，全部逐页渲染目视通过：20工作齐全、长名称完整、每页项目/日期轴/图例重复、7刻度清楚、白底无控件、任务行不拆。真实空日程PDF95684B/1页同样完整且原屏幕空态保留。[最终打印网页证据](evidence-archive.md "原路径：docs/qa-gantt-print-after.txt；SHA256：0885baf314c5dae94b0e56891e190f04f75d5011a4eefc5c7460520733f50540")。同包手机深色报告两页亦由root逐页确认，P13打印未受干扰。|

ADMIN09同族：Edit技术负责人/协管选项和已有协管表格改用共享ROLE_NAME，旧技术角色显示“技术工程师（旧）”，未知角色保留原码；原候选过滤与创建政策不变。coverage同窗口实际下拉已中文回归，专项同时覆盖未知码fallback。

前61项冻结轮次前端全量由root执行：91文件634项通过（63.53秒），生产构建成功，PWA预缓存147项/2299.04KiB，入口index-DlYd9NZL.js。上一轮首个ProjectList真实AntD竞态测试只有整体5秒预算超时，无断言失败；未改源码定向9项通过，随后仅该测试局部放宽15秒、保留全部断言，最终全量通过。该历史轮次后端全量由root实际执行：1,264项通过（706.19秒），保留16,499条既有弃用/警告输出，不声称零警告；此前1,254项全量与Dashboard9项、IO/归档26项均为历史独立验证，未将专项数量合并充作全量。真实生产路由与最终发布证据以主验收报告为准。

## 追加网页体验问题索引 UI13–UI16（主清单累计68项）

保留上述UI01–UI12与前61项轮次记录；追加实际网页问题和修复索引如下，不改写原证据。当前完整问题总数为68（P22/UI16/Worker18/Admin12），已登记步骤均网页回归通过，未执行组合仍以覆盖矩阵partial为准。

| 编号 | 实际网页前后与边界 | 证据 |
|---|---|---|
| UI13 | 采购值采购中、辅助名仍已到货；安排切已有任务辅助名仍现场新增工作。修后显式用途名称及Form.Item稳定关联：采购到货状态和项目/安排什么工作/任务/安排给谁均真实回读，实际系统管理员姓名正确。 | [字段名称前后](evidence-archive.md "原路径：docs/qa-followup-form-and-preparation.txt；SHA256：4e2c7b74eec49143ba06db57dd61c90d0d658286e3aca3a22ede6f4a4b74f864")、[主清单](browser-audit-2026-10-05.md) |
| UI14 | 无写权限PM原准备表缺客户/项目团队等责任方；修后责任与跟进只读可见，桌面与390实际读取，未扩大写权限。 | [字段前后](evidence-archive.md "原路径：docs/qa-followup-form-and-preparation.txt；SHA256：4e2c7b74eec49143ba06db57dd61c90d0d658286e3aca3a22ede6f4a4b74f864")、[手机只读](evidence-archive.md "原路径：docs/qa-followup-preparation-readonly-mobile.png；SHA256：e00ca7fcbc725cad794f88f972363e204f158a7c1312636e4639ea062cc8920f") |
| UI15 | 固定项目字段快照曾显示UUID、草稿给可提交入口。新草稿实际可辨名称、项目用途label、保存并下达disabled；前往概况实际显示开始准备。 | [固定项目/草稿入口](evidence-archive.md "原路径：docs/qa-followup-form-and-preparation.txt；SHA256：4e2c7b74eec49143ba06db57dd61c90d0d658286e3aca3a22ede6f4a4b74f864") |
| UI16 | 同工作/执行人/日期重复提交新数量或工时/备注，后台保留旧条但前端原误绿色成功并关闭。manual/repair返回created布尔，false明示已有与本次未修改、保留弹窗输入。普通计划1与维修6h两入口实绿；取消刷新原单条/原计划量/备注保持，无假保存。 | [两入口重复安排实证](evidence-archive.md "原路径：docs/qa-followup-form-and-preparation.txt；SHA256：4e2c7b74eec49143ba06db57dd61c90d0d658286e3aca3a22ede6f4a4b74f864") |

补充专项按实际轮次分别记录，不相加成全量：UI13/15 WorkAssignment+a11y29项及tsc通过；UI16相关6文件46项及tsc通过；Archive/Inventory/WorkContext3文件24项在当地与UTC均通过。root最后Node22.23.3/TZ=UTC完整93文件657项通过（214.07秒），index-D9e42gYi.js类型与构建通过。后端业务保护全量1318项通过，之后仅两个DTO字段由4项契约覆盖，完整先后边界见[最终验证](evidence-archive.md "原路径：docs/qa-final-validation.txt；SHA256：80a89ee8c819dacb854118e29395343668e19067564de7cc99813a929cb840a6")。真实Docker/PG网页成品已建项/下达/保存/导出/重启/退出重登录验证，1440桌面及390浅深截图实际逐张查看；不把旧20/24/18入口遍历写成新产物全量再巡检。

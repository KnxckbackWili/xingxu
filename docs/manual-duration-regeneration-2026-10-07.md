# 2.1.4 人工工期与后续重排修复

> 本文引用的 QA 回执描述历史时点，原件已[归档](evidence-archive.md)；当前 v3 操作请从[文档入口](index.md)开始。

本轮处理用户实际遇到的 **DUR-01：缩短任务工期并保存后，重新排程又恢复较长工期**。2.1.3 的验收与交付记录保留为历史轮次；本页只说明本轮修复及其证据。最终产品源码为 `d0dfeb443d530715f0edcbedcc2b68aa4c90b03d`。下列16个验收范围均完成实际网页回归，[61份公开证据](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/validation-summary.json；SHA256：ac35eb514e6f949d913c222ad4d1d943abb9d70ef0e5f705a1f12b5166040e14")包含49份本轮网页记录、2份源码/验收摘要及10份PG、镜像与清理回执。前端完整测试、后端“全量基线＋最终IO回归”、本机 PostgreSQL 升级重启与实际网页读回均已通过。[源码与测试证明](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/source-validation-summary.json；SHA256：ca0a216ad1935a1623cd3e58b7ebbaadd7e5c17672da57c8625c5cd8fc0ad8d9")。

## 问题与规则

修复前，真实网页把“QA-工期保持-20项”从10天缩为2天，保存后再次生成仍恢复10天；独立 API 跨调用测试也复现目标10、自动估算5天，缩为2天后普通重排、逾期重排和受阻重排都恢复5天。原日期调整只修改日程条目，后续排程仍从目标数量与单位工时重新计算；本次估算倍率也没有作为项目偏好持久保存。

现在项目倍率与任务人工工期分别保存。自动任务采用项目保存的倍率；人工任务采用已确认的工作日预算，不再次乘项目倍率。调整起止跨度并确认会保存人工预算；整体平移只移动日期，不重写预算。恢复自动估算需要先预览再确认，取消预览保留原设置。确认自动后保存停用记录，旧审计中的人工工期不会再次复活。

“工作日”指项目休息规则下的预算天数，区别于首末日期的日历跨度、日程行数和实际有安排的日期数。同日多人或重复安排不会增加预算天数。数量按0.01精度分配，多日人工预算至少需要0.02基准数量，避免迁移了不可覆盖起止日期的预算。目标数量变化按原基准比例计算剩余工期；单位改变后，旧比例不再适用，必须重新确认人工工期或恢复自动估算。

既有已报工、已下达、锁定或不可重排安排仍由原保护规则保留，修复没有用自动锁定来阻止重排。新增的“仅取消人工工期”入口可用于已有执行记录或单位变化的任务，取消的是后续估算偏好，已有日程和报工不改。实际网页已验证预览、取消、确认及后续普通重排；确认前后6条日程和1条报工记录的行哈希完全一致，哈希为数据保全的补充证据，没有替代网页操作。

## 旧记录与复制边界

旧版本没有保存伸缩模式。仅当旧审计可明确证明跨度变化、且工作日期及单位/休息规则证据足够时，恢复对应人工预算；相同跨度的旧记录可能只是平移，日期稀疏、单位或休息规则发生后续变化等情况不猜测人工意图，并显示核对提示。预览或导出读取恢复结果不会写库；新确认记录带明确模式、工作日数、数量和单位基准。

完整项目 JSON 新增 `planning_schedule`，保留倍率及每项任务的人工预算或明确自动状态。导入及克隆映射到新任务，复制计划偏好；不复制偏好的旧作者、版本或来源审计身份，不新增执行确认、锁定或成员权限。克隆仍无旧日程和报工，从模板新建仍为自动估算。旧 JSON 缺少该字段时兼容为自动倍率1。活跃预算必须与对应任务单位一致；停用记录保留明确自动含义，不因历史基准单位不同而重新启用。

导入先检查任务来源ID、唯一性、字段类型、有限数值、范围、数量精度及多日最低数量，再创建任何项目。无效组合拒绝且不留下部分项目。系统完整备份按数据库原有备份机制包含新增策略表；本轮实际 PostgreSQL 升级只新增两张策略表，旧54表和61个原文件保全。没有把升级前私有备份及登录配置放入公开证据或交付包，也没有将本轮升级称为新版本完整备份恢复实测。

## 实际网页回归

下表均为本机隔离验收样本的浏览器操作。标为通过的行有真实保存或取消及读回证据；服务测试和源码检查不替代网页操作。

| 范围 | 实际结果 | 证据 |
|---|---|---|
| DUR-01 原问题 | 修复前10天→2天保存→重新排程恢复10天，已复现 | [保存2天](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-before-short-saved.txt；SHA256：c11c75698487217abe2b5f611dc936cb151c5d5e3e7fea72f57ec89564786faa") / [重新变长](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-before-reproduced.json；SHA256：9c3edecc4f834198b3604b213d0a306e3049a5ba85842f398895b12bdb0254df") |
| 可靠旧审计恢复 | 网页通过：普通预览、生成、刷新及再次生成保持10/15—10/16两天；37条日程、35条已下达 | [恢复读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-legacy-recovery-green.json；SHA256：968cfb55be0bca8da7588b15757c6d2b4dfa437e95ef00ef3652ac949e183404") / [再次生成](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-legacy-repeat-green.json；SHA256：6a5a6846722bfbbacb9889e839b75d049f9a9de6dd807151be9dcc9f802e8161") |
| 新伸缩确认后普通重排 | 网页通过：新确认2天，重新生成仍10/15—10/16 | [伸缩预览](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-fresh-resize-preview.txt；SHA256：dc20b7d558035d41aa34d1931072459ce11b3ae039b4c9feecda3ec17f795ca6") / [重排读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-fresh-resize-regenerate-green.json；SHA256：15b3786e9cc1187ba31bc3f67a16dcb7b0d3fbf5013eb87430e80bf7ab943814") |
| 逾期重排 | 网页通过：10/25起重排仍2天，为10/25—10/26 | [预览](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-overdue-preview.txt；SHA256：72e186720eca9041da263533e93e89c57db8055237a7f356f38d9742692674f9") / [保存读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-overdue-reschedule-green.json；SHA256：90349984aaedffa6e5c7e62fca50a4e6b337a53db47db51d022640713ba0127b") |
| 目标数量变化 | 网页通过：20→40后按原预算比例排4天，改回20后恢复2天 | [数量翻倍](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-quantity-double-green.json；SHA256：52fca593aaf21bd113fb6102840510d146eb5e7fab236baea12af69380a92cbe") / [恢复数量](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-quantity-restored-green.json；SHA256：15b3786e9cc1187ba31bc3f67a16dcb7b0d3fbf5013eb87430e80bf7ab943814") |
| 项目倍率保存及取消 | 网页通过：0.50刷新保持，人工2天没有叠乘；改2倍预览后取消仍0.50及2天 | [刷新读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-scale-reload-green.json；SHA256：bcc9872db948691b0a4dbd7a89cde69a4a53d062d3733fe1743006f3480e18a4") / [取消读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-scale-cancel-green.json；SHA256：e34af1e468893ade99a8f90e15d36c9405194f9349087451cc376758a3389a0e") |
| 日期窗口恢复自动 | 网页通过：预览取消仍2天，明确确认恢复自动后排5天，普通重排仍5天 | [取消](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-auto-reset-cancel-green.json；SHA256：576dec9f256a80f66a019477c3d6021d9f06e4407de56fcd28ba62188b166337") / [确认](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-auto-reset-save-green.json；SHA256：f76f1a43b5bb1c841c2b19a74c6629ecd5c039f7170f88607d14e72cc3b2e8a7") / [再次重排](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-auto-regenerate-green.json；SHA256：7fc577e5f7dbd6ec807185b9589adc1e802650c45af219bf44c0c22beb129838") |
| JSON完整计划迁移 | 网页通过：3工作日、基准20、倍率0.50导入，重新生成刷新仍3工作日（10/14—10/16）；日期可按新项目计算 | [导入及读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-import-policy-green.json；SHA256：d9620ee2b4a5e89fcfb8858d1de369f973528b91db16fd77b777ac4a65360ce1") |
| 克隆完整计划偏好 | 网页通过：新周期克隆无日程，生成、普通重排及刷新保持3工作日（11/09—11/11）和倍率0.50 | [克隆及读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-clone-policy-green.json；SHA256：4a9c879c53dc4bf63a2ce3d2dd2946616da24862732b74a12d33541f640c6964") |
| 鼠标拖动结束边缘 | 网页通过：克隆任务从11/09—11/11实际拖为11/09—11/10，预览明确保存人工2工作日、基准20项；确认后普通重排、刷新仍2天 | [拖动预览](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-drag-resize-preview.txt；SHA256：170d5ca40515b9857f1112cc73cc487df5c6fe54596a6738b03edf697010663b") / [重排刷新](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-drag-resize-regenerate-green.json；SHA256：c9fc4526b18edb4efbfbf2dfead0aab8fd821b52b34d662f135f9b07bf291acc") |
| 无法分配的导入预算 | 网页通过：活跃3工作日、基准0.01原预检误通过；修后拒绝并明确至少0.02，确认创建不可用、未创建项目 | [原误通过](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-invalid-budget-red.txt；SHA256：a496c89e19273487bd80dde4b2f4e6f41d08a4e362ec59e80cce5f24ceace2b6") / [拒绝](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-invalid-budget-green.txt；SHA256：2c5fb32ce4bf4a8f991392510f38f7cd44c4a9d68cbe29b20ac1cfd89a0282ad") |
| 克隆拒绝时附件原子性 | 网页通过：原非法克隆400、无新项目但附件91→95；校验前移后同类请求仍明确拒绝，附件95→95、路径不变、无新项目 | [原错误](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-clone-invalid-error-red.json；SHA256：bd54abab5b442b74d689c8e6a87e69405625cc63063f17c920d9ed5041403611") / [原孤立文件](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-clone-invalid-orphans-red.json；SHA256：0fc817926f06c14a58defff4b96441f1ad99e4b512cd54986c2336b9c5a2f365") / [修后拒绝](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-clone-invalid-error-green.json；SHA256：a67e6deac0749a9e5c0842e794b6a4322007587935f7223151c1b8335a2e2b7e") / [无新增文件](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-clone-invalid-orphans-green.json；SHA256：fdd8a5130651df77da3cc37683d5a29fa2ae9f0d24da501fc40919aa636e8817") |
| 已报工及单位变化后的自动恢复 | 网页通过：原报工1、单位改“个”的任务可从人工工期入口预览剩余19及自动5天；取消保持原偏好，确认仅撤销人工偏好，6条日程与1条报工行哈希不变；普通重排成功10/15—10/19五天，不再被旧单位卡住 | [原单位拒绝](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-reported-unit-auto-trap-red.json；SHA256：7d4ba028f360ab696019cb189e734e0af8640b0c0d0b85ff9cd56499d2717025") / [预览](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-reported-reset-preview.txt；SHA256：244f50a4108c40aa66cd3fa8a1714e2fc4855c692659c938ef1b2ddf9cec800a") / [取消读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-reported-reset-cancel-green.json；SHA256：28ad7fc43b180034cb506a95560b0261dc933fd6ec5ae1eb8324bd921105b187") / [取消保全](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-reported-reset-cancel-hashes-green.json；SHA256：b55830dc82d3a18a6edbfacb45e68a5ba5c77342418b3e6c631dae5f66efb605") / [确认保全](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-reported-reset-preservation-green.json；SHA256：02ac95114a899368ab0e077eaae6128b441c612709087133bafd2179dc56c4a8") / [重排读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-reported-reset-regenerate-green.json；SHA256：d0138e5eff7e1bae57a0610b5342fed68327ddc7d436b2e50651b41c72c4764e") |
| 空日程及非甘特视图恢复 | 网页通过：空日程克隆的“工作清单”可打开1项人工偏好；取消仍有1项、0条日程；确认后人工偏好入口消失且仍0条，随后生成自动五天11/09—11/13 | [清单预览](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-empty-reset-list-preview.txt；SHA256：35171ae1f52bb8e55a5aa7007aa3e009f247b2b8386d4f0029e5290d0a090e0b") / [取消与确认读回](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-empty-reset-green.json；SHA256：eacf4f505a015e68cc69dab9e662d4aa76be1b1378124101ddddb135b9f8254d") / [自动生成](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-empty-reset-generate-green.json；SHA256：35b40f50bee42253ac0b61879651a8748c06689899c5ce5707e6efa477f80739") |
| 手机自动选项 | 网页通过：390px三项模式均44px高，弹窗宽374、左距8px；最后手机截图已实际查看 | [原22px画面](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/mobile-auto-choice-before.png；SHA256：2a90f18ed4dcd425525f124bf4f751a7f4d3487822ba419e9d3459998edba923") / [实际测量](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-mobile-targets-green.json；SHA256：7e9338fbb6ada5ab4e243ac06faba457e47fec7306a8cfa218a992b7e8bb2ef9") / [最后手机画面](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/mobile-auto-choice-final.png；SHA256：9c65bb21de32d49bb27c5d2b3e7f943eb2db484467119e7e52d4ca27ad59a9ea") |
| 迟到预览或失败保存 | 网页通过：第二页改结束17日后，第一页旧16日预览确认被409拒绝；弹窗、16日输入和错误保留，可直接重新预览、保存并刷新为10/14—10/16 | [原丢输入](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-stale-range-failure.json；SHA256：5136efaf35d06fbb47f9171eeb37aa1e40cb3b5f44989f2f53bbaaeafde6485b") / [冲突保留](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-stale-range-preserved-green.json；SHA256：d4af09ba69e09d0a6a37d5b59d6d0c517701f006dc837868f76ad7c27509b3f6") / [重试刷新](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-stale-range-retry-green.json；SHA256：c614b7fe186b805b7348c5e25ef3ceed55473d2486b9a7160ddb9265128dabff") |

## 测试与交付状态

新增表结构专项9项通过：旧 SQLite 原行及列保全、重复建表、外键和删除级联，以及 PostgreSQL DDL离线编译。该专项没有连接实际 PostgreSQL。

最终后端按“全量基线＋最后IO回归”验证：完整基线1448项通过（18949 warnings，817.55秒），249份源码在全量前后完全一致。最后克隆原子性网页发现后，仅修改 `io_routes.py` 及 `test_schedule_policy_roundtrip.py`；其余247份源码与完整基线逐字一致。最终IO组67项通过（786 warnings，28.88秒），包含原IO、39项策略往返与9项表结构测试，249份源码在这次执行前后也完全一致。没有将最终IO源声称为重新运行1448项全量。

新增测试先复现数据库回滚后仍复制物理文件，再验证拒绝请求完全不改数据库数量和参考文件字节；有效克隆仍复制独立文件。往返覆盖倍率/人工预算/明确自动复制、同名任务ID映射、旧文件兼容、单位与数值校验、权限及无部分创建。早期54项、最低数量两项定向通过及曾中断的562项部分运行保留为中间记录，均未替代上述最终验证范围。

最终前端完整98文件739项通过（Node22.23.3/TZ=UTC，170.27秒），238份源码在执行前后无变化；最后49项定向通过及生产构建通过，主产物为 `index-BlwKqO6N.js`，PWA152项/2346.57KiB。249份后端与238份前端测试源码均逐字匹配最终产品提交，[公开证明](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/source-validation-summary.json；SHA256：ca0a216ad1935a1623cd3e58b7ebbaadd7e5c17672da57c8625c5cd8fc0ad8d9")。组件/API测试证明契约及边界，不能替代上表浏览器读回。

本机 [工作台](http://workflow.localhost:18004) 已用同一数据卷升级2.1.4并真实重启，PostgreSQL17.11、5个服务均运行；54张旧表的内容、6项目、4用户及JWT保持，新增两策略表后共56表，61个原文件无变化。人工已推进的“xyh”仍为计划中。原验收项目实际网页读取32任务、1成员、35条已下达，准备项4项、必需已通过1/4，“场地勘测”完成日期仍2026-10-05，最后准备截图已实际查看。[升级保全](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/upgrade-2.1.4-receipt.json；SHA256：e52386e2bbf8579987f2ac37d23555973570e4f14a3bf328b50ff2a6e945514d") / [概况](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-overview.txt；SHA256：23483dcf697163ccd8bc5193ee83c1514ff7ffa17235b732832766a48308cc4c") / [完成日期](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-preparation-date.json；SHA256：86f8a9aec1691177c4ddea85769415de9da1a92f9bd2da8ed9e0304e1b35c969") / [日程](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-schedule.json；SHA256：57bf18312c048ead2289244179c2a7c22c44875c583624a8f23cfb47bf0db57a") / [最后准备画面](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-preparation.png；SHA256：136b9f66abb83c03a00af93ed79053262510725c2b3dc01edf9105c8e3fd2cfd")。浏览器实际下载旧附件138B，SHA与原文件完全一致，[下载回执](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-browser-download.json；SHA256：66598139504b6901487c65e0fdecc786fc1f1d0f92bfee28826d0784e25f9d3c")。

ARM64离线镜像已实际导出并加载，208769692B，SHA256为 `4a317f9a4ed0409a0592d704ee237e983afe2b6f09eb5167feaaff02abb75a2d`。`agv-workflow:2.1.4-qa` 与 Compose默认的 `agv-pm:2.1.4` 指向同一镜像，源码为最终产品提交；一键启动命令实际运行成功。镜像与源码包不包含私有env或运行数据。最终源码包从已验证提交及文档提交生成，打包时再核已知私密值、ZIP完整性、文件模式、产物字节和独立解压启动；包内不含数据库、私有配置、登录资料或业务导出包。

验收浏览器Space6已关闭，2个受管页关闭、0页保留，[清理回执](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-cleanup-receipt.json；SHA256：aee5223107d7c56554eb8aef3af332aab2db58fba73cdad700c9a76d1eb8a8ae")。无效克隆遗留的4个测试文件已在可恢复保全后仅从隔离SQLite样本清理，原91条文件路径保持，未改数据库或实际PG，[测试文件清理](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-invalid-clone-test-cleanup.json；SHA256：14b6546c3fc4346c36c00e04dbcd2d193e4b7b1b35e2839a77ca126e3fff02b7")。正式NAS未部署、amd64未实际验收的边界保持不变。

上述结果限定于已执行的旅程，不把未穷举角色、网络、时区或并发组合写成零缺陷。

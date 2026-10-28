# 网页整改与交付说明

> 本文引用的 QA 回执描述历史时点，原件已[归档](evidence-archive.md)；当前 v3 操作请从[文档入口](index.md)开始。

## 2.3.2 当前交付与部署状态（2026-10-12）

项目列表新增个人收藏、最近浏览和保留筛选的刷新；准备事项支持“我跟进的事项”，手机长名称与状态分行，确认按钮至少 44px。[本轮 10 项整改清单与页面效果](便民功能与视觉优化-20261012.md)。

最终产品源码 `0e4b7a9add2632346c9f6284bd0e4e7f04be5a2e`：后端 Python 3.12 全量 **1621 项**、前端 Node 22 全量 **116 文件 / 954 项**、TypeScript 和生产构建通过；269 份后端、288 份前端源与测试一致，170 个编译资源直接来自该构建。[测试回执](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/source-validation.json；SHA256：4ce717d776c8524cec50b3d4f5148a74be0695eedd6a1fff9e1dba69cea8ca16")。

[本机工作台](http://workflow.localhost:18004)已更新并实际重启 2.3.2，单产品容器、PostgreSQL 17.11 和 5 个服务健康。58 张表的原始数据、4 用户、7 项目、84 个原文件的内容及权限、JWT 保持一致；本轮没有数据库迁移。自动 SQL 备份轮转后仅从冻结备份补回原文件；初次补回的两份权限差异已修正并通过完整复核，没有还原业务库或修改附件。[运行保全](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/upgrade-public.json；SHA256：030239259d302f1d88e1e339fde9a8a3bd9bd3586ef9c2ab8f06967ed1c89231")、[实际页面读回](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/actual-browser.json；SHA256：424f76c119dd343a6adaba884c38cd895949a7b5dee672fdcaa09ba09e6493c0")。

ARM64 镜像沿用已验证 2.3.1 依赖基础，替换最终后端与前端；36 个历史层扫描、私密值检查和实际 Docker 导入通过。[镜像构建](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/image-build.json；SHA256：926788537c090cac806a458bb9eeef104c2242d5c8c0083ef48acfff09adfc64")、[导入核对](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/image-load.json；SHA256：fd91b608c04ec08ca80c9ebe8d7128ebc91c8c94eef811ff2fb7200b785689d5")。本轮未完整执行标准 Dockerfile，正式 NAS 和 amd64 未实机验收。

NAS ARM64 新装可加载 `agv-project-workflow-2.3.2-linux-arm64-image.tar.gz`，设置 `AGV_IMAGE=agv-pm:2.3.2`，使用对应 Compose 入口与 `--no-build`；8002 入口配置 `docker/.env`，普通入口配置根 `.env`。x86_64 使用源码按标准 Dockerfile 构建。已有实例先完整备份并保留原卷与认证配置；2.3.2 与 2.3.1 迁移头均为 `d2e7f9a103b4`。本机已保留原 2.3.1 停止容器和私有一致备份。

## 2.3.1 历史交付与部署状态（2026-10-08）

项目负责人和获授权成员可直接“备份并删除”，在“项目回收站”还原同一个项目，无需审批。基本信息编辑提供“撤回修改 / 取消撤回”：未保存时处理当前输入，保存后按顺序处理本人资料修改；人员、授权、报工及已发布日程不通过资料历史回放。原“18项整改清单与操作说明”未包含在本次来源提交中；现行规则见[项目回收站](project-retention.md)。

最终产品源码为 `2a3031889dd2ab5a947fd664e087351666e52f40`。后端 Python 3.12 全量1617项、前端 Node 22 全量113文件935项、TypeScript及生产构建通过；268份后端、284份前端源码与测试时逐字节一致，169份前端构建产物与镜像及源码交付包一致。[测试与构建](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/source-validation-231.json；SHA256：b2680003508bd7ce67b76e6dc80bc41311c87af8db15ae71b8ce14b02e119bf5")。

隔离SQLite和PostgreSQL网页实际验证保存前/后多步撤回、取消撤回、负责人及授权现场成员直接删除、同ID还原、附件和任务记录保留、取消确认与撤权。独立禁止导出时仍可还原，但下载备份返回拒绝；桌面、平板及手机排版和深色模式已检查。[网页验收](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/browser-acceptance-231.json；SHA256：c23608da5ebb388a9f44a077eda7fcbe354345a744532657c323779274aedcaf")。

[本机工作台](http://workflow.localhost:18004)已沿用原卷升级并真实重启2.3.1，单产品容器、PostgreSQL17.11及5个服务健康。原4用户全部14列、7项目、82个原文件和JWT逐值/逐字节保全；只新增两张空恢复历史表并推进迁移头，未执行真实项目删除、编辑撤回或权限变动。[运行保全](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/upgrade-2.3.1-public-receipt.json；SHA256：5e133a287ea10183e5b8d0910276a7f770131f1f0abc032288daf3fc5b4feafc")。

ARM64离线镜像继承已验证2.3.0依赖，替换最终后端、迁移和前端；完整历史层、7个精确私有值扫描及实际Docker导入通过。该轮未完整执行标准Dockerfile，正式NAS和amd64尚未实际验收。[镜像验证](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/offline-image-231-public-proof.json；SHA256：b6d75d09d89427928623cea915b6e78262aea3cc15a778ca0a7fea3792eb0589")。

本轮还统一正式、演练及环境示例的默认镜像标签为2.3.1；三份YAML使用PyYAML静态解析并核对单服务、构建版本和镜像默认值，不计作Compose CLI或NAS运行验收。[部署默认值校验](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/deployment-defaults-231.json；SHA256：3b7010241a7b5680075bc50ef550dc0c41271dbde29b5eef7f9f2ceb3314d84e")。

NAS ARM64新装先加载 `agv-project-workflow-2.3.1-linux-arm64-image.tar.gz`，设置 `AGV_IMAGE=agv-pm:2.3.1`，使用对应Compose入口和 `--no-build`；8002入口配置 `docker/.env`，普通入口配置根 `.env`。x86_64使用源码按标准Dockerfile构建。已有实例先一致备份，保留原卷及认证配置。新迁移头 `d2e7f9a103b4` 不可直接交给缺少该脚本的旧2.3.0镜像；兼容回退镜像保留旧程序，仅补迁移脚本，且要求两张新恢复表均为空。已有恢复记录时应保持新程序，或明确采用完整一致备份恢复策略，不能无条件回退。

本机启动入口已验证2.3.1，原登录口令保留于本机600文件。网页验收TaskSpace12已关闭且零保留，临时后端、Vite和隔离PG容器已停止清理。[启动与清理](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/launcher-cleanup-231.json；SHA256：b7f25b40fe7c2a81a42e7888a4bb51ae72f2d8e26e1130d84d3b82b775431519")。以下内容为历史记录。

## 2.3.0 历史交付与部署状态（2026-10-08）

管理员在“设置 → 团队与权限 → 成员权限”按成员设置54项全系统操作。权限页提供分组、搜索、继承/允许/禁止、批量、结果来源、固定保存和冲突保护；原项目、本人资料与流程资格一起校验。见[详细目录、推荐设置及16项检查清单](system-member-permissions-2026-10-08.md)。

最终产品源码 `4667f02c470dc85265ac68ce69cd3258c0a0accd`：后端1563项、256份源前后及最终Git字节一致；前端106文件886项、269份源、TypeScript和生产构建通过。全新Node22依赖安装569包及完整性校验通过，依赖版本保持原锁定值。桌面/手机浅深色、同会话授权撤销、只读字典、现场独立动作、未保存、并发合并、审计与归档拒绝完成网页检查。[最终验证](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/validation-summary.json；SHA256：c8a2b422dd04e9981e01622cfa03511b2c74cb4b8aa3aa67a5257cfc7e232164")。

[本机工作台](http://workflow.localhost:18004/pm/permissions)已在原卷升级2.3.0并真实重启；单产品容器、PG17.11和5服务健康。4用户的原12列及ID、6项目、75原文件与JWT保持，2个新权限列仅默认继承。只变更预期User列和Alembic头，技术水位仅两个时间向前。原生成SQL备份按冻结归档逐字节补回，没有恢复数据库或改写用户文件。真实网页读回54项/4成员全继承、保护入口及39条已发布日程；没有给真实成员设置新策略。[升级保全](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/upgrade-2.3.0-public-receipt.json；SHA256：bcc2e4434a4cdb080db112b8fd8e5f16294d3649f814f4f6525d7b5e6b01b0dc")、[真实网页](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/actual-pg-permissions-readback-230.json；SHA256：1be4b76ab39d8c07b4847753c8654dc4519e4ad312608756a502e2823cd56dad")。

ARM64离线镜像 `agv-project-workflow-2.3.0-linux-arm64-image.tar.gz` 为211223953B，SHA256 `6129998853e668469ecdda5ead2616621065ad46a7244ad7c4529197f6571da2`。继承已验证2.2.3依赖基础，完整替换最终后端、迁移及164前端资源；26历史层、5个精确私有值零命中及实际Docker导入通过。该轮未完整执行标准Dockerfile；正式NAS与amd64尚未实际验收。[镜像回执](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/offline-image-230-public-proof.json；SHA256：032c3d7c6d630cd8ac99f0ebafcce1321ac92309311925353a65cc82ae0aba63")。

NAS ARM64新装先加载镜像，在对应环境文件设置 `AGV_IMAGE=agv-pm:2.3.0`，沿用相应Compose入口并使用 `--no-build`；8002入口用 `docker/.env`，普通入口用根 `.env`。x86_64从交付源码按标准Dockerfile构建。已有实例先一致备份，沿用原数据卷与认证配置；新迁移头b6不能直接交给不包含该迁移脚本的旧223镜像，应使用兼容回退镜像或对应的完整升级前快照与旧镜像。

本机一键启动入口已实际运行2.3.0就绪，登录密码保持，仅本机600文件提供。Space11三页关闭、零保留，临时后端与Vite已停止。[启动](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/launcher-230-public-proof.json；SHA256：0cbdd2472ac8d3d805a5f6d56fef88d3e15c84f28aefcc8f6837608d846f9fe9")、[清理](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/browser-cleanup-230.json；SHA256：63403cbcd7cd842f11293a6b349a3ec933cb369fd5cab878c30452f218f74eeb")。以下保留历史记录。


## 历史2.2.3交付与部署状态（2026-10-07）

“重新安排全部任务”从更多菜单移到日程页头。有待发布安排时与发布按钮并排；全部已发布时成为主操作；空排程仍用自动安排。更多保留排期设置和逾期/受阻调整，设置说明同步指向页头。点击仍先预览，确认保存才改变日程。[入口整改与网页证据](日程重排入口整改-20261007.md)。

最终产品`c11a01bc0d0c9393af1cd98f658a0fb9c9a36ea1`，Node22.23.3/UTC完整102文件824项（257.22秒）、TypeScript和构建通过，261源及160编译资源一致。1440/1100/700/390网页检查、桌面和手机预览取消通过。后端248份业务/测试源保持，仅版本默认变化，沿用历史1448基线＋最终IO67，本轮未新跑后端业务全量。

[本机工作台](http://workflow.localhost:18004)已保留原卷更新2.2.3并实际重启，单产品容器PG17.11及5服务健康；55业务表、73原文件、6项目、4用户和JWT保持，技术表仅两个时间字段自然前进。正常SQL轮转缺失的生成备份只从冻结归档精确补回，没有恢复数据库或改写附件。真实项目39条已发布、两项手动工期下，重排主按钮及390/1440尺寸实际读回；预览取消后日程响应逐字一致。[运行保全](evidence-archive.md "原路径：docs/qa-replan-2026-10-07/upgrade-2.2.3-public-receipt.json；SHA256：fc4937af79d4408d1824a1bb650df28611d7be609c789fb1dda6e51cefa94960")、[真实网页读回](evidence-archive.md "原路径：docs/qa-replan-2026-10-07/actual-pg-replan-readback-223.json；SHA256：f1fe702d90c611a74084de3358deb64d8a16957a77fabeaa1b131fc4d74b8624")。

Linux/arm64离线镜像`agv-project-workflow-2.2.3-linux-arm64-image.tar.gz`为209810892B，SHA256 `f57e7f44132ba6f641a4a9b8566c8dc974f13d3a5496ad68607f41ede09b794e`。镜像从已验证2.2.2运行基础继承，仅替换最终160个前端资源及后端版本配置，先删除旧dist；21个历史层完整扫描及实际docker load通过。该轮使用记录谱系的增量构建，仓库标准Dockerfile仅版本默认变化，本轮没有执行标准完整构建。[镜像回执](evidence-archive.md "原路径：docs/qa-replan-2026-10-07/offline-image-223-public-proof.json；SHA256：271ed4d96acfacf6d22700ecc569ca87392fadaf673d14988e493499101ad70d")。

NAS ARM64新装可先docker load，再在对应环境文件将`AGV_IMAGE=agv-pm:2.2.3`，使用与部署形态对应的Compose入口及`--no-build`；8002入口用`docker/.env`，普通入口用根`.env`。x86_64从[交付仓库](https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow)或2.2.3源码ZIP按下方标准Dockerfile构建。已有实例先一致备份并沿用原数据卷和认证配置。正式NAS及amd64未实际验收，源码ZIP解压启动结果见包旁回执。

本机一键启动的旧版本正则校验已修正，实际执行2.2.3就绪通过，[启动回执](evidence-archive.md "原路径：docs/qa-replan-2026-10-07/launcher-223-public-proof.json；SHA256：530faa1f5138bef65bcb2783f3f0df87c63c1598aed751e451c22b8a86cb2295")。Space10的2个任务页关闭、0页保留，临时QA后端/Vite停止，[清理回执](evidence-archive.md "原路径：docs/qa-replan-2026-10-07/browser-cleanup-223.json；SHA256：5c3a5cf729582adfe6550b2f712b31b38c49a90693b54b3fec973b5679013c7e")。下文为各历史轮次的状态。

## 2.2.2历史交付与部署状态（2026-10-07）

甘特图增加「按任务」和「按人员」：任务可展开每人的实际日程；人员视图逐日显示任务、数量及完成量，空档保持真实位置，同一天多条安排逐条查看。切换视角回到起点，滚动后每行仍保留姓名与阶段。手机日期格、日期调整及编辑按钮扩大，日历改为当天明细抽屉；月份、今日线、颜色对比和表格/弹窗尺寸一并核对。[13项检查与整改清单](甘特图多人分工与排版检查清单-20261007.md)。这次改善实际多人安排的展示，自动排程的人力算法沿用原规则，不会因为多名成员自动生成并行安排。

产品检查点`672248a7b4ac91742e4a5d15cf18aba6d8648631`：Node22.23.3/UTC/单worker完整102文件824项，242.63秒，TypeScript与生产构建通过，原时限与断言保持；261份源及160个编译资源逐字一致。后端248个业务/测试文件沿用已验收2.1.4字节，仅APP_VERSION变化；验证口径为历史1448项基线加最终67项IO回归，本轮没有新跑后端全量。

[本机工作台](http://workflow.localhost:18004)已保留原卷更新2.2.2并真实重启，只有一个运行的产品容器，内部PG17.11和5个服务健康。按本轮新鲜快照保全55张业务表、69个原文件、6项目、4用户与JWT；一张调度技术表仅两个时间字段自然前进。用户当前项目为待进场、39条安排已全部发布、2名执行人及3项多人任务，网页已读回；不沿用2.2.0的旧状态。仍有8条安排超出用户设定的项目周期，页面明确提示；本轮没有替用户改合同周期或已有日程。[运行保全回执](evidence-archive.md "原路径：docs/qa-gantt-multi-2026-10-07/upgrade-2.2.2-public-receipt.json；SHA256：9e0b1d72d291696023bbe0337fc1b66d2c9f8a0648bc62a0cdd70b3a2f12271b")、[真实网页读回](evidence-archive.md "原路径：docs/qa-gantt-multi-2026-10-07/actual-pg-person-readback-222.json；SHA256：015a92a9499897c256ebd4b37c04e9e19ea3d4cfba7c2d6e8636bf91c251f8e2")。

启动中的既有迁移备份轮转规则会清理最旧的自动SQL备份。本轮从冻结一致归档中仅补回被轮转的生成文件，逐字核对69个原文件；没有恢复数据库或改写用户附件，备份保留规则保持。升级前私有一致归档及旧回退容器继续留在本机；数据库、登录信息和真实项目截图不进入公开交付。

Linux/arm64离线镜像`agv-project-workflow-2.2.2-linux-arm64-image.tar.gz`为208787154B，SHA256 `ceee5a8f07c5ad12fd31911a6c62dc4d91553d47ca2c0b3712c8fb7cd33a8cee`。18个历史层全部扫描、实际docker load及RootFS/Config逐项核对通过；`agv-workflow:2.2.2-qa`与Compose默认`agv-pm:2.2.2`指向同一镜像，160个前端资源与测试构建一致，另经独立只读复核。[镜像回执](evidence-archive.md "原路径：docs/qa-gantt-multi-2026-10-07/offline-image-222-public-proof.json；SHA256：8831171611d683730b7591dbf7f049f2d3267aef6a98ba4cb7fefe619152a6bf")。正式NAS尚未部署2.2.2，amd64未实际验收。

NAS新装先确认架构：ARM64可导入上述镜像，再使用与下方部署形态对应的Compose入口及`--no-build`；x86_64从[交付仓库](https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow)或2.2.2源码ZIP构建。已有实例先做一致备份，沿用自己的持久卷、环境和认证配置，再按原部署形态更新。源码ZIP附编译前端、清单、证据与校验文件，包旁回执记录最终文档提交、逐文件核对及独立解压启动结果。

本机一键启动2.2.2实际执行成功，[启动回执](evidence-archive.md "原路径：docs/qa-gantt-multi-2026-10-07/launcher-222-public-proof.json；SHA256：2ecb530ed5679f4867184e002cefa634cb2c08427de786e29798d33e9a140059")。本轮Space9的3个任务页已关闭且0页保留，临时QA后端和Vite均停止，工作台持续在线，[清理回执](evidence-archive.md "原路径：docs/qa-gantt-multi-2026-10-07/browser-cleanup-222.json；SHA256：4d607202101eae01f6477a91c83c936edf6fd14848617620d72ea151c4dea7b7")。下文状态只对应各历史版本。

## 2.2.0历史交付与部署状态（2026-10-07）

界面按工作重排：全站四个常用入口，项目七个工作区域；页面正文、创建三步、任务与日程、现场、资料及手机工作同时整理。[23项改造与发现清单](整体界面重设计清单-20261007.md)、[名称与位置指引](功能位置与名称指引-20261007.md)。最终检查点`ff34aa22767184aebaae61218042a3fd7f474ee2`：Node22.23.3/UTC/单worker完整100文件796项、TypeScript与构建通过；255份源与159个编译资源逐字一致。后端248份非版本源/测试沿用已接受2.1.4字节，只改APP_VERSION；本轮未新跑后端全量。

[本机工作台](http://workflow.localhost:18004)已保留原卷升级2.2.0并实际重启，仍只有一个运行的产品容器，内含PG17.11和应用服务。原55业务表、65文件、6项目、4用户及JWT保持；另外一张调度技术表5行稳定字段保持，2个运行时间字段自然前进并独立绑定快照。原项目仍为计划中、32任务和89条待发布；手机旧名检索、原138B附件精确下载及新版一键启动通过。[运行回执](evidence-archive.md "原路径：docs/qa-redesign-2026-10-07/upgrade-2.2.0-public-receipt.json；SHA256：330752b8396b2eddf4d96da458e36ec35ebc67397467820bd2db040c29a9f836")、[网页读回](evidence-archive.md "原路径：docs/qa-redesign-2026-10-07/actual-pg-browser-readback-220.json；SHA256：4f454ea2bcb1984dd52f2f3614027ef0770b9e7ab566a07f47058628618fc733")。一致私有备份和旧回退容器保留，数据库、登录信息及实际项目照片不进入公开交付。

Linux/arm64离线镜像`agv-project-workflow-2.2.0-linux-arm64-image.tar.gz`为208784609B，SHA256 `6181fa7589bec3c6ae31927829ebfd5351c63d6893f5025f9b74a9a1c6d75849`。18个历史层全部扫描、实际docker load与RootFS/Config逐项核对通过；`agv-workflow:2.2.0-qa`和Compose默认`agv-pm:2.2.0`指向同一镜像，全部159前端资源与测试构建一致。正式NAS尚未更新本轮版本，amd64未实际验收。

NAS新装先确认架构：ARM64可导入上述镜像，再按下方对应Compose入口使用`--no-build`；x86_64从[交付仓库](https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow)或2.2.0源码ZIP按下方流程构建。已有实例先做一致备份，沿用自己的持久卷、环境和认证配置，再按原部署形态更新；不使用本机QA库替换。源码ZIP附编译前端、清单、证据与校验文件，私有数据另行保存在本机。

## 2.1.5历史成品（2026-10-07）

项目导航采用桌面左侧树及手机单目录抽屉，首页按环节展开，项目名和目录在切页时保持；深色确认框、手机长页操作及最后目录项的可点击范围已实际复测。[本轮11项问题与网页证据](tree-navigation-layout-2026-10-07.md)。产品源码`326fba6eb36e04660e72c723885d63d05e6c0489`；历史基线、未完成或定位错误的检查在本轮记录中区分，未当作最终通过。

| 交付项 | 本轮实际结果 |
|---|---|
| 前端 | Node22.23.3/UTC完整98文件784项通过，145.27秒；241份源与实际验收副本一致，tsc/build通过；150编译文件3029620B，主资源index-CHUArX4A.js |
| 后端 | 248份非版本源码及测试逐字保持已交付2.1.4，只改APP_VERSION默认；沿用1448项全量基线+最终67项IO回归，本轮没有重跑业务全量 |
| 网页 | 桌面18项目入口稳态点击读回、最终手机18项、目录搜索/焦点、只读权限、未保存继续/放弃、长页目录、两尺寸末叶和首页三浅深图均有实际证据；全站17页×2宽度浅色范围保留准确来源 |
| 本机成品 | [workflow.localhost:18004](http://workflow.localhost:18004)真实重启后2.1.5健康，PG17.11与5服务RUNNING；原56表、63文件、6项目、4用户及JWT保持，原项目首页/排程步骤及手机目录实际读回 |
| Linux/arm64镜像 | 208772213B，SHA256 `d5075d2d3f434130b9824b7b6f846a94351bf4edebc9273679b0384762af2a43`；实际save/load，同一镜像包含默认agv-pm:2.1.5与QA标签 |

本机一键入口`deliveries/启动AGV工作台.command`实际运行及打开工作台通过；本机登录文件权限0600，登录资料、真实用户截图、运行数据库、附件库和备份另行留在本机，不入公开源码或ZIP。源码ZIP从最终文档提交生成，附编译前端；逐字节、150资源、CRC、13个755脚本、引用、安全扫描及独立解压启动的结果以包旁回执为准。旧版本ZIP和离线镜像保留。

[验证摘要](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/validation-summary.json；SHA256：b36c51fc7164a63739737d46d7304dd5bbfc239196875bbece23489e924cbb7d")、[脱敏运行与镜像回执](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/upgrade-2.1.5-public-receipt.json；SHA256：8163a93b14ce433ff2571e38045729f97521e94e0039abed140b6c27919898cb")、[实际原PG网页读回](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/actual-pg-homepage-public-summary-215.json；SHA256：930ea7299482d02ce8c65fd0c6dc207dc34cacc00be37a9dcfd0f00573de832f")。Space7的3个任务页已关闭、0页保留，临时Vite停止，本机工作台持续在线，[清理回执](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/browser-cleanup-215.json；SHA256：994b9ce422df99d5d239cc8dddce64dc77125e5402769b95987c68bcba5fbae7")。正式NAS未部署、amd64未实际验收；下方“当前/最新”仅指各历史轮次。

## 2.1.4历史交付（2026-10-07）

人工确认的工期和项目倍率会持久保存，后续重排沿用；明确恢复自动估算后才按耗时重新计算。已有执行记录的任务可仅取消后续预算，原日程、报工、锁定与下达保持。另修复导入/克隆预算丢失、无效预算留下克隆文件、冲突保存丢输入，以及手机选项目标偏小。产品源码 `d0dfeb443d530715f0edcbedcc2b68aa4c90b03d`，范围与步骤见[16个实际网页验收范围](manual-duration-regeneration-2026-10-07.md)。

| 交付项 | 当前实测结果 |
|---|---|
| 前端 | Node22.23.3/UTC完整98文件739项通过，170.27秒；maxWorkers=2仅控制并发，原5秒不变，无跳项；238份源码清单前后完全一致，tsc/build通过 |
| 后端 | 1448项全量基线通过，817.55秒；其后仅IO路由与往返测试提前预算校验，最终67项IO组通过，28.88秒；其余247份字节相同，完整[组合验证口径](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/source-validation-summary.json；SHA256：ca0a216ad1935a1623cd3e58b7ebbaadd7e5c17672da57c8625c5cd8fc0ad8d9") |
| 网页 | 缩短后普通/逾期重排、拖拽、刷新、倍率取消/保存、数量变化、自动恢复、已报工单位救援、JSON与克隆、空日程/工作清单入口、冲突重试、手机44px等16个范围实际操作通过 |
| 本机成品 | [workflow.localhost:18004](http://workflow.localhost:18004)真实重启后2.1.4健康，PG17.11与5服务RUNNING，54旧表/61旧文件/4用户/6项目/JWT保持；原32任务/35下达/准备完成日期与138B附件已网页读回 |
| Linux/arm64离线镜像 | 208769692B，SHA256 `4a317f9a4ed0409a0592d704ee237e983afe2b6f09eb5167feaaff02abb75a2d`；实际save/load通过，`agv-workflow:2.1.4-qa`及默认`agv-pm:2.1.4`同一镜像 |
| 源码与NAS | [独立交付仓库](https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow)；正式NAS尚未部署，amd64未实际验收，x86_64需使用源码本机构建 |

新旧源码ZIP和镜像分别保留版本文件；当前2.1.4源码ZIP另含对应编译目录，最终包的逐文件字节、文件模式、CRC、资源引用及新安装启动结果记录在包旁回执和包内清单。私有一致备份、登录文件、真实密钥、数据库、附件库与虚拟环境不入包。[真实升级回执](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/upgrade-2.1.4-receipt.json；SHA256：e52386e2bbf8579987f2ac37d23555973570e4f14a3bf328b50ff2a6e945514d")、[原附件网页下载](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-browser-download.json；SHA256：66598139504b6901487c65e0fdecc786fc1f1d0f92bfee28826d0784e25f9d3c")。

浏览器验收空间已关闭，2个任务页全部关闭且0页保留；本机工作台持续在线，[清理回执](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/browser-cleanup-receipt.json；SHA256：aee5223107d7c56554eb8aef3af332aab2db58fba73cdad700c9a76d1eb8a8ae")。旧版记录在下方按历史日期保留，各轮结果对应各轮源码，不能把旧版结果当成新源码全量通过。

## 2.1.3历史范围与交付状态（2026-10-06）

本轮业务版本2.1.3，最终产品源码`c2e86490300344808e725c4ebfafcf902b577351`，新增[14项快捷操作与流程整改及54份证据文件](usability-remediation-2026-10-06.md)：准备清单与任务目标就地保存、问题及现场物品/申请/车辆状态快捷处理、甘特工期伸缩与估算调整、轻量提示、快捷导航及人员日历入口。创建向导固定从草稿开始，项目阶段、准备就绪结论和任务阶段分别显示；草稿可预排但不能下达，既有进场、执行证据、完成与归档保护继续生效，见[生命周期说明](project-lifecycle-remediation-2026-10-06.md)。14项主体网页操作对应`75ae5b2`；最后三项权限提示、完整前端及升级后PG网页回读均已在最终`c2e8649`构建验证。

| 交付项 | 本轮实际状态 |
|---|---|
| 前端测试 | 最终`c2e8649`完整97文件719项通过，Node22.23.3/TZ=UTC，130.13秒；tsc/build通过，236文件清单与实际tar及QA运行源一致 |
| 后端全量 | 1362项通过、17871 warnings、692.88秒；业务源执行前后无差异 |
| 14项网页整改 | 原步骤逐项通过，包含保存后刷新、断网错误/重试、取消不写、已有报工及只读成员保护；证据链接见本轮清单 |
| Linux/arm64镜像 | 最终`c2e8649`镜像已实际save/load，208750992B，SHA256：`cd84168b7eaecc02a1475458aa7ba3098adf66f99d7ff05513fe9869db05e39d`；同时含`agv-workflow:2.1.3-qa`和源码Compose默认`agv-pm:2.1.3`，对应同一镜像 |
| 本机成品工作台 | [workflow.localhost:18004](http://workflow.localhost:18004)持续在线；原卷升级2.1.3并真实重启，原用户及6项目保留；网页概况32任务/1成员/35下达、准备状态及原完成日期、目标/甘特快捷入口和138B附件下载均实际读回 |
| amd64与正式NAS | 本轮amd64未实际验收；未取得正式NAS部署目标与访问条件，不宣称已部署 |

本机一键入口仍为`deliveries/启动AGV工作台.command`；登录文件`deliveries/本机工作台登录信息.txt`权限0600，仅本机提供，不入源码、镜像或交付ZIP。2.1.2离线镜像与旧成品截图只证明历史版本。本轮四个实际查看的画面：[手机准备卡片](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/preparation-mobile-card.png；SHA256：d155abb892b48f7f2fbb50139ed127db6d8a19656096034b22d0a712eebef465")、[桌面甘特](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/gantt-desktop.png；SHA256：1847ea16fcc2af3c9ded828c2690cd0cd0a79792f44793caf57af298e195bd82")、[手机甘特预览](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/gantt-mobile-preview.png；SHA256：831237147e2496e58bd0de0ed3074f74146bf866eaf0dbc91ee16edfc3759793")、[最终PG准备清单](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/pg-final-preparation-desktop.png；SHA256：8991471c958cf46bae0ec119c73a8bf0977ba707000befb3a96fd1610a761ccb")。54份证据文件含网页读回、截图、测试/镜像摘要及环境清理回执；结果见[验证摘要](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/validation-summary.json；SHA256：38ee1596cd095f990c3268dd4cf8f8b5ccf72144b827a6e060c55612f2dd1140")和[最终验证记录](evidence-archive.md "原路径：docs/qa-final-validation.txt；SHA256：80a89ee8c819dacb854118e29395343668e19067564de7cc99813a929cb840a6")。

升级保全核对53张业务表、58个原文件、6项目及JWT一致，仅排程服务水位按正常运行推进，[保全证明](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/upgrade-2.1.3-data-preservation-proof.json；SHA256：bb0712561d024353a0c905b41af099338b03622778c5d166d61bfb0a8ed243b7")。最终前端清单SHA256为`02499c4cab54d39874229ee104d48a4eeb0cac3a827d7da13da5109a9660f759`，[源码一致性](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/frontend-node22-tips-final-source-check.json；SHA256：3148063e00e84cb63ae7db9ec7843bc12b5b5aafac9086ef9a8011e1aca2eedb")。实际PG附件网页下载138B/SHA256 `29de7cdc5adf157e2394cacfc1691e31c927e797e789d5424f09cabcef22b963`，原件保持，[下载证明](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/pg-final-browser-download.json；SHA256：66598139504b6901487c65e0fdecc786fc1f1d0f92bfee28826d0784e25f9d3c")。

此前并行构建时716项通过、3项5秒超时的记录保留；原断言、超时阈值及源码保持，定向56项通过后以独占CPU完整重跑取得719项通过。浏览器验收空间已关闭且0页保留，Vite已停止；本机PG工作台持续在线，[清理回执](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/browser-cleanup-receipt.json；SHA256：4cb39294c48bff4263e6760b00568ddf1cf09b6e6ac9aecf35911e51659bdb89")。

离线包限Linux/arm64。实际`docker load`后，源码`docker/docker-compose.yml`的默认`agv-pm:2.1.3`标签可直接用于`--no-build`；x86环境需重新构建，未把ARM64结果称为amd64验收。升级前一致备份、本机私有env、登录资料及业务数据不入源码或镜像交付包。

## 2.1.2历史网页审查与交付依据

以下保留2.1.2验收当时的交付内容与结果；其中“最新”“当前”限定于该历史轮次，不表示本轮2.1.3已完成。该版在基线 `9c2277399cbc24d7288da743f22d92769c8e2ce4` 上处理[完整清单](browser-audit-2026-10-05.md)累计登记的68项网页问题。包含管理端、项目经理、现场端的排版与手机操作、键盘与导航、保存保护、权限提示、工作量口径、异步状态、导入/导出和收尾交接，并补齐目标撤回与各下达入口的保护。累计68项已登记问题均完成网页回归，具体步骤与边界见主清单。

### 交付内容

- Gitea分支：`codex-mac/agv-project-workflow` 的 `codex/browser-audit-2026-10-05`。当前账号对原仓库 `got/agv-project-workflow` 只有读取权限，因此通过fork合并请求交给原仓库维护者；没有修改原main或部署NAS实例。
- ZIP交付包包含同一提交的源码、锁文件、修复测试、问题清单与网页证据，并额外包含已编译的 `frontend/dist`。包旁的 `.sha256` 可用于校验，包内 `DELIVERY-MANIFEST.json` 标明源码提交与编译信息。
- 本机可使用[成品工作台](http://workflow.localhost:18004)：最新e136源码的真实Docker单容器、PostgreSQL17.11持久实例。双击 `deliveries/启动AGV工作台.command`；登录资料在 `deliveries/本机工作台登录信息.txt`，权限0600。这两个文件是本机另行提供的配套文件，不在源码ZIP内；登录资料不写进源码或镜像。
- 完整网页验收业务样本保留在独立SQLite环境：[管理端](http://localhost:18000/pm/dashboard)、[现场端](http://127.0.0.1:18000/worker/today)，运行方法见[本地验收说明](local-browser-audit.md)。它与上面的本机PG成品使用各自数据，不替换用户已有正式数据。
- 离线Linux/arm64镜像位于`deliveries/agv-project-workflow-2.1.2-linux-arm64-image.tar.gz`，208787455B，附SHA256校验，已实际docker load；其它架构使用源码重新构建。
- 包内不含本机数据库、附件库、会话密钥、系统备份、真实密钥、虚拟环境或node_modules。重新安装生成独立数据；当前网页验收数据仍保留在本机原隔离目录。

### 安装与接入

早期隔离验收使用Python3.12.8、Node24.9.0；最终前端完整验证使用Node22.23.3/TZ=UTC（93文件657项通过），容器采用同轮业务源码。新环境按仓库 `backend/requirements.txt` 安装后端运行依赖；源码重编前端使用 `frontend/package-lock.json` 和 `npm ci`、`npm run build`。交付ZIP的前端已编译，FastAPI启动后直接提供该静态目录，不需要另起前端开发服务。

首次独立实例请按 `.env.example` 或对应部署样例配置独立数据目录、数据库、初始管理员密码及访问域名。生产默认 `SEED_DEMO_USERS=0`，首次需提供至少8字符的 `INITIAL_ADMIN_PASSWORD`；演示账号只用于上述本机隔离测试。已有正式数据应沿用原认证、数据库和附件配置，使用[部署说明](deployment.md)中的备份与更新流程，不能用验收数据库替换。

原正式8002部署使用PostgreSQL配置；对应 `docker/.env.example`、`docker/docker-compose.multica.yml` 和已有更新流程保持原策略。前61项阶段完成三份Compose解析；追加已实际构建与运行最新源码Docker/PG容器，并完成离线镜像加载、网页建项及镜像替换/重启持久化检查，最后PG网页排程/准备/导出/重启和退出重登录均通过，实际文件138B精确一致，见最终验证记录。未实际更新用户NAS，本包不等于已发布到正式实例。

### 验收依据与边界

前61项及追加7项已登记问题的原网页步骤均已回归，目标撤回与各下达入口正反、重复安排两入口逐项列在主清单。真实断网恢复、双角色交付审核、当前验收范围、归档只读、系统备份恢复与重新登录已实际操作。报告和甘特图打印文件逐页渲染查看，归档交接包附件精确比对；追加轮次最终全量及发布检查结果见[主验收清单](browser-audit-2026-10-05.md)。

[覆盖矩阵](browser-audit-coverage-2026-10-05.md)保留尚未穷举的状态、权限、输入与并发组合，不把入口遍历等同于业务全组合测试。外部AI实际返回402余额不足，本机固定QA响应只验证产品流程；AGV硬件和外部通知未实际接入。原61项阶段的PG分支为mock验证；追加轮次已使用真实PostgreSQL17.11和Linux/arm64容器，网页建32任务/1台车型及管理员执行成员保存，镜像替换和重启后数据、JWT保持；35条下达、准备日期备注、附件、导出、重启与退出重登录读回均完成，见最终验证记录，不把前轮结果当作新源码全量验收。尚未执行的边界组合在矩阵保留，不承诺未知缺陷不存在。

追加轮次前端在Node22.23.3/TZ=UTC完整重跑93文件657项通过（214.07秒），本地tsc/build及index-D9e42gYi.js通过；后端业务保护全量1318项通过（691.16秒），之后仅两个结果DTO字段由4项契约覆盖。前端此前两个UTC日期fixture失败已修复并由完整重跑覆盖。[完整验证及历史边界](evidence-archive.md "原路径：docs/qa-final-validation.txt；SHA256：80a89ee8c819dacb854118e29395343668e19067564de7cc99813a929cb840a6")。

可运行成品已完成桌面1440与手机390浅深色实际截图检查：[桌面](evidence-archive.md "原路径：docs/qa-final-pg-overview-desktop.png；SHA256：14599d7c9180c07b7b0ee6caaec7818af689c729fafe21baa9c7848589d524ee")、[手机浅色](evidence-archive.md "原路径：docs/qa-final-pg-overview-mobile.png；SHA256：e1319aaf7cf98ca216883a9238f68a0c12f8c00a79db53ede7dce75cee35f2f1")、[手机深色](evidence-archive.md "原路径：docs/qa-final-pg-overview-mobile-dark.png；SHA256：280d8cc7c6ffe41c7591ef4aa9c5669e51f3f2ecdf4826d2330c2a926a7a17f8")。实际重启5服务RUNNING、一键启动exit0/open成功；业务状态、138B附件下载和随机资料重新登录均已网页验证。[最终PG网页证明](evidence-archive.md "原路径：docs/qa-final-pg-browser-after-restart.txt；SHA256：7dd4edd2cbe38c3ec090ecadaec322364fbffe4c4c5679e97252d572939d253c")。

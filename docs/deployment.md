# 部署指南（NAS / 服务器）

> 本文引用的 QA 回执描述历史时点，原件已[归档](evidence-archive.md)；当前 v3 操作请从[文档入口](index.md)开始。

## 公网部署必改清单（T10）

公网访问必须显式启用 `PUBLIC_MODE=1`。内网 HTTP 可继续使用 `PUBLIC_MODE=0` 和原有配置。公网模式会在容器启动任何服务之前、以及应用初始化数据库之前检查以下四项；不满足时明确报错并停止：

- `COOKIE_SECURE=1`：所有会话 Cookie 带 `Secure`。
- `FORCE_HTTPS=1`：业务 HTTP 请求重定向到 HTTPS，HTTPS 响应包含 HSTS。
- `TRUSTED_HOSTS`：明确列出访问域名/IP；禁止 `*`（即使混在列表内）、空条目和全地址网段。
- `FORWARDED_ALLOW_IPS`：明确列出真正代理到应用的 IP 或有限 CIDR；禁止空值、`*`、`0.0.0.0/0`、`::/0` 和非法地址。推荐固定代理 IP，专用 Docker 网段也可使用；不要把普通访问者所在网段当作可信代理。

SQLite 部署编辑根 `.env`；8002 PostgreSQL 部署编辑 `docker/.env`。示例假定 Nginx 容器在专用网络中的固定地址为 `172.20.0.5`，并可直接访问同网络应用名 `agv-pm:8000`：

```dotenv
PUBLIC_MODE=1
COOKIE_SECURE=1
FORCE_HTTPS=1
TRUSTED_HOSTS=agv.example.com,127.0.0.1,localhost
FORWARDED_ALLOW_IPS=172.20.0.5
BIND_ADDRESS=127.0.0.1
SEED_DEMO_USERS=0
```

代理地址以**应用实际看到的连接对端**为准；宿主机反代经 Docker 端口转发时可能是网桥网关，不能凭域名、外部客户 IP 或 Nginx 页面地址猜测。仅开放 HTTPS 入口，应用 8000/8002 端口绑定回环或由防火墙限制为代理可访问。`TRUSTED_HOSTS` 中的回环地址用于容器健康检查，不会允许其他业务请求绕过 HTTPS。

Nginx HTTPS 示例（替换域名和证书路径；代理与应用须在上述同一网络）：

```nginx
server {
    listen 80;
    server_name agv.example.com;
    return 308 https://agv.example.com$request_uri;
}
server {
    listen 443 ssl;
    server_name agv.example.com;
    ssl_certificate /etc/nginx/certs/agv.example.com/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/agv.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://agv-pm:8000;
        proxy_set_header Host agv.example.com;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Forwarded "";
        proxy_set_header X-Forwarded-Host "";
    }
}
```

代理必须**覆盖**客户端传入的转发头，且只把实际代理对端加入 `FORWARDED_ALLOW_IPS`。应用只根据 Uvicorn 验证后的连接 scheme 判断 HTTPS，不直接采信请求的 `X-Forwarded-Proto`；不可信客户端伪造该头仍被重定向。使用仓库的 supervisord 启动命令，或手动启动时保留 `--proxy-headers` 并使用同一个 `FORWARDED_ALLOW_IPS`；误配代理地址会造成 HTTPS 重定向循环，应修正代理信任配置。

容器内 `GET /health` 仅在**回环连接、回环 Host、无 Cookie/Authorization**时允许 HTTP，仍需通过正常 Host 白名单；此例外不覆盖任何业务 API。外部 HTTP `/health` 与其他页面一样要求 HTTPS。健康检查默认使用 `http://127.0.0.1:8000/health`，不要从 Host 白名单移除 `127.0.0.1`。

上线核对：HTTP 域名跳转到 HTTPS；`curl -sS -D - -o /dev/null https://agv.example.com/health` 返回 HSTS；HTTPS 登录响应的四个会话 Cookie 均带 `Secure`；未配置域名返回 400。修改环境文件后重建/更新容器使启动校验生效。

## 2.3.2 当前交付与部署状态（2026-10-12）

项目列表新增个人收藏、最近浏览和保留筛选的刷新；准备事项支持“我跟进的事项”，手机长名称与状态分行，确认按钮至少 44px。[本轮 10 项整改清单与页面效果](便民功能与视觉优化-20261012.md)。

最终产品源码 `0e4b7a9add2632346c9f6284bd0e4e7f04be5a2e`：后端 Python 3.12 全量 **1621 项**、前端 Node 22 全量 **116 文件 / 9权限目录中的**、TypeScript 和生产构建通过；269 份后端、288 份前端源与测试一致，170 个编译资源直接来自该构建。[测试回执](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/source-validation.json；SHA256：4ce717d776c8524cec50b3d4f5148a74be0695eedd6a1fff9e1dba69cea8ca16")。

[本机工作台](http://workflow.localhost:18004)已更新并实际重启 2.3.2，单产品容器、PostgreSQL 17.11 和 5 个服务健康。58 张表的原始数据、4 用户、7 项目、84 个原文件的内容及权限、JWT 保持一致；本轮没有数据库迁移。自动 SQL 备份轮转后仅从冻结备份补回原文件；初次补回的两份权限差异已修正并通过完整复核，没有还原业务库或修改附件。[运行保全](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/upgrade-public.json；SHA256：030239259d302f1d88e1e339fde9a8a3bd9bd3586ef9c2ab8f06967ed1c89231")、[实际页面读回](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/actual-browser.json；SHA256：424f76c119dd343a6adaba884c38cd895949a7b5dee672fdcaa09ba09e6493c0")。

ARM64 镜像沿用已验证 2.3.1 依赖基础，替换最终后端与前端；36 个历史层扫描、私密值检查和实际 Docker 导入通过。[镜像构建](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/image-build.json；SHA256：926788537c090cac806a458bb9eeef104c2242d5c8c0083ef48acfff09adfc64")、[导入核对](evidence-archive.md "原路径：docs/qa-convenience-2026-10-12/image-load.json；SHA256：fd91b608c04ec08ca80c9ebe8d7128ebc91c8c94eef811ff2fb7200b785689d5")。本轮未完整执行标准 Dockerfile，正式 NAS 和 amd64 未实机验收。

NAS ARM64 新装可加载 `agv-project-workflow-2.3.2-linux-arm64-image.tar.gz`，设置 `AGV_IMAGE=agv-pm:2.3.2`，使用对应 Compose 入口与 `--no-build`；8002 入口配置 `docker/.env`，普通入口配置根 `.env`。x86_64 使用源码按标准 Dockerfile 构建。已有实例先完整备份并保留原卷与认证配置；2.3.2 与 2.3.1 迁移头均为 `d2e7f9a103b4`。本机已保留原 2.3.1 停止容器和私有一致备份。

## 2.3.1 历史交付与部署状态（2026-10-08）

最终产品源码为 `2a3031889dd2ab5a947fd664e087351666e52f40`。后端 Python 3.12 全量1617项、前端 Node 22 全量113文件935项、TypeScript及生产构建通过；268份后端、284份前端源码与测试时逐字节一致，169份前端构建产物与镜像及源码交付包一致。[测试与构建](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/source-validation-231.json；SHA256：b2680003508bd7ce67b76e6dc80bc41311c87af8db15ae71b8ce14b02e119bf5")。

ARM64离线镜像继承已验证2.3.0依赖，替换最终后端、迁移和前端；完整历史层、7个精确私有值扫描及实际Docker导入通过。该轮未完整执行标准Dockerfile，正式NAS和amd64尚未实际验收。[镜像验证](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/offline-image-231-public-proof.json；SHA256：b6d75d09d89427928623cea915b6e78262aea3cc15a778ca0a7fea3792eb0589")。

本轮还统一正式、演练及环境示例的默认镜像标签为2.3.1；三份YAML使用PyYAML静态解析并核对单服务、构建版本和镜像默认值，不计作Compose CLI或NAS运行验收。[部署默认值校验](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/deployment-defaults-231.json；SHA256：3b7010241a7b5680075bc50ef550dc0c41271dbde29b5eef7f9f2ceb3314d84e")。

NAS ARM64新装先加载 `agv-project-workflow-2.3.1-linux-arm64-image.tar.gz`，设置 `AGV_IMAGE=agv-pm:2.3.1`，使用对应Compose入口和 `--no-build`；8002入口配置 `docker/.env`，普通入口配置根 `.env`。x86_64使用源码按标准Dockerfile构建。已有实例先一致备份，保留原卷及认证配置。新迁移头 `d2e7f9a103b4` 不可直接交给缺少该脚本的旧2.3.0镜像；兼容回退镜像保留旧程序，仅补迁移脚本，且要求两张新恢复表均为空。已有恢复记录时应保持新程序，或明确采用完整一致备份恢复策略，不能无条件回退。

本机启动入口已验证2.3.1，原登录口令保留于本机600文件。网页验收TaskSpace12已关闭且零保留，临时后端、Vite和隔离PG容器已停止清理。[启动与清理](evidence-archive.md "原路径：docs/qa-project-recovery-2026-10-08/launcher-cleanup-231.json；SHA256：b7f25b40fe7c2a81a42e7888a4bb51ae72f2d8e26e1130d84d3b82b775431519")。以下内容为历史记录。

## 2.3.0 历史交付与部署状态（2026-10-08）

管理员在“设置 → 团队与权限 → 成员权限”按成员设置权限目录中的全系统操作。权限页提供分组、搜索、继承/允许/禁止、批量、结果来源、固定保存和冲突保护；原项目、本人资料与流程资格一起校验。见[详细目录、推荐设置及16项检查清单](system-member-permissions-2026-10-08.md)。

最终产品源码 `4667f02c470dc85265ac68ce69cd3258c0a0accd`：后端1563项、256份源前后及最终Git字节一致；前端106文件886项、269份源、TypeScript和生产构建通过。全新Node22依赖安装569包及完整性校验通过，依赖版本保持原锁定值。桌面/手机浅深色、同会话授权撤销、只读字典、现场独立动作、未保存、并发合并、审计与归档拒绝完成网页检查。[最终验证](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/validation-summary.json；SHA256：c8a2b422dd04e9981e01622cfa03511b2c74cb4b8aa3aa67a5257cfc7e232164")。

[本机工作台](http://workflow.localhost:18004/pm/permissions)已在原卷升级2.3.0并真实重启；单产品容器、PG17.11和5服务健康。4用户的原12列及ID、6项目、75原文件与JWT保持，2个新权限列仅默认继承。只变更预期User列和Alembic头，技术水位仅两个时间向前。原生成SQL备份按冻结归档逐字节补回，没有恢复数据库或改写用户文件。真实网页读回权限目录中的/4成员全继承、保护入口及39条已发布日程；没有给真实成员设置新策略。[升级保全](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/upgrade-2.3.0-public-receipt.json；SHA256：bcc2e4434a4cdb080db112b8fd8e5f16294d3649f814f4f6525d7b5e6b01b0dc")、[真实网页](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/actual-pg-permissions-readback-230.json；SHA256：1be4b76ab39d8c07b4847753c8654dc4519e4ad312608756a502e2823cd56dad")。

ARM64离线镜像 `agv-project-workflow-2.3.0-linux-arm64-image.tar.gz` 为211223953B，SHA256 `6129998853e668469ecdda5ead2616621065ad46a7244ad7c4529197f6571da2`。继承已验证2.2.3依赖基础，完整替换最终后端、迁移及164前端资源；26历史层、5个精确私有值零命中及实际Docker导入通过。该轮未完整执行标准Dockerfile；正式NAS与amd64尚未实际验收。[镜像回执](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/offline-image-230-public-proof.json；SHA256：032c3d7c6d630cd8ac99f0ebafcce1321ac92309311925353a65cc82ae0aba63")。

NAS ARM64新装先加载镜像，在对应环境文件设置 `AGV_IMAGE=agv-pm:2.3.0`，沿用相应Compose入口并使用 `--no-build`；8002入口用 `docker/.env`，普通入口用根 `.env`。x86_64从交付源码按标准Dockerfile构建。已有实例先一致备份，沿用原数据卷与认证配置；新迁移头b6不能直接交给不包含该迁移脚本的旧223镜像，应使用兼容回退镜像或对应的完整升级前快照与旧镜像。

本机一键启动入口已实际运行2.3.0就绪，登录密码保持，仅本机600文件提供。Space11三页关闭、零保留，临时后端与Vite已停止。[启动](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/launcher-230-public-proof.json；SHA256：0cbdd2472ac8d3d805a5f6d56fef88d3e15c84f28aefcc8f6837608d846f9fe9")、[清理](evidence-archive.md "原路径：docs/qa-permissions-2026-10-08/browser-cleanup-230.json；SHA256：63403cbcd7cd842f11293a6b349a3ec933cb369fd5cab878c30452f218f74eeb")。以下保留历史记录。

AGV 项目管理系统是一个**单容器**应用：前端（React SPA）由后端（FastAPI）直接托管，全部运行在一个 Docker 容器里。只需一个端口、一个数据卷。

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

## 2.1.5历史交付与部署状态（2026-10-07）

项目内采用桌面左侧树目录及手机目录抽屉；首页、准备提示和全站页面按本轮布局整理，详情见[整改说明](tree-navigation-layout-2026-10-07.md)。最终前端98文件784项、构建及已登记11项网页回归通过。后端248份非版本业务与测试文件与2.1.4逐字一致，只改APP_VERSION默认文字；沿用原1448项全量基线加67项IO回归，本轮未重新跑后端全量。[源码保全](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/backend-business-source-unchanged.json；SHA256：15820fb51bfdcc0d20d1f264a81cc7e3db4573e7e819b308b8ec14211d9717c2")。

[本机成品工作台](http://workflow.localhost:18004)已保留原卷升级2.1.5并真实重启，PostgreSQL17.11、5服务RUNNING；原56表、63文件、6项目、4用户及JWT保持。原生主页操作进入对应开工排程步骤，手机目录、搜索及目标数据读回通过。[脱敏运行回执](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/upgrade-2.1.5-public-receipt.json；SHA256：8163a93b14ce433ff2571e38045729f97521e94e0039abed140b6c27919898cb")、[实际网页读回](evidence-archive.md "原路径：docs/qa-layout-2026-10-07/actual-pg-homepage-public-summary-215.json；SHA256：930ea7299482d02ce8c65fd0c6dc207dc34cacc00be37a9dcfd0f00573de832f")。

Linux/arm64离线镜像208772213B、SHA256 `d5075d2d3f434130b9824b7b6f846a94351bf4edebc9273679b0384762af2a43`，已实际save/load；`agv-workflow:2.1.5-qa`及Compose默认`agv-pm:2.1.5`同一镜像，加载后可用对应`--no-build`入口。镜像和Node验收的全部150个前端资源逐字一致。正式NAS尚未部署，amd64未实际验收，x86_64请从源码构建。

已有实例沿用自己的数据卷、认证和环境配置，使用下方与原部署形态一致的备份/更新入口。旧版本镜像、ZIP和回退条件保留；私有备份、登录资料、数据库、真实用户项目截图及运行文件不入源码包。下面旧版状态为对应历史轮次，不代表当前在线版本。

## 2.1.4历史交付与部署状态（2026-10-07）

本轮产品源码 `d0dfeb443d530715f0edcbedcc2b68aa4c90b03d` 修复人工工期在后续重排时反弹，保存项目倍率，提供仅影响后续重排的自动估算恢复入口；已有执行记录、锁定和下达不随取消预算改变。16个实际网页范围全部通过，前端98文件739项全量与构建通过；后端1448项全量基线通过后，最后仅IO路由及对应测试增加克隆预算的提前校验，由最终67项IO组覆盖，其余247份后端源码与测试字节一致。具体口径与证据见[本轮工期修复](manual-duration-regeneration-2026-10-07.md)。

[本机工作台](http://workflow.localhost:18004)已从原2.1.3实例保留原卷升级2.1.4并真实重启，仍是一个产品容器，内部PostgreSQL17.11。54张旧表、61个旧文件、4用户、6项目与JWT保持，新增2张空策略表；原项目的最新状态按升级前新鲜快照保留。网页读回32任务/1成员/35下达、4项准备及原2026-10-05完成日期，原138B附件真实下载SHA256一致。[升级与镜像回执](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/upgrade-2.1.4-receipt.json；SHA256：e52386e2bbf8579987f2ac37d23555973570e4f14a3bf328b50ff2a6e945514d")、[网页准备清单](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-preparation.png；SHA256：136b9f66abb83c03a00af93ed79053262510725c2b3dc01edf9105c8e3fd2cfd")、[网页下载证明](evidence-archive.md "原路径：docs/qa-duration-2026-10-07/pg-final-browser-download.json；SHA256：66598139504b6901487c65e0fdecc786fc1f1d0f92bfee28826d0784e25f9d3c")。

Linux/arm64离线镜像208769692B，SHA256 `4a317f9a4ed0409a0592d704ee237e983afe2b6f09eb5167feaaff02abb75a2d`，已实际 `docker load`。包内 `agv-workflow:2.1.4-qa` 与源码Compose默认 `agv-pm:2.1.4` 指向同一镜像，可加载后使用对应Compose的 `--no-build` 入口。x86_64 NAS从[交付仓库](https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow)取得源码并按下方现有安装/更新流程本机构建；本轮未把ARM64测试称为amd64验证，尚未更新正式NAS。

已有实例沿用自己的数据库、附件、认证和环境配置，执行与其原部署形态对应的备份更新入口；本轮新增两张表由启动建表，不替换原业务表或工时。2.1.3离线镜像、旧回退容器及升级前一致私有备份保留。本机私有配置、登录资料、数据库与业务附件不进入源码或镜像交付包。

## 2.1.3历史部署状态（2026-10-06）

本轮业务版本2.1.3，最终产品源码`c2e8649`，新增[14项快捷操作与流程整改及54份证据文件](usability-remediation-2026-10-06.md)，项目默认草稿及阶段契约见[生命周期说明](project-lifecycle-remediation-2026-10-06.md)。14项已实际网页回归，最终前端97文件719项（130.13秒）、后端1362项及构建通过；三条权限提示及原PG实例升级后的网页读回通过，见[最终验证摘要](evidence-archive.md "原路径：docs/qa-usability-2026-10-06/validation-summary.json；SHA256：38ee1596cd095f990c3268dd4cf8f8b5ccf72144b827a6e060c55612f2dd1140")。

本机[成品工作台](http://workflow.localhost:18004)已在原单产品容器/容器内PostgreSQL数据卷升级2.1.3并真实重启，原用户及6项目保留；53张业务表、58个原文件及JWT一致。网页实际读回32任务/1成员/35下达、准备原状态及10/05完成日期、目标与甘特快捷入口，原138B附件真实下载一致。升级前完成一致备份；新安装或已有实例更新均按下方对应部署形态使用入口，沿用持久数据与认证配置，不替换为验收数据库。

最终`c2e8649` Linux/arm64离线镜像已实际save/load，208750992B、SHA256 `cd84168b7eaecc02a1475458aa7ba3098adf66f99d7ff05513fe9869db05e39d`。包内`agv-workflow:2.1.3-qa`和源码Compose默认`agv-pm:2.1.3`指向同一镜像，arm64下加载后可使用`docker/docker-compose.yml`的`--no-build`入口；x86须重新构建。amd64尚未实际验收；本文架构支持和Registry多架构发布要求不等于本轮已交付多架构镜像。正式NAS尚未取得部署目标和访问条件，本轮没有更新正式NAS。下文旧版本标签与实测段落保留为历史示例，不能作为2.1.3已安装的证明；当前结果统一见[交付说明](browser-audit-delivery.md)与[验证记录](evidence-archive.md "原路径：docs/qa-final-validation.txt；SHA256：80a89ee8c819dacb854118e29395343668e19067564de7cc99813a929cb840a6")。

## 环境要求

| 项目 | 要求 |
|---|---|
| Docker | 20.10+（群晖 Container Manager / QNAP Container Station / Unraid 均可用） |
| CPU | x86_64 或 arm64（如群晖 ARM 机型） |
| 内存 | ≥ 512MB（限制值 512MB，建议 1GB） |
| 存储 | 数据文件约几 MB ~ 几十 MB |

## 首次部署（群晖 NAS）

通过 SSH 登录 NAS。以下使用 `/volume1/docker/agv-pm`；QNAP 或其他 NAS 请替换为自己的绝对路径。

```bash
mkdir -p /volume1/docker
cd /volume1/docker
git clone --branch v1.9.0 https://gitea.arrowwood.top:8773/claude/agv-pm.git
cd agv-pm
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，首次至少确认下面这些值：

```dotenv
DEPLOY_MODE=build
APP_VERSION=1.9.0
AGV_IMAGE=agv-pm:1.9.0
INITIAL_ADMIN_PASSWORD=请换成至少16位的独立强密码
SEED_DEMO_USERS=0
BIND_ADDRESS=127.0.0.1
APP_PORT=8000
DATA_PATH=/volume1/docker/agv-pm-data
BACKUP_DIR=/volume1/backup/agv-pm
TRUSTED_HOSTS=agv.example.com,192.168.1.137
FORCE_HTTPS=1
MAX_BACKUP_UPLOAD_MB=2048
MAX_BACKUP_EXPANDED_MB=8192
```

### AI 项目整理助手（可选）

系统的分域 AI 助手统一使用 OpenAI Chat Completions 兼容协议，内置 DeepSeek、小米 MiMo、MiniMax 三组预设。项目建档、排程研判、问题分诊、现场物品和交接归档分别使用独立 Skill，并显示读取、调用、解析、校验进度。未配置时不影响任何手工业务。

Unraid 容器模板中至少新增：

```dotenv
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的 DeepSeek 密钥
MIMO_API_KEY=你的小米 MiMo 密钥
MINIMAX_API_KEY=你的 MiniMax 密钥
AI_TIMEOUT_SECONDS=180
```

只需填写实际使用的密钥。默认模型分别为 `deepseek-v4-flash`、`mimo-v2.5-pro`、`MiniMax-M2.7`，可用 `DEEPSEEK_MODEL`、`MIMO_MODEL`、`MINIMAX_MODEL` 覆盖。小米 Token Plan 用户可设置 `MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1`。

自建服务设置 `AI_PROVIDER=custom`、`AI_PROVIDER_NAME`、`AI_BASE_URL`、`AI_MODEL`、`AI_API_KEY`。如果内网服务不校验密钥，可将 `AI_API_KEY` 留空并设置 `AI_ALLOW_NO_KEY=1`。系统会请求 API 根路下的 `/chat/completions`。

密钥只在后端读取，不会返回前端；上传原文不落盘，但提取后的文字会发送给页面中选择的 AI 服务，应按你与该服务商的数据协议使用。

公网部署不要在前端代码、导入 JSON、Gitea 仓库或截图中填写密钥。如需 Docker Secret，可改用 `AI_API_KEY_FILE=/run/secrets/ai_api_key`。

`SECRET_KEY` 可留空，系统会在数据目录生成并持久化随机密钥。不要把密码或密钥提交到 Git。

开始部署并检查：

```bash
bash docker/scripts/manage.sh install
bash docker/scripts/manage.sh status
```

成功时 `/health` 会返回当前版本，例如 `{"status":"ok","version":"1.9.0"}`。首次账号是 `admin`，密码是 `.env` 中的 `INITIAL_ADMIN_PASSWORD`。

### 公网访问

在 NAS 反向代理中配置：

```text
外部：https://agv.example.com:443
内部：http://127.0.0.1:8000
```

只向公网开放 HTTPS，禁止直接转发数据库目录、备份目录或 Docker API。域名证书生效后再设置 `FORCE_HTTPS=1`。

### Registry 部署（外网鉴权修复后）

镜像发布到 Gitea Registry 后，NAS 可跳过本地构建，直接拉取多架构镜像：

```bash
docker login gitea.arrowwood.top:8773
sed -i 's|^DEPLOY_MODE=.*|DEPLOY_MODE=registry|' .env
sed -i 's|^AGV_IMAGE=.*|AGV_IMAGE=gitea.arrowwood.top:8773/claude/agv-pm:1.9.0|' .env
bash docker/scripts/manage.sh install
```

发布镜像需同时包含 `linux/amd64` 和 `linux/arm64`。账号密码只交给 `docker login`，不要写入 `.env` 或 Compose 文件。

### GitHub 自动构建（GHCR）

GitHub 仓库的 `.github/workflows/docker-image.yml` 会自动构建 `linux/amd64` 与 `linux/arm64` 镜像，发布到 `ghcr.io/knxckbackwili/xingxu`：

| 触发 | 发布的标签 | 用途 |
|---|---|---|
| 推送 `master` | `edge`、`sha-<7 位提交号>` | 试用最新代码；`sha-` 标签固定不变，可用于回滚 |
| 推送 `v<版本>` 标签 | `<版本>`、`latest` | 正式版本；先运行 `release-check.sh`，标签必须与 `frontend/package.json` 版本一致 |

仓库是私有的，镜像默认也是私有。NAS 先用 GitHub 账号和一个只勾选 `read:packages` 的个人访问令牌登录，再切换为 registry 模式：

```bash
docker login ghcr.io -u <GitHub 用户名>
sed -i 's|^DEPLOY_MODE=.*|DEPLOY_MODE=registry|' .env
sed -i 's|^AGV_IMAGE=.*|AGV_IMAGE=ghcr.io/knxckbackwili/xingxu:3.4.0|' .env
bash docker/scripts/manage.sh install
```

正式环境使用版本号或 `sha-` 标签，不要直接跟随 `edge`。

默认只监听 NAS 本机 `127.0.0.1:8000`。在群晖/QNAP 的反向代理中创建一个 HTTPS 域名，将上游指向 `http://127.0.0.1:8000`，不要直接把 8000 端口映射到公网。如确需局域网直连，把 `.env` 的 `BIND_ADDRESS` 改为 `0.0.0.0`。

公网启用时必须按文首清单配置：

```dotenv
PUBLIC_MODE=1
TRUSTED_HOSTS=agv.example.com,127.0.0.1,localhost
FORWARDED_ALLOW_IPS=172.20.0.5
FORCE_HTTPS=1
COOKIE_SECURE=1
```

### Nginx Proxy Manager（NPM）反代 8002（T023，2026-08-25 实测）

以 `docker-compose.multica.yml` 部署到 8002 时，端口按 `BIND_ADDRESS:8002 → 8000` 发布（历史未配置时为 `0.0.0.0`；公网设 `127.0.0.1` 或防火墙限制代理来源），容器内 uvicorn 监听 `0.0.0.0:8000`。`TRUSTED_HOSTS` 默认仅本机回环（`127.0.0.1,localhost`）；被 NPM 反代时必须在 `docker/.env` 显式加入访问域名（如 `agv.example.com`），否则 Host 校验会拒绝请求。

**NPM Proxy Host 配置（三条即可）：**

| 配置项 | 值 |
|---|---|
| 域名（Domain Names） | `agv.example.com`（或你的外网域名） |
| Scheme / Forward Hostname | `http` + 宿主机局域网 IP（如 `192.168.1.136`）；若 NPM 与 8002 同 Docker 网络，可直接填容器名 `agv-pm-8002` + 端口 `8000` |
| Forward Port | `8002`（指向宿主机映射端口；同一网络指向容器时填 `8000`） |
| WebSockets Support | **开启**（`/Advanced` 里勾选 `Websockets Support`，为 WebSocket 链路预留） |

**为什么这样可行（本次修复的落点）：**

1. **SSE 流式无需在 NPM 手动关缓冲**：AI 对话流式是 `text/event-stream`。nginx/NPM 默认 `proxy_buffering on` 会把整段 SSE 缓冲、流结束才吐出，表现为"反代后 AI 聊天挂起"。后端已在 SSE 响应加 `X-Accel-Buffering: no`（`backend/app/routers/ai_projects.py`），nginx/NPM 自动即时转发，无需在 NPM 面板改任何缓冲设置。
2. **代理头默认不信任任意来源（T024 加固）**：`FORWARDED_ALLOW_IPS` 默认**为空**，容器内 uvicorn 因此不信任代理头（原生启动且完全未设置该环境变量时，Uvicorn 默认仅信任 `127.0.0.1`）。直连 8002 的局域网/外部客户端伪造 `X-Forwarded-For/Proto` 会被一律忽略（登录审计 IP 与登录限流均使用真实对端，伪造头无法绕过限流）。需要 NPM 反代拿到真实客户端 IP 与 https scheme 时，将 `FORWARDED_ALLOW_IPS` 显式配置为 NPM 可信地址/网段（见下方「T024 配置」）。
3. **完整链路已验证**：临时反代容器（独立 bridge 网络 → 宿主机 `host.docker.internal:8002`）实测——页面加载、深链刷新、登录、登录后 API、SSE 流式（含 `X-Accel-Buffering: no`）全部 200；宿主机局域网 IP（如 `192.168.1.136:8002`）直连同样 200。
4. **常见误区**：NPM 的 Forward Hostname 不要填 `127.0.0.1`（NPM 容器自己的回环地址，会连接拒绝）；应填宿主机局域网 IP、`host.docker.internal`，或同网络容器名。容器内服务间调用不受影响（`NO_PROXY=*` 已兜底）。

**HTTPS 反代必须同步设 `COOKIE_SECURE=1`（HYPE-99）**：浏览器会话已改为 HttpOnly Cookie 承载（不再把令牌写进 localStorage）。NPM 在容器外终止 HTTPS，容器内 uvicorn 看到的仍是 http——`FORCE_HTTPS=1` 负责 HTTPS 重定向和 HSTS，`COOKIE_SECURE=1` 单独负责 Set-Cookie 的 Secure 属性。若 `docker/.env` 不设 `COOKIE_SECURE=1`，https 页面下浏览器会拒绝非 Secure 的 HttpOnly Cookie，表现为**登录接口 200 成功、但随后每个请求都 401，界面回到登录页**。在 `docker/.env` 加一行再 `make update`：

```dotenv
COOKIE_SECURE=1
```

### T024 配置：`FORWARDED_ALLOW_IPS`（代理头信任，默认安全）

| 场景 | `FORWARDED_ALLOW_IPS` | uvicorn 行为 |
|---|---|---|
| 容器默认 | 空 | 不信任代理头；局域网/外部伪造 `X-Forwarded-*` 一律忽略 |
| 原生 Uvicorn 默认 | 完全不设置环境变量 | Uvicorn 默认仅信任 `127.0.0.1` |
| NPM 反代（推荐） | NPM 容器 IP，如 `172.17.0.5` | 仅该可信代理转发的 `X-Forwarded-For/Proto` 生效，登录审计/限流按真实客户端 |
| NPM 反代（同网段） | 桥接网段，如 `172.16.0.0/12` | 该网段内可信；**注意**：若网段含 Docker 网关（`*.0.1`），经发布端口直连的外部流量源 IP 即网关，也会被信任——生产更推荐收敛到 NPM 容器具体 IP |

```dotenv
# .env 示例：NPM 容器与 8002 同 Docker 网络时，收敛到 NPM 容器 IP
FORWARDED_ALLOW_IPS=172.17.0.5
# 或用 docker network inspect 查看 8002 所在网络里 NPM 容器的 IP
```

安全基线（T024 回归测试 `docs/scripts/t024_proxy_security_test.py` 与 `backend/tests/test_proxy_security.py` 覆盖）：
- 默认模式下，非可信对端伪造 `X-Forwarded-For` 无效——uvicorn 访问日志与登录失败 key 均用真实对端 IP；
- 轮换伪造头无法绕过登录限流（第 9 次仍按真实对端触发 429）；
- 显式配置可信网段后，可信代理转发的头生效（审计 IP = 转发头中的真实客户端）。

### T025 登录失败限流：PostgreSQL 原子共享计数（多 worker / 重启不绕过）

登录失败限流（阈值 8 次、窗口 15 分钟）由进程内 `_login_failures` 改为 **PostgreSQL 共享计数**，复用 T006 导出限流的共享桶设计：

- **表** `login_failure_buckets`：`key`=真实客户端 IP + 用户名（`request.client.host`，T024 可信代理后即真实客户端）、`bucket`=当前固定窗口、`window`=窗口秒数（PG 保留字，SQL 内双引号引用）、`count`=失败数。启动 `create_all` 自动建表，无需迁移操作。
- **原子性**：`INSERT ... ON CONFLICT (key, bucket, "window") DO NOTHING` 幂等建行 + `UPDATE ... SET count = count + 1 WHERE count < :limit RETURNING count` 原子递增——PG 行锁保证并发（含 `WEB_CONCURRENCY=2` 多 worker）下恰好 8 次成功，第 9 次返回空 → 429。
- **语义不变**：仅统计失败；**成功登录清空**该 key 全部失败计数；每桶清理早于上一桶的过期行防膨胀；SQLite/单进程保留原内存路径（测试与本地行为不变）。
- **运行时回归**：`docs/scripts/t025_login_limit_test.py`（真实 8002 单容器）：确认 uvicorn `--workers 2`（master + 2 worker 子进程）、顺序 9 次失败登录前 8 次 401 第 9 次 429（跨 worker 全局累计）、不同账号隔离（PG 两 key 计数 {8,1}）、`docker restart` 后同一账号仍 429（窗口未被绕过）、重启后另一账号仍 401、清理测试行后 `/health` 200。

### HYPE-24：`TRUSTED_HOSTS` 白名单支持 IP 网段（CIDR）

**故障链路（复现定位）**：HYPE-19 暴露面收口把 `docker/.env` 的 `TRUSTED_HOSTS` 配成
**静态精确 IP 白名单**（回环 + 本机 hostname + 两个 LAN IP）。Starlette 自带
`TrustedHostMiddleware` 只做精确匹配/`*.domain` 后缀通配，无法表达"整个局域网网段"，
于是以下任一合法访问都会被 400 `Invalid host header` 拒绝：

- 经 NPM/nginx 反代以**公网域名**访问（Host = 域名，不在白名单）；
- **DHCP 重新分配 LAN IP**（Host = 未逐条列出的新 IP）；
- 新增**网卡/VPN 接口**（Host = 白名单外本机其他接口 IP）。

**修复（不放开校验）**：`backend/app/middleware.py` 新增 `TrustedHostsMiddleware`，
在保留精确/`*.domain` 语义基础上支持 **IP 网段（CIDR）** 条目；未命中任何条目仍返回
400 `Invalid host header`。回归测试 `backend/tests/test_trusted_hosts.py`（8 项）与全量
pytest 通过。

**部署侧配置**：把白名单中的精确 LAN IP 收敛为网段，并补上反代域名。示例：

```dotenv
# docker/.env（8002 单容器部署）
TRUSTED_HOSTS=127.0.0.1,localhost,HUAWEI-Harmony-mini.local,192.168.1.0/24,agv.example.com
```

- `192.168.1.0/24`：该网段任意 IP 可访问，DHCP 换 IP / 新增网卡不失效；
- `agv.example.com`：反代访问的公网域名必须显式列出（或 `*.example.com`），否则
  反代链路仍 400；
- 不要用 `TRUSTED_HOSTS=*` 掩盖问题——任意 Host 校验仍保留。

### 手动构建运行

```bash
cd AGV-项目管理
docker build -f docker/Dockerfile -t agv-pm .
docker run -d \
  --name agv-pm \
  -p 8000:8000 \
  -e SECRET_KEY="请替换为随机长字符串" \
  -e INITIAL_ADMIN_PASSWORD="请替换为至少8位的首次密码" \
  -e SEED_DEMO_USERS=0 \
  -v /path/to/data:/app/data \
  --restart unless-stopped \
  agv-pm
```

## 首次使用

生产模式首次只创建管理员账号：

| 账号 | 密码 | 角色 |
|---|---|---|
| admin | `.env` 中的 `INITIAL_ADMIN_PASSWORD` | 管理员（用户管理） |

本地演示如需预置 `pm`、`worker1`、`worker2`，可在 `.env` 设置 `SEED_DEMO_USERS=1`。该选项仅在空数据库首次启动时生效，不建议用于生产。

修改密码：登录后 → 右上角头像 → 修改密码（或由管理员在「用户管理」中修改）。

存量 admin 的运维轮换（忘记当前密码 / 计划性轮换）：在 `.env` 设置 `ADMIN_PASSWORD_ROTATE=1` 并同时提供 `INITIAL_ADMIN_PASSWORD`（≥8 位）后重启，启动时会显式改密并使所有已登录会话失效；密码未变时幂等跳过。轮换完成后建议移除 `ADMIN_PASSWORD_ROTATE=1`，避免每次重启重复轮换。明文只从环境变量读取，不会写入日志或落盘。

## 数据与备份

所有数据保存在挂载卷的 `data/` 目录下：

```
data/
├── agvpm.db          # SQLite 数据库（全部业务数据）
├── agvpm.db-wal      # WAL 日志（运行时产生）
├── secret.key        # 登录令牌密钥
├── uploads/          # 项目与交付附件
└── backups/          # 系统界面生成的完整备份
```

推荐使用项目自带脚本执行在线一致性备份：

```bash
bash docker/scripts/backup.sh
```

脚本会把数据库一致性快照、附件和持久化密钥打包到 `backups/agv-pm-日期时间.tar.gz`。可通过 `BACKUP_DIR=/备份目录` 修改输出位置。直接复制 `data/` 仅建议在容器停止后进行。

恢复使用 `bash docker/scripts/manage.sh restore /备份路径/agv-pm-时间.tar.gz`。系统会在容器启动前校验并恢复，且自动保存恢复前快照。不要在运行中的容器上手工覆盖数据库。

### 定时自动备份（推荐）

在 NAS 任务计划中每天执行：

```bash
cd /volume1/docker/agv-pm && bash docker/scripts/manage.sh backup
```

备份包含数据库一致性快照、上传附件和登录密钥，并生成 SHA-256 校验文件。再用 Hyper Backup、rsync 或对象存储把 `/volume1/backup/agv-pm` 同步到另一台设备；同一块 NAS 里的备份不能防硬盘或整机故障。保留建议：每日 30 份、每月 12 份，每季度做一次恢复演练。`backup.sh` 已按此建议实现自动轮转：默认日备保留 30 份、月备保留 12 份（每个日历月最新一份），可通过 `BACKUP_KEEP_DAILY` / `BACKUP_KEEP_MONTHLY` 覆盖；pre-restore 快照（`agvpm-pre-restore-*`）纳入轮转并单独设保留数 `BACKUP_KEEP_PRE_RESTORE`（默认 20）。迁移前快照（`agvpm-before-migrate-*`，应用启动时生成）保留最近 20 份的逻辑不变。

## 后续更新

发布新版本后，先安排短暂维护窗口。以 `v1.9.0` 为例：

```bash
cd /volume1/docker/agv-pm
git fetch --tags origin
git checkout v1.9.0
bash docker/scripts/manage.sh update
bash docker/scripts/manage.sh status
```

源码构建模式会自动把 `.env` 的 `APP_VERSION` 和本地镜像标签同步到新版本。Registry 模式需先把 `AGV_IMAGE` 改为已发布的新版本镜像。不要使用 `latest`。

更新脚本会：

1. 在线生成数据库、附件和密钥的完整一致性备份及校验值。
2. 将正在运行的旧镜像保存为带时间戳的回滚镜像。
3. 在旧容器继续在线时先构建或拉取固定版本，完成后才进入切换窗口。
4. 重新创建唯一的 `agv-pm` 容器，等待 Docker 健康检查并请求 `/health`。
5. 新版失败时自动恢复旧镜像和升级前数据，并保存失败日志。

更新成功后登录核对项目数、用户数、附件和一条核心业务流程。升级前备份与回滚镜像至少保留 7 天。

## 回滚与恢复

新版健康但业务验证发现问题时：

```bash
cd /volume1/docker/agv-pm
bash docker/scripts/manage.sh rollback
```

该命令只切回旧镜像，不会删除更新后新增的数据。若确认数据库迁移与旧版不兼容，再按照命令输出的备份路径执行 `restore`。恢复备份会丢弃备份时间点之后的数据，应先征得业务负责人确认。

常用运维命令：

```bash
bash docker/scripts/manage.sh status
bash docker/scripts/manage.sh backup
docker logs --tail 200 agv-pm
```

## 一键验证（可选）

在任意有 Docker 的机器上运行：

```bash
bash docker/scripts/verify.sh
```

脚本会自动：构建镜像 → 启动容器 → 登录 → 建项目/车型 → 生成任务 → 排程 → 检查 SPA/PWA → 清理。全部通过即说明构建链路正常。

## 正式部署（单容器 PostgreSQL，8002）

从 v2.1 起支持**容器内 PostgreSQL**：仍是单容器，但数据库由 supervisord 托管的 PostgreSQL 17 承担（A1/A2），适合 500 项目级并发写入。这是**正式部署**使用的唯一入口（`make deploy` / `make update`），统一由 `docker/scripts/deploy.sh` 驱动。

### 需要配置的变量（极少）

只需准备一个 `docker/.env`（从 `docker/.env.example` 复制），通常只填前几项：

```bash
cp docker/.env.example docker/.env
chmod 600 docker/.env
# 编辑 docker/.env，首次部署至少设置 INITIAL_ADMIN_PASSWORD（≥8 位）
```

| 变量 | 说明 | 默认 |
|---|---|---|
| `INITIAL_ADMIN_PASSWORD` | 首次部署必填（≥8 位）；`SEED_DEMO_USERS=0` 时未设置会启动失败 | 空 |
| `SEED_DEMO_USERS` | `0`=仅 admin（正式）；`1`=额外建演示账号（评审/演示用） | `0` |
| `TRUSTED_HOSTS` | Host 白名单：域名/IP/`*.domain`/IP 网段（CIDR） | `127.0.0.1,localhost` |
| `PUBLIC_MODE` | `1` 启用公网配置强制检查；内网 HTTP 用 `0` | `0` |
| `FORWARDED_ALLOW_IPS` | 反代可信 IP/有限网段；公网模式必须显式配置 | 空 |
| `WEB_CONCURRENCY` | uvicorn worker 数 | `2` |
| `COOKIE_SECURE` | `1`=HTTPS 反代前置时给会话 Cookie 打 Secure。容器内 uvicorn 看到的是 http，`FORCE_HTTPS=1` 负责重定向和 HSTS，不替代 `COOKIE_SECURE=1`——https 页面下浏览器会拒绝非 Secure 的 HttpOnly Cookie，表现为登录成功但随即回到登录页/接口 401 | `0` |
| `COOKIE_SAMESITE` | 会话 Cookie SameSite 策略：`lax`（默认）/ `strict` / `none`（`none` 必须同时 `COOKIE_SECURE=1`） | `lax` |
| `ADMIN_PASSWORD_ROTATE` | `1` 且提供 `INITIAL_ADMIN_PASSWORD` 时启动显式改密并使旧会话失效（幂等） | `0` |
| `AGV_IMAGE` / `APP_VERSION` | 镜像标签与版本（自动从源码同步，一般无需改动） | 自动 |

> 演示账号（`SEED_DEMO_USERS=1`）若仍持默认口令（pm123/worker123），seed 会在启动时幂等禁用并失效其旧会话；需保留演示角色请先用 `DEMO_ADMIN_PASSWORD` / `DEMO_PM_PASSWORD` / `DEMO_WORKER_PASSWORD` 轮换为强口令。

其余变量（AI 密钥、备份上限等）不配置即用内置默认值。**二次部署通常无需改动任何变量。**

### 首次部署

```bash
make deploy
```

流程：构建镜像 → 启动单容器（容器内 PostgreSQL）→ 等待健康检查。成功输出 `/health` 版本号与访问地址 `http://127.0.0.1:8002`。首次登录账号 `admin`，密码为 `docker/.env` 中的 `INITIAL_ADMIN_PASSWORD`。

### 二次部署（更新到当前代码）

```bash
# 拉取新代码后，一条命令完成二次部署：
git pull
make update
```

`make update` 自动完成四步，**失败自动回滚，无需手工干预**：

1. 构建新镜像（当前容器保持在线，不中断服务）；
2. 全量备份（`pg_dump -Fc` → `backups/`）并**立即校验备份 SHA-256**，校验不过则中止更新（不留不可回滚的现场）；保留旧镜像为回滚镜像；
3. 切换到新镜像；
4. 等待健康检查；未通过则自动回滚——**先切回旧镜像，再恢复已校验备份，最后做最终健康检查**（成功才输出“已自动回滚…已恢复”），输出失败日志路径。

安全保证：备份恢复（`restore.sh`）前**强制校验 SHA-256**，校验失败拒绝执行破坏性恢复（不 dropdb/createdb）；自动回滚区分两条失败路径——容器切换命令失败时只切回旧镜像并检查健康（数据未动，不盲目恢复）；新版本健康检查失败时**不以恢复前的旧镜像健康为门槛**（迁移可能令旧版本与新 schema 不兼容，恢复前健康检查会提前退出），而是切回旧镜像 → 恢复已校验备份 → 再做最终健康检查，且只有“切回旧镜像 + 恢复数据 + 最终健康检查”全部成功才输出“已自动回滚…已恢复”的成功措辞，任一步失败都会明确报错并保留失败日志（`backups/failed-update-*.log`、`backups/failed-restore-*.log`），不会误报恢复成功。

更新成功后核对 `/health` 版本与核心业务数据即可。回滚镜像与更新前备份保留在 `backups/`。

### PostgreSQL 恢复失败时

`restore.sh` 会先记录原应用服务状态，再停止 `web`、`scheduler`、`healthwatch`，并确认三者均为 `STOPPED`，保留 PostgreSQL 服务供恢复使用。无法确认停止状态时，脚本不会进入恢复，也不会自动启动服务。确认停写后，若恢复前快照或归档校验失败，数据库和文件尚未改动，脚本只恢复本次操作前确实为 `RUNNING` 的服务，并返回非零退出码；原本已停止或原状态未知的服务保持停止，避免失败后的维护重试再次启动半恢复状态。

一旦开始替换文件或恢复数据库，后续失败会返回非零退出码，并明确显示“服务保持停止”。此时保持维护停写，不要直接重启容器或手动启动应用服务；保留失败输出、原完整备份以及输出中列出的 `agvpm-pre-restore-*.dump`。该 dump 只包含恢复前数据库，不包含附件和密钥，不能代替完整备份。

先排除磁盘空间、文件权限或数据库恢复报错，再对来源可靠、校验通过的完整备份重新执行 `restore.sh`。只有文件与数据库恢复均成功后，脚本才启动应用服务；随后检查 `/health`、项目和附件。若启动应用服务本身失败，脚本也会返回非零退出码，不会输出“恢复完成”。恢复会覆盖当前数据，选择恢复时间点前应与业务负责人确认。

SQLite 恢复请求同样先核实停写；备份先复制到临时文件，复制完整后才发布为 `restore-pending.tar.gz`。提交或启动服务失败均返回非零退出码。成功输出“恢复请求已提交”，表示交给应用启动引导处理，仍需在重启后核对 `/health`、项目与附件，不表示已经完成数据验收。

### 其他运维命令

```bash
make status        # 容器状态 + /health
make logs          # 跟踪日志
make backup        # 全量备份（pg_dump -Fc → backups/）+ 旧包轮转
make restore BACKUP=backups/agv-pm-xxx.tar.gz   # 恢复（PG/SQLite 自动识别；恢复前强制 SHA-256 校验）
make rollback      # 回滚到上一次 update 前的镜像（依据状态文件 PREVIOUS_REF，不覆盖数据）
```

> `make rollback` 以更新时记录的 `PREVIOUS_REF`（上一次 update 前容器实际使用的镜像引用）为回滚目标，自定义 `AGV_IMAGE` 或版本升级后同样能精确回到更新前镜像，不依赖写死的 `2.1.0`。

要点：

#### O2：unhealthy 自动重启（容器内看门狗）

`restart: unless-stopped` 只在容器进程退出时生效，`/health` 失败（如 uvicorn 多 worker 全部挂起、PG 故障）不会触发重启，容器可能带病运行。本版本在 **不改变单容器部署形态** 的前提下，由 supervisord 新增 `healthwatch` 进程实现 health-based 自愈：

- 每 `HEALTH_CHECK_INTERVAL`（默认 15s）GET `HEALTH_CHECK_URL`（默认 `http://127.0.0.1:8000/health`）；
- **连续失败 `HEALTH_FAIL_THRESHOLD` 次**（默认 3，约 45s）→ `supervisorctl restart web`，快速恢复 web 挂起而无需重启整个容器；
- **同一窗口内 web 重启达 `HEALTH_WEB_RESTART_LIMIT` 次**（默认 2）仍未恢复 → `supervisorctl shutdown`，容器主进程退出 → Docker 按 `restart: unless-stopped` 重建容器（覆盖 PG/整体性故障）；
- **启动窗口**：应用首次成功前 `HEALTH_START_GRACE` 秒（默认 180）内只观察不动作，避免 PG 初始化/迁移阶段误判；应用成功过一次后立即进入正常判断。

权衡：autoheal sidecar 需额外常驻容器 + Docker socket（破坏单容器形态、提升攻击面）；宿主 watchdog 需 NAS 上额外 systemd/cron（逻辑不在仓库内）。看门狗为仓库内代码（`backend/app/services/healthwatch.py`），零外部依赖，两个 compose（SQLite 基线与 8002/PG）默认都启用。参数均可用环境变量覆盖（见 `.env.example`）。

#### C6-1：问题 SLA 扫描配置

每分钟扫描尚未关闭或作废的问题，按性质使用经过小时阈值，并用持久凭据避免重复通知 PM 与总监。普通问题的小时配置留空时兼容原天数配置：

```dotenv
ISSUE_SLA_DAYS=3
ISSUE_SLA_NORMAL_HOURS=
ISSUE_SLA_ACCIDENT_HOURS=24
ISSUE_SLA_QUALITY_HOURS=24
REPORT_WEEKLY_TIME=20:00  # 每个项目当地周日晚
```

修改后重启容器（`make deploy` 或 `docker compose -f docker/docker-compose.multica.yml up -d`）生效。

### 部署参数（8002 单容器）

**几乎零配置即可启动**：不准备 `.env` 时 `make deploy` 直接使用 compose 默认值——演示账号
`admin/admin123`、数据库为容器内 PostgreSQL、宿主端口 `8002`。

需要覆盖参数时写 `.env` 并注意其位置：`make deploy` 等价于
`docker compose -f docker/docker-compose.multica.yml up -d --build`，compose 从
**compose 文件所在目录（`docker/`）** 读取 `.env`（`docker/.env`）；而 `manage.sh`
基线显式 `--env-file` 指向仓库根 `.env`，两者不是同一个文件。

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `INITIAL_ADMIN_PASSWORD` | 视模式 | 空 | 非空值一律用作 admin 密码且必须 ≥8 字符（`seed_data.py` 校验，演示模式下同样生效——短密码即使 `SEED_DEMO_USERS=1` 也会启动失败）；`SEED_DEMO_USERS=0` 时必填；留空且演示模式时 admin 用 `admin123` |
| `SEED_DEMO_USERS` | 否 | `1`（本 compose；`.env.example` 的 `0` 是 SQLite 基线默认） | `1` 预置演示账号 `admin/admin123`、`pm/pm123`、`worker1/worker2/worker123`；`0` 仅建 admin |
| `SECRET_KEY` | 否 | 空 | 留空自动生成并持久化到 `/app/data/secret.key`（重启不失效）；生产建议显式设置 |
| `APP_PORT` | 否 | `8002` | 宿主映射端口 → 容器内 `8000`。若 `docker/.env` 直接复制了 `.env.example` 的 `APP_PORT=8000`，会覆盖为 8000，不再是 8002 |
| `AGV_IMAGE` | 否 | `agv-pm-multica:2.1.2` | 固定版本标签；生产不要用 `latest` |
| `TRUSTED_HOSTS` | 否 | `*` | 逗号分隔 Host 白名单：精确域名/IP、`*.domain`、CIDR 网段（`192.168.1.0/24`）；生产收敛为局域网网段 + 反代域名，否则反代访问 400 |
| `PUBLIC_MODE` | 公网必须 | `0` | `1` 强制校验 HTTPS、Secure Cookie、Host 和代理信任配置 |
| `FORWARDED_ALLOW_IPS` | 公网必须 | 空 | NPM/nginx 反代时填可信代理地址/网段（如 NPM 容器 IP），uvicorn 才信任 `X-Forwarded-*`；容器默认空值不信任代理头 |
| `FORCE_HTTPS` | 否 | `0` | HTTPS 反代正确配置后设 `1`（重定向业务 HTTP 并下发 HSTS） |
| `COOKIE_SECURE` | 否 | `0` | 会话 Cookie 打 Secure。NPM/nginx 终止 HTTPS 后容器内 uvicorn 看到的是 http（`FORCE_HTTPS=1` 不会传导给 Cookie），https 页面下浏览器拒绝非 Secure 的 HttpOnly Cookie → 登录成功但无会话/接口 401；**HTTPS 反代部署必须设 `1`**，本地/内网 http 直连保持 `0` |
| `COOKIE_SAMESITE` | 否 | `lax` | 会话 Cookie SameSite：`lax`/`strict`/`none`（`none` 必须同时 `COOKIE_SECURE=1`） |
| `WEB_CONCURRENCY` | 否 | `2` | uvicorn worker 数；多 worker 下登录/导出限流由 PostgreSQL 共享计数保证 |
| `MAX_BACKUP_UPLOAD_MB` / `MAX_BACKUP_EXPANDED_MB` | 否 | `2048` / `8192` | 备份上传 / 恢复解压大小上限 |
| AI（可选，可全不配） | 否 | 见说明 | `AI_PROVIDER`（`deepseek`）、`DEEPSEEK_API_KEY/MODEL/BASE_URL`、`MIMO_API_KEY/MODEL/BASE_URL`、`MINIMAX_API_KEY/MODEL/BASE_URL`；自建服务 `AI_PROVIDER=custom` + `AI_PROVIDER_NAME`/`AI_BASE_URL`/`AI_MODEL`/`AI_API_KEY`，内网不校验密钥可加 `AI_ALLOW_NO_KEY=1`；`AI_TIMEOUT_SECONDS`（180）、`INBOX_AUTO_ORGANIZE`（0） |

> 说明：`config.py` 还支持 `CORS_ORIGINS`、`TIMEZONE` 等键（旧 `SOFT_DELETE_RETENTION_DAYS` 已由 #85 停用，回收站不自动到期），但
> **8002 compose（`docker-compose.multica.yml`）未对这三个变量做 `environment` 透传**，写进
> `docker/.env` 只参与 interpolation、不会注入容器进程，因此不会生效。它们仅在直接运行
> uvicorn（本地开发）或自建 compose 显式透传时可用，故不列入上表。

**验证**：`curl http://127.0.0.1:8002/health` 返回 `{"status":"ok","version":"2.1.2"}`；
`make status` / `docker compose -f docker/docker-compose.multica.yml ps` 见容器
`agv-pm-8002` healthy；浏览器访问 `http://127.0.0.1:8002` 用 `admin/admin123` 登录。

## 常见问题

| 问题 | 解决 |
|---|---|
| macOS OrbStack 报 `Permission denied while opening data image` | 数据目录权限被迁移助理改坏。打开 OrbStack 应用 → 设置 → 重置；或在系统设置 → 隐私与安全 中授予终端对 OrbStack 容器的访问权限 |
| Registry 登录跳转到错误端口或返回 EOF | 检查 Gitea `[server] ROOT_URL` 是否包含外网 HTTPS 端口，并让反向代理保留原始 `Host` 端口 |
| 端口 8000 被占用 | 修改 docker-compose.yml 的 `ports: "8080:8000"` |
| 手机访问不了 | 确认 NAS 防火墙放行该端口；群晖需在「控制面板→安全性→防火墙」放行 |
| 忘记密码 | 首选：登录后右上角头像 →「修改密码」；管理员可在「用户管理」中代改。兜底（部署主机受限终端）：`python3 docker/scripts/reset_password.py <用户名>` —— 用户名作命令行参数，新密码经 TTY 隐藏输入（getpass，不回显、两次一致、≥6 位），绝不进入命令行参数、环境变量、shell 历史或日志；成功后原子同步 `.secrets/` 对应凭据条目（临时文件 + os.replace，保持 0600），token_version 递增使旧会话全部失效。生产账号改密须在隔离演练容器验证过该脚本后再执行 |
| 数据库损坏 | 使用最近的备份文件替换 `data/agvpm.db` 后重启容器 |

## 性能说明

- 当前按约 **100 个账号 / 100 个项目**规划；单 worker + SQLite WAL 适合项目管理这种中低并发工作负载。若持续并发写入显著增加，再迁移 PostgreSQL。
- 如需更高并发，可将 `DATABASE_URL` 切换到 PostgreSQL（代码使用 SQLAlchemy，切换成本低）

## 离线使用（现场人员）

1. 现场人员用手机浏览器打开系统地址 → 登录
2. 浏览器菜单选择「添加到主屏幕」（iOS Safari：分享 → 添加到主屏幕；Android Chrome：菜单 → 安装应用）
3. 打开后即为全屏 App，界面和资源已离线缓存
4. **断网时**：仍可查看今日任务（缓存）并填写数量 → 记录进入本地队列
5. **联网后**：点击「同步」按钮（或自动同步），本地记录上传服务器

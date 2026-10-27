# 软件更新与宿主信任

管理员可以在「管理设置 → 软件更新」中检查当前来源，由宿主验证版本信任后再确认安装。多来源的选择、添加与删除收进默认折叠的“高级”。页面地址是 `/pm/system-updates`。只有已启用、角色为 `admin` 的真实管理员可以使用；成员权限授权不能代替管理员身份。

网页负责检查和展示进度，宿主机上的更新服务负责备份、构建和切换容器。首次接入需要部署管理员在宿主机操作一次；接入后，日常更新从网页完成。系统不会因为检查到新版本就自动安装。

## 在网页中更新

1. 打开「软件更新」，核对当前版本、当前提交和更新服务连接状态。
2. 在「更新来源」中编辑当前仓库、标签或分支。编辑后点击「保存并检查更新」；来源选择、添加和删除在默认折叠的“高级”中。检查失败时，已保存的配置仍然有效。
3. 等待宿主验证签名标签或该仓库的已登记完整 SHA；只有“信任已验证”才允许安装。查看目标版本、提交和检查时间。未签名/不受信任的版本显示原因，网页不能添加信任。
4. 点击「安装更新」。确认其他成员已保存输入，再点击「自动备份并安装」。系统随后准备新版本、备份数据、切换容器并检查健康状态。
5. 更新期间保留页面。页面每 6 秒读取进度，容器切换造成的暂时断连会显示等待恢复，不会直接判为更新失败。成功后点击「刷新页面使用新版本」；页面不会自动刷新。

首次使用默认选择「我的 Gitea」：`https://gitea.arrowwood.top:8773/codex-mac/agv-project-workflow`，分支为 `main`。这里只预填来源，打开页面不会联网检查或自动安装。已有2.4.0单源配置会保留原地址、分支、令牌与选中状态，另增加默认项。

可以保存最多20个来源（含默认项），每个来源分别保存分支、HTTP选项和加密令牌。新增来源后自动选中；切换时若有未保存输入会先确认。切换、编辑、添加或删除都会使先前检查失效，需要重新检查后才能安装；后台正在更新或等待人工处理时不能修改来源。

默认项可以修改但不能删除。删除当前自定义来源会切回默认项；删除前需确认。来源按规范化后的仓库地址与分支去重，相同仓库的不同分支可以分别保存。切换来源不会把上一个来源的令牌带到新来源，修改仓库地址仍会清除该条来源原令牌。

| 来源字段 | 填写方法 |
|---|---|
| 来源名称 | 便于辨认的名称，例如“我的 Gitea”“测试分支”或“备用仓库”。 |
| Gitea 仓库地址 | 完整的 HTTP/HTTPS 仓库 URL，例如 `https://git.example.com/team/agv-project-workflow`；有端口或 Gitea 子路径时也要带上。末尾 `.git` 可以保留。 |
| 分支或标签 | 默认 `main`，也可以填 `release/2.4` 或 `v2.4.1` 等实际存在的分支、标签。不要填网页中的 `/src/branch/...` 地址。 |
| 私有访问令牌 | 公开仓库通常留空；私有仓库填写具备目标仓库读取权限的 Gitea 个人访问令牌。令牌只放在密码框中，不要拼进仓库 URL。 |
| 清除已保存的令牌 | 勾选后保存，删除原令牌。同一仓库留空且不勾选时保留原令牌；更换仓库 URL 会清除旧令牌，新的私有仓库需重新填写。 |
| 允许局域网 HTTP 地址 | 地址以 `http://` 开头时必须显式勾选，例如 `http://192.168.1.20:3000/team/agv-project-workflow`。HTTP 不加密，仅用于可信局域网；HTTPS 无需勾选。 |

Gitea 令牌在「用户设置 → 应用 → 访问令牌」中创建，选择仓库读取权限 `read:repository`，所属账号也必须能读取该私有仓库。无需授予仓库写入或站点管理权限；可以使用只拥有目标仓库读取权限的专用账号。具体菜单以所用 Gitea 版本为准，参见 [Gitea 官方 API 与令牌说明](https://docs.gitea.com/1.27/development/api-usage/)。

保存后密码框会清空，页面只显示是否已保存令牌；接口不回传令牌。服务端加密保存令牌，备份与恢复时需要保留配套的应用密钥。

以下情况需要先处理再安装：

- **更新服务未连接**：仍可保存来源、检查版本，安装按钮不可用。按下文接入宿主服务。
- **来源有未保存的修改**：先保存。后台读取状态不会覆盖正在填写的内容；若另一位管理员已经修改来源，需核对最新配置后重新保存。
- **检查已经过期或使用过**：重新检查。检查结果有效期为 30 分钟，绑定保存时的来源版本和固定提交；分支之后变化不会偷偷改变已经确认的安装目标。
- **没有可安装更新**：低版本被拒绝，已经运行的同一提交不会重复安装。同版本的新提交可以安装，用于分支修复；发布时仍应维护正确的版本号。旧安装的当前提交为 `unknown` 时，系统无法据此判定是否已经运行目标提交。
- **正在更新或需要人工处理**：来源编辑和再次安装被锁定，等待当前任务结束或完成恢复处理。

Gitea 必须能被**应用容器**访问。浏览器能打开仓库，不代表容器也能访问。不要使用 `localhost`、`127.0.0.1` 或云元数据地址；局域网 Gitea 应使用容器可达的局域网 IP 或域名。HTTPS 必须使用受容器信任的证书，页面没有跳过证书检查的开关。仓库 URL 不支持 SSH 格式、用户名密码、查询参数或片段。

目标仓库需要包含完整的行序源码、有效的 `frontend/package.json` 版本，以及兼容的 `docker/update-protocol.json`。2.4.0 使用协议 `1`，标识为 `{"application":"xingxu-workbench","protocol":1}`。只填一个普通 Git 仓库、压缩包链接或发行附件链接不能安装。

## 宿主信任：签名标签或预登记完整提交

T13 起，仓库内容返回一个 SHA、HTTP 成功和压缩包校验和均不能证明源码可信。宿主必须为**准确的仓库地址**配置签名公钥，或预先登记允许安装的 40 位小写完整提交。信任不跨仓库复用，同一 SHA 在另一个来源仍需独立登记。网页只显示验证结果，没有信任编辑入口。

宿主策略由 `--trust-file /绝对路径/trust.json` 指定；默认 `--work-dir` 下的 `trust.json`。文件及目录由宿主管理员维护，建议目录 `0700`、策略 `0600`，公钥文件不得被组或其他用户写入；不能位于应用可写挂载或下载任务目录。安装时应把 `update-trust.py` 与 `update-runner.py`、现有部署/备份脚本一起放在可信安装目录。新旧 runner 的信任能力独立协商；旧 runner 和旧检查不能获得新安装许可。旧的prepare压缩包桥接操作已无条件关闭，不能通过伪造应用状态中的能力字段重新开启。

为本次授权交付登记经复核的完整 SHA（以下均是占位，不能原样执行）：

```bash
python3 /srv/xingxu/docker/scripts/update-trust.py \
  --trust-file /var/lib/agv-update-runner/trust.json allow-commit \
  --repository https://git.example.com/team/workbench \
  --commit VERIFIED_40_CHARACTER_LOWERCASE_COMMIT
python3 /srv/xingxu/docker/scripts/update-trust.py \
  --trust-file /var/lib/agv-update-runner/trust.json verify-policy
```

登记只修改宿主策略，不安装、不联网，也不会自动信任其他提交。随后网页需重新检查，宿主会真实取得该提交的 Git 对象、校验版本与协议，再发布通过结果。删除或修改登记后，已有检查失效；安装执行前和备份/切换阶段会重新核对策略。

签名发布可使用如下策略；`allowed_commits` 可省略。SSH 文件采用 Git 的 allowed-signers 格式，内容为 `principal ssh-ed25519 公钥内容`，私钥只留在发布者处。OpenPGP 使用仅含所准许发布者公钥的导出文件；两种方式可择一。

```json
{
  "version": 1,
  "repositories": [{
    "repository_url": "https://git.example.com/team/workbench",
    "ssh_allowed_signers": "/etc/xingxu/release-allowed-signers",
    "openpgp_public_keys": ["/etc/xingxu/release-public.asc"]
  }]
}
```

仅带签名的 annotated tag 可用签名方式授权；轻量标签、无签名标签、未知/撤销公钥和指向不同提交的标签均拒绝。签名按 [Git verify-tag](https://git-scm.com/docs/git-verify-tag) 和 [Git 公钥信任设置](https://git-scm.com/docs/git-config#Documentation/git-config.txt-gpgsshallowedSignersFile) 本地验证，Gitea 的“已验证”标记不作为信任根。若来源仍填分支，则该提交必须有宿主完整 SHA 登记，或同名签名 tag 指向相同已确认提交。

宿主不会把应用提供的 tar 包当作已确认 SHA 的证据：它独立获取 Git 对象、验证签名/提交，并从这些对象本地生成构建包。HTTPS 验证保持启用，禁止 Git 重定向、外部凭据 helper、系统/用户 Git 配置和非 HTTP(S) 传输。读取凭据前先检查仓库许可，令牌只绑定该仓库的请求。Git HTTPS 使用仓库范围的 Basic PAT 请求头，依据 [Gitea 的令牌认证逻辑](https://github.com/go-gitea/gitea/blob/main/services/auth/basic.go) 从令牌识别用户，不将令牌拼进 URL。下载期间限制对象大小、输出和耗时，不执行仓库 hooks、不检出或运行代码。

检查回执保存在宿主私有工作目录，绑定检查 ID、来源 ID/版本、规范化仓库、ref、完整 SHA、产品版本和 Git tree；安装前再次验证真实对象与策略。旧检查、修改后的目标/来源、已用回执换新任务 ID、策略撤销和源码暂存修改都拒绝。宿主工作目录、策略、公钥、安装脚本及 Compose/环境文件不能被应用写入；探测会拒绝相交的可写挂载、特权应用容器，以及包括只读形式的 Docker/容器管理 socket 挂载。正常备份、停写、回滚和实际版本核验继续沿用。宿主桥接侧进程会跳过SQLite pending bootstrap，避免心跳在写服务仍运行时提前消费网页待重启恢复；真正web启动和可信CLI apply仍执行该协议。

更新服务未连接或尚未验证时，页面可保存来源并发起检查，但不能安装。签名/登记失败显示公开原因，公钥路径、令牌、原始 Git 输出不跨越宿主边界，不回传网页。首次升级到 T13 须先更新并重启宿主 runner；不要让旧 runner 与新 runner 同时管理同一实例。

## 一次接入宿主更新服务

### 支持的安装方式

支持本项目两套 **Docker Compose 受管安装**，2.4.2 起也可以显式指定保留现有配置的完整本机 Compose 文件：

| 模式 | 已安装的 Compose 文件 | 通常使用的环境文件 | 容器名称 |
|---|---|---|---|
| `standard` | `docker/docker-compose.yml` | 项目根目录 `.env` | `agv-pm`，当前标准配置固定使用此名称 |
| `multica` | `docker/docker-compose.multica.yml` | `docker/.env` | 默认 `agv-pm-8002`，以实际 `AGV_CONTAINER_NAME` 配置为准 |
| 自定义安装 | `--compose-file` 指定的绝对路径 | `--env-file` 指定的原安装环境文件 | 配置中 `agv-pm` 服务的实际 `container_name` |

接入会验证现有容器的 Compose 项目、服务 `agv-pm`、容器名和 `/app/data` 数据挂载，与指定的 Compose 和环境文件一致。验证失败时不会接管或更换数据卷。

通过 `docker run` 手动创建的容器不能直接使用网页安装。需先备份，记录原镜像、环境、端口、安全设置和挂载，停写并停止旧容器，再由 Compose 使用同一镜像及原数据卷真实创建容器。完成健康、账号、业务与附件核验后才能接入 runner；两个 PostgreSQL 容器不能同时使用同一数据卷。不要补造 Compose 标签、另建空数据卷或按默认模板覆盖原部署。没有宿主服务时，网页的来源保存和版本检查仍可使用。

### 保留现有配置的自定义安装

`--compose-file /绝对路径/compose.private.json` 是**完整替代安装文件**，由宿主管理员维护，可使用 Compose 支持的 JSON 或 YAML；它不是追加覆盖文件，也不会从 Gitea 下载。`--mode standard` 或 `--mode multica` 仍用于选择已安装的可信部署入口，单容器 PostgreSQL 通常选择 `multica`。

自定义文件只能包含一个 `agv-pm` 服务，保留原 `container_name` 和可写 `/app/data` 挂载。已有命名数据卷应以 `external: true` 和准确的 `name` 引用；端口绑定、全部业务环境、安全设置与资源限制按原实例保留。以下只展示必须严格保留的三个版本占位，**不是可直接部署的完整配置**：

```yaml
services:
  agv-pm:
    image: ${AGV_IMAGE}
    environment:
      APP_VERSION: ${APP_VERSION}
      GIT_SHA: ${GIT_SHA}
```

不要给这三个占位写死旧值或添加 `:-默认值`；对应值放入安装环境文件。实际容器必须由指定文件创建，runner 会核对 Compose 标签记录的首个配置文件路径、项目、服务、容器名和真实数据挂载。完整配置含有秘密时，文件及环境文件使用 `0600`，所在安装目录使用 `0700`。

确认该安装已完成迁移后，使用原账号和 Docker 连接验证：

```bash
python3 /srv/xingxu/docker/scripts/update-runner.py \
  --project-dir /srv/xingxu \
  --mode multica \
  --container your-existing-container \
  --env-file /srv/xingxu/installation.private.env \
  --compose-file /srv/xingxu/compose.private.json \
  --work-dir /var/lib/agv-update-runner/custom \
  --probe
```

升级成功或自动回滚通过健康检查后，可信脚本会在解除维护前原子保存实际 `AGV_IMAGE`、`APP_VERSION`、`GIT_SHA`。镜像固定为不可变的 `sha256` ID，其他环境配置原文保留，后续使用同一文件执行 `compose up -d --no-build` 会使用已核验版本。保存失败时保持维护停写并显示需要人工处理。更新宿主脚本时须一并保留 `docker/scripts/persist-update-runtime.py`；人工恢复也应核对安装环境文件与最终实际版本一致。

### 宿主准备

宿主需要 Python 3.9 或更新版本（建议使用与项目一致的 3.12）、Git、Bash、Docker CLI、Docker Compose v2（支持 `config --format json` 和 `--no-interpolate`）、`curl`，以及 `sha256sum` 或 `shasum`。验证 SSH 签名需要 `ssh-keygen`，OpenPGP 签名需要 `gpg` 与 `gpgconf`。更新服务仅使用 Python 标准库，无需额外 `pip install`。下方分别提供 Linux systemd 和 macOS LaunchAgent 示例。

还需要：

- 应用已具备 2.4.0 更新接口，宿主保留相匹配的可信项目目录、Compose 文件及 `docker/scripts/` 脚本。较早版本首次接入仍需按原部署流程升级到支持此功能的版本。
- 运行账号能读取可信脚本、读写原环境文件及其所在目录、调用实际部署使用的 Docker，并能写入独立工作目录。原环境文件需要原子替换以持久保存已核验版本。Docker 访问权具有宿主管理能力，应交给部署账号；不要把 Docker socket 挂进网页容器。
- 宿主有足够空间存放源码、新旧镜像及完整备份，构建过程能取得所需基础镜像和依赖。保留原环境文件、应用密钥、端口和数据挂载，不重新生成一套配置。
- 安装目录中的部署脚本、Compose 和环境文件不能由网页进程修改。仅使用可信 Gitea 仓库作为源码来源。

标准安装没有新增必填的 `.env` 变量；自定义安装需设置上述三个持久版本值。宿主服务通过本机 `docker exec` 与应用通信，无需额外开放端口，也不需要在服务配置中填写 Gitea 令牌。令牌仅通过本机 stdin 桥接临时进入宿主内存，供已获宿主信任的固定仓库读取；不会写入策略、命令行、日志、Git配置文件或任务记录。

### 先验证，再常驻

以下使用示例安装目录 `/srv/xingxu`、已有部署账号 `agv-deploy`、独立工作目录 `/var/lib/agv-update-runner/standard`。**先替换成这台机器实际存在的账号和绝对路径。** 后续探测、服务运行、恢复操作使用同一账号、同一 `HOME`、同一 Docker 连接和同一工作目录。

先为现有部署账号准备工作目录；示例假定同名用户组已存在：

```bash
sudo install -d -o agv-deploy -g agv-deploy -m 0700 /var/lib/agv-update-runner
sudo install -d -o agv-deploy -g agv-deploy -m 0700 /var/lib/agv-update-runner/standard
```

标准模式验证：

```bash
sudo -u agv-deploy -H python3 /srv/xingxu/docker/scripts/update-runner.py \
  --project-dir /srv/xingxu \
  --mode standard \
  --container agv-pm \
  --env-file /srv/xingxu/.env \
  --work-dir /var/lib/agv-update-runner/standard \
  --probe
```

PostgreSQL 单容器模式改用以下参数，并先为该账号创建独立工作目录：

```bash
sudo -u agv-deploy -H python3 /srv/xingxu/docker/scripts/update-runner.py \
  --project-dir /srv/xingxu \
  --mode multica \
  --container agv-pm-8002 \
  --env-file /srv/xingxu/docker/.env \
  --work-dir /var/lib/agv-update-runner/multica \
  --probe
```

成功会打印「受管安装身份与数据挂载验证通过」。`--probe` 会创建或复用宿主工作目录、身份文件和锁，但只验证接入条件，不发心跳、不认领任务、不安装版本，因此网页此时仍可能显示未连接。去掉 `--probe` 才会持续运行；`--once` 是最多处理一个任务后退出，**已有待执行任务时会真的安装**，不能用作探测命令。两种参数不能同时使用。

工作目录存放宿主身份、任务日志和备份，权限为 `0700`，关键文件为 `0600`。不要放进临时目录、公开共享目录或随更新删除的源码目录，也不要在重启服务时换一个空目录。省略 `--work-dir` 时使用运行账号的 `$HOME/.local/state/agv-update-runner/` 下按 Docker 连接和容器生成的独立目录；即使显式指定工作目录，锁文件仍保存在该 `HOME` 下。

### Linux systemd 示例

将以下内容保存为 `/etc/systemd/system/xingxu-update-runner.service`，替换账号、路径和容器。示例账号的实际主目录为 `/home/agv-deploy`；使用其他位置时同步修改 `HOME`。如果原部署使用 rootless Docker、Docker context 或 `DOCKER_HOST`，也应让服务使用相同连接，不能仅因命令能在个人终端运行就假定服务能访问。

```ini
[Unit]
Description=Xingxu software update runner
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=agv-deploy
Group=agv-deploy
Environment=HOME=/home/agv-deploy
WorkingDirectory=/srv/xingxu
ExecStart=/usr/bin/python3 /srv/xingxu/docker/scripts/update-runner.py --project-dir /srv/xingxu --mode standard --container agv-pm --env-file /srv/xingxu/.env --work-dir /var/lib/agv-update-runner/standard
UMask=0077
Restart=on-failure
RestartSec=10
KillMode=process
TimeoutStopSec=infinity

[Install]
WantedBy=multi-user.target
```

`multica` 安装同步改为 `--mode multica`、实际容器名、`docker/.env` 和对应工作目录。确认没有同一实例的前台 runner 正在运行后启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now xingxu-update-runner.service
sudo systemctl status xingxu-update-runner.service
sudo journalctl -u xingxu-update-runner.service -n 100 --no-pager
```

返回网页，应看到更新服务「已连接」。服务持续领取任务，通常每 15 秒报告存活；超过 60 秒没有有效心跳时页面视为未连接。探测通过只证明受管身份和挂载条件，不等于已经完成一次真实升级或回滚。

正常停服务请先等待当前任务终态。这里的 `KillMode=process` 和 `TimeoutStopSec=infinity` 让停止请求交给 runner，等待当前更新或恢复子进程结束，避免默认的超时强杀打断数据恢复；这两个设置应配套保留。若任务卡住，保留日志并人工排查，不能通过反复杀进程重放更新。配置语义见 [systemd.kill](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html) 与 [systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)。

### macOS LaunchAgent 示例

以下用于已登录的部署账号。先替换全部占位绝对路径，包括 Python、Docker socket、含 Compose 插件的 `DOCKER_CONFIG`、安装目录及容器名；plist 不会展开 `~`、`$HOME` 或读取个人 shell 配置。用与服务完全相同的 `HOME`、`PATH`、`DOCKER_HOST`、`DOCKER_CONFIG` 完成 `--probe`，并确认 `docker compose version` 可用。

先以该账号创建持久工作和日志目录，权限均为 `0700`：

```bash
install -d -m 0700 /Users/DEPLOY_USER/.local/share/xingxu-updater
install -d -m 0700 /Users/DEPLOY_USER/.local/share/xingxu-updater/state
install -d -m 0700 /Users/DEPLOY_USER/.local/share/xingxu-updater/logs
```

保存为 `/Users/DEPLOY_USER/Library/LaunchAgents/com.xingxu.update-runner.plist`（先创建 `LaunchAgents` 目录），文件权限设为 `0600`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.xingxu.update-runner</string>
  <key>ProgramArguments</key><array>
    <string>/ABSOLUTE/PATH/TO/python3</string>
    <string>/Users/DEPLOY_USER/.local/share/xingxu-updater/installation/docker/scripts/update-runner.py</string>
    <string>--project-dir</string><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/installation</string>
    <string>--mode</string><string>multica</string>
    <string>--container</string><string>your-existing-container</string>
    <string>--env-file</string><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/installation/installation.private.env</string>
    <string>--compose-file</string><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/installation/compose.private.json</string>
    <string>--work-dir</string><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/state</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>HOME</key><string>/Users/DEPLOY_USER</string>
    <key>PATH</key><string>/ABSOLUTE/PYTHON/BIN:/ABSOLUTE/DOCKER/BIN:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>DOCKER_HOST</key><string>unix:///ABSOLUTE/PATH/TO/docker.sock</string>
    <key>DOCKER_CONFIG</key><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/docker-cli</string>
  </dict>
  <key>WorkingDirectory</key><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/installation</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>ExitTimeOut</key><integer>3600</integer>
  <key>Umask</key><integer>63</integer>
  <key>StandardOutPath</key><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/logs/runner.stdout.log</string>
  <key>StandardErrorPath</key><string>/Users/DEPLOY_USER/.local/share/xingxu-updater/logs/runner.stderr.log</string>
</dict></plist>
```

`Umask` 的十进制 `63` 等于八进制 `0077`，新日志文件使用私有权限；已有日志另核对为 `0600`。`ExitTimeOut=3600` 给停止请求最多一小时的退出等待时间，并不保证任意恢复都能在此时间内完成。停止、登出、重启或更换脚本前仍应先等待网页任务终态；不要通过强杀或 `kickstart -k` 中断更新。参数语义已按系统 `man launchd.plist` 和 [Apple launchd 配置手册](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5) 核对。

确认没有同一实例的前台 runner 后，在该账号登录会话中启动并检查：

```bash
plutil -lint /Users/DEPLOY_USER/Library/LaunchAgents/com.xingxu.update-runner.plist
launchctl bootstrap "gui/$(id -u)" /Users/DEPLOY_USER/Library/LaunchAgents/com.xingxu.update-runner.plist
launchctl print "gui/$(id -u)/com.xingxu.update-runner"
```

返回网页确认「已连接」。需要停服务时，在任务完成后执行 `launchctl bootout "gui/$(id -u)/com.xingxu.update-runner"`。LaunchAgent 只在该用户登录期间运行；登出会离线，机器睡眠或 Docker 虚拟机停止时也无法继续更新或发送心跳。重新登录或唤醒后还需 Docker 可用；若中断时已有任务，按实际记录处理，不能把重新连接视为更新完成。用户会话生命周期见 [Apple LaunchAgent 说明](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)。

## 备份、维护与失败恢复

更新会先把检查时固定的提交下载并校验，在宿主构建新镜像。执行部署的是**已经安装在宿主上的可信脚本**，不会下载远程安装脚本后直接在宿主执行，也不使用 `curl | sh`。下载的源码参与镜像构建，因此仓库及其构建文件仍必须可信。将来协议或宿主能力改变时，需要部署管理员单独更新宿主脚本。

2.4.2 宿主脚本还会在停写前比较现有 PostgreSQL 数据目录与新镜像的 PostgreSQL 主版本；不一致会拒绝安装，保留原实例运行。跨主版本数据库升级需要单独安排迁移，不能通过网页更新自动完成。下载源码只作为构建上下文，使用固定的 `docker/Dockerfile` 和已确认版本参数，不会替换宿主 Compose、环境文件或可信部署脚本。

正式切换前会暂停业务写入和后台调度，保存完整备份；维护状态跨容器重建保留。成功后通过健康检查再恢复服务。失败时是否能自动恢复取决于失败发生阶段，页面状态是判断依据：

| 状态 | 含义与处理 |
|---|---|
| `queued` / 等待更新 | 请求已受理，等待宿主服务领取。不要再次提交。 |
| `downloading` / 下载更新 | 下载并校验固定提交的源码。 |
| `building` / 准备新版本 | 构建镜像，尚未切换运行版本。构建耗时受宿主性能和网络影响。 |
| `backing_up` / 自动备份 | 进入维护、暂停写入并备份。此时不要手工恢复写入服务。 |
| `installing` / 安装更新 | 正在切换容器，网页可能短暂无法连接。 |
| `verifying` / 验证更新 | 检查新版本运行情况，等待明确结果。 |
| `succeeded` / 更新完成 | 新版本通过检查，可点击刷新页面。 |
| `failed` / 更新未完成 | 未成功完成升级，通常在切换前已停止；读取页面说明和宿主日志，排除原因后重新检查再安装。 |
| `rolled_back` / 已恢复原版本 | 自动恢复旧镜像和升级前数据，并通过恢复检查。核对业务后再决定是否重试。 |
| `needs_attention` / 需要人工处理 | 自动恢复未能确认安全完成，或发现未完成的宿主任务。保持维护停写，由部署管理员处理；不能直接再次安装或启动写入服务。 |

网页暂时断连或“安装请求结果待确认”不代表失败。保留当前任务并等待连接恢复，避免创建新的安装意图。

### 查找本次记录

以显式配置的 `<工作目录>` 为准：

- `<工作目录>/runner.json`：宿主身份，重启后保留。
- `<工作目录>/active-job.json`：当前或最近任务的恢复记录，不能手动改成成功。
- `<工作目录>/<任务 ID>/deployment.log`：本次部署详细日志。
- `<工作目录>/backups/`：自动备份包、配套 `.sha256` 校验文件，以及部署保存的恢复信息。备份可能包含业务数据和密钥，应限制访问并按已有备份策略异地保留。

应用数据卷中的 `system-update-config.json` 保存更新来源和加密令牌；系统备份包含它及已有的 `secret.key`。若应用密钥由环境变量 `SECRET_KEY` 提供，应另外保全该原环境配置。恢复不含更新配置的旧备份后，需要重新配置来源；普通业务备份恢复不会重放以前排队的更新任务。

### 需要人工处理时

1. 停止宿主 runner，确认没有残余的部署或恢复子进程在继续操作。保留维护状态、工作目录、旧镜像、备份包和校验文件。
2. 根据本次 `deployment.log`、恢复记录及 [部署指南](deployment.md) 的备份恢复流程，确定实际运行的镜像和数据状态。需要回退时，恢复与升级前备份配套的旧镜像、数据库、附件、项目回收站备份和密钥；只切换镜像不构成完整回退。
3. 核对恢复后的版本、完整提交 SHA、健康检查、用户与项目数据、附件和原访问配置。没有完成数据核验时保持维护，不删除维护标记或任务记录。
4. 由部署管理员运行恢复收尾工具，确认本次实际结果后再恢复服务、启用 runner。不能把重启 runner 当成数据恢复或健康核验。

恢复工具只核对版本及任务等元数据并解除维护，不核验业务数据完整性、不执行回滚，也不启停服务。请在完成上述人工核验、保持业务停写时使用原 runner 的账号、`HOME`、Docker 连接及工作目录；保留原 `runner.json`。以下示例用于**已经人工恢复旧版本及数据**的任务，先替换全部占位值：

```bash
sudo -u agv-deploy -H python3 /srv/xingxu/docker/scripts/recover-update.py \
  --container agv-pm \
  --work-dir /var/lib/agv-update-runner/standard \
  --job-id '<原更新任务 UUID>' \
  --expected-version '<已核验的实际运行版本>' \
  --expected-commit '<已核验的完整40位提交 SHA>' \
  --outcome rolled_back \
  --confirm-data-verified
```

`--outcome` 按实际结果选择：`rolled_back` 表示已恢复旧镜像和配套数据；`failed` 表示结束本次未完成的更新且当前运行与数据已核验；`succeeded` 表示目标版本及数据已核验，实际版本和提交还必须匹配原安装目标。不要为了通过检查选择另一个结果。

`--expected-version` 必须与实际 `APP_VERSION` 一致，`--expected-commit` 必须与实际 `GIT_SHA` 一致且为完整 40 位 SHA。实际提交为 `unknown` 或短 SHA 时工具会拒绝解除维护；应继续由部署管理员核实并恢复具备准确来源信息的可信镜像，不能编造提交信息绕过校验。存在尚未应用的恢复快照时也会拒绝收尾。

`--confirm-data-verified` 是管理员对已经完成人工数据核验的确认，工具不会替你完成该核验。收尾只接受 `needs_attention` 或同一任务已确认的相同终态，成功后保存恢复记录、解除维护并同步宿主任务记录。收尾前的状态保存在容器数据目录 `system-updates/recovery-records/<任务 ID>.json`，权限为 `0600`。若响应丢失或最后落盘失败，保持停写，可用相同参数重试；不要换任务 ID 或新建工作目录。成功后再按部署流程恢复服务、核对健康状态并启动原 runner。不得使用通用 `rm` 命令绕过维护保护。

## API 契约

应用的 HTTP 前缀为 `/api`，下列接口均要求已启用的真实管理员会话，沿用应用现有认证与写请求保护；不能靠成员授权获得权限。所有成功响应返回同一份状态对象。

| 方法与路径 | 请求体 | 成功响应 |
|---|---|---|
| `GET /api/system/updates` | 无 | `200`，当前版本、来源、宿主状态、最近检查与任务 |
| `PUT /api/system/updates/source` | `repository_url`、`ref`、`allow_http`、当前 `revision`，可选 `name`、`token` 或 `clear_token` | `200`，编辑当前来源；以前的检查结果失效 |
| `POST /api/system/updates/sources` | `name`、`repository_url`、`ref`、`allow_http`、当前 `revision`，可选 `token` | `201`，新增并选中来源 |
| `POST /api/system/updates/sources/{id}/select` | 当前 `revision` | `200`，切换当前来源并清除检查结果 |
| `DELETE /api/system/updates/sources/{id}?revision=N` | 无 | `200`，删除自定义来源；删除当前项时切回默认 |
| `POST /api/system/updates/check` | `{"source_revision": 3}` | `200`，针对该保存版本的检查结果 |
| `POST /api/system/updates/install` | `{"check_id":"检查 UUID","confirm":true}` | `202`，安装请求已受理；不代表安装完成 |

状态结构示例（版本和提交仅作格式展示）：

```json
{
  "current": { "version": "2.4.1", "commit": "unknown" },
  "active_source_id": "default-gitea",
  "maintenance": false,
  "source": {
    "id": "default-gitea",
    "name": "我的 Gitea",
    "is_default": true,
    "repository_url": "https://git.example.com/team/agv-project-workflow",
    "ref": "main",
    "has_token": true,
    "allow_http": false,
    "revision": 3
  },
  "sources": [{
    "id": "default-gitea", "name": "我的 Gitea", "is_default": true,
    "repository_url": "https://git.example.com/team/agv-project-workflow",
    "ref": "main", "has_token": true, "allow_http": false, "revision": 3
  }],
  "runner": { "online": true, "last_seen": "2026-10-19T08:00:00+00:00", "protocol": 1 },
  "check": {
    "id": "00000000-0000-4000-8000-000000000001",
    "source_revision": 3,
    "commit": "1111111111111111111111111111111111111111",
    "version": "2.4.2",
    "checked_at": "2026-10-19T08:00:00+00:00",
    "update_available": true
  },
  "job": null
}
```

`check`、`job` 在没有记录时为 `null`，`runner.last_seen` 也可能为 `null`。任务对象包含 `id`、`status`、`phase`、`message`、`target_version`、`target_commit`、`created_at`、`updated_at`。`current.commit` 可能是旧安装留下的短 SHA 或 `unknown`；更新目标必须是服务端解析得到的完整 40 位提交 SHA。

`sources` 是已保存来源列表，`source` 是当前选中项，二者只返回令牌是否存在，不返回令牌内容。`maintenance` 表示维护窗口，即使当前没有任务也会禁止配置变更和新检查/安装。所有来源共用一个 `revision` 做并发保护；检查结果必须匹配 `source_revision`。冲突、忙态、检查过期、宿主未连接等条件会拒绝安装，业务错误通过中文 `detail` 返回。安装请求只接收已检查的 `check_id`，不接收客户端另传的仓库或提交；对同一次检查重复提交会返回原任务，不能强制再执行一次。终态后如需重试，重新检查并获取新的检查 ID。

宿主桥接与恢复能力仅通过本机容器命令调用，不是对外 HTTP 管理接口。API 状态、审计日志和普通错误信息均不应包含私有令牌。

## 验证范围

本指南描述 2.4.2 的实现和接入方法，不表示某台主机已经接入，也不表示已经在真实业务环境完成升级或回滚演练。接入以该主机的探测结果、网页连接状态为准；一次更新是否成功，以该次任务终态、宿主日志及业务核验为准。

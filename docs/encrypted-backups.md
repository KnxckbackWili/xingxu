# T12：加密备份与恢复

系统备份采用 AES-256-GCM，口令通过 scrypt（N=32768、r=8、p=3，32 MiB 工作内存）派生 256 位密钥。每个文件重新生成 16 字节盐和 12 字节随机 nonce；完整头部作为 AAD，末尾保存 16 字节认证标签。版本 1 文件头为 `XINGXU\0\1`。参数由格式版本固定，不能静默修改已发布版本的参数。

加密和解密按 1 MiB 块处理。解密输出先写入数据卷上 0700 临时目录中的 0600 文件；完整认证成功后才允许归档检查、解包和安装。错误口令、头部/密文/标签修改、截断都拒绝。归档额外拒绝路径穿越、链接、重复路径、非普通文件和超限展开，恢复时将文件权限收紧到 0600、目录到 0700。数据库检查和恢复前加密快照失败时不替换现有安装。

## 设置与密钥保管

公网安装可在宿主私有环境文件设置独立 `AUTH_SIGNING_KEY`，重启后使旧登录、刷新、二次验证挑战和外部短会话失效；分享链接本身仍按原有效期及撤销规则使用。此密钥不参与数据加密，不写入完整备份。备份中的 `secret.key` 继续用于已保存凭据、认证器密钥和退役资料；恢复安装时单独生成或保管会话签名密钥，再重新登录即可。未配置独立值的旧安装兼容使用 `SECRET_KEY` 签名。

真实管理员还需拥有 `system.backups.configure` 权限，在“系统备份”设置至少 12 个字符的口令。设置、生成、删除和准备恢复均写操作记录；口令不会进入记录、响应或备份。设置由独占锁与审计事务协调；保存失败会恢复旧口令，并发备份不能读到尚未提交的口令。更换口令只影响新备份，旧备份仍需旧口令。

运行时口令使用独立随机密钥包装后保存在 `DATA_DIR/backup-security/`（目录 0700、文件 0600）。该目录整体不进入备份。它与应用 `secret.key` 分离，恢复应用密钥不会破坏当前备份口令设置。灾难恢复仍需操作者单独保管的原始口令；遗失后无法解开对应备份。

运维可提供 `BACKUP_PASSPHRASE_FILE`，内容为 UTF-8 口令，权限须为 0600。容器内运行时优先使用管理员设置，之后才读取该环境变量指向的容器文件。宿主的 `backup.sh` 在尚未配置口令时，将此私有文件通过校验过的 stdin 传输写入容器临时位置；成功生成并验证密文后保存包装配置，随后删除传输文件。不得把真实口令写进命令行、Git、镜像、Compose 明文变量或日志。

```bash
# 私有文件须由运维安全提供；示例仅展示路径，不生成或打印真实口令。
chmod 600 /private/path/backup-passphrase
BACKUP_PASSPHRASE_FILE=/private/path/backup-passphrase \
  AGV_CONTAINER=your-installed-container bash docker/scripts/backup.sh
```

初装缺少口令时仍能启动并进入管理员设置。迁移前数据库备份保持原有 best-effort 行为，明确在 stderr 显示缺口令/pg_dump 失败，不产生明文替代品。CLI/update 的完整备份缺口令明确失败，不能越过更新前备份门禁。

## 完整备份与历史文件

新完整备份为 `*.tar.gz.agvenc`，包括 SQLite 一致副本或 PostgreSQL 自定义格式 dump、清单、应用 `secret.key`、附件、更新源配置、项目删除历史 ZIP、`migration-exports/`。不包含备份自身、备份口令/包装密钥、更新任务状态。`migration-exports` 与 `secret.key` 一起保全，供 T03 的 owner 隔离退休数据读取工具恢复验证。

若部署通过环境变量提供 `SECRET_KEY`，须单独保留相同部署密钥；恢复数据库中通知渠道等密文时仍需要它。文件中已有的 `secret.key` 始终纳入备份。自定义外部配置和外部数据库凭据仍应由运维独立保管。

历史明文备份保留原文件，网页下载时临时加密，下载后删除临时密文。网页不允许上传明文恢复包。轮转仅针对新加密备份，历史明文不自动删除。当前项目删除 ZIP 的历史存储格式由 T03/#85 后续专项迁移；系统完整包会保护这些 ZIP，不能据此声称旧独立 ZIP 已迁移加密。

所有新文件使用时间戳加唯一后缀，原子发布拒绝覆盖已有目的文件。迁移前 SQLite/PG 快照同秒多线程/多进程也不覆盖最早快照；仅轮转新密文快照的最近 20 份。

## 网页与命令行恢复

网页恢复只支持目标 SQLite，需输入该份备份的口令；当前安装也须已配置备份口令，保护恢复前快照。认证、数据库类型和归档检查成功后才发布 0600 的内部 `restore-pending.tar.gz`。重启时多进程锁确保只应用一次，安装失败回滚数据库、WAL/SHM、附件、应用密钥、更新配置和迁移导出。普通恢复清除旧更新队列；自动更新回滚保留受维护标记保护的任务日志。

宿主恢复入口保留强制 SHA-256 侧车校验。旧包缺少侧车只允许显式 `SKIP_SHA_CHECK=1`，已有但不匹配的侧车仍拒绝。自动更新回滚强制禁止跳过 SHA。

```bash
BACKUP_PASSPHRASE_FILE=/private/path/password-for-this-backup \
  AGV_CONTAINER=your-installed-container \
  bash docker/scripts/restore.sh /private/backups/backup.tar.gz.agvenc
```

宿主先认证并检查数据库类型，随后核实 web/scheduler/healthwatch 全部停止。PostgreSQL 在 dropdb 前生成完整加密快照并验证，且先通过 `pg_restore --list` 检查导入 dump；失败留在维护停写并保留加密快照。此脚本的 PostgreSQL 破坏性恢复仅支持 `USE_POSTGRES=1` 的容器内库，外部 PostgreSQL 需由数据库管理员隔离恢复；不得误操作容器内部同名库。

SQLite CLI 和 `manage.sh` 自动回滚使用安装目录里的可信 `backup_runtime.py`，经 stdin 在容器 Python 执行并完成 pending 安装，再启动应用。这样旧 2.4.3 镜像不需要导入新 app 模块，也不会因旧归档白名单缺少 `migration-exports` 而拒绝；恢复前快照同样是密文。镜像/数据库 schema 的版本兼容仍由既有更新前备份和对应回滚镜像保证，不能把任意新版本数据库交给任意旧版本应用。

**部署与 runner 安装必须把 `backup_runtime.py` 和 backup/restore/update-common/manage/deploy 脚本一起安装到可信安装目录。** 更新源码只提供构建上下文，不能覆盖可信脚本。新镜像也将同一个文件复制到 `/app/backup_runtime.py`，应用通过薄适配器复用它。

迁移前的 `.db.agvenc`/`.sql.agvenc` 是数据库文件快照，不是完整 tar 包。恢复人员可用显式 raw-file 工具解密到新 0600 文件，再按对应数据库恢复流程处理；错误口令不创建输出，已有输出不会覆盖：

```bash
install -d -m 700 /private/recovery-work
python docker/scripts/backup_runtime.py decrypt-file \
  --data-dir /private/recovery-work \
  --input /private/backups/agvpm-before-migrate-unique.sql.agvenc \
  --output /private/recovery-work/recovered.sql \
  --passphrase-file /private/path/password-for-this-backup
```

共享 `encrypt_file`/`decrypted_file` 接口也供 T03 永久删除前项目备份复用，调用方仍须完成自己的权限、审计、项目一致性和恢复验证。

## 验证依据

格式认证边界遵循 [cryptography GCM 文档](https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/)；scrypt 参数采用 [OWASP 的 32 MiB 参数组合](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)。实现没有使用未认证的解密输出。

精准测试覆盖错误密码/标签/头部/密文/截断、12 MiB 流式处理、私有权限、无覆盖发布、口令审计回滚与并发读取、SQLite/PG 恢复保全、真实 PG17 dump→新建独立恢复库→pg_restore、同秒 PG 多进程快照、网页历史下载加密。真实 Bash 故障注入检查停写、快照、恢复失败和部分启动失败；只读根目录的隔离 Docker 容器验证可信 runtime 无 app 模块也能处理完整备份和 migration-exports。前端精准测试与类型检查/构建覆盖设置权限、清空、防重复、恢复口令提交与错误重试。

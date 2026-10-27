# v3 旧备份迁移核对

`backend/scripts/verify_v3_migration.py` 只向新隔离副本执行在线迁移。它不接受现有业务目标库，不调用 pytest，不启动业务应用、调度器或外部通知。PostgreSQL 目标由脚本在 loopback 服务上生成随机库名；SQLite 目标是新目录内解出的副本。原备份始终只读。

运行时使用 backend Python 环境，工作目录必须不存在、父目录已存在、位于 Git 仓库之外。目录权限 0700，私有证据文件 0600。支持旧明文系统 tar 和带独立口令文件的加密系统备份。

```sh
python backend/scripts/verify_v3_migration.py \
  --backup /private/input/source-backup.tar.gz \
  --expected-sha256 '<已独立核验的SHA256>' \
  --work-dir /private/migration-run-001 \
  --pg-restore /path/to/matching-postgresql/bin/pg_restore
```

PG 服务必须在 `127.0.0.1`、`::1` 或 `localhost`。可用 `--pg-port`、`--pg-user`、`--pg-password-file` 配置本机专用服务；密码不放命令行或日志。`pg_restore` 至少匹配源转储版本。备份加密口令使用 `--backup-passphrase-file`，与 PostgreSQL 连接密码独立。

脚本验证未迁移的 `d2e7f9a103b4` 源库，在 g01 之前捕获全部原行字段、表指纹、原件 SHA 和旧版数量权重进度；先执行冻结 g01，再执行 `ScriptDirectory` 动态发现的唯一 head。g01 的原字段修订逐列核对冻结修复原因，新增行只允许明确的定义种子、已有成员关系和迁移审计，不允许新增报工、提交或完成事实。未知改变会失败。

后续字段变化必须精确对应到保留字段、项目资料来源快照、旧车辆数量凭证或已经解密核对的 T03 历史导出。资料逐原项位置核对，保留同名项、原提交/审核信息、时间、真实文件关联；无原件的旧 done 不算新 submitted。车辆数量凭证保留未知车号和未知日期，不生成逐车完成。报告同时核对原件与支持文件 SHA、当前附件 SHA/大小、完整 ORM schema、外键和第二次升级无变化。

head 事务成功后还执行真实启动使用的冻结 `finalize_files`：先验证加密导出，再移除已经导出且没有活动/归档引用的原件副本。此步骤仅对隔离副本生效，不执行 `init_db` 或任何新业务播种。随后同时验证二次 head 与二次 finalize 幂等；演示项目的 owner 导出不是新项目的未归类文件。

退出码：0 为本轮核对通过；1 为明确差异；2 为输入、恢复、迁移或受控验收条件失败。原始异常内容、SQL 参数和环境不会打印。

新目录中保留 `source-before.private.json`、`t01-checkpoint.private.json`、`verification.private.json`、`created-database.private.json`（仅 PG）、原件和克隆数据库。标识、来源定位、用户、客户和本机路径只在这些私有文件中。不得把副本或私有报告加入 Git，也不得对克隆库运行 pytest。stdout 与 `summary.sanitized.json` 仅含脱敏统计。数据库保留以供复核，不自动删除。

正式验收需根任务确定最终链后，重新获取真实新鲜 2.4.3 源备份，在**另一个新目录和新库**重跑，并额外提供：

```sh
  --final-head '<获准的精确最终Alembic修订>' \
  --fresh-backup-attested
```

正式条件要求来源 manifest 版本精确为 `2.4.3`、固定备份 SHA、显式新鲜来源声明、指定最终修订等于动态 head，且全部核对通过。脚本不能从业务内容自动证明备份新鲜度；操作者须依据实际取备份过程作声明。构造 fixture、旧源或已迁移库不符合正式来源要求。

## 首轮隔离演练（暂定，未完成 T60）

2026-10-27，基于集成提交 `855abaf5bccdf522527b06a23fcbce23c0a3d4b2` 的唯一 head `g3a53b000001`，用真实旧自动备份完成 17 条待迁修订。源归档 SHA256 为 `b38656026bf6190abb6badc7ff7ff3818e4fc82d1ff5432ac048e163e61569e9`。其 manifest 实际标为 **2.4.2**，这是升级 2.4.3 前的同结构备份；本轮明确为 provisional，不冒称新鲜 2.4.3。

| 核对 | 首轮结果 |
|---|---|
| 原库 | 58 表、2,734 业务行、46,876 原字段、4 用户 |
| g01 | 原业务字段修改 0，新增行 0 |
| 项目 | 8 → 4；另 4 个演示项目完整保留在经解密核对的历史导出 |
| 附件 | 5 → 1；另 4 行属于上述演示项目，精确保全 |
| 逐车 | 8 → 0；另 8 行属于演示项目，精确保全 |
| 车辆批次 | 9 → 5 |
| 项目资料 | 114 原来源逐项对应 114 定义/实例；0 个版本，无假 submitted |
| 无法归类 | 1 份项目未归类文件；37 条历史车辆环节数量凭证保留待认领来源，本源未认领完成数为 0 |
| 原件 | 56/56 SHA 一致，仍在 uploads 或经核验的加密导出 |
| 原状态 | draft 1、planning 1、preparing 1、executing 5 |
| 新状态 | preparing 3、executing 1；原状态存入 legacy_lifecycle |
| 正式项目进度 | 4 个项目迁前/迁后均为 0%；新口径显式为车辆环节与等权工作项 |
| Schema / 外键 | 差异 0 / 违规 0 |
| 重复升级 / 原归档 | 行和文件不变 / 原归档 SHA 不变 |

验证脚本的 16 个 unittest 包含真实 SQLite 冻结源全链演练：非零旧数量保留待认领、同名资料不同来源位置、无附件 old-done 仍 pending、真实文件旧提交和人/时刻/审核保全、未知 g01 事实拒绝、正式条件门禁、路径/链接/重复成员防护。执行：

```sh
python -m unittest discover -s backend/scripts/tests -p test_verify_v3_migration.py -v
```

等待 T34/T40 最终迁移入链和新鲜 2.4.3 源备份后，必须重跑。首轮通过不代表最终迁移验收或上线完成。

## T34 冻结后的中间复验

接入 `3430477bc1d9d855f62daec809367628bcc0246c` 后，脚本另外精确核对 `legacy_work_snapshot` 的 task/module/phase、原报工总量与条数、NULL/列表区别、分组与范围、阶段归属。非车辆完成资格从原目标、原报工和原检查独立重算；须同时核对当前 manual 字段和唯一 system `migrate_work` 审计，只有快照不能证明转换正确。已有人为完成事实的人/时间保持原值。

真实旧源再次在新隔离 PG 库执行 18 条待迁修订至 `g3a34b000001`：544 份工作来源快照精确核对，0 个新转换（该源正式项目原进度均 0），Schema/外键 0 差异，原件和重复升级仍通过。仍标旧 2.4.2 provisional。

当前21个 unittest包含SQLite真实全链：额外构造非零已达目标的非车辆工作，核对真实转换；数量不足、安全待检、缺审计、伪操作人、遗漏NULL键、NULL变空列表、伪模块来源都被拒绝。额外生成而无法对应真实旧来源的项目资料/规则也会失败，避免虚增历史义务。最终 T40/T33 入链后，使用 root 新取的真实 2.4.3 备份正式重跑。

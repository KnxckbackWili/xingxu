# 大文件与明确授权清理（T25）

项目文件通过 `POST /api/projects/{pid}/uploads` 建立账号绑定的稳定UUID意图，然后逐片 `PUT /uploads/{sid}/chunks/{index}`。默认 `MAX_UPLOAD_MB=2048`，单位MiB，部署compose与示例配置均可覆盖；`GET /api/storage/limits` 是客户端上限真值。默认每片8MiB，每片SHA-256与服务端完整文件SHA-256均验证；失败不生成附件、资料版本或签单事实。旧表格、配置及内存型multipart接口仍最多10MiB。

每次start/status/chunk/finish重查当前用户、项目资格、可提交资料与统一保密策略；接收网络流前释放项目锁，落片前重新取得项目锁并核原会话版本。finish流式合并后再次核授权，附件/多项资料版本/明确签单日期/审计在同一事务提交；失败回收已发布文件。重复chunk/finish幂等，不重复提交版本或覆盖当前保密ACL。完成重试以当前ACL为准。私有缓存位于DATA_DIR/.upload-sessions（目录0700、文件0600），不挂HTTP下载。会话7天过期；启动及每小时任务回收过期缓存，同UUID与原本地文件可重新续传。正式文件仍为UPLOAD_DIR下平级UUID文件。

`GET /api/system/storage` 返回真实物理资源汇总与当前可见项目；`GET /projects/{pid}/storage` 只统计当前ACL可见的项目文件与空白模板。共享原件在不同项目的逻辑占用不能简单相加。当前原件、私有临时缓存、已清理的历史逻辑字节分别报告。全局资源读沿用system.backups.read，清理沿用project.update。

清理必须先POST cleanup-preview，再以相同keep_periods（默认8）、fingerprint及明确reason POST cleanup-confirm。候选只限同一资料要求、同一真实车号、平台的旧weekly周次；最新/当前期与最近N期全部版本保护。超N期旧周次的唯一版本可以清理，原提交事实与完整元数据继续保留。其它资料/任务/问题/空白模板/原件别名/保留archive引用、签单关联版本、实际事件最近前后版本均保护。日期精度事件按项目当地整日和所在ISO周保守保护，包括旧arrival_all日历锚点；旧状态审计补登不当成精确业务日期，保守保留。缺失原件、未知记录时刻、异常周次也保护。

确认在项目锁内重读所有规则、版本、引用、事件、文件stat、账号权限与预览指纹。任一变化409，全部重新预览；完整SHA不符也409，不跳过或部分执行。原件先原子移到DATA_DIR/.storage-trash，以fsync后的私有journal记录来源，再提交不可变receipt与tombstone。事务回滚恢复原件；提交后回收私有字节，失败明确pending_reclaim_bytes且启动/定时重试。另一worker恢复journal先等待同一项目锁，不把仍活跃事务误判成崩溃。service预览保持纯读；HTTP实际展示已授权私密文件元数据时记录T26访问审计，公开预览不加审计，访问日志不改变指纹。

迁移g3a25b000001新增upload_sessions、upload_chunks、file_cleanup_receipts、file_removal_records，均有项目CASCADE FK；chunks同时归属session，removal同时RESTRICT引用Attachment和receipt，用户引用SET NULL。Attachment/DocumentTemplateFile/TemplateDoc文件长度在PG升BIGINT；SQLite原生INTEGER已是有符号64位，避免重建破坏证据FK。迁移冻结schema，不导入live ORM；回退请恢复一致备份，不能丢弃上传/清理审计事实。

历史文件响应storage_state=removed_by_policy并给清理人、时间、原因；原字节下载410。旧期submitted只有精确receipt/原hash/原版本及当时完整保全范围能证明已交，T27门禁不把它误作普通缺失；最新/近期仍必须有真实原件。以后补录里程碑触及已清理范围，会如实展示storage_warnings，不造假恢复文件。

#85完整项目快照保留四表及所有旧版本/附件元数据。加密项目备份manifest逐条验证清理凭据，明确已授权清理的原字节不在包内，其余真实原件必须完整。恢复继续保留tombstone；永久删除需完整覆盖并验证全部项目FK后才能移除项目。永久删除后残留的已提交清理journal与未完成分片，通过存续的加密永久备份与完整指纹核对后回收，不能因现场receipt已删除而复活成孤儿原件；无法验证时保留私有journal。系统备份SQLite从备份数据库本身读原件清单，PG用同一REPEATABLE READ导出快照供pg_dump和清单；逐文件流式核长度/hash并确认全部普通原件已入包，否则不发布。系统还原同时移除旧私有缓存，客户端保留本地文件重传缺片。配置备份不包含临时分片、口令存储及旧已清字节；所有事实保留在数据库和清理凭据中。

项目整包HTTP与所选资料ZIP均在DATA_DIR私有目录以8MiB spool和1MiB块流式生成，避免2GiB整读及部署256MiB /tmp tmpfs限制；正式HTTP不调用兼容的小文件bytes wrapper。整包manifest对授权清理单独声明，不冒充普通缺失或包内原字节。

独立重型验收命令为backend/scripts/verify_resumable_storage.py，要求新建空*_t25_stream PostgreSQL库。实际loopback服务、2GiB真文件、3片后断开重连、重复chunk/finish、错整hash无入库及流式下载SHA核对；普通CI只跑小文件相同协议。验收证据见audit-artifacts/v3-t25-real-2gib.json。

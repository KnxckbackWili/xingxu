# AGV 项目管理系统优化报告

更新日期：2026-08-11
基线版本：1.5.1

## 结果摘要

- 原始 1.5.1 源码已复制到独立工作区，未复制运行数据库、上传附件、密钥、依赖缓存和构建产物。
- 后端测试从 141 项增加到 147 项，完整回归全部通过。
- Docker 端到端验证 9/9 通过，覆盖登录、项目、任务、排程、附件、报告、导出和 PWA。
- 前端生产构建通过，无超过 1 MB 的构建警告；PWA 预缓存从 2642.13 KiB 降至 2184.12 KiB，减少约 17.3%。
- ECharts 产物从 1052.15 kB 降至 548.84 kB，减少约 47.8%。

## 已完成优化

### 安全与数据边界

- 刷新令牌从 URL 查询参数改为 JSON 请求体，避免进入访问日志和浏览器历史。
- 项目不可见统一返回 404，避免通过接口差异探测项目存在性。
- 附件挂到任务或问题时校验实体必须属于当前项目。
- 静态资源路径解析限制在 `frontend/dist` 内，阻止目录穿越。
- 增加 `nosniff`、禁止 iframe、Referrer Policy 和 Permissions Policy 响应头。
- 默认不开放跨域；开发环境可通过 `CORS_ORIGINS` 精确配置。
- 生产首次启动必须提供 `INITIAL_ADMIN_PASSWORD`，默认关闭演示用户。
- Compose 不再注入固定弱密钥；留空时在数据卷生成并持久化随机密钥。

### 离线与 PWA

- 修复“服务端已写入但客户端丢失响应”导致重复填报永久滞留离线队列的问题。
- API 缓存由全部 `/api/*` 收紧为现场端只读接口，避免共享设备账号切换后读取前一用户缓存。
- 登录、刷新令牌和退出时自动清理账号相关 API 缓存。

### 后端性能

- 任务完成量、有效目标和检查项状态改为批量聚合，项目进度树不再逐任务重复查询。
- 总览、趋势和统一统计复用批量进度结果，移除主要 N+1 查询。
- 趋势图正确计入筛选窗口之前的累计完成量。
- 定时报告的逾期任务由逐任务查询改为两个聚合查询。
- 报告问题集只读取本周期变化或仍未解决的数据。
- 八周统计由八次数据库查询收敛为一次按日聚合。

### 前端性能与可用性

- 管理端、现场端、项目页及项目内部标签页按路由懒加载。
- ECharts 改为按需注册折线图、柱状图、饼图及必要组件。
- 移除强制合并整个 Ant Design 的大块策略，让构建器按实际共享关系拆包。
- 恢复移动端缩放能力，改善可访问性。
- 开发代理支持 `VITE_API_PROXY_TARGET`，可与已有生产容器并行运行。

### 部署与运维

- Dockerfile 改为 Node + Python 多阶段构建，干净源码无需预先提交 `frontend/dist` 即可部署。
- 增加 `.dockerignore`，排除数据库、密钥、依赖和本地产物。
- 增加数据库连通性健康检查。
- 增加 `docker/scripts/backup.sh`，在线一致性备份 SQLite、附件和持久化密钥。
- 验证脚本失败或中断时自动清理专用测试容器和镜像。

## 验证记录

```text
Backend: 147 passed
Frontend: tsc -b + vite build passed
Docker: verify.sh 9/9 passed
Compose: config validation passed
Shell: backup.sh and verify.sh syntax passed
Backup: live archive verified with agvpm.db + secret.key + uploads/
```

## 后续建议

1. 用 Alembic 建立正式迁移基线（版本追踪 + 空库回放），与 `_migrate()` 的幂等补列逻辑并存：存量库仍由 `_migrate()` 的 `ensure_column` 兜底，Alembic 主责版本链与可回放性。
2. 登录令牌迁移到 HttpOnly Cookie，并配套 CSRF 防护，进一步降低 XSS 后的令牌风险。
3. 逐页收敛前端 `any` 类型，并增加 Vitest 与关键流程浏览器测试。
4. 当并发写入或项目规模明显增长时，将 `projects.members` 正规化并评估 PostgreSQL。

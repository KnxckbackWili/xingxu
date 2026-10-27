# Agent 接入：Hermes、MCP 与 HTTP

外部接口保留只读查询和排程模拟。准确工具目录由 `GET /api/agent/tools` 按令牌范围返回；项目修改由有权成员在网页完成。

## 1. 创建访问令牌

管理员打开「系统 → Agent 接口」（`/pm/ai-tokens`），创建 Token 并绑定系统账号。

- 新令牌默认只读。已有令牌的权限不会自动增加，新增能力需管理员显式授权或重新签发令牌。
- Token 明文只显示一次；服务端只保存哈希。过期、停用、绑定账号停用都会拒绝访问。
- 每次调用同时检查 Token 权限、绑定账号的项目范围以及该操作的业务权限。

## 2. Hermes

在 `~/.hermes/config.yaml` 中加入：

```yaml
mcp_servers:
  agv:
    url: "https://agv.arrowwood.top:8773/api/ai/mcp/"
    headers:
      Authorization: "Bearer ${AGV_AGENT_TOKEN}"
```

在 Hermes 的环境变量或 `~/.hermes/.env` 设置 `AGV_AGENT_TOKEN` 为刚创建的令牌，重新启动 / 连接 Hermes，让其发现工具。不要把真实令牌提交到仓库。

配置格式依据 [Hermes 官方 MCP 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)：远程 HTTP 服务、请求头与环境变量引用。已验证标准 MCP 协议的初始化、工具发现和调用；未在用户机器安装或运行 Hermes 客户端。

其他支持 **Streamable HTTP MCP + Bearer 请求头** 的 Agent 使用相同 URL。MCP 服务采用无会话 JSON 响应，每次请求独立鉴权，适合经过 Nginx Proxy Manager 转发；保留 URL 末尾 `/` 和 `Authorization` 请求头。

## 3. 通用 HTTP 接口

不支持 MCP 的客户端也可使用相同 Token：

```bash
# AGV_AGENT_TOKEN 从环境读取；勿开启 shell 调试输出。
curl -H "Authorization: Bearer $AGV_AGENT_TOKEN" \
  https://agv.arrowwood.top:8773/api/agent/tools

curl -H "Authorization: Bearer $AGV_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{}}' \
  https://agv.arrowwood.top:8773/api/agent/tools/projects_list

# PROJECT_UUID 替换为 projects_list 返回的项目 id。
curl -H "Authorization: Bearer $AGV_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"project_id":"PROJECT_UUID"}}' \
  https://agv.arrowwood.top:8773/api/agent/tools/project_readiness
```

`GET /api/agent/tools` 只列出该 Token 获准的工具，包含 `inputSchema`、说明、所需 scope 和只读提示。`POST /api/agent/tools/{name}` 与 MCP 共用参数校验、工具实现和业务权限。

- 成功：`{"ok":true,"data":...}`。
- 业务拒绝（项目不可见、业务权限不足、业务参数越界等）：`{"ok":false,"error":"..."}`。客户端必须检查 `ok`，不能仅判断 HTTP 200。
- HTTP 401：Token 无效；403：工具 scope 未授权；404：工具不存在；422：参数不符合工具 schema。
- 非预期服务端异常不会向调用者返回数据库异常明细。

## 4. 工具目录

工具名称使用下划线，以下名称与实际注册一致。

| 工具 | 用途 | Scope |
|---|---|---|
| `projects_list` / `project_get` | 项目列表 / 基本信息 | `projects:read` |
| `project_readiness` | 工作量缺口、成员数、日程分配 / 下发状态、进场阻塞 | `projects:read` + `tasks:read` + `schedule:read` + `preparations:read` |
| `tasks_tree` | 执行任务与检查项，按模块返回并标明阶段 | `tasks:read` |
| `templates_list` / `template_get` | 模板版本、工作规则、检查项、准备与采购要求 | `templates:read` |
| `project_members` | 成员姓名、项目角色与账号是否启用 | `team:read` |
| `project_vehicles` | 车型配置、现场单车状态与问题数量 | `vehicles:read` |
| `project_files` | 文件元数据；`limit` 1–100，`offset` ≥0，默认50条 | `files:read` |
| `project_activity` | 最近动态与操作人；`limit` 1–100，默认30条 | `activity:read` |
| `get_schedule` | 当前执行日程 | `schedule:read` |
| `schedule_preview` | 模拟排程，不写入日程 | `schedule:preview` + 排程业务权限 |
| `preparations_summary` | 准备提醒与就绪状态 | `preparations:read` |
| `issues_list` | 项目问题 | `issues:read` |
| `inventory_list` | 现场物品 | `inventory:read` |
| `dashboard_overview` | 可见项目组合概况 | `dashboard:read` |

`project_files` 不提供文件正文、磁盘路径或下载凭据；分页响应含 `items` 和 `next_offset`，后者为 `null` 表示结束。不要把该工具的目录读取权限误当作附件下载权限。


## 5. 建议的 Agent 使用流程

1. `projects_list` 定位项目，避免猜测 UUID。
2. `project_readiness` 找出开工缺口；需要工作明细时读取 `tasks_tree`。
3. 按需查看 `get_schedule`、`issues_list`、`project_vehicles`、`project_activity`。
4. 整理建议并引用任务 / 文件 / 动态的具体 ID。
5. 将整理结果交项目负责人确认，由其在网页保存。

最近使用时间按5分钟粒度写入；鉴权和停用检查仍逐请求执行。工具数据库操作在线程池运行，避免外部 Agent 的同步查询占用 Web 事件循环。

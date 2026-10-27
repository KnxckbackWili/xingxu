# 消息通知外部渠道接入说明（HYPE-58）

站内通知（消息通知页）始终保留。本功能把站内通知**异步外发**到外部平台（当前支持：钉钉自定义
机器人 / 通用 JSON webhook）。外发是**尽力而为**——失败只记队列状态并重试，绝不影响站内通知
与主业务流程。

## 1. 架构（outbox 模式）

```
业务触发点 → notify()（同一事务内）
   ├─ 写站内通知 Notification（始终成功）
   └─ 写出站队列 notification_outbox（status=pending / 无渠道则 disabled）
                                              │
独立 scheduler 进程（SCHEDULER_ENABLED=1，每分钟）↓
   deliver_outbox(db, batch_size)
   └─ 逐条投递：pending → delivering → delivered
                                  └→ failed（attempts² × 60s 退避后重试）→ dead（超过最大次数）
```

- **业务事务里绝不发起外部 HTTP**：notify() 只落库，请求线程零外发延迟。
- **失败不重入主业务**：投递失败只改 outbox 行状态，不抛异常、不重发站内通知。
- **幂等**：每条通知带 `idempotency_key`，同时作 HTTP 头 `X-Idempotency-Key` 下发，接收方可去重；
  队列行对该键唯一。
- **安全**：密钥/URL 只从环境变量或文件读取，绝不写死；日志只打印 `scheme://host/path`，
  绝不打印 query（access_token/签名）或密钥。
- 未配置任何外部渠道时，notify() 直接把 outbox 行标记 `disabled`，不产生积压。

## 2. 管理员界面配置「通知渠道」（HYPE-58 新增）

管理员可在 **桌面侧栏 / 移动抽屉 → 系统 → 通知渠道**（`/pm/notification-channels`）管理外部渠道：

- **站内通知**：始终开启，不可停用；外部渠道启停不影响站内收件。
- **钉钉机器人**：启用开关、Webhook、可选加签 Secret、保存 / 停用 / 「发送测试通知」（二次确认）。
- **配置优先级**：部署环境变量 > 界面（数据库）配置。env 已配置时页面只读展示
  「由部署环境托管」，修改需改部署环境；无 env 配置时使用界面配置——调度器每次投递
  动态读取，保存 / 停用立即生效，**无需重启**。
- **安全边界**：
  - Webhook 与加签 Secret 使用 `channel_crypto`（cryptography Fernet + HKDF-SHA256，密钥派生自 `SECRET_KEY`/`secret.key`）加密落库，
    接口与日志只返回 `configured`、掩码（`access_token=****`）、来源与最近测试结果，绝无明文；
  - Webhook 仅允许 HTTPS + 官方主机 `oapi.dingtalk.com` + 官方路径 `/robot/send`，
    拒绝内网/回环/保留地址、非 443 端口、URL 内嵌凭据与未知参数（SSRF 防护）；
  - 「发送测试通知」仅 admin、需二次确认、每用户 10 分钟限流 5 次，结果写入审计
    （`last_test_*`，掩码存储）；测试直发、不走 outbox，不产生重复业务通知；
  - Secret 留空保存 = 保留现有值；「清除 Secret」显式清除；
  - 非管理员：入口不渲染，直达页面 403，全部 API 403；
  - 交付默认关闭，系统不会替用户启用钉钉。

## 3. 配置（环境变量）

| 变量 | 说明 | 示例 |
|---|---|---|
| `NOTIFY_CHANNELS` | 启用的外部渠道，逗号分隔：`dingtalk` / `json` | `dingtalk,json` |
| `DINGTALK_WEBHOOK_URL` | 钉钉机器人 Webhook 地址 | `https://oapi.dingtalk.com/robot/send?access_token=xxx` |
| `DINGTALK_WEBHOOK_SECRET` | 机器人加签密钥（可选；未加签机器人可留空） | `SECxxxxxxxx` |
| `DINGTALK_WEBHOOK_SECRET_FILE` | 加签密钥文件路径（可选，优先于环境变量场景） | `/run/secrets/dingtalk_secret` |
| `JSON_WEBHOOK_URL` | 通用 JSON webhook 地址（任意 HTTP 接收端） | `https://your-bot.example.com/hook` |
| `JSON_WEBHOOK_TOKEN` | 通用渠道鉴权 token，以 `Authorization: Bearer` 头发送（可选） | `tok_xxx` |
| `JSON_WEBHOOK_TOKEN_FILE` | 通用渠道 token 文件路径（可选） | `/run/secrets/json_token` |
| `NOTIFY_TIMEOUT_SECONDS` | 外发超时（秒，默认 3） | `3` |
| `NOTIFY_RETRY_MAX_ATTEMPTS` | 单条最大投递尝试次数（默认 3，超过转 dead） | `3` |
| `NOTIFY_RETRY_BASE_SECONDS` | 退避基数：`attempts² × 基数` 秒（默认 60） | `60` |
| `NOTIFY_DELIVERY_BATCH_SIZE` | 每轮投递最大条数（默认 50） | `50` |

**部署必须开启调度器**：`SCHEDULER_ENABLED=1`，否则出站队列不会自动投递。

**钉钉加签与不加签二选一**：
- 机器人安全设置选「加签」→ 把密钥填入 `DINGTALK_WEBHOOK_SECRET`（或文件）。
- 选「自定义关键词」→ 密钥留空即可（需保证消息含该关键词）。

密钥放文件时，把文件路径给 `*_FILE` 变量，与 AI key 的 `DEEPSEEK_API_KEY_FILE` 等读取模式
一致，方便挂载 Docker secret / K8s secret。

## 4. 接入步骤（单容器部署）

1. 钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 自定义（Webhook）。或准备一个可接收
   `POST {json}` 的通用 webhook 地址。
2. 复制 Webhook 地址，钉钉按需选「加签」或「自定义关键词」。
3. 部署时注入环境变量（`docker compose -f docker/docker-compose.multica.yml up -d --build` 前）：

   ```bash
   export SCHEDULER_ENABLED=1
   export NOTIFY_CHANNELS=dingtalk,json
   export DINGTALK_WEBHOOK_URL="https://oapi.dingtalk.com/robot/send?access_token=xxx"
   export DINGTALK_WEBHOOK_SECRET="SECxxxx"   # 加签时
   export JSON_WEBHOOK_URL="https://your-bot.example.com/hook"
   export JSON_WEBHOOK_TOKEN="tok_xxx"        # 可选
   ```

   或写入 `.env`（与 `docker/docker-compose.multica.yml` 同目录），compose 自动读取。

4. 验证：在系统里触发任意站内通知（如问题上报/指派、日程下达），钉钉群/JSON 接收端应收到
   消息。无外部凭据时系统照常运行，仅不外发（`NOTIFY_CHANNELS` 为空，outbox 行直接 disabled）。

## 5. 外发消息形态

**钉钉**（markdown 消息）：
- 标题：通知标题（截断 20 字）；正文：`### 标题` + 详情 + `> 类型：xxx`
- 超长内容截断到 4000 字符，避免被机器人限长拒绝

**通用 JSON webhook**（POST，`Content-Type: application/json`，可选 `Authorization: Bearer`）：
```json
{
  "title": "问题已上报",
  "content": "详情……",
  "type": "issue_reported",
  "project_id": "p1",
  "occurred_at": "2026-08-30T10:00:00",
  "idempotency_key": "uuid-xxxx",
  "source": "agv-pm"
}
```
同时下发 `X-Idempotency-Key` 请求头，接收方可按键去重。

## 6. 可扩展性

新增渠道：在 `app/services/notify_channels.py` 增加 `_send_<channel>()`、`<channel>_enabled()`
并在 `_deliver_one()` 中加入分发分支即可（`NOTIFY_CHANNELS` 天然支持逗号分隔多渠道）。
钉钉加签算法、JSON 负载、投递状态机（delivered/failed/dead/disabled）与幂等键均有单测覆盖
（`tests/test_notify_channels.py`），改动注意同步。

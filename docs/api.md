# 接口

所有接口在 `/api` 下。每个接口必须声明谁能调用，三选一：

- 依赖 `get_current_user`：任何启用中的账号；
- 依赖 `require_admin`：只有系统管理员；
- `@public("原因")`：不需要登录（只有登录、刷新、退出和未知路径）。

应用启动时检查全部路由（`backend/app/access.py`），有一个没声明就拒绝启动；`tests/test_foundation.py` 里有同样的测试。

浏览器用 HttpOnly Cookie 登录，写请求必须带 `X-CSRF-Token`；脚本可以用登录返回的 `access_token` 走 `Authorization: Bearer`。

| 分组 | 接口 | 说明 |
| --- | --- | --- |
| 登录 | `POST /auth/login`、`POST /auth/refresh`、`POST /auth/logout`、`GET /auth/me`、`PUT /auth/password` | 同一来源和用户名 15 分钟内输错 8 次后限速；改密码、重置密码、停用账号会让已有会话失效 |
| 首页 | `GET /overview` | 全部项目和各自的五类缺口。带 ETag，没变化返回 304 |
| 项目 | `GET /projects`、`POST /projects`、`GET /projects/{id}`、`PATCH /projects/{id}` | `GET /projects/{id}` 是项目快照：项目页要的全部内容一次返回，带 ETag |
| 项目删除 | `DELETE /projects/{id}`、`POST /projects/{id}/restore`、`GET /trash/projects`、`DELETE /trash/projects/{id}` | 管理员 |
| 记录 | `POST /projects/{id}/{kind}`、`PATCH …/{rid}`、`DELETE …/{rid}`、`POST …/{rid}/restore`、`PUT /projects/{id}/{kind}/order` | kind：`steps`、`vehicles`、`vehicle-records`、`work`、`issues`、`documents`、`items` |
| 车辆勾 | `PUT /projects/{id}/vehicles/{vid}/steps/{sid}`、`PUT /projects/{id}/steps/{sid}/all` | 单格、整列。请求体 `{"done": true}` |
| 文件 | `POST /projects/{id}/files`、`GET /files/{fid}`、`DELETE /files/{fid}`、`POST /files/{fid}/restore` | 上传用 multipart：`file`、`owner_kind`、`owner_id`、`id` |
| Excel | `GET /projects/{id}/export.xlsx`、`GET /projects/{id}/lifecycle.xlsx`、`POST /projects/{id}/import/{kind}?preview=true` | 导入 kind：`lifecycle`、`vehicles`、`work`、`documents`、`items` |
| 模板 | `GET/POST /templates`、`GET/PATCH/DELETE /templates/{id}`、`POST /templates/{id}/restore`、`POST /templates/{id}/copy`、`/templates/{id}/rows…`、`GET /templates/{id}/export.xlsx`、`POST /templates/{id}/import` | 清单行的接口和项目记录相同 |
| 车型库 | `GET/POST /vehicle-types`、`PATCH/DELETE /vehicle-types/{id}` | |
| 操作记录 | `GET /history?project_id=&user_id=&before=&limit=` | 账号、备份、更新的记录只有管理员看得到 |
| 账号 | `GET /users/names`；`GET/POST /users`、`PUT /users/{id}` | 后三个仅管理员 |
| 备份与更新 | `/system/backups…`、`/system/restore`、`/system/updates…` | 管理员 |
| 健康检查 | `GET /health` | 不在 `/api` 下，不需要登录 |

## 改一个格子

```
PATCH /api/projects/P/items/R
{ "quantity": { "from": 2, "to": 3 } }
```

- `from` 是编辑开始时格子里的值。数据库里现在的值等于 `from` 才写入；否则返回 409：`{"detail": …, "conflicts": {"quantity": {"current": 5, "by": "李娜"}}, "row": {…}}`，这次请求里的其他栏目也不写入。
- 不带 `from` 表示直接设定，打勾用这种写法。
- 一次可以改多个栏目。标记为固定的栏目（车辆记录所属的车辆、模板行所属的清单）创建后不能改。

## 新增一行

请求体带客户端生成的 `id`（UUID）。同一个 `id` 再发一次，返回已有的那一行，不会多出一行。

## 导入

带 `preview=true` 时走完整个导入过程后回滚，返回的数字就是确认导入后会发生的事。结果里的 `counts` 是逐项数量，`problems` 是读不了的行，`unknown_models` 是车型库里还没有的型号。

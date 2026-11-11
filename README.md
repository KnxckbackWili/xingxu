# 行序

AGV 实施项目的记录工具。把每个项目的车辆、工作、问题、资料、物品记下来，多人可以同时改，打开首页就能看到哪里缺什么、哪里还没做。支持 SQLite / PostgreSQL 和 Docker 单容器部署。

当前版本为 **4.0.0**。4.0 是从零重写的版本，不读 3.x 的项目数据，升级前请先看[从 3.x 升级到 4.0](docs/upgrade-to-4.md)。历史版本见 [CHANGELOG](CHANGELOG.md)。

开源地址：<https://github.com/KnxckbackWili/xingxu>（[MIT 许可证](LICENSE)）。正式版本的多架构镜像由 GitHub Actions 发布到 `ghcr.io/knxckbackwili/xingxu`。

## 它做什么

- **首页是一张缺口表**：一行一个项目，车辆、工作、问题、资料、物品各差多少，点数字直达。
- **在表格里直接记**：点格子就改，离开自动保存，最后一行回车新增，点一下打勾。手机上一行是一张卡片。
- **多人同时编辑**：别人的修改几秒内自动出现；改不同格子互不影响，改同一格会提示。
- **留痕和后悔药**：谁在什么时候改了什么都有记录；删除的内容 30 天内可以恢复。
- **Excel**：整个项目导出；公司的 AGV 生命周期表可以导入、导出。
- **只有两种账号**：系统管理员和员工。没有审批、没有截止日期、没有逾期。

## 快速开始

取得源码并为新安装准备配置（`<版本>` 用[最新发布标签](https://github.com/KnxckbackWili/xingxu/tags)的版本号）：

```sh
git clone --branch v<版本> https://github.com/KnxckbackWili/xingxu.git
cd xingxu
cp .env.example .env
# 编辑 .env，设置唯一的 INITIAL_ADMIN_PASSWORD，并核对部署安全配置
bash docker/scripts/manage.sh install
```

默认端口为 8000，首次账号为 admin，密码使用刚设置的值。不想在本机构建时，可按[部署说明](docs/deployment.md)直接使用 GHCR 镜像。已有实例升级、8002 部署、HTTPS/代理、加密备份和失败恢复请按[部署说明](docs/deployment.md)操作；软件更新接入见[更新指南](docs/software-updates.md)。

## 文档

- [使用说明](docs/user-guide.md)：一页讲完怎么用。
- [文档入口](docs/index.md)：术语、数据表、接口、多人编辑、部署、备份和更新。
- [开发约定](CLAUDE.md)、[版本历史](CHANGELOG.md)。

## 参与和反馈

问题和建议请在 [GitHub Issues](https://github.com/KnxckbackWili/xingxu/issues) 提交。提交代码前请阅读[开发约定](CLAUDE.md)。

## 许可证

[MIT](LICENSE)。第三方依赖遵循各自的许可证。

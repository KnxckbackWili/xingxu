# 行序 · 项目工作台

面向 AGV 实施团队的项目工作台，集中管理项目资料、车辆环节、现场问题、人员与计划，并保留真实文件、版本和审计来源。支持 SQLite / PostgreSQL 和 Docker 单容器部署。

当前版本为 **3.4.0**（已准备发布，尚未部署验收）。功能说明不代表迁移总验收或部署已完成；历史版本与当时的验收记录见 [CHANGELOG](CHANGELOG.md)。

## 快速开始

在可信源码目录中为新安装准备配置：

```sh
cp .env.example .env
# 编辑 .env，设置唯一的 INITIAL_ADMIN_PASSWORD，并核对部署安全配置
bash docker/scripts/manage.sh install
```

默认端口为 8000，首次账号为 admin，密码使用刚设置的值。已有实例升级、8002 部署、HTTPS/代理、加密备份和失败恢复请按[部署说明](docs/deployment.md)操作；软件更新接入见[更新指南](docs/software-updates.md)。

## 文档

- [项目经理](docs/quickstart-project-manager.md)、[实施工程师](docs/quickstart-engineer.md)、[管理员](docs/quickstart-admin.md)、[外部人员](docs/quickstart-external.md)：各一页说明。
- [文档入口](docs/index.md)与[术语表](docs/glossary.md)：查当前流程、资料、车辆、权限和运维规则。
- [开发约定](CLAUDE.md)、[版本历史](CHANGELOG.md)、[QA 证据归档与 SHA](docs/evidence-archive.md)。

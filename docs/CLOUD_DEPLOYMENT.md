# 云端部署交接状态 · 2026-10-20

目标：腾讯云轻量服务器 `121.4.117.45`，登录用户 `ubuntu`。

通过用户已登录的 OrcaTerm 浏览器终端实际检查：

- Ubuntu 24.04.4 LTS，Python 3.12.3。
- Docker 29.6.1，Docker Compose v5.3.1。
- 80/443 没有监听服务，Docker 当前没有运行中的容器。
- 根磁盘剩余约 42 GB，`ubuntu` 可通过 `sudo -n docker` 执行 Docker 管理命令。

部署材料：`deploy/compose.yaml`、`deploy/Dockerfile`、`deploy/Caddyfile`，以及 `backend/wsgi.py`。

验证：Gunicorn 实际 HTTP 健康检查、注册和鉴权调用通过；Compose YAML 已解析检查；WSGI 规范、代理 IP 信任、限流、在线 SQLite 备份、单监测器文件锁测试通过。Docker 镜像尚未在目标机实际构建。

代码交付改为 GitHub 仓库：`https://github.com/cms7058/PEBS_anti_miss.git`。云服务器通过 `git clone` 获取项目，更新时使用 `git pull --ff-only`；操作步骤见 `deploy/README.md`。本地账号、位置数据库、SSH/APNs 私钥和构建产物不提交。

待完成：

1. 从上述仓库拉取代码，在服务器构建 Docker 镜像并验证健康检查。
2. 如先用公网 IP 和 HTTP 测试，使用 `deploy/compose.http.yaml`，明确设置公网监听并开放对应腾讯云防火墙端口。该配置默认只监听本机。
3. 日常使用需配置 HTTPS；当前尚未提供域名。

本机 SSH 尚无可用的服务器登录密钥；用户已登录 OrcaTerm，可继续使用浏览器终端，不再依赖浏览器上传本地文件。

目前仅完成服务器只读检查，尚未启动云端后台。不能把本记录当作云服务已经上线的证明。

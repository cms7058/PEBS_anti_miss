# 腾讯云 Ubuntu 24.04 + Docker 云端部署

当前文件是部署准备材料，不代表已经部署成功。连接服务器后必须检查现有服务、端口、磁盘和 Docker 网络，再确定实际配置。

## 架构

`手机 HTTPS → Caddy（80/443）→ Gunicorn（Docker 内部 8087）→ SQLite 持久化卷`

- 后台使用专门的 WSGI 入口 `backend.wsgi:create_app()`，不将本地调试 HTTP 服务直接暴露到公网。
- Gunicorn 为单 worker、8 线程。定时监测另有文件锁，防止进程替换期间两个调度器重复执行通知任务。
- Caddy 自动申请和续期域名证书，覆盖客户端传来的 X-Real-IP；后台仅信任配置中的 Caddy 容器 IP。
- 后台没有映射到宿主机的端口；腾讯云安全组只需按实际管理来源允许 SSH，以及向客户端开放 TCP 80、443。不要公开 8087。
- 数据库在 `familyguard_backend_data` 卷；证书也使用独立卷。更新容器不删除这些数据。禁止使用 `docker compose down -v`。
- 部署包仅包含明确列出的源码与模板，排除本地数据库、照片、账号和 APNs 密钥。云端开始时是独立的空数据库；本地账号和老人绑定不会自动迁移。

## 连接前需要提供

1. 服务器公网 IP、SSH 用户名和端口。
2. 本机 SSH 主机别名或私钥文件路径；不要粘贴密码、私钥内容。
3. 已解析到服务器公网 IP 的域名。DNS 中不要保留指向其他服务器的 AAAA 记录。

域名准备、备案及端口可用性由服务器实际地区和云端配置决定；拿到服务器信息后核实，不会在此自动购买或创建付费资源。

## 生成代码部署包

也可使用 GitHub 仓库部署：本机提交代码并推送到指定仓库，云服务器通过 `git clone` 获取代码；更新时先确认服务器工作区没有未提交修改，再执行 `git pull --ff-only` 并重新构建镜像。每次发布记录 Git commit ID，便于回退。私有仓库的拉取需要 GitHub 已有授权，不能将访问令牌写入仓库、克隆 URL 或聊天记录。

`.gitignore` 已排除本地数据库、构建产物、环境配置和常见私钥文件。云端配置和持久化卷与 Git 工作区分开保存。

在项目根目录运行：

```sh
python3 scripts/package_backend.py
```

输出在 `build/deploy/`，包含归档 SHA-256 和内部逐文件校验清单。上传后先验证 `sha256sum -c MANIFEST.sha256`，再构建镜像。

## Docker 部署步骤

以下为需在确认过的服务器上执行的步骤；目前尚未执行。

1. 检查 `docker version`、`docker compose version`、`ss -lntp`、磁盘和 `docker network ls`，避免占用已有站点的 80/443 或与 `172.30.87.0/24` 冲突。
2. 将代码包解压到 `/opt/familyguard/releases/<release>/`，将 `/opt/familyguard/current` 指向该版本。配置保存在 `/etc/familyguard/cloud.env`，权限 600。不要将私有配置打进镜像。
3. 复制 `deploy/cloud.env.example` 到该配置路径，设置真实 `DOMAIN` 和独立 `RELEASE_TAG`。如果服务器已有 HTTPS 入口，复用其反向代理并调整 Compose，不能直接替换原站点。
4. 在发布目录创建 `deploy/secrets/`。没有 APNs 密钥时保持 APNS_KEY_PATH 为空；需要推送时放入私钥并使容器内 UID 10001 可读，权限 400，配置路径为 `/run/secrets/AuthKey.p8`。
5. 在发布目录执行：

```sh
docker compose --env-file /etc/familyguard/cloud.env -f deploy/compose.yaml config --quiet
docker compose --env-file /etc/familyguard/cloud.env -f deploy/compose.yaml build --pull backend
docker compose --env-file /etc/familyguard/cloud.env -f deploy/compose.yaml run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file /etc/familyguard/cloud.env -f deploy/compose.yaml up -d --wait
```

6. 验证 `https://实际域名/health` 证书和状态，实际注册测试账号、绑定测试设备并检查断网和异常事件。两端改填 `https://实际域名`，不带 `/health`。
7. 记录容器镜像 ID、归档校验值、域名证书、重启策略、数据库卷名和监测进程。真实苹果推送另需 APNs 密钥与真机签名，API 上线不代表推送已经配置。

## 无域名的临时 HTTP 测试

可以直接用 `http://121.4.117.45:8087` 访问服务器，无需域名。当前 Android Debug APK 和 iOS Debug 构建允许 HTTP；Release 构建要求 HTTPS。

HTTP 会明文传输登录密码、会话令牌和位置，临时联调使用专用测试账号和模拟位置。日常守护应使用 HTTPS。没有域名也可以研究 IP 地址证书，而不必把 HTTP 作为长期方案；[Let's Encrypt 已提供短期 IP 地址证书](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)，需配置对应的证书申请与自动续期。

`compose.http.yaml` 是独立测试配置，不需要 DOMAIN，也不运行 Caddy。默认只绑定服务器回环地址，先完成内部测试：

```sh
mkdir -p deploy/secrets
sudo docker compose -f deploy/compose.http.yaml up -d --build --wait
curl --fail http://127.0.0.1:8087/health
```

确定要开放 HTTP 临时测试后，使用：

```sh
sudo env HTTP_BIND_IP=0.0.0.0 docker compose -f deploy/compose.http.yaml up -d --wait
```

此时还需要在腾讯云轻量服务器防火墙以及启用的系统防火墙中，按实际测试来源允许 TCP 8087。变更云防火墙前确认已有规则及测试来源，不覆盖 SSH 规则。

客户端填写 `http://121.4.117.45:8087`；浏览器健康检查使用该地址后接 `/health`。HTTP 与 HTTPS 两套配置不可同时启动同一个 backend 服务。两者使用同一个项目名和数据库卷，切换前停止当前容器，保留卷和备份。项目仓库为 `https://github.com/cms7058/PEBS_anti_miss.git`，首次获取代码可执行：

```sh
git clone https://github.com/cms7058/PEBS_anti_miss.git
cd PEBS_anti_miss
```

## 备份与恢复

使用 SQLite 在线备份，不能直接复制处于 WAL 写入中的单个数据库文件：

```sh
docker compose --env-file /etc/familyguard/cloud.env -f deploy/compose.yaml exec -T backend python deploy/backup.py
```

备份存入数据卷 `/data/backups/`，执行完整性检查并使用仅所有者可读的权限，不自动删除旧备份。部署时再按实际服务器路径配置每日定时执行，并监测磁盘占用。备份仍在同一台服务器上，跨服务器或云存储备份需要另外指定目的地。

恢复前停止后台，保留现有数据库和 WAL 文件的恢复副本；使用完整性检查通过的备份创建新的数据卷并验证后再切换。不要直接覆盖正在运行的数据库。

更新代码前先备份，再用新 RELEASE_TAG 构建；回退可使用之前的镜像 ID 及同一个数据库卷，但若后续版本引入数据库迁移，应按该版本的恢复步骤操作。

## 不使用 Docker 的备用方案

`familyguard.service`、`backend.env.example` 和 `familyguard-backup.*` 是 systemd + Python venv 备用模板，不与 Docker 主方案同时启用。代码放 `/opt/familyguard/current`，状态在 `/var/lib/familyguard`，APNs 文件在 `/etc/familyguard/apns/`。Docker 主方案不需要安装宿主机 Gunicorn。

## 官方参考

- [Caddy 安装](https://caddyserver.com/docs/install)
- [Caddy 请求体限制](https://caddyserver.com/docs/caddyfile/directives/request_body)
- [Gunicorn 配置](https://docs.gunicorn.org/en/stable/settings.html)

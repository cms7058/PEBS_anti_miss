# 老人端个推接入 · 2026-10-22

AppID：`NtGxfjmcjPAb27hjz2R1e1`；包名：`cn.familyguard.elder`。

## 当前实现

- Android 已加入个推 SDK 3.3.16.0 / GTC 3.3.3.0 依赖、CID登记和透传接收代码。
- 没有围栏和 active 行程时不自动定位，也不每30秒检查服务端。仅在开启守护、推送到达、SDK重新连接等事件后同步；一次同步网络失败最多额外重试两次。
- 围栏或 active 行程期间约每分钟同步及定位；45秒定位窗口后停止订阅。
- 后端同时给定位请求、设置变更排队推送；有限重试、有效期和回执，接受推送不等于已收到位置。只发送同步信号，不发送位置、用户或设备凭证。
- 停止共享关闭本机推送和定位；解除绑定删除服务端设备通道和队列。
- 首次启用SDK需在老人端确认推送说明；未同意不初始化。应用中提供个推隐私说明入口。
- 无自动守护规则时，后台不会因旧位置触发“位置长时间未更新”事件；按需请求仍有独立超时。

## 配置密钥

在电脑或服务器复制 `deploy/getui.env.example` 为 `deploy/getui.env`，权限设为600。文件已被Git忽略，并被Docker构建上下文排除。不要上传到仓库或发送聊天。

```dotenv
GETUI_APP_ID=NtGxfjmcjPAb27hjz2R1e1
GETUI_APP_KEY=填写个推控制台的AppKey
GETUI_MASTER_SECRET=填写个推控制台的MasterSecret
```

MasterSecret仅给后端使用，AppSecret在当前接入中不需要。两个Compose文件会可选加载同目录的getui.env；需要Docker Compose 2.24及以上。配置文件缺失时，服务仍可运行，推送显示尚未配置。

将配置文件在云服务器上单独填写后，在项目目录运行原有Compose构建启动命令；不要删除数据库卷。`/health` 的 `elder_push_configured` 仅表示参数已填写，不代表鉴权或手机收信成功。

## 验证和限制

后端45项单元/HTTP测试、iOS编译、小程序接口测试及WXML/WXSS编译通过。Android 0.1.3（versionCode 4）构建成功，APK v2签名校验通过。包路径：`android/app/build/outputs/apk/debug/app-debug.apk`。SHA-256：`8adfb14e481e3e797eea27889c85df7c24015d751fb7a689dec1c2f4d693340e`。

本机配置已通过个推官方鉴权接口验证（只鉴权，未发送设备消息）。云端须单独配置，不能从GitHub拉取密钥。云端升级顺序：拉取代码；如无配置则复制`deploy/getui.env.example`为`deploy/getui.env`；填写AppKey、MasterSecret并chmod 600；原有Compose命令重建启动；最后安装手机端。不要覆盖已有密钥文件。

下载问题实际来自当前电脑的代理/域名解析路径。使用两个公共DNS的官方域名解析结果、保持HTTPS证书校验，从官方仓库获取依赖到被忽略的`build/toolchains/getui-maven`，构建使用该可选本地仓库。GTSDK和GTC的MD5均与官网页面匹配。没有修改系统代理或DNS。

安装前先更新云端并配置密钥，随后真机应验证：CID登记；无规则锁屏无定时定位；管理端请求后有新采集时间；规则启停能同步；断网超时；停止共享后不再采集。

当前仅接入个推在线透传通道，没有接入厂商离线通道。SDK维持通信连接，仍有耗电。Hi nova 11的后台保活、锁屏收信和耗电尚未验证。守护服务已被系统终止时，收到推送会展示打开应用的提示，不尝试绕过后台启动定位限制；推送也未到达时只能等待恢复或超时。不能宣称可随时静默唤醒。

## 官方参考

- https://docs.getui.com/getui/mobile/android/androidstudio/
- https://docs.getui.com/getui/mobile/android/api/
- https://docs.getui.com/getui/server/rest_v2/standard/
- https://docs.getui.com/getui/server/rest_v2/token/
- https://docs.getui.com/getui/server/rest_v2/push/

## 重装老人端或更换手机

成功使用过的绑定码会作废，不提供历史口令查询。需要重新绑定时，主管理员打开原有老人详情，点击“重新绑定老人手机”，确认后显示有效15分钟的新口令；新手机输入并确认共享后，旧设备令牌、推送通道和待处理定位指令会失效，围栏、行程及家属授权保留。不要重复添加老人。

这次需同时升级后端与iOS/小程序管理端，老人端0.1.3无需为此再次重装。生成口令不立即断开旧设备，取消或过期不会影响旧设备。只有主管理员能生成替换口令。

如果云服务器不能访问GitHub，可上传本地生成的`PEBS_anti_miss-main.bundle`到`/home/ubuntu/`，在项目目录执行：

```sh
git pull --ff-only /home/ubuntu/PEBS_anti_miss-main.bundle main
sudo env HTTP_BIND_IP=0.0.0.0 docker compose -f deploy/compose.http.yaml up -d --build --wait
```

离线Git包包含提交历史和源代码，不包含本地未跟踪的密钥或数据库。服务器的getui.env仍需单独配置。

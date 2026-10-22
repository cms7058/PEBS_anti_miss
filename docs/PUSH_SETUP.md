# 老人端个推接入 · 2026-10-22

最新为老人端0.1.4：需覆盖安装此版本，原有0.1.3已安装的用户也要更新。版本与手动刷新说明见文末最新记录。

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

## 定位查询与自动上报、异常删除（2026-10-22后续修正）

- 围栏或active行程期间自动采集是正常行为，管理端明确显示模式；无规则时继续按需查询。
- 在请求有效期内收到、且采集时间不早于请求的新位置，会满足该次查询。`completion_source=automatic`表示自动上报，`requested`表示设备携带对应请求号返回，不混称已成功唤醒。
- 旧位置、超时后采集的位置不冒充本次成功；晚到的新位置仍保存在地图上。界面会说明旧请求未直接响应，保留更新的位置。
- 推送未配置且没有自动守护规则时，管理端禁用主动获取按钮。自动守护运行但推送不可用时，按钮显示“等待下一次自动位置”。
- 主管理员及有设置修改权限的家属可删除事件。DELETE `/elders/{id}/events/{event_id}`实际删除事件、事件位置、关联推送队列。只保留不含内容和坐标的本轮异常种类关闭标记，防止同一持续异常每15秒重建；恢复后该标记清除，再次发生仍会提醒。
- 只读家属不能删除。删除属于共享数据操作，所有家属看到的列表都会更新。不会删除老人当前定位、围栏、行程或账号。
- 已有数据库启动时自动增加定位请求来源字段，保留旧记录。

### 云端仍显示推送未配置时

电脑的getui.env不随Git更新，须单独传到服务器。本次已从公网health核实云端老人推送配置为false。若云端GitHub访问失败，可在Mac终端上传离线包和已填写的配置：

```sh
scp /Users/mingyue/PEBS_anti_miss/build/deploy-transfer/PEBS_anti_miss-main.bundle /Users/mingyue/PEBS_anti_miss/deploy/getui.env ubuntu@121.4.117.45:/home/ubuntu/
```

云服务器终端：

```sh
cd ~/PEBS_anti_miss
git pull --ff-only /home/ubuntu/PEBS_anti_miss-main.bundle main
install -m 600 /home/ubuntu/getui.env deploy/getui.env
sudo env HTTP_BIND_IP=0.0.0.0 docker compose -f deploy/compose.http.yaml up -d --build --wait
curl --fail http://127.0.0.1:8087/health
```

health中elder_push_configured应为true；这只代表字段已配置，手机能否收到仍需测试。重新用Xcode安装管理端即可使用这轮修正，老人端0.1.3不需要重装。

## 最新：手动刷新页面与推送登记诊断（0.1.4）

- 老人端0.1.4 / versionCode 5，APK路径仍为`android/app/build/outputs/apk/debug/app-debug.apk`，覆盖安装，不要先卸载或清除数据。
- SDK经确认同意后preInit，显式登记ElderPushReceiver及ElderPushService，避免仅依赖自动发现；SDK已生成但回调遗漏的CID会从本地缓存取回。
- 启动期间最多5次本地CID检查，不增加永久联网轮询。SDK初始化失败不阻止已有自动守护，错误状态保留以便排查。
- 首页显示版本和具体推送状态，增加“重试推送登记”。未知版本的旧设备不再被管理端一律提示安装新版。
- POST `/device/diagnostics`仅允许已绑定设备写入本机版本、推送同意、CID是否存在、SDK连接状态及登记阶段；不接受或暴露CID原文、密钥、用户凭证。解绑/重新绑定时清除旧状态。
- iOS取消15秒后台数据轮询。首次进入登录会话读取一次，后续通过“立即刷新后台数据”、下拉刷新或用户操作更新。前台收到通知不自动替换位置快照；用户点击通知属于主动操作，可读取新快照。
- 小程序详情页同样取消普通15秒自动刷新。打开页面读取一次；主动定位查询最多等待40轮，每5秒一次，离开页面取消。iOS主动查询也只在用户点击后有限等待返回，不恢复永久轮询。
- 管理端不自动刷新不等于停止手机自动守护：围栏/active行程依然约每分钟采集，无规则时仅响应有效定位请求。
- 更新顺序：更新云端后端以支持诊断上报；覆盖安装0.1.4并开启守护（必要时点重试登记）；Xcode重新编译安装管理端；点击刷新后查看版本与登记状态。
- 当前仅完成编译和接口测试。Hi nova 11是否实际取得CID和可锁屏收信，仍需用户真机反馈；不得仅凭构建通过宣称登记已恢复。

## 最新：移动时定位、上传重试和异常按钮（0.1.5）

- 老人端0.1.5（versionCode 6），版本化包`build/releases/familyguard-elder-0.1.5-debug.apk`，覆盖安装保留绑定。
- GPS获取窗口最多90秒，运动时优先较新的样本；用单调时钟判断采集新旧，并容许原有服务端允许的小幅GPS/墙钟偏差，不要求手机静止。
- 最新待传位置写入本机私有配置，仅保留一个原始时间戳样本；移动网络中断时按5/15/30秒有限重试，网络恢复事件也会重试。超过120秒不再当作当前位置上传，停止共享/解绑清除待传位置。
- 上传与推送登记、诊断上报分离，SDK登记不再占用位置上传线程；丢失HTTP确认时用服务端最后采集时间核对，避免一次网络切换导致丢弃已采集位置。
- 服务端围栏连续样本最大间隔由120秒放宽至180秒，适应90秒采集窗口及网络重试；精度、误差边界、至少两次定位和outside_delay持续时间条件保留。更长空档仍重新计算连续越界。
- 按用户确认，目的地行程active或arrived时仍允许离开围栏，家属结束行程后才恢复围栏。界面显示监测中/行程豁免/精度不足/等待新位置/持续越界等原因。
- iOS异常行内按钮使用borderless样式独立响应，删除确认捕获指定事件，并可左滑删除，避免点删除触发地图或接手动作。
- 新增GET `/alerts`，只返回授权老人的事件列表，不返回当前定位、电量。管理端前台每15秒只更新异常，普通位置与电量仍手动刷新；小程序同样分离。
- Debug iOS允许本地通知权限，新发现的前台异常可提示；没有改变Debug远程推送签名设置。当前服务器APNs未配置，App退出/锁屏系统通知仍不能保证。
- 本次用户明确报告的是App打开时主动位置超时；尚未真机复测移动/网络切换效果。上述采集和重试修正需在同一手机复测，不能把代码测试通过当作现场完全恢复。

复测：更新云端、覆盖安装0.1.5、Xcode安装新管理端；开始守护后移动并主动查询；如测试日常围栏先结束目的地行程，再离开半径及定位误差边界，持续超过设定时长观察前台异常。位置失败时查看老人端“未取得位置”还是“已取得位置、上传失败”以区分采集和联网。

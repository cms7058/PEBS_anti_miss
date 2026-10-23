# 主动定位超时：现场只读诊断

iOS和小程序通过同一后端与老人手机获取位置。仅凭最终“超时”不能判断是推送未到达、定位无样本、网络上传失败还是部署版本不一致。定位请求state为received表示服务端记录到了设备命令读取，不等于已经取得GPS位置。

## 运行方法

先在管理端发起一次“获取最新位置”，等待约30秒，在Mac终端上传诊断脚本：

```bash
scp /Users/mingyue/PEBS_anti_miss/scripts/diagnose_location.py ubuntu@121.4.117.45:/home/ubuntu/
```

然后在已经登录的云服务器终端执行：

```bash
cd ~/PEBS_anti_miss
git log -1 --oneline
sudo docker compose -f deploy/compose.http.yaml exec -T backend python - < /home/ubuntu/diagnose_location.py
```

即使该请求已经超时，仍可运行。脚本以SQLite URI mode=ro读取，不触发请求状态更新，不重启容器，也不新建数据库。诊断脚本可以直接传入容器，不需要把它打进新镜像。

输出只含服务端时间、推送代码指纹/补发能力、配置是否齐全、匿名设备序号、手机曾上报的版本及SDK状态、请求/补发阶段和采集/上传距今秒数。不会输出姓名、坐标、电量、手机号、CID、绑定码、账号令牌或推送密钥。SDK在线状态是最近一次设备上报的历史状态，必须结合diagnostics_age_seconds判断，不能当作实时在线证明。

## 如何理解

- ack_retry_code_present=false：运行中的镜像没有27f012b引入的补发代码，即使仓库文件已更新，也需要确认容器是否完成了重新构建。
- state=pending/expired、command_fetch_recorded=false：未记录到老人手机读取本次命令，继续排查推送送达/后台服务；send_attempts和getui_configured帮助区分尚未发送与个推已受理。
- command_fetch_recorded=true、post_request_capture_present=false：命令读取已记录，但尚未保存请求后的新定位，需要设备日志判断定位无样本还是上传失败。
- post_request_capture_present=true：已有请求后采集的位置，需要结合state核对完成状态与管理端刷新。
- app_version为空或diagnostics_age_seconds很大：缺少或过期的设备报告，不能推断老人手机现在运行的版本/连接状态。

没有手机日志时，不把某个代码分支当作现场根因。此工具不修改定位逻辑，不需要重新安装管理端或老人端。


## 老人手机不在身边时：查询个推当前连接状态

可使用同一工具的`--live-push`选项。在Mac重新上传更新后的脚本，然后在云端执行：

```bash
cd ~/PEBS_anti_miss
sudo docker compose -f deploy/compose.http.yaml exec -T backend python - --live-push < /home/ubuntu/diagnose_location.py
```

不需要重建容器，也不需要操作老人手机。工具从容器已有配置中读取个推鉴权信息，从SQLite只读获取已绑定CID，调用个推官方`GET /user/status/$cid`。只返回匿名设备槽位对应的`online`/`offline`/`unknown`及是否查询成功，不输出原始接口响应、身份标识或凭据。不会调用发送推送接口，不修改任何手机设置。鉴权会按正常API流程获取临时访问凭据。

- `getui_live_query.succeeded=true`且`getui_status_now=offline`：查询时该App的个推连接离线；不等同于整个手机没有互联网。
- `getui_status_now=online`：查询时CID在线，不保证GPS已取得位置或手机已读取本次命令。
- `getui_status_now=unknown`或`succeeded=false`：查询失败/状态不明，不能当作离线；可能是配置、API权限或云端到个推的网络问题。
- `location_hint.last_send_failed`：最后一次发送是否记录失败；服务端仅配置了凭据不等同于每次发送成功。

此查询替代“55分钟前SDK上报为在线”来核查当前连接状态，仍不能静默修复系统禁止联网/启动的问题。

依据：[个推官方用户状态接口](https://docs.getui.com/getui/server/rest_v2/user/)。

## Wi-Fi 切换到移动数据后的恢复（老人端 0.1.8）

此前只在默认网络 `onAvailable` 时同步，5秒内的下一次切换可能被忽略，也没有处理稍后网络验证成功的事件。0.1.8 按网络身份合并事件，延迟1.5秒恢复：重新调用现有推送初始化/启用流程，重试缓存上传并读取命令。网络稍后通过互联网验证、或系统解除联网阻止时再触发一次恢复；旧网络的丢失回调不会取消新网络的恢复。同步失败沿用最多两次重试，不增加待机轮询或无规则时的定时定位。

这修补了可确认的恢复缺口，不证明它就是某台手机离线的唯一原因。`turnOnPush` 不是保证重连成功的接口；移动网络无法访问个推/后端、服务被系统停止等情况仍需实机日志确认。旧版手机离线时无法从服务端远程应用此修复。管理端和后端无需为此更新。

回归检查覆盖快速连续切换、延迟验证、重复事件、旧网络回调及解除联网阻止。APK编译通过不等同于已完成该手机的移动网络实测。

依据：[Android 网络回调与验证时序](https://developer.android.com/develop/connectivity/network-ops/reading-network-state)、[个推 Android API](https://docs.getui.com/getui/mobile/android/api/)。

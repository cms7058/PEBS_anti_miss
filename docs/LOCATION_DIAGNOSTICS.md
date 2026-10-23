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

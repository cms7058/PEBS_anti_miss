# 管理端：范围半径与页面更新

电子围栏可设为1–10000米，目的地到达半径可设为1–2000米。iOS支持直接输入整数、每次加减1米及常用范围快捷选项，小程序按米输入。编辑已有地点会保留中心，修改半径时不必重新搜索地址。

可设置1米不等于定位能精确到1米。手机最近定位误差大于设定半径时，界面会提示；越界和到达依然需要满足原来的定位误差过滤。例如到达半径1米，而手机误差约10米，不能仅凭坐标中心在目的地就确认到达。

位置页以地图和获取最新位置为主：手机电量、定位误差、采集时间集中显示。获取最新位置请求老人手机采集；刷新记录只读取服务端已有位置。围栏和目的地各有独立卡片，点击卡片编辑。连接诊断、授权、绑定及提醒规则收进详情或更多设置；异常提醒仍会在前台自动同步。

## 安装与部署

1. 云端需要更新代码并重新构建容器，否则小于100米的设置会被旧服务端拒绝。使用最新Git代码或离线bundle拉取后执行：

```bash
cd ~/PEBS_anti_miss
git pull --ff-only /home/ubuntu/PEBS_anti_miss-main.bundle main
sudo env HTTP_BIND_IP=0.0.0.0 docker compose -f deploy/compose.http.yaml up -d --build --wait
```

离线包在Mac的`/Users/mingyue/PEBS_anti_miss/build/deploy-transfer/PEBS_anti_miss-main.bundle`，先按此前流程通过scp上传服务器。

2. iOS在Xcode重新编译安装；这是管理端界面更新，必须重新安装编译后的版本才能看到。
3. 老人端APK无需更换。
4. 微信开发者工具重新编译，并按原流程生成体验版；本次没有上传或发布小程序。

模拟器页面截图（虚构数据）保存在项目build目录：ios-dashboard-location.png、ios-dashboard-radius.png。

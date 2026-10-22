# 家人守护 · 第一版开发原型

老人使用 **Android App**，儿女使用 **iPhone App（iOS 17+）或微信小程序（苹果/鸿蒙）**，通过同一个后台同步。当前是用于开发联调的原型，尚未完成两部真机的连续守护验收或上架。

2026-10-20 开发验证：Android Debug APK 已成功构建并通过签名校验；iPhone 工程已通过模拟器目标编译并在模拟器启动。具体记录见 [开发验证](docs/VERIFICATION.md)。

## 已实现

- Android：老人知情确认绑定、GPS / 系统网络定位、定位前台服务及常驻通知、最近同步状态、电量上报、停止共享和解除绑定。不依赖 Google Play Services。
- iPhone：账号注册登录、添加老人、地图查看、地点搜索、圆形围栏、本次目的地和到达时间、可配置异常阈值、事件位置、家属接手处理。
- 授权：主管理员生成一次性邀请；被授权人员可查看位置和处理提醒，可按邀请授予设置修改权；仅主管理员能邀请和移除人员。
- 后台：SQLite 持久化、会话鉴权、确定性异常判断、离线监测、事件去重、设置版本冲突检测、Apple APNs 通知队列和重试。
- iPhone 会显示“设置等待同步”“尚未配置苹果推送”等实际状态；APNs 接受通知与手机真正展示通知不会混为一谈。
- 接口坐标统一为 WGS-84，苹果地图展示及中国大陆搜索结果在界面边界做 GCJ-02 转换；近似转换已经提供参考点测试，地图服务在实际目标设备的坐标表现仍须实测。当前矩形区域判断针对大陆常见城市，不能作为完整国界数据。

## 第一版规则（可继续讨论）

| 情况 | 默认行为 |
|---|---|
| 日常活动 | 以指定中心和半径监测圆形围栏 |
| 持续越界 | 精度不超过 100 米；扣除误差后仍在围栏外；至少两次定位且持续 120 秒后报警 |
| GPS 漂移 | 边缘不确定区不直接判定越界；低精度位置不触发围栏或到达判定 |
| 指定目的地 | 本次行程暂时允许离开日常围栏；不会判断偏离路线 |
| 到达 | 新鲜且精度合格的位置及其误差范围落在到达区域内，确认到达；家属结束行程后恢复日常围栏 |
| 超时未到达 | 到达期限后仍无到达确认，通知家属；提醒不会声称已经证实老人迷路 |
| 位置未更新 | 10 分钟没有新位置就提醒；从绑定开始，即使从未上报也会检测 |
| 家属接手 | 所有已授权家属可见谁已接手；接手不代表异常已经恢复 |
| 异常恢复 | 保留事件历史，结束该异常的活动状态；以后再次异常可生成新事件 |

**当前采用的行程规则：** 从指定目的地开始到家属点击“结束本次行程”，暂停日常围栏。到达后允许在目的地停留，避免因正常外出重复触发日常围栏；期间仍监测超时未到达和位置未更新。路线偏离与目的地停留范围监测留待后续讨论。

## 运行后台

云服务器部署使用 [Docker Compose 部署说明](deploy/README.md)，对应腾讯云 Ubuntu 24.04 + Docker。部署包不会包含当前电脑上的数据库和密钥。

Python 3.9+。基础 API 和测试不需要安装第三方包。

```sh
cd /Users/mingyue/PEBS_anti_miss
python3 -m backend.server
```

默认仅监听 `127.0.0.1:8087`，避免与 HBuilderX 常用的 8080 端口冲突。iPhone 模拟器可以连接此地址。已经在 App 中保存过旧服务地址的，需要手动把端口改为 8087。两部真机联调时，在可信局域网运行：

```sh
HOST=0.0.0.0 DATABASE_PATH=build/family-dev.sqlite3 python3 -m backend.server
```

两部手机填写这台电脑的局域网地址，如 `http://192.168.1.20:8087`。HTTP 仅供 Debug 局域网联调，真实位置数据上线需要部署 HTTPS；Release 客户端拒绝 HTTP。

环境变量：`HOST`、`PORT`（默认 8087）、`DATABASE_PATH`（默认当前目录 family.sqlite3）。数据库、密码和推送密钥不要提交到版本库。原型未设置自动清理策略，正式部署前应确定位置、事件和账号的保留期限。

如果再次出现端口占用，服务会直接提示并退出。可以使用 `PORT=8088 python3 -m backend.server` 指定其他空闲端口，并同步修改手机 App 中的地址。终端按 Control+C 可停止后台；不要重复启动多个实例。

## iPhone 管理端

打开 [Xcode 工程](ios_app_antimiss/ios_app_antimiss.xcodeproj)，选择 `ios_app_antimiss` scheme。

- 模拟器：选择 iPhone 模拟器运行。首次创建管理账号，添加老人，复制绑定码。
- 真机测试：在 Signing & Capabilities 选择自己的 Apple 开发者 Team；使用自己注册的 Bundle ID，选择 Debug 编译安装。Debug 默认使用空的 `FamilyGuard.Debug.entitlements`，不要求苹果推送权限；可测试位置及管理功能。
- 正式苹果推送：Release 使用 `FamilyGuard.entitlements`，需要匹配的 Push Notifications 描述文件和后台 APNs 配置。若后续要用 Debug 测试 APNs，需先配置支持推送的开发描述文件，再恢复 Debug 的推送签名与注册逻辑。
- 管理授权：老人详情 → 管理授权人员 → 选择是否允许修改设置 → 生成邀请；另一位家属使用自己的账号接受邀请。
- 通知状态：主页 → 账号 → 启用 / 重试通知。允许系统通知，且后台配置 APNs 后才能测试退出 App 后的推送。

编译验证（不改变系统的 Xcode 选择）：

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
xcodebuild -project ios_app_antimiss/ios_app_antimiss.xcodeproj -scheme ios_app_antimiss \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/ios CODE_SIGNING_ALLOWED=NO build
```

源码位于 `ios_app_antimiss/ios_app_antimiss/`，Xcode 工程会自动识别目录内的 Swift 文件。迁移前的工程和模板文件备份在 `build/ios-migration-backup/`，无需运行旧的工程生成脚本。

## 微信小程序管理端

使用微信开发者工具导入 `wechat_app/`，AppID 为 `wx4ce2e3522237bc1d`。当前按 HTTP 内部体验配置，未上传/发布；真机需核实调试模式和平台网络限制。可登录现有 iOS 账号。

已实现位置地图、围栏/目的地地图点选、家属邀请与权限、事件接手；尚无微信后台订阅消息推送。导入、体验版和验收步骤见 [小程序说明](wechat_app/README.md)。鸿蒙原生端暂停，保留现有 iOS App。

## Android 老人端

使用 Android Studio 打开 `android/`，环境为 JDK 17、Gradle 8.11.1、Android SDK 35、Build Tools 35.0.0。标准工程不需要 Google 定位服务。

```sh
cd android
gradle :app:assembleDebug
```

也提供 `scripts/prepare_android_tools.py`，仅将经官方摘要验证的编译工具下载到项目 `build/toolchains`，不修改系统设置。适用于 Apple Silicon Mac，不自动接受任何 SDK 许可；具体使用仍须遵循供应商许可。若使用此工具，用 `scripts/build_android.sh` 编译。

测试包路径：`android/app/build/outputs/apk/debug/app-debug.apk`。

在老人手机安装后：

1. 输入服务地址和家属提供的绑定码。
2. 确认知情同意位置共享，点击绑定。
3. 点击“开始守护”，允许精确定位和通知。
4. 按该手机实际设置允许后台活动，检查常驻守护通知是否显示。
5. 锁屏步行测试，家属端核对位置时间、围栏触发和耗电。

开启守护后允许退到桌面和锁屏，并保留常驻通知。服务使用 START_STICKY 请求系统在普通回收后恢复；重新打开应用时会根据已保存的共享开关自动续接，手动停止或解绑后不自动恢复。Android 11+ 还会在没有新定位时尝试向系统请求当前位置。Hi nova 的应用启动管理、后台活动和电池优化仍需真机配置与验收。

目前不自动从开机广播启动定位；手机重启后需重新打开应用，以续接此前开启的守护。强制停止、关闭定位、失去权限或无网时不能承诺连续定位；云端会根据最近定位时间提示未更新。原型将监测放在服务器，没有网络时不会在老人手机本地报警。

## 苹果推送配置

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

在启动服务的环境中设置：

```sh
export APNS_KEY_PATH=/absolute/private/path/AuthKey.p8
export APNS_KEY_ID=your_key_id
export APNS_TEAM_ID=your_team_id
export APNS_TOPIC=your_registered_bundle_id
export APNS_ENV=sandbox
.venv/bin/python -m backend.server
```

Debug 真机签名使用 sandbox；TestFlight / App Store 使用 `APNS_ENV=production`，并使用正确签名和权限。通知默认只展示异常原因；具体位置由 App 登录后读取。没有推送凭据时事件会保存在 App，推送队列保持 pending，不会伪造已发送。

## 验证

```sh
python3 -m unittest backend.test_server -v
python3 -m unittest backend.test_http -v
python3 scripts/check_api_contract.py
```

`docs/ACCEPTANCE.md` 提供真机测试清单。当前代码不能代替一次在 Hi nova 11 和家属 iPhone 上完成的长时间实测，尤其要确认地图坐标、后台保活和真实推送。

## 官方参考

- [Android 定位前台服务限制](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- [Apple APNs 注册与签名要求](https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns)
- [Apple 推送服务端](https://developer.apple.com/documentation/usernotifications/setting-up-a-remote-notification-server)
- [MapKit for SwiftUI](https://developer.apple.com/documentation/mapkit/mapkit-for-swiftui)

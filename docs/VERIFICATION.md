# 开发验证记录 · 2026-10-20

本记录描述本机实际执行的验证，区别于尚未完成的真机验收。

## Android

- JDK：Temurin 17.0.20.1+1，官方下载并比对 SHA-256。
- Gradle：8.11.1，官方分发包并比对 SHA-256。
- SDK Platform / Build Tools：35 / 35.0.0，来自 Google 官方包并与其仓库元数据摘要比对。
- 命令：`sh scripts/build_android.sh`。
- 结果：`BUILD SUCCESSFUL`，35 项构建任务执行成功。
- 包名：`cn.familyguard.elder`，版本 0.1.0，最低 Android API 26。
- 测试包：`android/app/build/outputs/apk/debug/app-debug.apk`。
- `apksigner verify --verbose`：通过，APK Signature Scheme v2。
- APK SHA-256：`5ec25e3dd9e212fdf352384a0427130bbcf5b9a5cb09adb5e30928ed0e9b17c8`。
- Google 的 platform-tools / adb 尚未安装，构建时出现缺失及许可证提示；平台工具不是本次 assembleDebug 必需项，构建已成功。没有自动接受该许可。连接 Android 真机前应通过 Android Studio 正常安装并自行确认许可。
- 没有在老人 Hi nova 11 真机安装运行，不宣称后台定位、耗电或系统 API 兼容性已验收。

## iPhone

- Xcode：26.6（通过命令指定 `DEVELOPER_DIR`，未修改系统 Xcode 选择）。
- SDK：iPhone Simulator 26.5；部署目标 iOS 17.0。
- 工程：`ios_app_antimiss/ios_app_antimiss.xcodeproj`，scheme `ios_app_antimiss`（迁移前为 `FamilyGuard`）。
- Debug 模拟器目标构建：`BUILD SUCCEEDED`。
- 初始版本已在 iPhone 17 Pro / iOS 26.5 模拟器安装并启动，登录页面正常显示。之后的行程规则与坐标适配版本再次编译成功。
- 截图：`build/ios-login.png`（登录页，无真实用户位置）。
- 没有进行 iPhone 真机签名、TestFlight 分发或真实 APNs 通知投递。

### 工程目录迁移

- SwiftUI 源码已移至 `ios_app_antimiss/ios_app_antimiss/`，接入用户已有的 `ios_app_antimiss/ios_app_antimiss.xcodeproj`。
- 保留该工程的开发者 Team、Bundle ID 与 Assets；使用单一的 `ios_app_antimissApp` 启动入口。
- 新工程 Debug 模拟器目标构建：`BUILD SUCCEEDED`；后台响应与 Swift Codable 模型的对接检查通过。
- 原模板及旧工程备份：`build/ios-migration-backup/`。旧生成脚本已归入备份，不再用于生成当前工程。

### 图标与登录反馈修正

- 使用用户提供的 `docs/ChatGPT 图像 2026年10月20日 13_01_22.png`，将 1254 × 1254 原图转换为 AppIcon 要求的 1024 × 1024 不透明 PNG；保留 docs 原图。
- AppIcon 目录引用 `AppIcon.png`，移除没有指定图片的可选深色 / 着色槽位，系统使用默认图标。
- 图标修正及登录反馈代码均通过 Debug 模拟器构建和不签名的 `generic/platform=iOS` 真机构建。真机构建仍需开发者签名后才能安装，构建通过不等同于真机运行通过。
- 登录页新增后台连接测试、等待指示与就地错误文字。错误提示放到 ContentView，使预览和正常启动均可显示；通知授权与家庭数据刷新改在登录成功切换页面后执行。
- 本次没有取得用户点击注册时的具体运行错误；尚未宣称复现并确认了最初“没有反应”的唯一原因。更新后可根据连接测试和错误信息继续定位。

## 后台与模型

- `python3 -m unittest backend.test_server backend.test_http -v`：25 项测试。
- 覆盖绑定同意、口令过期、账号登录退出、分级授权与撤销、并发设置冲突、GPS 误差、持续越界、采样中断、行程豁免与结束、到达和超时、失联与恢复、过期位置、报警接手、通知队列及 APNs 模拟响应、真实回环 HTTP 请求和限流。
- Swift 坐标检查：北京参考点、正反转换、上海正反转换、海外坐标不转换，全部通过。
- `python3 scripts/check_api_contract.py`：iPhone 的实际 Codable 模型成功解析真实后台生成的完整测试响应，包括位置、设置、成员权限、事件与推送状态。
- Apple 地图实际搜索结果和 GPS 的坐标一致性，仍须在目标区域和真机上核对。参考点测试不能代替该实测。

下一阶段验收见 `docs/ACCEPTANCE.md`。本次没有部署公网服务、发布商店版本或发送任何真实家属通知。


## 2026-10-22 后台守护与刷新恢复

- Android 测试版本 0.1.1（versionCode 2）：保留用户守护开关，前台启动的定位服务可在退到桌面和锁屏后继续运行；普通回收请求 START_STICKY 恢复，重新打开时自动续接。手动停止/解绑先关闭共享开关，避免被自动恢复。
- 提供系统定位和电池优化设置入口；Android 11+ 无新定位时尝试 getCurrentLocation，并取消已销毁服务的请求；不把上次成功上传的位置重复当作新定位。
- 不提供开机广播自启，不保证厂商省电策略或强制停止后仍能运行；Hi nova 11 锁屏持续定位、后台恢复和耗电仍须真机验收。
- iOS：通知授权与数据刷新独立启动；一次网络错误后仍每 15 秒重试；界面分别标记后台刷新时间与老人定位时间，旧位置明确显示历史提示。防止旧会话/旧请求覆盖当前家庭数据。
- Swift 刷新循环的临时失败恢复和取消测试通过；iOS 模拟器 Debug 编译通过。Android Debug APK 构建及签名检查通过，尚未在用户手机完成覆盖安装与锁屏验收。

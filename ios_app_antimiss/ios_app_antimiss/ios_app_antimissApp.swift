import SwiftUI
import UserNotifications

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let value = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { @MainActor in await AppModel.shared.receivedPushToken(value) }
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in AppModel.shared.pushStatus = "推送不可用：\(error.localizedDescription)" }
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let id = response.notification.request.content.userInfo["elder_id"] as? String
        Task { @MainActor in
            AppModel.shared.selectedID = id
            try? await AppModel.shared.refresh()
        }
        completionHandler()
    }
}

@main struct ios_app_antimissApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel.shared
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            ContentView()
            .environmentObject(model)
            .tint(Color(red: 0.08, green: 0.42, blue: 0.36))
            .task(id: model.token) {
                guard !model.token.isEmpty else { return }
                // Initial load only. Subsequent telemetry changes require a user refresh.
                do { try await model.refresh() } catch { }
            }
            .task(id: scenePhase == .active ? model.token : "") {
                guard scenePhase == .active, !model.token.isEmpty else { return }
                await model.enablePush()
            }
        }
    }
}

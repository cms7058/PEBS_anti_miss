import Foundation
import Combine
import Security
import UIKit
import UserNotifications

enum Vault {
    static func read() -> String {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "cn.familyguard.session", kSecAttrAccount as String: "guardian",
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var value: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &value) == errSecSuccess,
              let data = value as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    static func write(_ token: String) throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "cn.familyguard.session", kSecAttrAccount as String: "guardian"]
        SecItemDelete(query as CFDictionary)
        if token.isEmpty { return }
        var item = query
        item[kSecValueData as String] = Data(token.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw ClientError.message("无法安全保存登录信息（钥匙串错误 \(status)）。请在运行后的模拟器或真机中重试。")
        }
    }
}
enum ClientError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}
final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

@MainActor final class AppModel: ObservableObject {
    static let shared = AppModel()
    @Published var token = Vault.read()
    @Published var server = UserDefaults.standard.string(forKey: "server") ?? "http://127.0.0.1:8087"
    @Published var elders: [Elder] = []
    @Published var error: String?
    @Published var notice: String?
    @Published var selectedID: String?
    @Published var pushStatus = "尚未启用通知"
    @Published var pushConfigured = false
    @Published var lastRefresh: Date?
    @Published var refreshFailure: String?
    private var refreshSequence = 0
    @Published var busy = false
    private var pushToken = ""
    private let network: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 20
        return URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
    }()

    func request<T: Decodable>(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> T {
        let base = server.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: base + path), let components = URLComponents(string: base),
              components.host != nil, components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil else { throw ClientError.message("服务地址无效") }
        #if DEBUG
        guard ["http", "https"].contains(url.scheme ?? "") else { throw ClientError.message("服务地址无效") }
        #else
        guard url.scheme == "https" else { throw ClientError.message("正式版本需要 HTTPS 服务地址") }
        #endif
        var request = URLRequest(url: url)
        request.timeoutInterval = 20
        request.httpMethod = method
        if !token.isEmpty { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await network.data(for: request)
        } catch let failure as URLError {
            switch failure.code {
            case .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed, .timedOut, .networkConnectionLost, .notConnectedToInternet:
                throw ClientError.message("无法连接后台 \(base)。请确认终端中的后台正在运行，并检查服务地址和端口；模拟器可用 127.0.0.1，真机需要电脑的局域网 IP。")
            case .appTransportSecurityRequiresSecureConnection:
                throw ClientError.message("系统阻止了 HTTP 连接。测试服务请使用最新 Debug 构建重新安装；正式版本请使用 HTTPS。")
            default:
                throw failure
            }
        }
        guard let response = response as? HTTPURLResponse else { throw ClientError.message("服务响应无效") }
        guard (200..<300).contains(response.statusCode) else {
            let content = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw ClientError.message(content?["error"] as? String ?? "请求失败（\(response.statusCode)）")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
    func perform(_ action: () async throws -> Void) async {
        guard !busy else { return }
        error = nil
        busy = true; defer { busy = false }
        do { try await action() } catch { self.error = error.localizedDescription }
    }
    func authenticate(name: String, password: String, register: Bool) async throws {
        // Changing the server requires logout, preventing credentials from going to a different host accidentally.
        let session: Session = try await request(register ? "/auth/register" : "/auth/login", method: "POST", body: ["name": name, "password": password])
        do { try Vault.write(session.token) }
        catch {
            let prefix = register ? "账号已创建，但登录未完成。关闭“首次使用”后可再次登录。\n" : ""
            throw ClientError.message(prefix + error.localizedDescription)
        }
        token = session.token
        UserDefaults.standard.set(server, forKey: "server")
        // Loading family data and requesting notifications run after the login screen changes.
        // A notification permission dialog must not hold the registration button in a busy state.
    }
    func refresh() async throws {
        guard !token.isEmpty else { return }
        let session = token, address = server
        refreshSequence += 1
        let sequence = refreshSequence
        do {
            let result: ElderList = try await request("/elders")
            try Task.checkCancellation()
            guard token == session, server == address, sequence == refreshSequence else { return }
            elders = result.elders
            lastRefresh = Date()
            refreshFailure = nil
            if let health: Health = try? await request("/health"),
               token == session, server == address, sequence == refreshSequence {
                pushConfigured = health.push_configured
            }
        } catch {
            if !Task.isCancelled, token == session, server == address, sequence == refreshSequence {
                refreshFailure = error.localizedDescription
            }
            throw error
        }
    }
    func enablePush() async {
        #if DEBUG
        pushStatus = "当前 Debug 测试版未启用苹果推送；可查看位置和 App 内异常记录"
        return
        #else
        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            pushStatus = granted ? "通知已允许，正在注册设备…" : "通知未允许，请到系统设置开启"
            if granted { UIApplication.shared.registerForRemoteNotifications() }
        } catch { pushStatus = "通知授权失败：\(error.localizedDescription)" }
        #endif
    }
    func receivedPushToken(_ value: String) async {
        pushToken = value
        guard !token.isEmpty else { return }
        do {
            let _: OK = try await request("/push/device", method: "POST", body: ["token": value])
            pushStatus = "推送设备已注册"
        } catch { pushStatus = "推送注册失败，请重试：\(error.localizedDescription)" }
    }
    func logout() async throws {
        if !pushToken.isEmpty { let _: OK = try await request("/push/device", method: "DELETE", body: ["token": pushToken]) }
        let _: OK = try await request("/auth/logout", method: "POST", body: [:])
        try Vault.write("")
        token = ""; elders = []; selectedID = nil; lastRefresh = nil; refreshFailure = nil
        UIApplication.shared.unregisterForRemoteNotifications()
    }
    func save(elder: Elder, settings: GuardSettings) async throws {
        let data = try JSONEncoder().encode(settings)
        let object = try JSONSerialization.jsonObject(with: data)
        let _: Elder = try await request("/elders/\(elder.id)/settings", method: "PUT", body: ["version": elder.version, "settings": object])
        try await refresh()
    }
}

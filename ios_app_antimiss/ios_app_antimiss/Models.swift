import Foundation
import CoreLocation

struct Point: Codable {
    var lat: Double
    var lon: Double
    var radius: Double
    var coordinate: CLLocationCoordinate2D { let p = Coordinates.display(lat: lat, lon: lon); return .init(latitude: p.lat, longitude: p.lon) }
}
struct Trip: Codable {
    var name: String
    var lat: Double
    var lon: Double
    var radius: Double = 200
    var deadline: Double
    var status: String = "active"
    var coordinate: CLLocationCoordinate2D { let p = Coordinates.display(lat: lat, lon: lon); return .init(latitude: p.lat, longitude: p.lon) }
}
struct GuardSettings: Codable {
    var fence: Point?
    var trip: Trip?
    var outside_delay: Double = 120
    var offline_after: Double = 600
    var automatic: Bool { fence != nil || trip?.status == "active" }
}
struct Position: Codable {
    let lat: Double
    let lon: Double
    let accuracy: Double
    let recorded_at: Double
    let battery: Double
    var coordinate: CLLocationCoordinate2D { let p = Coordinates.display(lat: lat, lon: lon); return .init(latitude: p.lat, longitude: p.lon) }
    var rawCoordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
}
struct Delivery: Codable { let state: String; let attempts: Int; let last_error: String? }
struct GuardEvent: Codable, Identifiable {
    let id: String
    let kind: String
    let message: String
    let created: Double
    let location: Position?
    let active: Int
    let handler: String?
    let delivery: [Delivery]
}
struct Member: Codable, Identifiable { let id: String; let name: String; let can_edit: Int }
struct ElderPushDelivery: Codable {
    let state: String
    let last_error: String?
}
struct ElderPushStatus: Codable {
    let configured: Bool
    let registered: Bool
    let location_delivery: ElderPushDelivery?
    let settings_delivery: ElderPushDelivery?
    var label: String {
        if !configured { return "老人端推送尚未配置，远程请求暂不能主动送达" }
        if !registered { return "老人手机尚未登记推送，请安装新版并开启守护" }
        switch location_delivery?.state {
        case "failed": return "推送发送失败，请检查服务器配置或稍后重试"
        case "accepted": return "个推已接受指令，等待手机接收"
        default: return "已配置老人端推送；手机休眠或停止服务可能影响响应"
        }
    }
}
struct LocationRequest: Codable {
    let id: String
    let requested_at: Double
    let expires: Double
    let state: String
    let completed_at: Double?
    let completion_source: String?
    var waiting: Bool { ["pending", "received"].contains(state) && expires > Date().timeIntervalSince1970 }
    var label: String {
        if ["pending", "received"].contains(state) && !waiting { return "定位请求已超时，请确认老人手机联网并开启守护" }
        switch state {
        case "pending": return "等待老人手机接收请求…"
        case "received": return "老人手机已收到请求，等待新位置…"
        case "completed": return completion_source == "automatic" ? "已收到请求后的自动上报位置" : "本次请求已取得新位置（\(timeLabel(completed_at ?? requested_at))）"
        default: return "定位请求已超时，请确认老人手机联网并开启守护"
        }
    }
}
struct Elder: Codable, Identifiable {
    let id: String
    let name: String
    let elder_push: ElderPushStatus?
    let location_request: LocationRequest?
    let paired: Bool
    let is_owner: Bool
    let can_edit: Bool
    let location: Position?
    let last_seen: Double?
    let version: Int
    let applied_version: Int
    let settings: GuardSettings
    let members: [Member]
    let events: [GuardEvent]
}
extension Elder {
    var canRequestPosition: Bool { paired && (settings.automatic || elder_push == nil || (elder_push!.configured && elder_push!.registered)) }
    var positionRequestTitle: String {
        if settings.automatic && !(elder_push?.configured == true && elder_push?.registered == true) { return "等待下一次自动位置" }
        return "获取最新位置"
    }
    var positionRequestLabel: String? {
        guard let request = location_request else { return nil }
        if request.state == "completed" { return request.label }
        if let position = location, position.recorded_at >= request.requested_at {
            return request.waiting ? "已收到更新位置，正在同步请求状态" : "已显示更新的位置；此前的定位请求未获得直接响应"
        }
        if request.waiting && settings.automatic { return "等待请求后的新位置，自动守护上报也可满足本次查询" }
        if request.waiting && !canRequestPosition { return "远程定位通道不可用，暂未能向老人手机发送请求" }
        return request.label
    }
}
struct ElderList: Codable { let elders: [Elder] }
struct Session: Codable { let token: String; let user_id: String; let name: String }
struct CodeResponse: Codable { let code: String; let expires: Double }
struct CreatedElder: Codable { let id: String; let code: String; let expires: Double }
struct OK: Codable { let ok: Bool }
struct Health: Codable { let ok: Bool; let push_configured: Bool }

func timeLabel(_ epoch: Double) -> String {
    Date(timeIntervalSince1970: epoch).formatted(date: .abbreviated, time: .shortened)
}

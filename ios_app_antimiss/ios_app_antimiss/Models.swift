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
struct LocationRequest: Codable {
    let id: String
    let requested_at: Double
    let expires: Double
    let state: String
    let completed_at: Double?
    var waiting: Bool { ["pending", "received"].contains(state) && expires > Date().timeIntervalSince1970 }
    var label: String {
        if ["pending", "received"].contains(state) && !waiting { return "定位请求已超时，请确认老人手机联网并开启守护" }
        switch state {
        case "pending": return "等待老人手机接收请求…"
        case "received": return "老人手机已收到请求，等待新位置…"
        case "completed": return "本次请求已取得新位置（\(timeLabel(completed_at ?? requested_at))）"
        default: return "定位请求已超时，请确认老人手机联网并开启守护"
        }
    }
}
struct Elder: Codable, Identifiable {
    let id: String
    let name: String
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
struct ElderList: Codable { let elders: [Elder] }
struct Session: Codable { let token: String; let user_id: String; let name: String }
struct CodeResponse: Codable { let code: String; let expires: Double }
struct CreatedElder: Codable { let id: String; let code: String; let expires: Double }
struct OK: Codable { let ok: Bool }
struct Health: Codable { let ok: Bool; let push_configured: Bool }

func timeLabel(_ epoch: Double) -> String {
    Date(timeIntervalSince1970: epoch).formatted(date: .abbreviated, time: .shortened)
}

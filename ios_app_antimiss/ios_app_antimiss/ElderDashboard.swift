import SwiftUI
import MapKit

struct LocationDashboard: View {
    @EnvironmentObject var model: AppModel
    let elder: Elder
    @Binding var camera: MapCameraPosition
    var body: some View {
        // Update age locally even if the user leaves the page open without refreshing.
        TimelineView(.periodic(from: .now, by: 1)) { context in
            content(at: context.date)
        }
    }
    private func content(at date: Date) -> some View {
        let stale = elder.locationIsHistorical(at: date)
        return VStack(alignment: .leading, spacing: 16) {
            Map(position: $camera) {
                if let position = elder.location {
                    Marker(stale ? "历史位置 · \(elder.name)" : elder.name, systemImage: "person.fill", coordinate: position.coordinate).tint(stale ? .orange : .teal)
                    MapCircle(center: position.coordinate, radius: position.accuracy).foregroundStyle(.teal.opacity(0.08))
                }
                if let fence = elder.settings.fence {
                    MapCircle(center: fence.coordinate, radius: fence.radius).foregroundStyle(.teal.opacity(0.12)).stroke(.teal, lineWidth: 2)
                }
                if let trip = elder.settings.trip, ["active", "arrived"].contains(trip.status) {
                    Marker(trip.name, systemImage: "flag.fill", coordinate: trip.coordinate).tint(.orange)
                }
            }.frame(height: 250).clipShape(RoundedRectangle(cornerRadius: 20))
                .overlay(alignment: .topLeading) {
                    Label(elder.settings.automatic ? "自动守护" : "按需查询", systemImage: elder.settings.automatic ? "shield.lefthalf.filled" : "location")
                        .font(.caption.weight(.semibold)).padding(.horizontal, 12).padding(.vertical, 8)
                        .background(.regularMaterial, in: Capsule()).padding(12)
                }
                .overlay(alignment: .bottomTrailing) {
                    if let position = elder.location {
                        Button {
                            camera = .region(MKCoordinateRegion(center: position.coordinate, latitudinalMeters: 1000, longitudinalMeters: 1000))
                        } label: { Image(systemName: "scope").padding(12).background(.regularMaterial, in: Circle()) }
                            .buttonStyle(.plain).accessibilityLabel("地图居中到老人位置").padding(12)
                    }
                }
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top) {
                    DashboardMetric(symbol: "battery.75percent", title: stale ? "上次电量" : "采集时电量", value: elder.location.map { "\(Int($0.battery))%" } ?? "—")
                    DashboardMetric(symbol: "scope", title: "定位误差", value: elder.location.map { "约 \(Int($0.accuracy)) 米" } ?? "—")
                    DashboardMetric(symbol: stale ? "clock.badge.exclamationmark" : "clock", title: stale ? "历史位置" : "采集时间", value: elder.location.map { Date(timeIntervalSince1970: $0.recorded_at).formatted(date: .omitted, time: .shortened) } ?? "未定位")
                }
                if stale && elder.location != nil {
                    Label("暂无3分钟内的位置 · 地图仅为历史参考，请获取最新位置", systemImage: "clock.badge.exclamationmark")
                        .font(.caption).foregroundStyle(.orange)
                }
                if let position = elder.location {
                    Text("采集于 \(timeLabel(position.recorded_at))").font(.caption).foregroundStyle(stale ? Color.orange : Color.secondary)
                    Text(String(format: "纬度 %.6f · 经度 %.6f", position.lat, position.lon))
                        .font(.footnote.monospaced()).textSelection(.enabled)
                    Text("\(position.sourceLabel) · 坐标系 WGS-84").font(.caption2).foregroundStyle(.secondary)
                } else { Text(elder.paired ? "等待老人手机首次定位" : "请先绑定老人手机").font(.caption).foregroundStyle(.secondary) }
                RemoteLocationView(elder: elder, historical: stale)
                HStack {
                    Button { Task { await model.perform { try await model.refresh() } } } label: { Label("刷新记录", systemImage: "arrow.clockwise") }
                        .disabled(model.busy)
                    Spacer()
                    if let position = elder.location {
                        Button { MKMapItem(placemark: MKPlacemark(coordinate: position.coordinate)).openInMaps() } label: { Label("打开地图", systemImage: "arrow.up.right.square") }
                    }
                }.font(.subheadline).buttonStyle(.borderless)
                if let failure = model.refreshFailure { Label(failure, systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange) }
                if let refreshed = model.lastRefresh {
                    Text("记录读取于 \(refreshed.formatted(date: .omitted, time: .standard)) · 位置与电量为上次采集值")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }.padding(.horizontal, 18).padding(.bottom, 18)
        }.background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 22))
    }
}

private struct DashboardMetric: View {
    let symbol: String
    let title: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(title, systemImage: symbol).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline).monospacedDigit()
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct GuardDashboard: View {
    @EnvironmentObject var model: AppModel
    let elder: Elder
    let edit: (String) -> Void
    let members: () -> Void
    let pair: () -> Void
    @State private var showRules = false
    private var tripActive: Bool { elder.settings.trip.map { ["active", "arrived"].contains($0.status) } ?? false }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                ruleCard(mode: "fence", title: "电子围栏", symbol: "shield.lefthalf.filled", color: .teal,
                    value: elder.settings.fence.map { "\(Int($0.radius)) 米" } ?? "未设置",
                    detail: elder.settings.fence == nil ? "设置安全活动范围" : tripActive ? "行程期间暂停" : "安全活动半径")
                ruleCard(mode: "trip", title: "本次目的地", symbol: "flag.fill", color: .orange,
                    value: elder.settings.trip?.name ?? "未指定",
                    detail: elder.settings.trip.map { "到达半径 \(Int($0.radius)) 米" } ?? "指定地点与到达时间")
            }
            VStack(alignment: .leading, spacing: 10) {
                if let status = elder.fence_status, elder.settings.fence != nil {
                    Label(status.message, systemImage: status.state == "inside" ? "checkmark.shield" : "info.circle")
                        .foregroundStyle(status.state == "inside" ? Color.teal : Color.secondary)
                }
                if let trip = elder.settings.trip, tripActive {
                    Label(trip.status == "arrived" ? "已到达 · 结束行程后恢复围栏" : "预计 \(timeLabel(trip.deadline)) 前到达", systemImage: trip.status == "arrived" ? "checkmark.circle" : "clock")
                }
                if let accuracy = elder.location?.accuracy,
                   (elder.settings.fence.map { $0.radius < accuracy } ?? false) || (elder.settings.trip.map { $0.radius < accuracy } ?? false) {
                    Label("设定半径小于最近定位误差，可能暂时无法判定。", systemImage: "location.slash").foregroundStyle(.orange)
                }
                if elder.version != elder.applied_version {
                    Label("等待老人手机同步设置", systemImage: "arrow.triangle.2.circlepath").foregroundStyle(.orange)
                }
                if elder.elder_push?.settings_delivery?.state == "failed" {
                    Label("设置推送失败，请打开老人端同步", systemImage: "exclamationmark.circle").foregroundStyle(.orange)
                }
            }.font(.caption)
            HStack {
                if elder.can_edit && tripActive {
                    Button("结束行程", systemImage: "flag.slash") { changeSettings { $0.trip = nil } }.buttonStyle(.bordered)
                }
                Spacer(minLength: 0)
                Menu {
                    if elder.can_edit {
                        Button("提醒规则", systemImage: "bell") { showRules = true }
                        if elder.settings.fence != nil { Button("关闭电子围栏", role: .destructive) { changeSettings { $0.fence = nil } } }
                    }
                    if elder.is_owner {
                        Button("管理授权人员", systemImage: "person.2") { members() }
                        Button(elder.paired ? "重新绑定老人手机" : "获取老人手机绑定码", systemImage: "link") { pair() }
                    }
                } label: { Label("更多设置", systemImage: "ellipsis.circle") }.disabled(!elder.can_edit && !elder.is_owner)
            }.font(.subheadline).buttonStyle(.borderless).disabled(model.busy)
        }.padding(16).background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 22))
            .sheet(isPresented: $showRules) { NavigationStack { RulesView(elder: elder).toolbar { Button("完成") { showRules = false } } } }
    }
    private func ruleCard(mode: String, title: String, symbol: String, color: Color, value: String, detail: String) -> some View {
        Button { edit(mode) } label: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: symbol).font(.title3).foregroundStyle(color)
                    Spacer(minLength: 0)
                    if elder.can_edit { Image(systemName: "pencil").font(.caption).foregroundStyle(.secondary) }
                }
                Text(title).font(.subheadline).foregroundStyle(.secondary)
                Text(value).font(.title3.bold()).foregroundStyle(.primary).lineLimit(2).multilineTextAlignment(.leading)
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, minHeight: 144, alignment: .topLeading).padding(14)
                .background(color.opacity(0.07), in: RoundedRectangle(cornerRadius: 16))
        }.buttonStyle(.plain).disabled(!elder.can_edit || model.busy)
    }
    private func changeSettings(_ update: @escaping (inout GuardSettings) -> Void) {
        Task { await model.perform { var settings = elder.settings; update(&settings); try await model.save(elder: elder, settings: settings) } }
    }
}

struct RadiusEditor: View {
    @Binding var text: String
    let maximum: Int
    private var value: Int { Int(text) ?? 1 }
    private var valid: Bool { Int(text).map { (1...maximum).contains($0) } ?? false }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 16) {
                Button { text = String(max(1, min(maximum, value - 1))) } label: { Image(systemName: "minus.circle.fill").font(.title) }
                    .accessibilityLabel("半径减少 1 米").disabled(value <= 1)
                TextField("半径", text: $text).keyboardType(.numberPad).multilineTextAlignment(.center)
                    .font(.system(.largeTitle, design: .rounded).bold()).monospacedDigit().accessibilityLabel("半径，单位米")
                Text("米").foregroundStyle(.secondary)
                Button { text = String(min(maximum, max(1, value + 1))) } label: { Image(systemName: "plus.circle.fill").font(.title) }
                    .accessibilityLabel("半径增加 1 米").disabled(value >= maximum)
            }.buttonStyle(.borderless)
            Slider(value: Binding(get: { Double(max(1, min(maximum, value))) }, set: { text = String(Int($0)) }), in: 1...Double(maximum), step: 1)
            HStack {
                ForEach([25, 50, 100, 200, 500], id: \.self) { preset in
                    Button("\(preset)") { text = String(preset) }.buttonStyle(.bordered).tint(value == preset ? .teal : .secondary)
                        .frame(maxWidth: .infinity).accessibilityLabel("半径 \(preset) 米")
                }
            }.font(.caption)
            Text(valid ? "可输入 1–\(maximum) 米，按 1 米调整" : "请输入 1–\(maximum) 米的整数")
                .font(.caption).foregroundStyle(valid ? Color.secondary : Color.orange)
        }.padding(.vertical, 8)
    }
}

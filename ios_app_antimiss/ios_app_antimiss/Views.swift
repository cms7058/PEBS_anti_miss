import SwiftUI
import MapKit

struct LoginView: View {
    @EnvironmentObject var model: AppModel
    @State private var name = ""
    @State private var password = ""
    @State private var register = false
    @State private var checkingConnection = false
    @State private var connectionStatus: String?
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("家人守护", systemImage: "heart.circle.fill").font(.largeTitle.bold()).padding(.vertical)
                    Text("查看家人位置，让每次出门都安心。")
                }
                Section("连接服务") {
                    TextField("HTTPS 服务地址", text: $model.server)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                        .disabled(model.busy)
                    Text("模拟器：http://127.0.0.1:8087；真机请填写电脑的局域网 IP。")
                        .font(.caption).foregroundStyle(.secondary)
                    Button {
                        Task {
                            checkingConnection = true
                            connectionStatus = nil
                            defer { checkingConnection = false }
                            await model.perform {
                                let health: Health = try await model.request("/health")
                                guard health.ok else { throw ClientError.message("后台健康检查未通过") }
                                connectionStatus = "后台连接正常"
                            }
                        }
                    } label: {
                        HStack {
                            if checkingConnection { ProgressView() }
                            Text(checkingConnection ? "正在检查连接…" : "测试后台连接")
                        }
                    }.disabled(model.busy)
                    if let connectionStatus { Label(connectionStatus, systemImage: "checkmark.circle.fill").foregroundStyle(.teal) }
                }
                Section("管理人员账号") {
                    TextField("账号（至少 2 字）", text: $name).textInputAutocapitalization(.never).autocorrectionDisabled().disabled(model.busy)
                    SecureField("密码（至少 10 字）", text: $password).disabled(model.busy)
                    Toggle("首次使用，创建账号", isOn: $register).disabled(model.busy)
                    Button {
                        let submittedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
                        let submittedPassword = password
                        let creatingAccount = register
                        Task { await model.perform { try await model.authenticate(name: submittedName, password: submittedPassword, register: creatingAccount) } }
                    } label: {
                        HStack {
                            if model.busy && !checkingConnection { ProgressView() }
                            Text(model.busy && !checkingConnection ? (register ? "正在创建账号…" : "正在登录…") : (register ? "创建账号并进入" : "登录"))
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }.disabled(model.busy || name.trimmingCharacters(in: .whitespacesAndNewlines).count < 2 || password.count < 10)
                    if let error = model.error { Text(error).font(.footnote).foregroundStyle(.red).textSelection(.enabled) }
                }
            }.navigationTitle("欢迎回家")
                .onChange(of: model.server) { _, _ in connectionStatus = nil }
        }
    }
}

struct HomeView: View {
    @EnvironmentObject var model: AppModel
    @State private var newName = ""
    @State private var invite = ""
    @State private var add = false
    @State private var showAccount = false
    @State private var code: String?
    var body: some View {
        NavigationStack {
            List {
                Section { DataSyncStatusView() }
                Section {
                    ForEach(model.elders) { elder in
                        NavigationLink(value: elder.id) {
                            VStack(alignment: .leading, spacing: 8) {
                                Label(elder.name, systemImage: "person.crop.circle.fill").font(.title3.bold())
                                Text(summary(elder)).font(.subheadline).foregroundStyle(.secondary)
                                let count = elder.events.filter { $0.active == 1 && $0.handler == nil }.count
                                if count > 0 { Text("\(count) 条提醒待处理").foregroundStyle(.orange) }
                            }.padding(.vertical, 6)
                        }
                    }
                    if model.elders.isEmpty { ContentUnavailableView("尚未添加家人", systemImage: "person.badge.plus", description: Text("添加老人，或输入其他家属的邀请。")) }
                } header: { Text("我的家人") }
                Section("加入已有家庭") {
                    TextField("输入邀请口令", text: $invite).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button("接受邀请") {
                        Task { await model.perform {
                            let _: OK = try await model.request("/invites/accept", method: "POST", body: ["code": invite.trimmingCharacters(in: .whitespacesAndNewlines)])
                            invite = ""; try await model.refresh()
                        } }
                    }.disabled(invite.isEmpty || model.busy)
                }
                if !model.pushConfigured { Section { Label("服务器尚未配置苹果推送；提醒会保存在 App 内。", systemImage: "bell.slash").foregroundStyle(.orange) } }
            }
            .navigationTitle("家人守护")
            .navigationDestination(for: String.self) { ElderView(id: $0) }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("账号", systemImage: "person.circle") { showAccount = true } }
                ToolbarItem(placement: .topBarTrailing) { Button("添加", systemImage: "plus") { add = true } }
            }
            .refreshable { do { try await model.refresh() } catch { model.error = error.localizedDescription } }
            .alert("添加老人", isPresented: $add) {
                TextField("老人称呼，例如妈妈", text: $newName)
                Button("添加") {
                    Task { await model.perform {
                        let result: CreatedElder = try await model.request("/elders", method: "POST", body: ["name": newName])
                        code = result.code; newName = ""; try await model.refresh()
                    } }
                }
                Button("取消", role: .cancel) { }
            }
            .sheet(isPresented: Binding(get: { code != nil }, set: { if !$0 { code = nil } })) { CodeView(title: "老人手机绑定码", code: code ?? "", detail: "15 分钟内，在老人手机输入此码并确认位置共享。") }
            .sheet(isPresented: $showAccount) { account }
            .sheet(item: Binding(get: { model.selectedID.map { Selection(id: $0) } }, set: { model.selectedID = $0?.id })) { selection in NavigationStack { ElderView(id: selection.id).toolbar { Button("完成") { model.selectedID = nil } } } }
        }
    }
    func summary(_ elder: Elder) -> String {
        if !elder.paired { return "等待老人手机绑定" }
        guard let loc = elder.location else { return "等待首次定位" }
        return "最近定位 \(timeLabel(loc.recorded_at)) · 电量 \(Int(loc.battery))%"
    }
    var account: some View {
        NavigationStack {
            Form {
                Section("通知状态") { Text(model.pushStatus); Button("启用 / 重试通知") { Task { await model.enablePush() } }; Button("打开系统设置") { if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) } } }
                Section { Text(model.server); Button("退出登录", role: .destructive) { Task { await model.perform { try await model.logout(); showAccount = false } } }.disabled(model.busy) }
            }.navigationTitle("账号与通知").toolbar { Button("完成") { showAccount = false } }
        }
    }
}
struct Selection: Identifiable { let id: String }
struct CodeView: View {
    let title: String
    let code: String
    let detail: String
    @Environment(\.dismiss) var dismiss
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Image(systemName: "person.2.badge.key.fill").font(.system(size: 56)).foregroundStyle(.tint)
                Text(code).font(.title.monospaced().bold()).textSelection(.enabled)
                Text(detail).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Button("复制口令") { UIPasteboard.general.string = code }.buttonStyle(.borderedProminent)
            }.padding(32).navigationTitle(title).toolbar { Button("完成") { dismiss() } }
        }
    }
}

struct ElderView: View {
    @EnvironmentObject var model: AppModel
    let id: String
    @State private var edit: String?
    @State private var members = false
    @State private var pairCode: String?
    @State private var camera: MapCameraPosition = .automatic
    var elder: Elder? { model.elders.first { $0.id == id } }
    var body: some View {
        Group {
            if let elder {
                List {
                    Section { DataSyncStatusView() }
                    Section {
                        Map(position: $camera) {
                            if let location = elder.location { Marker(elder.name, systemImage: "person.fill", coordinate: location.coordinate).tint(.teal) }
                            if let fence = elder.settings.fence { MapCircle(center: fence.coordinate, radius: fence.radius).foregroundStyle(.teal.opacity(0.13)).stroke(.teal, lineWidth: 2) }
                            if let trip = elder.settings.trip, ["active", "arrived"].contains(trip.status) { Marker(trip.name, systemImage: "flag.fill", coordinate: trip.coordinate).tint(.orange) }
                        }.frame(height: 270).clipShape(RoundedRectangle(cornerRadius: 18))
                        if let loc = elder.location {
                            Text("定位于 \(timeLabel(loc.recorded_at)) · 精度约 \(Int(loc.accuracy)) 米").font(.caption).foregroundStyle(Date().timeIntervalSince1970 - loc.recorded_at > elder.settings.offline_after ? .orange : .secondary)
                            if Date().timeIntervalSince1970 - loc.recorded_at > elder.settings.offline_after {
                                Label("此为历史位置，老人端尚未上报新位置", systemImage: "clock.badge.exclamationmark")
                                    .font(.caption).foregroundStyle(.orange)
                            }
                            Text("电量 \(Int(loc.battery))% · \(loc.lat.formatted(.number.precision(.fractionLength(5)))), \(loc.lon.formatted(.number.precision(.fractionLength(5))))").font(.caption)
                            Button("在地图中查看此位置") { MKMapItem(placemark: MKPlacemark(coordinate: loc.coordinate)).openInMaps() }
                        } else { Text(elder.paired ? "等待老人手机上传位置" : "等待老人手机绑定") }
                        if elder.version != elder.applied_version { Label("设置已保存，等待老人手机同步", systemImage: "arrow.triangle.2.circlepath").foregroundStyle(.orange) }
                    }
                    Section("守护设置") {
                        LabeledContent("电子围栏", value: elder.settings.fence.map { "半径 \(Int($0.radius)) 米" } ?? "未设置")
                        if let trip = elder.settings.trip {
                            LabeledContent("目的地", value: trip.name)
                            Text(trip.status == "active" ? "预计 \(timeLabel(trip.deadline)) 前到达；本次行程允许离开日常围栏" : trip.status == "arrived" ? "已确认到达；家属结束行程后恢复日常围栏监测" : "行程已结束")
                        }
                        if elder.can_edit {
                            Button("设置电子围栏") { edit = "fence" }
                            Button("指定本次目的地") { edit = "trip" }
                            if let trip = elder.settings.trip, ["active", "arrived"].contains(trip.status) {
                                Button("结束本次行程") { Task { await model.perform { var s = elder.settings; s.trip = nil; try await model.save(elder: elder, settings: s) } } }
                            }
                            if elder.settings.fence != nil {
                                Button("关闭电子围栏", role: .destructive) { Task { await model.perform { var s = elder.settings; s.fence = nil; try await model.save(elder: elder, settings: s) } } }
                            }
                            NavigationLink("提醒规则") { RulesView(elder: elder) }
                        }
                        if elder.is_owner {
                            Button("管理授权人员") { members = true }
                            if !elder.paired { Button("获取老人手机绑定码") { Task { await model.perform { let result: CodeResponse = try await model.request("/elders/\(id)/pair-code", method: "POST", body: [:]); pairCode = result.code } } } }
                        }
                    }
                    Section("异常提醒") {
                        if elder.events.isEmpty { Text("暂无提醒").foregroundStyle(.secondary) }
                        ForEach(elder.events) { event in
                            VStack(alignment: .leading, spacing: 9) {
                                Text(event.message).font(.headline)
                                Text(timeLabel(event.created)).font(.caption).foregroundStyle(.secondary)
                                if let position = event.location {
                                    Button("查看事件记录的位置（\(timeLabel(position.recorded_at))）") { MKMapItem(placemark: MKPlacemark(coordinate: position.coordinate)).openInMaps() }
                                }
                                Text(event.active == 1 ? "异常仍存在" : "异常已恢复").foregroundStyle(event.active == 1 ? .orange : .secondary)
                                if let handler = event.handler { Text("\(handler) 已接手").foregroundStyle(.teal) }
                                else { Button("我来处理") { Task { await model.perform { let _: OK = try await model.request("/elders/\(id)/events/\(event.id)/ack", method: "POST", body: [:]); try await model.refresh() } } } }
                                if !event.delivery.isEmpty { Text(deliveryText(event.delivery)).font(.caption).foregroundStyle(.secondary) }
                            }.padding(.vertical, 5)
                        }
                    }
                }.navigationTitle(elder.name)
                    .refreshable { do { try await model.refresh() } catch { model.error = error.localizedDescription } }
                    .sheet(item: Binding(get: { edit.map { Selection(id: $0) } }, set: { edit = $0?.id })) { mode in PlaceEditor(elder: elder, mode: mode.id) }
                    .sheet(isPresented: $members) { MembersView(id: id) }
                    .sheet(isPresented: Binding(get: { pairCode != nil }, set: { if !$0 { pairCode = nil } })) { CodeView(title: "老人手机绑定码", code: pairCode ?? "", detail: "有效期 15 分钟，请在老人手机输入并确认。") }
            } else { ContentUnavailableView("无法查看此家人", systemImage: "person.slash", description: Text("请刷新或确认管理授权。")) }
        }
    }
    func deliveryText(_ delivery: [Delivery]) -> String {
        if delivery.contains(where: { $0.state == "accepted" }) { return "苹果推送服务已接受通知，是否展示取决于手机状态与通知设置" }
        if delivery.contains(where: { $0.state == "failed" }) { return "推送失败，提醒已保存在 App 内" }
        if delivery.contains(where: { $0.state == "pending" }) { return "通知等待推送" }
        return "通知推送已取消"
    }
}

struct SearchPlace: Identifiable { let id = UUID(); let name: String; let coordinate: CLLocationCoordinate2D }
struct PlaceEditor: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    let elder: Elder
    let mode: String
    @State private var query = ""
    @State private var results: [SearchPlace] = []
    @State private var selected: SearchPlace?
    @State private var radius: Double = 500
    @State private var deadline = Date().addingTimeInterval(3600)
    @State private var searching = false
    var body: some View {
        NavigationStack {
            Form {
                Section("选择位置") {
                    TextField("搜索地址、小区、公园或医院", text: $query)
                    Button(searching ? "搜索中…" : "搜索") { Task { await search() } }.disabled(query.isEmpty || searching)
                    if mode == "fence", let loc = elder.location {
                        Button("以老人最近一次位置为中心") { selected = SearchPlace(name: "老人最近位置", coordinate: loc.rawCoordinate) }
                        Text("该位置采集于 \(timeLabel(loc.recorded_at))").font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(results) { place in Button(place.name) { selected = place } }
                    if let selected { Label(selected.name, systemImage: "checkmark.circle.fill").foregroundStyle(.teal) }
                }
                Section(mode == "fence" ? "安全范围" : "到达判定") {
                    Slider(value: $radius, in: 100...(mode == "fence" ? 5000 : 1000), step: 50)
                    Text("半径 \(Int(radius)) 米")
                    if mode == "trip" { DatePicker("预计到达时间", selection: $deadline, in: Date().addingTimeInterval(120)...Date().addingTimeInterval(6 * 86400)) }
                }
                Section {
                    Button("保存") { Task { await model.perform { try await save(); dismiss() } } }.disabled(selected == nil || model.busy)
                    Text(mode == "fence" ? "持续越界且定位精度满足条件时提醒家属。" : "本次行程允许离开日常围栏；超时仍未确认到达时提醒家属。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle(mode == "fence" ? "设置围栏" : "指定目的地").toolbar { Button("取消") { dismiss() } }
                .onAppear { radius = mode == "fence" ? elder.settings.fence?.radius ?? 500 : 200 }
        }
    }
    func search() async {
        searching = true; defer { searching = false }
        do {
            let request = MKLocalSearch.Request(); request.naturalLanguageQuery = query
            if let loc = elder.location { request.region = MKCoordinateRegion(center: loc.coordinate, latitudinalMeters: 30000, longitudinalMeters: 30000) }
            let response = try await MKLocalSearch(request: request).start()
            results = response.mapItems.map { item in
                let raw = item.placemark.coordinate
                let wgs = Coordinates.canonical(lat: raw.latitude, lon: raw.longitude, country: item.placemark.isoCountryCode)
                return SearchPlace(name: item.name ?? "搜索结果", coordinate: .init(latitude: wgs.lat, longitude: wgs.lon))
            }
            if results.isEmpty { model.error = "未找到该地点，请补充城市和地址" }
        } catch { model.error = error.localizedDescription }
    }
    func save() async throws {
        guard let selected else { return }
        var settings = elder.settings
        if mode == "fence" { settings.fence = Point(lat: selected.coordinate.latitude, lon: selected.coordinate.longitude, radius: radius) }
        else { settings.trip = Trip(name: selected.name, lat: selected.coordinate.latitude, lon: selected.coordinate.longitude, radius: radius, deadline: deadline.timeIntervalSince1970) }
        try await model.save(elder: elder, settings: settings)
    }
}

struct RulesView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    let elder: Elder
    @State private var delay: Double = 120
    @State private var offline: Double = 600
    var body: some View {
        Form {
            Section("持续越界后提醒") { Slider(value: $delay, in: 30...600, step: 30); Text("\(Int(delay)) 秒") }
            Section("位置未更新后提醒") { Slider(value: $offline, in: 180...1800, step: 60); Text("\(Int(offline / 60)) 分钟") }
            Button("保存规则") { Task { await model.perform { var s = elder.settings; s.outside_delay = delay; s.offline_after = offline; try await model.save(elder: elder, settings: s); dismiss() } } }.disabled(model.busy)
        }.navigationTitle("提醒规则").onAppear { delay = elder.settings.outside_delay; offline = elder.settings.offline_after }
    }
}

struct MembersView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    let id: String
    @State private var canEdit = false
    @State private var code: String?
    @State private var pendingRemoval: Member?
    var elder: Elder? { model.elders.first { $0.id == id } }
    var body: some View {
        NavigationStack {
            Form {
                Section("邀请管理人员") {
                    Toggle("允许修改围栏和目的地", isOn: $canEdit)
                    Text("所有授权人员均可查看位置、接收提醒和接手处理；只有主管理员可以邀请或移除人员。").font(.footnote)
                    Button("生成一次性邀请") { Task { await model.perform { let result: CodeResponse = try await model.request("/elders/\(id)/invites", method: "POST", body: ["can_edit": canEdit]); code = result.code } } }.disabled(model.busy)
                }
                Section("已授权人员") {
                    ForEach(elder?.members ?? []) { member in
                        HStack {
                            VStack(alignment: .leading) { Text(member.name); Text(member.can_edit == 1 ? "可修改设置" : "查看位置与接收提醒").font(.caption).foregroundStyle(.secondary) }
                            Spacer()
                            Button("移除", role: .destructive) { pendingRemoval = member }
                        }
                    }
                }
            }.navigationTitle("管理授权").toolbar { Button("完成") { dismiss() } }
                .sheet(isPresented: Binding(get: { code != nil }, set: { if !$0 { code = nil } })) { CodeView(title: "家属邀请口令", code: code ?? "", detail: "有效期 24 小时，仅可使用一次。请交给你希望授权的家属。") }
                .confirmationDialog("移除这位管理人员？", isPresented: Binding(get: { pendingRemoval != nil }, set: { if !$0 { pendingRemoval = nil } }), titleVisibility: .visible) {
                    Button("移除授权", role: .destructive) {
                        if let member = pendingRemoval { Task { await model.perform { let _: OK = try await model.request("/elders/\(id)/members/\(member.id)", method: "DELETE"); try await model.refresh() } } }
                    }
                    Button("取消", role: .cancel) { pendingRemoval = nil }
                }
        }
    }
}

struct DataSyncStatusView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let refreshed = model.lastRefresh {
                Text("后台刷新于 \(refreshed.formatted(date: .abbreviated, time: .standard))")
                    .font(.caption).foregroundStyle(.secondary)
            } else { Text("正在读取后台数据…").font(.caption).foregroundStyle(.secondary) }
            if let failure = model.refreshFailure {
                Text("刷新失败，将自动重试：\(failure)").font(.caption).foregroundStyle(.orange)
            }
            Button("立即刷新后台数据") { Task { await model.perform { try await model.refresh() } } }
                .disabled(model.busy)
        }
    }
}

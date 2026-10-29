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
                                TimelineView(.periodic(from: .now, by: 1)) { context in
                                    Text(summary(elder, at: context.date)).font(.subheadline).foregroundStyle(.secondary)
                                }
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
    func summary(_ elder: Elder, at date: Date) -> String {
        if !elder.paired { return "等待老人手机绑定" }
        guard let loc = elder.location else { return "等待首次定位" }
        return "\(elder.locationIsHistorical(at: date) ? "历史位置 · " : "最近采集 · ")\(timeLabel(loc.recorded_at)) · 采集时电量 \(Int(loc.battery))%"
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
    @State private var confirmRebind = false
    @State private var deletingEvent: GuardEvent?
    @State private var camera: MapCameraPosition = .automatic
    var elder: Elder? { model.elders.first { $0.id == id } }
    var body: some View {
        Group {
            if let elder {
                List {
                    Section {
                        LocationDashboard(elder: elder, camera: $camera)
                    }.listRowInsets(EdgeInsets()).listRowBackground(Color.clear).listRowSeparator(.hidden)
                    Section("守护设置") {
                        GuardDashboard(elder: elder, edit: { edit = $0 }, members: { members = true },
                            pair: { if elder.paired { confirmRebind = true } else { generatePairCode(replace: false) } })
                    }.listRowInsets(EdgeInsets()).listRowBackground(Color.clear).listRowSeparator(.hidden)
                    Section("老人手机设置") { RemoteDeviceSettingsView(elder: elder) }
                    Section("异常提醒") {
                        if let failure = model.alertsFailure { Label("提醒同步失败：\(failure)", systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange) }
                        if !model.pushConfigured {
                            Text("苹果远程通知未配置：App打开时会检查异常；退出或锁屏后不能依靠此方式收提醒。")
                                .font(.caption).foregroundStyle(.orange)
                        }
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
                                if elder.can_edit { Button("删除此提醒", role: .destructive) { deletingEvent = event }.disabled(model.busy) }
                            }.padding(.vertical, 5).buttonStyle(.borderless)
                                .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                    if elder.can_edit { Button("删除", role: .destructive) { deletingEvent = event } }
                                }
                        }
                    }
                }.navigationTitle(elder.name)
                    .refreshable { do { try await model.refresh() } catch { model.error = error.localizedDescription } }
                    .sheet(item: Binding(get: { edit.map { Selection(id: $0) } }, set: { edit = $0?.id })) { mode in PlaceEditor(elder: elder, mode: mode.id) }
                    .sheet(isPresented: $members) { MembersView(id: id) }
                    .alert("删除这条异常提醒？", isPresented: Binding(get: { deletingEvent != nil }, set: { if !$0 { deletingEvent = nil } }), presenting: deletingEvent) { event in
                        Button("删除", role: .destructive) {
                            deleteEvent(event)
                            deletingEvent = nil
                        }
                        Button("取消", role: .cancel) { deletingEvent = nil }
                    } message: { _ in
                        Text("会从服务端删除此提醒及其记录的位置，所有家属同步移除。删除不改变围栏或行程；同一异常恢复后再次发生仍会提醒。")
                    }
                    .confirmationDialog("重新绑定这位老人的手机？", isPresented: $confirmRebind, titleVisibility: .visible) {
                        Button("生成重新绑定码") { generatePairCode(replace: true) }
                        Button("取消", role: .cancel) { }
                    } message: {
                        Text("适用于重装应用或更换手机。生成口令后旧设备仍可使用；新手机输入口令并确认后，旧设备失效。已有围栏、行程和家属授权保留。")
                    }
                    .sheet(isPresented: Binding(get: { pairCode != nil }, set: { if !$0 { pairCode = nil } })) { CodeView(title: "老人手机绑定码", code: pairCode ?? "", detail: "有效期 15 分钟，请在老人手机输入并确认。重新绑定成功后旧设备失效，已有守护设置保留。") }
            } else { ContentUnavailableView("无法查看此家人", systemImage: "person.slash", description: Text("请刷新或确认管理授权。")) }
        }
    }
    private func deleteEvent(_ event: GuardEvent) {
        Task { await model.perform {
            let _: OK = try await model.request("/elders/\(id)/events/\(event.id)", method: "DELETE")
            try await model.refresh()
        } }
    }
    private func generatePairCode(replace: Bool) {
        Task { await model.perform {
            let result: CodeResponse = try await model.request("/elders/\(id)/pair-code", method: "POST", body: ["replace": replace])
            pairCode = result.code
        } }
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
    @State private var radiusText = "500"
    @State private var initialized = false
    private var maximumRadius: Int { mode == "fence" ? 10000 : 2000 }
    private var validRadius: Int? { guard let value = Int(radiusText), (1...maximumRadius).contains(value) else { return nil }; return value }
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
                    RadiusEditor(text: $radiusText, maximum: maximumRadius)
                    if let accuracy = elder.location?.accuracy, let value = validRadius, Double(value) < accuracy {
                        Label("半径小于最近定位误差（约 \(Int(accuracy)) 米），可能无法确认到达或越界。", systemImage: "location.slash")
                            .font(.caption).foregroundStyle(.orange)
                    }
                    Text("按 1 米设置范围，不代表手机能定位到 1 米。判定仍保留定位误差过滤。")
                        .font(.caption).foregroundStyle(.secondary)
                    if mode == "trip" { DatePicker("预计到达时间", selection: $deadline, in: Date().addingTimeInterval(120)...Date().addingTimeInterval(6 * 86400)) }
                }
                Section {
                    Button("保存") { Task { await model.perform { try await save(); dismiss() } } }.disabled(selected == nil || validRadius == nil || model.busy)
                    Text(mode == "fence" ? "持续越界且定位精度满足条件时提醒家属。" : "本次行程允许离开日常围栏；超时仍未确认到达时提醒家属。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle(mode == "fence" ? "设置围栏" : "指定目的地").toolbar { Button("取消") { dismiss() } }
                .onAppear {
                    guard !initialized else { return }; initialized = true
                    if mode == "fence", let fence = elder.settings.fence {
                        radiusText = String(Int(fence.radius))
                        selected = SearchPlace(name: "现有围栏中心", coordinate: .init(latitude: fence.lat, longitude: fence.lon))
                    } else if mode == "trip", let trip = elder.settings.trip {
                        radiusText = String(Int(trip.radius))
                        selected = SearchPlace(name: trip.name, coordinate: .init(latitude: trip.lat, longitude: trip.lon))
                        deadline = max(Date().addingTimeInterval(180), Date(timeIntervalSince1970: trip.deadline))
                    } else { radiusText = mode == "fence" ? "500" : "200" }
                }
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
        guard let selected, let value = validRadius else { return }
        let radius = Double(value)
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
            Section("自动守护期间位置未更新后提醒") { Slider(value: $offline, in: 180...1800, step: 60); Text("\(Int(offline / 60)) 分钟") }
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
                Text("刷新失败，请点击重试：\(failure)").font(.caption).foregroundStyle(.orange)
            }
            Text("位置和电量为手动读取快照；异常提醒在前台自动更新。")
                .font(.caption).foregroundStyle(.secondary)
            if let failure = model.alertsFailure {
                Text("异常提醒同步失败：\(failure)").font(.caption).foregroundStyle(.orange)
            }
            Button("立即刷新后台数据") { Task { await model.perform { try await model.refresh() } } }
                .disabled(model.busy)
        }
    }
}

struct RemoteLocationView: View {
    @EnvironmentObject var model: AppModel
    let elder: Elder
    let historical: Bool
    @State private var queryRun = 0
    @State private var queryWaiting = false
    @State private var queryFollowing = false
    @State private var queryMessage: String?
    private var pending: Bool { ["pending", "received"].contains(elder.location_request?.state ?? "") }
    var body: some View {
        Button {
            queryMessage = nil
            queryRun += 1
            queryWaiting = true
            queryFollowing = true
        } label: {
            HStack {
                if queryWaiting { ProgressView().tint(.white) }
                else { Image(systemName: "location.fill") }
                Text(queryWaiting ? "正在请求新位置…" : queryFollowing ? "正在跟进手机响应…" : pending ? "查询本次结果" : elder.positionRequestTitle).fontWeight(.semibold)
            }.frame(maxWidth: .infinity).padding(.vertical, 8)
        }.buttonStyle(.borderedProminent).controlSize(.large)
            .disabled(model.busy || (!elder.canRequestPosition && !pending) || queryFollowing)
        if let message = queryMessage {
            Label(message, systemImage: "info.circle").font(.caption).foregroundStyle(.secondary)
        } else if pending && !queryWaiting {
            Text("上次请求仍在后台处理，可查询结果；地图保留上次采集的位置。").font(.caption).foregroundStyle(.secondary)
        } else if historical && elder.location_request?.state == "completed" {
            Text("上次定位请求已完成；当前暂无3分钟内的位置，请重新获取").font(.caption).foregroundStyle(.orange)
        } else if let label = elder.positionRequestLabel {
            Label(label, systemImage: elder.location_request?.state == "completed" ? "checkmark.circle" : "clock")
                .font(.caption).foregroundStyle(.secondary)
        }
        DisclosureGroup("连接与定位说明") {
            VStack(alignment: .leading, spacing: 8) {
                if let status = elder.pushDescription { Text(status) }
                if let diag = elder.device_diagnostics { Text("老人端 \(diag.app_version) · 状态上报于 \(timeLabel(diag.updated_at))") }
                Text("5秒内先反馈进度，之后继续跟进本次请求。新位置到达后自动更新；离线或GPS冷启动不能保证5秒完成。旧位置保留原采集时间。")
            }.font(.caption).foregroundStyle(.secondary).padding(.top, 6)
        }.font(.caption).tint(.secondary)
        // Fast feedback is separate from following a real request to completion.
        .task(id: queryFollowing ? queryRun : nil) {
            guard queryFollowing else { return }
            let run = queryRun
            do { try await Task.sleep(for: .seconds(5)) } catch { return }
            guard queryFollowing, queryRun == run else { return }
            let current = model.elders.first(where: { $0.id == elder.id })?.location_request
            let state = current?.state
            if let current, !["pending", "received"].contains(current.state) {
                queryMessage = current.state == "completed" ? "正在确认本次请求，地图仍为上次采集位置。" : current.label
            } else {
            queryMessage = state == "received" ? "手机已收到请求，定位仍在进行；新位置到达后将自动显示。"
                : state == "pending" ? "尚未收到手机响应，正在继续跟进；地图仍为上次采集位置。"
                : "正在确认后台请求状态，取得新位置后将自动显示。"
            }
            queryWaiting = false
        }
        .task(id: queryFollowing ? queryRun : nil) {
            guard queryFollowing else { return }
            let run = queryRun
            do {
                // The server reuses a live request, or creates one if the cached request expired.
                // A previous local timeout can leave this view holding an old pending snapshot.
                do {
                    let _: LocationRequest = try await model.request("/elders/\(elder.id)/location-request", method: "POST", body: [:])
                } catch {
                    if Task.isCancelled { throw error }
                    try await model.refreshElder(elder.id)
                    guard let request = model.elders.first(where: { $0.id == elder.id })?.location_request,
                          ["pending", "received"].contains(request.state) else { throw error }
                }
                try Task.checkCancellation()
                while !Task.isCancelled && queryFollowing && queryRun == run {
                    do { try await model.refreshElder(elder.id) }
                    catch { if Task.isCancelled { return }; queryMessage = "后台连接暂时失败，正在继续读取同一次请求的结果。" }
                    let current = model.elders.first(where: { $0.id == elder.id })?.location_request
                    if let current, !["pending", "received"].contains(current.state) {
                        queryMessage = current.state == "completed" ? nil : current.label
                        queryFollowing = false
                        queryWaiting = false
                        return
                    }
                    try await Task.sleep(for: .milliseconds(queryWaiting ? 400 : 2000))
                }
            } catch {
                guard !Task.isCancelled, queryRun == run, queryFollowing else { return }
                queryMessage = error.localizedDescription + "；尚未确认本次定位结果。"
                queryFollowing = false
                queryWaiting = false
            }
        }
        .task(id: queryFollowing ? queryRun : nil) {
            guard queryFollowing else { return }
            do { try await Task.sleep(for: .seconds(180)) } catch { return }
            queryMessage = "本次请求未取得新位置，请检查老人手机的联网、推送和后台权限后重试。"
            queryFollowing = false
            queryWaiting = false
        }
        .onDisappear { queryFollowing = false; queryWaiting = false }
    }
}


struct RemoteDeviceSettingsView: View {
    @EnvironmentObject var model: AppModel
    let elder: Elder
    @State private var interval = 60
    @State private var notice: String?
    private let actions = [("location", "定位权限"), ("background", "后台定位"), ("battery", "电池限制"), ("notifications", "通知权限"), ("startup", "自启动与后台活动")]
    var body: some View {
        DisclosureGroup("远程参数与权限检查") {
            Picker("自动采集间隔", selection: $interval) {
                Text("30秒 · 较频繁").tag(30)
                Text("60秒 · 标准").tag(60)
                Text("120秒 · 较省电").tag(120)
            }
            Text("仅围栏或进行中的行程启用时生效，无规则时仍按需定位。间隔越长，越界确认越慢。需老人端0.1.11及以上。").font(.caption).foregroundStyle(.secondary)
            Button("下发采集间隔") {
                Task { await model.perform {
                    var settings = elder.settings
                    settings.automatic_interval = interval
                    try await model.save(elder: elder, settings: settings)
                    notice = "设置已保存，等待老人手机读取并确认应用。"
                } }
            }.disabled(model.busy || !elder.can_edit || !elder.paired)
            if let state = elder.device_state {
                Text("以下为手机上报于 \(timeLabel(state.updated_at)) 的历史状态，不代表当前在线。").font(.caption).foregroundStyle(.secondary)
                stateRow("精确定位", state.precise_location)
                stateRow("系统定位", state.location_enabled)
                stateRow("后台定位", state.background_location)
                stateRow("电池限制已解除", state.battery_unrestricted)
                stateRow("通知权限", state.notifications)
                stateRow("系统网络辅助", state.network_location)
                stateRow("守护开关", state.guard_enabled)
                stateRow("守护服务运行", state.service_running)
                if let connected = state.command_stream_connected { stateRow("备用指令通道", connected) }
                Text("手机已应用间隔：\(state.automatic_interval)秒 · 设置版本 \(state.settings_version)/\(elder.version)")
                    .font(.caption).foregroundStyle(state.settings_version == elder.version ? Color.secondary : Color.orange)
            } else { Text("尚未收到手机权限状态，请安装老人端0.1.11及以上并打开一次。").font(.caption).foregroundStyle(.orange) }
            Menu("发送系统设置提醒") {
                ForEach(actions, id: \.0) { item in
                    Button(item.1) { sendReminder(item.0) }
                }
            }.disabled(model.busy || !elder.can_edit || !elder.paired)
            if let request = elder.setup_request { Text(request.label).font(.caption).foregroundStyle(.secondary) }
            Text("只能发送提醒，系统权限需要本人在老人手机确认。自启动状态无法统一读取；手机离线或已停止共享时不能保证提醒送达。").font(.caption).foregroundStyle(.secondary)
            if let notice { Text(notice).font(.caption).foregroundStyle(.teal) }
            Button("刷新手机状态") { Task { await model.perform { try await model.refreshElder(elder.id) } } }.disabled(model.busy)
        }.onAppear { interval = elder.settings.automatic_interval ?? 60 }
    }
    private func stateRow(_ label: String, _ enabled: Bool) -> some View {
        HStack { Text(label); Spacer(); Label(enabled ? "已开启" : "未开启", systemImage: enabled ? "checkmark.circle.fill" : "exclamationmark.circle")
            .foregroundStyle(enabled ? Color.teal : Color.orange) }.font(.subheadline)
    }
    private func sendReminder(_ action: String) {
        Task { await model.perform {
            let _: SetupRequest = try await model.request("/elders/\(elder.id)/setup-request", method: "POST", body: ["action": action])
            try await model.refreshElder(elder.id)
            notice = "提醒已提交，等待老人手机接收；未远程修改系统权限。"
        } }
    }
}

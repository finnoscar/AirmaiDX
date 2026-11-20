import SwiftUI
import AppKit
import AirmaiCore

@main struct AirmaiDXApp: App {
    @StateObject private var model = AppModel()
    @AppStorage(AppLanguage.preferenceKey) private var language = AppLanguage.system.rawValue
    private var selectedLanguage: AppLanguage { AppLanguage(rawValue: language) ?? .system }
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(model)
                .environment(\.locale, selectedLanguage.locale)
                .frame(minWidth: 940, minHeight: 680)
                .modifier(AirmaiWindowChrome())
        }
        .defaultSize(width: 1180, height: 820)
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(after: .newItem) {
                Button(L10n.text("导入游戏包…")) { model.importSheet = true }.keyboardShortcut("o")
            }
            CommandMenu(L10n.text("游戏")) {
                Button(L10n.text("启动游戏")) { model.start() }.keyboardShortcut(.return, modifiers: .command).disabled(model.running || model.busy)
                Button(L10n.text("停止游戏")) { model.stop() }.disabled(!model.running)
            }
        }
        Settings {
            Form {
                Section("语言") {
                    Picker("界面语言", selection: $language) {
                        ForEach(AppLanguage.allCases) { item in
                            Text(verbatim: item.label).tag(item.rawValue)
                        }
                    }
                    Text("切换界面语言不会修改游戏或 AquaMai 的语言设置。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("AirmaiDX") {
                    Text("AirmaiDX")
                    Text("直接使用所选 HDD，支持外接 SSD。运行环境和配置备份保存在本机。").foregroundStyle(.secondary)
                    Link("第三方组件与许可", destination: Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/Runtime/NOTICES.md"))
                }
            }.formStyle(.grouped).frame(width: 540, height: 390)
                .environment(\.locale, selectedLanguage.locale)
        }
    }
}

enum AirmaiTheme {
    static let accent = Color(red: 0.22, green: 0.65, blue: 1)
    static func background(_ scheme: ColorScheme) -> LinearGradient {
        LinearGradient(colors: scheme == .dark
                       ? [Color(red: 0.025, green: 0.065, blue: 0.15), Color(red: 0.045, green: 0.14, blue: 0.29), Color(red: 0.025, green: 0.085, blue: 0.20)]
                       : [Color(red: 0.07, green: 0.17, blue: 0.33), Color(red: 0.12, green: 0.29, blue: 0.49)],
                       startPoint: .topLeading, endPoint: .bottomTrailing)
    }
}

extension View {
    /// Keep native button behavior, roles, shortcuts, and accessibility across OS versions.
    func airmaiActionStyle(prominent: Bool = false) -> some View {
        modifier(AirmaiActionStyle(prominent: prominent))
    }
}

private struct AirmaiActionStyle: ViewModifier {
    let prominent: Bool

    @ViewBuilder func body(content: Content) -> some View {
        // System glass responds to pointer interaction, contrast, and Reduce Transparency.
        // Scope this to actions; content panels, links, menus, and alerts keep their own styles.
        if prominent {
            content.buttonStyle(.borderedProminent)
        } else if #available(macOS 26.0, *) {
            content.buttonStyle(.glass).buttonBorderShape(.capsule).tint(.gray)
        } else {
            content.buttonStyle(.bordered)
        }
    }
}

private struct AirmaiWindowChrome: ViewModifier {
    @ViewBuilder func body(content: Content) -> some View {
        if #available(macOS 26.0, *) {
            content
                .toolbar(removing: .title)
                .toolbarBackgroundVisibility(.hidden, for: .windowToolbar)
                .scrollEdgeEffectHidden(true, for: .top)
                .overlay(alignment: .top) {
                    GeometryReader { geometry in
                        Rectangle().fill(.ultraThinMaterial)
                            .frame(height: geometry.safeAreaInsets.top + 30)
                            .mask {
                                LinearGradient(stops: [
                                    .init(color: .black.opacity(0.78), location: 0),
                                    .init(color: .black.opacity(0.62), location: 0.38),
                                    .init(color: .clear, location: 1)
                                ], startPoint: .top, endPoint: .bottom)
                            }
                            .frame(maxHeight: .infinity, alignment: .top)
                            .ignoresSafeArea(.container, edges: .top)
                    }
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
                }
        } else {
            content
        }
    }
}

extension ToolbarContent {
    @ToolbarContentBuilder func airmaiIndependentBackground() -> some ToolbarContent {
        if #available(macOS 26.0, *) {
            self.sharedBackgroundVisibility(.visible)
        } else {
            self
        }
    }
}

struct RootView: View {
    @Environment(\.locale) private var locale
    @EnvironmentObject private var model: AppModel
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    Image("SidebarBrand")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 48, height: 38)
                        .accessibilityHidden(true)
                    Text("AirmaiDX").font(.title3.bold())
                    Spacer()
                }.padding(20)
                if !model.games.isEmpty {
                    Picker("当前游戏", selection: $model.selectedID) {
                        ForEach(model.games) { Text($0.name).tag(Optional($0.id)) }
                    }.labelsHidden().padding(.horizontal, 16).padding(.bottom, 12).disabled(model.busy || model.running)
                }
                List(Page.allCases, selection: $model.page) { page in
                    Label(LocalizedStringKey(page.rawValue), systemImage: page.symbol).padding(.vertical, 6).tag(page)
                }.listStyle(.sidebar)
                Divider()
                HStack(spacing: 8) {
                    Image(systemName: model.running ? "play.circle.fill" : "circle.dotted")
                        .foregroundStyle(model.running ? .green : .secondary)
                    Text(LocalizedStringKey(model.running ? "游戏运行中" : "本机游戏环境")).font(.caption)
                    Spacer()
                }.padding(16)
            }.navigationSplitViewColumnWidth(min: 210, ideal: 230, max: 280)
        } detail: {
            VStack(spacing: 0) {
                    if model.busy {
                        HStack(spacing: 12) {
                            ProgressView().controlSize(.small)
                            Text(L10n.text(model.progressMessage.isEmpty ? "正在处理…" : model.progressMessage)).font(.callout)
                            Spacer()
                            if let fraction = model.progressFraction {
                                ProgressView(value: fraction).frame(width: 140)
                            }
                        }.padding(14).background(.regularMaterial)
                    }
                    Group {
                        switch model.page {
                        case .home: HomeView()
                        case .machine: MachineView()
                        case .display: DisplaySettingsView()
                        case .controller: ControllerView()
                        case .phoneReader: PhoneReaderView()
                        case .mods: ConfigEditorView(name: "AquaMai.toml", title: "模组配置", subtitle: "", isTOML: true)
                        case .music: MusicLibraryView()
                        case .diagnostics: DiagnosticsView()
                        }
                    }.id(model.page.rawValue + (model.selectedID ?? ""))
            }
            .background { AirmaiTheme.background(scheme).ignoresSafeArea() }
            .toolbar {
                if #unavailable(macOS 26.0) {
                    ToolbarItem(placement: .principal) {
                        Text(model.game?.name ?? "AirmaiDX").font(.headline)
                    }
                }
                if #available(macOS 26.0, *) {
                    ToolbarSpacer(.flexible, placement: .primaryAction)
                }
                ToolbarItem(placement: .primaryAction) {
                    Button { model.importSheet = true } label: { Label("导入游戏", systemImage: "folder.badge.plus") }
                        .help("导入游戏").disabled(model.busy)
                }.airmaiIndependentBackground()
                if #available(macOS 26.0, *) {
                    ToolbarSpacer(.fixed, placement: .primaryAction)
                }
                ToolbarItem(placement: .primaryAction) {
                    if model.running {
                        Button { model.stop() } label: { Label("停止", systemImage: "stop.fill") }
                            .help("停止游戏").disabled(model.busy)
                    } else {
                        Button { model.start() } label: { Label("启动游戏", systemImage: "play.fill") }
                            .help("启动游戏").disabled(model.busy || model.game == nil)
                    }
                }.airmaiIndependentBackground()
            }
        }
        .tint(AirmaiTheme.accent)
        .onChange(of: model.selectedID) { _, _ in model.clearMusic(); model.session = nil }
        .sheet(item: $model.setupModal) { modal in
            switch modal {
            case .importer: ImportView()
            case .guide:
                if let issue = model.setupIssue { LaunchGuideView(issue: issue).id(issue.kind) }
            }
        }
        .alert("未能完成", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("关闭") { model.error = nil }
        } message: { Text(LocalizedStringKey(model.error ?? "")) }
        .overlay(alignment: .bottom) {
            if let notice = model.notice {
                Label(LocalizedStringKey(notice), systemImage: "checkmark.circle.fill")
                    .font(.callout).padding(.horizontal, 18).padding(.vertical, 12)
                    .background(.regularMaterial, in: Capsule()).padding(20)
                    .task(id: notice) {
                        try? await Task.sleep(for: .seconds(5))
                        if model.notice == notice { model.notice = nil }
                    }
                    .accessibilityAddTraits(.updatesFrequently)
            }
        }
    }
}

struct PageLayout<Content: View>: View {
    let title: String
    let subtitle: String
    @ViewBuilder var content: Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(LocalizedStringKey(title)).font(.largeTitle.bold()).foregroundStyle(.white)
                    if !subtitle.isEmpty { Text(LocalizedStringKey(subtitle)).font(.body).foregroundStyle(.white.opacity(0.78)) }
                }.padding(.top, 8)
                content
            }.frame(maxWidth: 1040, alignment: .leading).padding(32).frame(maxWidth: .infinity)
        }
    }
}

struct Panel<Content: View>: View {
    let title: String
    var symbol: String? = nil
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                if let symbol { Image(systemName: symbol).foregroundStyle(AirmaiTheme.accent) }
                Text(LocalizedStringKey(title)).font(.headline)
            }
            content
        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(.primary.opacity(0.06)))
    }
}

struct HomeView: View {
    @Environment(\.locale) private var locale
    @EnvironmentObject var model: AppModel
    @State private var presentation: GamePresentation?
    @State private var artwork: NSImage?
    @State private var pendingDeletion: GameInstallation?
    var body: some View {
        PageLayout(title: "游戏库", subtitle: "") {
            if let game = model.game {
                Panel(title: "当前游戏") {
                    HStack(alignment: .center, spacing: 24) {
                        Group {
                            if let artwork {
                                Image(nsImage: artwork).resizable().scaledToFit().padding(8)
                            } else {
                                Image(systemName: "opticaldisc").font(.system(size: 44, weight: .light))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(width: 184, height: 116)
                        .background(.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityLabel(presentation?.title ?? game.name)
                        VStack(alignment: .leading, spacing: 12) {
                            Text(game.name).font(.title2.bold())
                            if let presentation {
                                Text([presentation.title, L10n.text(presentation.region)].filter { !$0.isEmpty }.joined(separator: " · "))
                                    .foregroundStyle(.secondary)
                            }
                            HStack(spacing: 12) {
                                Label(LocalizedStringKey(game.ready ? "可启动" : "未初始化"), systemImage: game.ready ? "checkmark.circle.fill" : "arrow.down.circle")
                                Label("\(game.settings.width) × \(game.settings.height)", systemImage: "rectangle.inset.filled")
                            }.font(.caption).foregroundStyle(.secondary)
                            Text([game.gameId, presentation?.version ?? game.gameVersion].compactMap { $0 }.joined(separator: " · "))
                                .font(.caption.monospaced()).foregroundStyle(.secondary)
                            if game.storageMode == "direct" {
                                Text(verbatim: game.packagePath).font(.caption).foregroundStyle(.secondary)
                                    .lineLimit(2).truncationMode(.middle).textSelection(.enabled)
                            }
                            if !game.ready, let note = game.compatibilityNote {
                                Text(LocalizedStringKey(note)).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    Divider()
                    HStack {
                        Text(LocalizedStringKey(model.session?.message ?? "未运行")).foregroundStyle(.secondary)
                        Spacer()
                        Button(LocalizedStringKey(game.storageMode == "direct" ? "移除游戏…" : "删除游戏…"), systemImage: "trash", role: .destructive) { pendingDeletion = game }
                            .labelStyle(.iconOnly)
                            .airmaiActionStyle()
                            .foregroundStyle(.red)
                            .help(LocalizedStringKey(game.storageMode == "direct" ? "移除游戏…" : "删除游戏…"))
                            .controlSize(.large)
                            .disabled(model.busy || model.running)
                        if !game.ready {
                            Button("准备运行环境") { model.prepare() }.airmaiActionStyle(prominent: true).controlSize(.large).disabled(model.busy)
                        } else {
                            Button(LocalizedStringKey(model.running ? "停止游戏" : "启动游戏"), systemImage: model.running ? "stop.fill" : "play.fill") {
                                model.running ? model.stop() : model.start()
                            }.airmaiActionStyle(prominent: true).controlSize(.large).disabled(model.busy)
                        }
                    }
                }
                if let checks = game.startupChecks, !checks.isEmpty {
                    Panel(title: "包内启动检查", symbol: "network") {
                        Text("此包启动时需要读取指定网站的启用状态。允许后，其他游戏联网设置保持原样。")
                            .foregroundStyle(.secondary)
                        ForEach(checks) { check in
                            VStack(alignment: .leading, spacing: 8) {
                                Toggle("允许此启动检查", isOn: Binding(get: {
                                    model.game?.allowedStartupChecks?.contains(check.url) == true
                                }, set: { model.setStartupCheck(check, allowed: $0) }))
                                .disabled(model.busy || model.running)
                                Text(check.url).font(.caption.monospaced()).textSelection(.enabled)
                                if !check.sendsMachineData {
                                    Text("该检查读取公开状态，不附带机台标识、卡号或账号。")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                HStack(alignment: .top, spacing: 16) {
                    Panel(title: "显示与性能", symbol: "display") {
                        Text(LocalizedStringKey(game.settings.fillDisplay ? "默认铺满选定显示器" : "使用窗口显示"))
                        Text(LocalizedStringKey(game.settings.metalHUD ? "Metal HUD 已开启" : "Metal HUD 已关闭")).foregroundStyle(.secondary)
                        Button("调整显示设置") { model.page = .display }.buttonStyle(.link)
                    }
                    Panel(title: "输入设备", symbol: "gamecontroller") {
                        Text(LocalizedStringKey(model.session?.inputMode == "mouse" ? "鼠标与键盘" : model.session?.inputMode == "hdx" ? "HDX · 按键 / 触摸 / 灯光 / 读卡" : model.session?.inputMode == "adx" ? "ADX 原生输入" : "启动时自动检测"))
                        Text("启动时自动识别手台，未连接时默认使用鼠标与键盘。").foregroundStyle(.secondary)
                        Button("查看连接状态") { model.page = .controller }.buttonStyle(.link)
                    }
                }
            } else {
                Panel(title: "导入游戏", symbol: "folder.badge.plus") {
                    VStack(alignment: .leading, spacing: 16) {
                        Text("选择完整的 HDD 或 Package 文件夹。").font(.title2.weight(.semibold))
                        Text("直接从所选目录运行，外接 SSD 请在游戏期间保持连接。").foregroundStyle(.secondary)
                        Button("导入游戏包…", systemImage: "folder.badge.plus") { model.chooseImport() }
                            .airmaiActionStyle(prominent: true).controlSize(.large).disabled(model.busy)
                    }.padding(.vertical, 18)
                }
            }
            Panel(title: "运行组件", symbol: "shippingbox") {
                ForEach(model.components) { component in
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: component.status == "缺失" ? "exclamationmark.circle" : "checkmark.circle.fill")
                            .foregroundStyle(component.status == "缺失" ? .orange : .green)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(LocalizedStringKey(component.name))
                            Text(LocalizedStringKey(component.detail)).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(LocalizedStringKey(component.status)).font(.caption).foregroundStyle(.secondary)
                    }.padding(.vertical, 4)
                }
            }
        }.alert("移除游戏？", isPresented: Binding(get: { pendingDeletion != nil }, set: { if !$0 { pendingDeletion = nil } }), presenting: pendingDeletion) { game in
            Button("取消", role: .cancel) { pendingDeletion = nil }
            Button("移到废纸篓", role: .destructive) { model.deleteGame(game); pendingDeletion = nil }
        } message: { game in
            Text(verbatim: L10n.format(game.storageMode == "direct"
                ? "从游戏库移除“%@”，并将本机运行环境、配置备份和记录移到废纸篓。所选 HDD 目录及其中的存档会保留。"
                : "将“%@”的应用副本、存档、配置及运行资料移到废纸篓，并从游戏库移除。原始 HDD 文件夹会保留。", game.name))
        }.task(id: model.game?.id) {
            presentation = nil; artwork = nil
            guard let game = model.game else { return }
            guard let info: GamePresentation = try? await model.worker.request("gamePresentation", ["id": game.id]),
                  !Task.isCancelled, model.game?.id == game.id else { return }
            presentation = info
            if let path = info.artworkPath { artwork = NSImage(contentsOfFile: path) }
        }
    }
}

struct ImportView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Image(systemName: "folder.badge.plus").font(.system(size: 44, weight: .light)).foregroundStyle(AirmaiTheme.accent)
            Text("导入游戏").font(.largeTitle.bold())
            Text("选择包含 Sinmai.exe 和 Sinmai_Data 的完整 HDD 或 Package 文件夹。").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 14) {
                Label("直接运行所选 HDD，支持外接 SSD", systemImage: "externaldrive")
                Label("自动初始化运行环境和依赖", systemImage: "shippingbox")
                Label("配置显示器、分辨率和实体手台", systemImage: "display")
            }
            Text("AirmaiDX 不提供游戏内容。请仅导入你有权使用的游戏包。").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("取消", role: .cancel) { dismiss() }.airmaiActionStyle()
                Spacer()
                Button("选择游戏文件夹…") { dismiss(); model.chooseImport() }
                    .airmaiActionStyle(prominent: true).keyboardShortcut(.defaultAction)
            }
        }.padding(32).frame(width: 560)
    }
}

struct MachineView: View {
    @EnvironmentObject var model: AppModel
    @State private var name = "segatools.ini"
    var body: some View {
        ConfigEditorView(name: name, title: "机台配置", subtitle: "", isTOML: false, machineSelection: $name).id(name)
    }
}

private struct MachineConnectionSettings: View {
    @EnvironmentObject var model: AppModel
    @Binding var selection: String
    var body: some View {
        Panel(title: "连接设置", symbol: "network") {
            connectionRow("允许游戏联网") {
                Toggle("允许游戏联网", isOn: networkBinding(\.networkEnabled)).labelsHidden().toggleStyle(.switch)
            }
            Divider()
            connectionRow("兼容连接") {
                Toggle("兼容连接", isOn: networkBinding(\.transportCompatibility)).labelsHidden().toggleStyle(.switch)
                    .help("处理旧版服务连接，并支持通过物理网卡连接。")
            }
            Divider()
            connectionRow("网络接口") {
                Picker("网络接口", selection: Binding(get: { model.game?.settings.networkInterface ?? "" }, set: { value in
                    guard var settings = model.game?.settings else { return }
                    settings.networkInterface = value
                    model.perform { try await model.saveSettings(settings) }
                })) {
                    Text("自动选择物理网卡").tag("")
                    ForEach(model.networkInterfaces, id: \.self) { Text($0).tag($0) }
                }.labelsHidden().frame(width: 270)
            }
            Divider()
            connectionRow("配置文件") {
                Picker("配置文件", selection: $selection) {
                    Text("Segatools · 网络与机台").tag("segatools.ini")
                    Text("mai2 · 游戏与设备").tag("mai2.ini")
                    Text("AMDaemon · 通用").tag("config_common.json")
                    Text("AMDaemon · 服务端").tag("config_server.json")
                    Text("AMDaemon · 客户端").tag("config_client.json")
                }.labelsHidden().frame(width: 270)
            }
        }.disabled(model.busy || model.running)
    }
    private func connectionRow<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        HStack(spacing: 24) {
            Text(LocalizedStringKey(title))
            Spacer(minLength: 24)
            content()
        }.frame(maxWidth: .infinity)
    }
    private func networkBinding(_ key: WritableKeyPath<GameSettings, Bool>) -> Binding<Bool> {
        Binding(get: { model.game?.settings[keyPath: key] ?? false }, set: { value in
            guard var settings = model.game?.settings else { return }
            settings[keyPath: key] = value
            model.perform { try await model.saveSettings(settings) }
        })
    }
}

struct ConfigEditorView: View {
    @EnvironmentObject var model: AppModel
    let name: String
    let title: String
    let subtitle: String
    let isTOML: Bool
    var machineSelection: Binding<String>? = nil
    @State private var file: ConfigFile?
    @State private var fileGameID: String?
    @State private var document = SettingsDocument(text: "")
    @State private var raw = false
    @State private var search = ""
    @State private var dirty = false
    @State private var saving = false
    @State private var revealKey = false
    var body: some View {
        PageLayout(title: title, subtitle: subtitle) {
            if let selection = machineSelection, model.game != nil {
                MachineConnectionSettings(selection: selection)
            }
            if model.game == nil {
                Panel(title: "还没有游戏包", symbol: "folder") { Text("先在游戏库导入游戏，再编辑它的配置。").foregroundStyle(.secondary) }
            } else if file != nil {
                Panel(title: name, symbol: "doc.text") {
                    HStack {
                        if !name.hasSuffix(".json") {
                            Picker("编辑方式", selection: $raw) {
                                Text("图形编辑").tag(false); Text("原文").tag(true)
                            }.pickerStyle(.segmented).labelsHidden().frame(width: 180)
                                .accessibilityLabel("编辑方式")
                        }
                        Spacer()
                        Button("重新载入") { Task { await load() } }.airmaiActionStyle().disabled(saving)
                        Button("保存设置") { Task { await save() } }
                            .airmaiActionStyle(prominent: true).disabled(!dirty || model.running || saving || fileGameID != model.game?.id)
                    }
                    if model.running {
                        Label("游戏正在运行，停止后可保存修改。", systemImage: "info.circle").font(.callout).foregroundStyle(.secondary)
                    }
                    if name == "mai2.ini" || name == "segatools.ini" || name == "config_common.json" {
                        Text("设备连接项会随输入模式临时调整，退出后还原。键位可在“输入与手台”页面设置。").font(.caption).foregroundStyle(.secondary)
                    }
                    if raw || name.hasSuffix(".json") {
                        TextEditor(text: Binding(get: { document.text }, set: { document = SettingsDocument(text: $0, isTOML: isTOML); dirty = true }))
                            .font(.system(.body, design: .monospaced)).frame(minHeight: 430)
                    } else {
                        TextField("搜索设置、分组或说明", text: $search).textFieldStyle(.roundedBorder)
                        if name == "segatools.ini", search.isEmpty {
                            VStack(alignment: .leading, spacing: 12) {
                                Text("网络与 Keychip").font(.headline)
                                quickField("游戏服务器", section: "dns", key: "default")
                                quickField("Aime 服务器", section: "dns", key: "aimedb")
                                HStack {
                                    Text("Keychip ID").frame(width: 110, alignment: .leading)
                                    Group {
                                        if revealKey { TextField("机台标识", text: quickBinding("keychip", "id")) }
                                        else { SecureField("机台标识", text: quickBinding("keychip", "id")) }
                                    }.textFieldStyle(.roundedBorder)
                                    Button { revealKey.toggle() } label: { Image(systemName: revealKey ? "eye.slash" : "eye") }
                                        .help(revealKey ? "隐藏 Keychip ID" : "显示 Keychip ID")
                                }
                            }.padding(16).background(AirmaiTheme.accent.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
                        }
                        if isTOML {
                            ModSettingsList(document: $document, dirty: $dirty, search: search)
                        } else {
                        ForEach(filteredSections) { section in
                            DisclosureGroup {
                                VStack(spacing: 0) {
                                    ForEach(section.entries) { entry in
                                        entryRow(entry).padding(.vertical, 9)
                                        if entry.id != section.entries.last?.id { Divider() }
                                    }
                                }.padding(.top, 8)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(section.name).font(.headline)
                                        if !section.help.isEmpty { Text(section.help).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                                    }
                                    Spacer()
                                    if isTOML {
                                        Toggle("启用 \(section.name)", isOn: Binding(get: {
                                            !section.commented && section.entries.first(where: { $0.key == "Disabled" })?.boolValue != true
                                        }, set: { value in document.setSectionEnabled(section, enabled: value); dirty = true }))
                                        .labelsHidden().toggleStyle(.switch).controlSize(.small)
                                    }
                                }
                            }.padding(.vertical, 8)
                        }
                        }
                    }
                }
            } else {
                Panel(title: "正在读取配置") { ProgressView() }
            }
        }.task(id: (model.game?.id ?? "") + "|" + name) { await load() }
        .onChange(of: model.running) { _, running in if !running && !dirty { Task { await load() } } }
    }
    private var filteredSections: [SettingsDocument.Section] {
        if search.isEmpty { return document.sections }
        return document.sections.compactMap { original in
            if original.name.localizedCaseInsensitiveContains(search) { return original }
            var section = original
            section.entries = section.entries.filter { ($0.key + $0.help).localizedCaseInsensitiveContains(search) }
            return section.entries.isEmpty ? nil : section
        }
    }
    private func quickBinding(_ section: String, _ key: String) -> Binding<String> {
        Binding(get: { document.value(section: section, key: key) }, set: { document.set(section: section, key: key, value: $0); dirty = true })
    }
    private func quickField(_ label: String, section: String, key: String) -> some View {
        HStack {
            Text(LocalizedStringKey(label)).frame(width: 110, alignment: .leading)
            TextField(LocalizedStringKey(label), text: quickBinding(section, key)).textFieldStyle(.roundedBorder)
        }
    }
    @ViewBuilder private func entryRow(_ entry: SettingsDocument.Entry) -> some View {
        HStack(alignment: .top, spacing: 18) {
            VStack(alignment: .leading, spacing: 4) {
                Text(entry.key).textSelection(.enabled)
                if !entry.help.isEmpty { Text(entry.help).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
            }.frame(maxWidth: .infinity, alignment: .leading)
            if entry.isBoolean {
                Toggle(entry.key, isOn: Binding(get: { entry.boolValue }, set: {
                    let numeric = ["0", "1"].contains(entry.value)
                    document.set(entry, value: numeric ? ($0 ? "1" : "0") : ($0 ? "true" : "false")); dirty = true
                })).labelsHidden().toggleStyle(.switch).controlSize(.small)
            } else {
                TextField(entry.key, text: Binding(get: { entry.value }, set: { document.set(entry, value: $0, active: !entry.commented); dirty = true }))
                    .textFieldStyle(.roundedBorder).frame(width: 230)
            }
            Toggle("自定义 \(entry.key)", isOn: Binding(get: { !entry.commented }, set: { document.set(entry, value: entry.value, active: $0); dirty = true }))
                .toggleStyle(.checkbox).labelsHidden().help(entry.commented ? "使用自定义值" : "使用文件默认值")
        }.help(entry.help)
    }
    private func load() async {
        guard let game = model.game else { return }
        do {
            let f: ConfigFile = try await model.worker.request("readConfig", ["id": game.id, "name": name])
            guard !Task.isCancelled, model.game?.id == game.id else { return }
            fileGameID = game.id; file = f; document = SettingsDocument(text: f.text, isTOML: isTOML); dirty = false
        } catch { model.error = error.localizedDescription }
    }
    private func save() async {
        guard let game = model.game, let file, fileGameID == game.id, file.name == name else { return }
        saving = true; defer { saving = false }
        do {
            let saved: ConfigFile = try await model.worker.request("saveConfig", ["id": game.id, "name": name, "text": document.text, "sha256": file.sha256, "encoding": file.encoding])
            guard model.game?.id == game.id else { return }
            self.file = saved; dirty = false; model.notice = "设置已保存，恢复点已创建。"
        } catch { model.error = error.localizedDescription }
    }
}

struct DisplaySettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var settings = GameSettings()
    private let presets = [(720,1280),(1080,1920),(1440,2560),(2160,3840)]
    var body: some View {
        PageLayout(title: "显示与性能", subtitle: "") {
            if model.game != nil {
                Panel(title: "显示器", symbol: "display.2") {
                    HStack(alignment: .bottom, spacing: 18) {
                        ForEach(model.displays) { display in
                            Button {
                                settings.displayUUID = display.id
                            } label: {
                                VStack(spacing: 10) {
                                    RoundedRectangle(cornerRadius: 7)
                                        .fill(settings.displayUUID == display.id ? AirmaiTheme.accent.opacity(0.3) : Color.primary.opacity(0.05))
                                        .overlay(Image(systemName: display.height > display.width ? "display" : "display.2").foregroundStyle(AirmaiTheme.accent))
                                        .frame(width: display.height > display.width ? 64 : 128, height: display.height > display.width ? 114 : 72)
                                        .overlay(RoundedRectangle(cornerRadius: 7).stroke(settings.displayUUID == display.id ? AirmaiTheme.accent : .secondary.opacity(0.3), lineWidth: 2))
                                    Text(display.name).font(.callout.weight(.medium))
                                    Text("\(display.width) × \(display.height) · \(Int(display.refresh)) Hz").font(.caption).foregroundStyle(.secondary)
                                }.padding(12)
                            }.buttonStyle(.plain).accessibilityLabel(display.label)
                        }
                    }.padding(.vertical, 8)
                    Picker("在哪个显示器显示", selection: $settings.displayUUID) {
                        Text("自动选择竖屏").tag("")
                        ForEach(model.displays) { Text($0.label).tag($0.id) }
                    }
                    Toggle("铺满选定显示器", isOn: $settings.fillDisplay)
                    Text("默认使用无边框铺满。显示器断开时回到可用屏幕，原设置会保留。").font(.caption).foregroundStyle(.secondary)
                }
                Panel(title: "渲染与性能", symbol: "speedometer") {
                    Picker("游戏渲染分辨率", selection: Binding(get: { settings.width }, set: { value in settings.width = value; settings.height = presets.first { $0.0 == value }?.1 ?? settings.height })) {
                        ForEach(presets, id: \.0) { w,h in Text("\(w) × \(h)" + (w == 2160 ? " · 4K" : "")).tag(w) }
                    }
                    Text("降低场景渲染分辨率时，画面仍铺满目标屏幕。设置将在下次启动时应用。").font(.caption).foregroundStyle(.secondary)
                    Divider()
                    Toggle("显示 Metal HUD", isOn: $settings.metalHUD)
                    Text("在游戏中显示帧率、GPU 时间和实际输出尺寸。").font(.caption).foregroundStyle(.secondary)
                    if let s = model.session, s.running {
                        HStack(spacing: 32) {
                            Metric(label: "呈现帧率", value: s.fps.map { String(format: "%.1f FPS", $0) } ?? "—")
                            Metric(label: "GPU 时间", value: s.gpuMS.map { String(format: "%.2f ms", $0) } ?? "—")
                            Metric(label: "场景渲染", value: s.renderWidth.flatMap { w in s.renderHeight.map { "\(w) × \($0)" } } ?? "正在读取")
                        }.padding(.top, 8)
                    }
                }
                HStack {
                    Spacer()
                    Button("预览 20 秒") { model.previewDisplay(settings) }
                        .airmaiActionStyle().controlSize(.large)
                        .disabled(!model.running || model.busy || !settings.fillDisplay)
                        .help("临时预览显示器与渲染分辨率，20 秒后自动恢复，不改变已保存设置。")
                    Button("保存显示设置") { model.perform { try await model.saveSettings(settings) } }
                        .airmaiActionStyle(prominent: true).controlSize(.large).disabled(model.busy)
                }
            } else {
                Panel(title: "先导入游戏") { Text("每个游戏独立保存显示设置。") }
            }
        }.task(id: model.game?.id) { settings = model.game?.settings ?? GameSettings() }
    }
}

struct Metric: View {
    let label: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(LocalizedStringKey(label)).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.monospacedDigit().weight(.semibold))
        }
    }
}

struct ControllerView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        PageLayout(title: "输入与手台", subtitle: "") {
            if let game = model.game {
                Panel(title: "鼠标控制", symbol: "computermouse") {
                    Toggle("未连接手台时启用鼠标", isOn: Binding(get: {
                        model.game?.settings.mouseEnabled ?? true
                    }, set: { value in
                        var settings = game.settings; settings.mouseEnabled = value
                        model.perform { try await model.saveSettings(settings) }
                    })).disabled(model.busy || model.running)
                    Text("点击圆形区域的边缘模拟外圈八键，点击内部模拟触摸；按住并拖动可持续触摸。").foregroundStyle(.secondary)
                    Text("右键用于开始 / 选择。窗口左下角提供开始和服务投币按钮。鼠标一次只能操作一个位置。").font(.caption).foregroundStyle(.secondary)
                    Text("连接设置在下次启动时生效，键盘仍可使用。").font(.caption).foregroundStyle(.secondary)
                    Text("手台输入正常时，鼠标触摸、外圈键和游戏内鼠标按钮会自动停用；输入中断后恢复。切换后请先松开鼠标。").font(.caption).foregroundStyle(.secondary)
                }
            }
            if model.game != nil { KeyboardBindingsView() }
            ControllerDevicesView()
            Panel(title: "HDX", symbol: "gamecontroller") {
                HStack(spacing: 24) {
                    ZStack {
                        Circle().stroke(AirmaiTheme.accent.opacity(0.2), lineWidth: 24).frame(width: 120, height: 120)
                        ForEach(0..<8) { i in
                            RoundedRectangle(cornerRadius: 5).fill(AirmaiTheme.accent.opacity(0.75)).frame(width: 24, height: 14)
                                .offset(y: -62).rotationEffect(.degrees(Double(i)*45))
                        }
                        Image(systemName: "hand.point.up.left").font(.largeTitle).foregroundStyle(AirmaiTheme.accent)
                    }.frame(width: 160, height: 160).accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 14) {
                        Text("HDX 02").font(.title2.weight(.semibold))
                        Text("外圈按键通过键盘输入；触摸、灯光与内置读卡器由 Mac 原生连接服务接入。").foregroundStyle(.secondary)
                        Text("启动时自动检测已验证的 HDX 02 接口。").font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let game = model.game {
                    Toggle("启动时连接 HDX 手台", isOn: Binding(get: { model.game?.settings.hdxEnabled ?? false }, set: { value in
                        var settings = game.settings; settings.hdxEnabled = value
                        model.perform { try await model.saveSettings(settings) }
                    })).disabled(model.busy)
                }
                if model.running, model.session?.inputMode == "keyboard" {
                    Label("当前使用键盘模式", systemImage: "keyboard").foregroundStyle(.secondary)
                }
                Divider()
                connection("外圈按键", subtitle: "标准键盘输入", state: nil, symbol: "keyboard")
                connection("触摸", subtitle: "35 区域 · 原生串口", state: model.session?.touch, symbol: "hand.draw")
                connection("灯光", subtitle: "原始 RGB 灯效", state: model.session?.led, symbol: "lightbulb")
                connection("实体读卡器", subtitle: "真实读卡响应 · 本机虚拟端口", state: model.session?.reader, symbol: "wave.3.right.circle")
            }
            Panel(title: "连接说明", symbol: "info.circle") {
                Text("各通道状态在游戏启动后更新。未连接手台时可使用键盘。刷卡和账号确认在游戏内操作。").foregroundStyle(.secondary)
                Text("当前已验证 HDX 02。其他型号会在识别并验证后加入设备预设。").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
    private func connection(_ title: String, subtitle: String, state: Bool?, symbol: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol).foregroundStyle(AirmaiTheme.accent).frame(width: 24)
            VStack(alignment: .leading, spacing: 3) { Text(LocalizedStringKey(title)); Text(LocalizedStringKey(subtitle)).font(.caption).foregroundStyle(.secondary) }
            Spacer()
            Label(LocalizedStringKey(symbol == "keyboard" ? "系统键盘" : state == true ? "已连接" : model.running ? "未连接" : "启动时检测"), systemImage: state == true ? "checkmark.circle.fill" : "circle.dotted")
                .font(.caption).foregroundStyle(state == true ? .green : .secondary)
        }.padding(.vertical, 4)
    }
}

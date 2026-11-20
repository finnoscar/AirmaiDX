import AppKit
import SwiftUI
import CoreGraphics
import Darwin
import AirmaiCore

enum Page: String, CaseIterable, Identifiable {
    case home = "游戏库", machine = "机台配置", display = "显示与性能", controller = "输入与手台", phoneReader = "iPhone 读卡器", mods = "模组", music = "谱面管理", diagnostics = "诊断与恢复"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .home: return "square.grid.2x2"
        case .machine: return "slider.horizontal.3"
        case .display: return "display.2"
        case .controller: return "gamecontroller"
        case .phoneReader: return "iphone.radiowaves.left.and.right"
        case .mods: return "puzzlepiece.extension"
        case .music: return "music.note.list"
        case .diagnostics: return "waveform.path.ecg"
        }
    }
}

@MainActor final class AppModel: ObservableObject {
    @Published var games: [GameInstallation] = []
    @Published var selectedID: String? = UserDefaults.standard.string(forKey: "selectedGame")
    @Published var page: Page = .home
    @Published var displays: [DisplayChoice] = []
    var networkInterfaces: [String] {
        var pointer: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&pointer) == 0, let first = pointer else { return [] }
        defer { freeifaddrs(pointer) }
        var result = Set<String>()
        var current: UnsafeMutablePointer<ifaddrs>? = first
        while let value = current {
            let item = value.pointee
            let name = String(cString: item.ifa_name)
            if name.hasPrefix("en"), item.ifa_addr?.pointee.sa_family == UInt8(AF_INET) { result.insert(name) }
            current = item.ifa_next
        }
        return result.sorted()
    }
    @Published var controllerInventory: ControllerInventory?
    @Published var scanningControllers = false
    @Published var controllerError: String?
    @Published var components: [ComponentStatus] = []
    @Published var session: SessionStatus?
    @Published var error: String?
    @Published var notice: String?
    @Published var busy = false
    @Published var progressMessage = ""
    @Published var progressFraction: Double?
    @Published var setupModal: SetupModal?
    @Published private(set) var setupIssue: LaunchGuideIssue?
    @Published private(set) var setupError: String?
    private var setupRun: SetupRun?
    private var watchedLaunch: (gameID: String, previousSession: String?)?
    var setupGameName: String? { games.first { $0.id == setupRun?.gameID }?.name }
    var importSheet: Bool {
        get { setupModal == .importer }
        set {
            if newValue && (setupModal == nil || setupModal == .importer) { setupModal = .importer }
            else if !newValue && setupModal == .importer { setupModal = nil }
        }
    }
    @Published private(set) var musicCatalog = MusicCatalog()
    @Published var scanning = false
    private var musicScanID: UUID?
    private var catalogGameID: String?
    let worker = WorkerClient()
    var game: GameInstallation? { games.first { $0.id == selectedID } }
    var running: Bool { session?.running == true }
    private var timer: Timer?
    private var polling = false
    init() {
        refreshDisplays()
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refreshDisplays() }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            Task { await self?.poll() }
        }
        Task {
            await refresh()
            if games.isEmpty, error == nil, setupModal == nil, !busy,
               !UserDefaults.standard.bool(forKey: "offeredFirstGameImport") {
                UserDefaults.standard.set(true, forKey: "offeredFirstGameImport")
                importSheet = true
            }
            let _: PhoneReaderStatus? = try? await worker.request("phoneStart", ["parentPID": ProcessInfo.processInfo.processIdentifier])
        }
    }
    func refreshControllers() async {
        guard !scanningControllers else { return }
        scanningControllers = true
        defer { scanningControllers = false }
        do {
            controllerInventory = try await worker.request("controllers")
            controllerError = nil
        } catch { controllerError = error.localizedDescription }
    }
    func refreshDisplays() {
        displays = NSScreen.screens.compactMap { screen in
            guard let id = (screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value,
                  let uuid = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue() else { return nil }
            let identity = CFUUIDCreateString(nil, uuid) as String
            let mode = CGDisplayCopyDisplayMode(id)
            return DisplayChoice(id: identity, name: screen.localizedName, width: mode?.pixelWidth ?? Int(screen.frame.width), height: mode?.pixelHeight ?? Int(screen.frame.height), scale: screen.backingScaleFactor, refresh: mode?.refreshRate ?? 0)
        }
    }
    func refresh() async {
        do {
            games = try await worker.request("list")
            if selectedID == nil || !games.contains(where: { $0.id == selectedID }) { selectedID = games.first?.id }
            components = try await worker.request("components")
            await poll()
        } catch { self.error = error.localizedDescription }
    }
    func poll() async {
        guard !polling else { return }
        polling = true; defer { polling = false }
        guard let game else { session = nil; return }
        UserDefaults.standard.set(game.id, forKey: "selectedGame")
        if let state: SessionStatus = try? await worker.request("status", ["id": game.id]), self.game?.id == game.id {
            session = state
            if let watch = watchedLaunch, watch.gameID == game.id, let path = state.sessionPath, path != watch.previousSession {
                if state.phase == "error", !state.running, setupModal == nil {
                    watchedLaunch = nil
                    showSetupIssue(.init(kind: .launchFailed, message: state.message), run: .init(gameID: game.id, intent: .launch))
                } else if state.phase == "running" || state.phase == "stopped" { watchedLaunch = nil }
            }
        }
    }
    func perform(_ action: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task {
            defer { busy = false; progressFraction = nil }
            do { try await action() } catch { self.error = error.localizedDescription }
        }
    }
    func importFolder(_ url: URL) {
        perform {
            self.importSheet = false
            self.progress("正在检查 HDD…", nil)
            do {
                let game: GameInstallation = try await self.worker.request("import", ["source": url.path], progress: self.progress)
                if self.games.contains(where: { $0.id == game.id }) { self.replace(game) }
                else { self.games.append(game) }
                self.selectedID = game.id
                self.page = .home
                await self.runSetup(.init(gameID: game.id, intent: .imported))
            } catch {
                self.showSetupIssue(.init(kind: .importFailed, message: error.localizedDescription), run: nil)
            }
        }
    }
    func prepare(repairOnly: Bool = false) {
        guard let game else { return }
        perform { await self.runSetup(.init(gameID: game.id, intent: repairOnly ? .repair : .prepare)) }
    }
    func deleteGame(_ game: GameInstallation) {
        perform {
            let _: Bool = try await self.worker.request("delete", ["id": game.id])
            self.games.removeAll { $0.id == game.id }
            if self.selectedID == game.id {
                self.clearMusic(); self.session = nil
                self.selectedID = self.games.first?.id
            }
            self.notice = "游戏已从游戏库移除。"
            await self.refresh()
        }
    }
    func progress(_ message: String, _ fraction: Double?) {
        progressMessage = message; progressFraction = fraction
    }
    func replace(_ game: GameInstallation) {
        if let index = games.firstIndex(where: { $0.id == game.id }) { games[index] = game }
    }
    func saveSettings(_ settings: GameSettings) async throws {
        guard let game else { return }
        let result: GameInstallation = try await worker.request("settings", ["id": game.id, "settings": try WorkerClient.dictionary(settings)])
        replace(result); notice = running ? "已保存，将在下次启动时使用。" : "显示与启动设置已保存。"
    }
    func previewDisplay(_ settings: GameSettings) {
        guard let game else { return }
        perform {
            let _: Bool = try await self.worker.request("previewDisplay", ["id": game.id, "settings": try WorkerClient.dictionary(settings)], progress: self.progress)
            self.notice = "显示预览已结束，原来的显示设置已恢复。"
        }
    }
    func setStartupCheck(_ check: StartupCheck, allowed: Bool) {
        guard let game else { return }
        perform {
            let updated: GameInstallation = try await self.worker.request("allowStartupCheck", ["id": game.id, "url": check.url, "allowed": allowed])
            self.replace(updated)
        }
    }
    func start() {
        guard let game else { importSheet = true; return }
        perform { await self.runSetup(.init(gameID: game.id, intent: .launch)) }
    }
    private func showSetupIssue(_ issue: LaunchGuideIssue, run: SetupRun?) {
        setupRun = run
        setupError = nil
        setupIssue = issue
        setupModal = .guide
    }
    func dismissSetup() {
        setupModal = nil
        setupIssue = nil
        setupRun = nil
        setupError = nil
    }
    func leaveSetup(for target: Page, gameID: String? = nil) {
        dismissSetup()
        if let gameID { selectedID = gameID }
        page = target
    }
    func chooseReplacement() {
        // If the picker is cancelled, leave the current instructions visible.
        chooseImport()
    }
    func continueSetup(keychip: String? = nil, approveChecks: Bool = false, installRuntime: Bool = false) {
        guard let run = setupRun else { return }
        let checks = setupIssue?.checks ?? []
        perform {
            self.setupError = nil
            self.progress("正在检查启动条件…", nil)
            do {
                if installRuntime {
                    let _: Bool = try await self.worker.request("installRuntime", progress: self.progress)
                }
                if let keychip {
                    let _: Bool = try await self.worker.request("saveKeychip", ["id": run.gameID, "value": keychip])
                }
                if approveChecks {
                    let updated: GameInstallation = try await self.worker.request("allowStartupChecks", ["id": run.gameID, "urls": checks.map(\.url), "allowed": true])
                    self.replace(updated)
                }
            } catch let issue as LaunchGuideIssue {
                self.showSetupIssue(issue, run: run)
                return
            } catch {
                self.setupError = error.localizedDescription
                return
            }
            await self.runSetup(run)
        }
    }
    private func runSetup(_ run: SetupRun) async {
        guard let game = games.first(where: { $0.id == run.gameID }) else { return }
        progress("正在检查启动条件…", nil)
        do {
            if run.intent != .repair {
                let _: Bool = try await worker.request("launchGuide", ["id": game.id])
            }
            if run.intent != .launch || !game.ready {
                let prepared: GameInstallation = try await worker.request("prepare", ["id": game.id], progress: progress)
                replace(prepared)
            }
            if run.intent == .launch {
                let previous: SessionStatus? = try? await worker.request("status", ["id": game.id])
                let result: [String: String] = try await worker.request("start", ["id": game.id, "language": AppLanguage.current.rawValue], progress: progress)
                watchedLaunch = (game.id, previous?.sessionPath)
                if let value = result["disabledMods"], let count = Int(value), count > 0 {
                    notice = L10n.format("已停用 %lld 个不兼容模组，可在「诊断与恢复」查看。", count)
                }
            } else {
                notice = run.intent == .imported ? "游戏已导入，运行环境准备完成。" : "运行环境已就绪"
            }
            dismissSetup()
            await refresh()
        } catch let issue as LaunchGuideIssue {
            showSetupIssue(issue, run: run)
        } catch {
            showSetupIssue(.init(kind: run.intent == .launch ? .launchFailed : .prepareFailed, message: error.localizedDescription), run: run)
            if let updated: [GameInstallation] = try? await worker.request("list") { games = updated }
        }
    }
    func stop() {
        guard let game else { return }
        perform {
            if self.watchedLaunch?.gameID == game.id { self.watchedLaunch = nil }
            let _: Bool = try await self.worker.request("stop", ["id": game.id])
            await self.poll()
        }
    }
    func scanMusic() {
        guard let game else { return }
        if catalogGameID != game.id { musicCatalog = MusicCatalog() }
        catalogGameID = game.id
        let scanID = UUID()
        musicScanID = scanID
        scanning = true
        Task {
            defer { if musicScanID == scanID { scanning = false } }
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    try MusicLibrary.catalog(package: URL(fileURLWithPath: game.packagePath))
                }.value
                if musicScanID == scanID, self.game?.id == game.id { musicCatalog = result }
            } catch {
                if musicScanID == scanID, self.game?.id == game.id { self.error = error.localizedDescription }
            }
        }
    }
    func clearMusic() {
        musicScanID = nil
        catalogGameID = nil
        musicCatalog = MusicCatalog()
        scanning = false
    }
    func chooseImport() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.allowsMultipleSelection = false
        panel.message = L10n.text("选择你拥有的完整 HDD 或 Package 文件夹。")
        panel.prompt = L10n.text("导入游戏")
        if panel.runModal() == .OK, let url = panel.url {
            dismissSetup()
            importFolder(url)
        }
    }
}

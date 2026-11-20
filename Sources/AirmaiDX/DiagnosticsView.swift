import SwiftUI
import AppKit
import AirmaiCore
import UniformTypeIdentifiers

struct DiagnosticsView: View {
    @EnvironmentObject var model: AppModel
    @State private var backups: [BackupItem] = []
    @State private var showLogs = false
    @State private var exporting = false
    @State private var exportMessage = ""
    var body: some View {
        PageLayout(title: "诊断与恢复", subtitle: "") {
            Panel(title: "当前状态", symbol: "waveform.path.ecg") {
                Label(LocalizedStringKey(model.session?.message ?? "尚未启动游戏"), systemImage: model.session?.phase == "error" ? "exclamationmark.triangle" : "checkmark.circle")
                if let s = model.session, s.running {
                    Label(LocalizedStringKey(s.networkOnline == true ? "游戏服务已连接" : model.game?.settings.networkEnabled == true ? "等待游戏服务连接" : "离线运行"), systemImage: s.networkOnline == true ? "network" : "network.slash")
                        .foregroundStyle(s.networkOnline == true ? .green : .secondary)
                    HStack(spacing: 32) {
                        Metric(label: "帧率", value: s.fps.map { String(format: "%.1f FPS", $0) } ?? "—")
                        Metric(label: "GPU", value: s.gpuMS.map { String(format: "%.2f ms", $0) } ?? "—")
                    }
                }
                HStack {
                    Button("重新检查") { Task { await model.refresh() } }.airmaiActionStyle()
                    Button("打开本次运行记录") {
                        if let path = model.session?.sessionPath { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
                    }.airmaiActionStyle().disabled(model.session?.sessionPath == nil)
                    Spacer()
                    Button("修复运行环境") { model.prepare(repairOnly: true) }.airmaiActionStyle().disabled(model.game == nil || model.running || model.busy)
                }
            }
            Panel(title: "运行日志", symbol: "doc.text.magnifyingglass") {
                Text("查看最近一次运行、Unity 和图形日志。").foregroundStyle(.secondary)
                HStack {
                    Button("查看日志") { showLogs = true }.airmaiActionStyle().disabled(model.game == nil)
                    Button("导出诊断报告…") { exportLogs() }.airmaiActionStyle().disabled(model.game == nil || exporting)
                    if exporting { ProgressView().controlSize(.small) }
                    if !exportMessage.isEmpty { Text(LocalizedStringKey(exportMessage)).font(.caption).foregroundStyle(.secondary) }
                }
                Text("常见机台标识、卡号和认证字段会自动遮盖，请在分享前检查内容。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Panel(title: "配置恢复点", symbol: "clock.arrow.circlepath") {
                if backups.isEmpty {
                    Text("保存配置前会自动创建恢复点。").foregroundStyle(.secondary)
                } else {
                    ForEach(backups.prefix(20)) { backup in
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(backup.file).lineLimit(1)
                                Text(backup.created).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button("恢复") { restore(backup) }.disabled(model.running || model.busy)
                        }.padding(.vertical, 4)
                    }
                }
            }
            Panel(title: "组件与许可", symbol: "doc.text") {
                Text("应用不包含游戏本体、机台 ID、卡号或账号资料。").foregroundStyle(.secondary)
                Text("运行组件使用 Wine、DXMT 与 Mono，不包含 GPTK / D3DMetal。").foregroundStyle(.secondary)
                Button("查看第三方许可与组件来源") {
                    NSWorkspace.shared.open(Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/Runtime/NOTICES.md"))
                }.buttonStyle(.link)
            }
        }.task(id: model.game?.id) { await load() }
            .sheet(isPresented: $showLogs) {
                if let game = model.game { DiagnosticLogViewer(gameID: game.id).environmentObject(model) }
            }
    }
    private func load() async {
        guard let game = model.game else { return }
        backups = (try? await model.worker.request("backups", ["id": game.id])) ?? []
    }
    private func restore(_ item: BackupItem) {
        guard let game = model.game else { return }
        model.perform {
            let _: Bool = try await model.worker.request("restore", ["id": game.id, "backupID": item.id])
            model.notice = "已恢复配置，恢复前的版本也已保存。"
            await load()
        }
    }
    private func exportLogs() {
        guard let game = model.game else { return }
        exporting = true; exportMessage = ""
        Task {
            defer { exporting = false }
            do {
                let snapshot: DiagnosticSnapshot = try await model.worker.request("diagnostics", ["id": game.id])
                if try saveDiagnosticReport(snapshot) { exportMessage = "诊断报告已保存" }
            } catch { model.error = error.localizedDescription }
        }
    }
}

@MainActor private func saveDiagnosticReport(_ snapshot: DiagnosticSnapshot) throws -> Bool {
    let panel = NSSavePanel()
    panel.title = L10n.text("导出诊断报告")
    panel.allowedContentTypes = [.plainText]
    panel.canCreateDirectories = true
    panel.nameFieldStringValue = "AirmaiDX-Diagnostics-\(snapshot.session ?? "Setup").txt"
    guard panel.runModal() == .OK, let url = panel.url else { return false }
    let info = Bundle.main.infoDictionary ?? [:]
    let version = "\(info["CFBundleShortVersionString"] as? String ?? "?") (\(info["CFBundleVersion"] as? String ?? "?"))"
    try snapshot.report(appVersion: version).write(to: url, atomically: true, encoding: .utf8)
    return true
}

private struct DiagnosticLogViewer: View {
    @Environment(\.locale) private var locale
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let gameID: String
    @State private var snapshot: DiagnosticSnapshot?
    @State private var selected = ""
    @State private var loading = false
    @State private var message = ""
    private var log: DiagnosticLog? { snapshot?.logs.first { $0.id == selected } }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("运行日志").font(.title2.bold())
                Spacer()
                Button("完成") { dismiss() }.airmaiActionStyle().keyboardShortcut(.cancelAction)
            }
            HStack {
                Picker("日志", selection: $selected) {
                    ForEach(snapshot?.logs ?? []) { log in
                        Text("\(L10n.text(log.title)) · \(log.id.components(separatedBy: "/").last ?? log.id)").tag(log.id)
                    }
                }.disabled(snapshot?.logs.isEmpty != false)
                Button("刷新", systemImage: "arrow.clockwise") { Task { await refresh() } }.airmaiActionStyle().disabled(loading)
                if loading { ProgressView().controlSize(.small) }
            }
            if let log {
                HStack {
                    Text(log.modified).textSelection(.enabled)
                    if log.truncated { Text("仅显示文件末尾 128 KiB") }
                }.font(.caption).foregroundStyle(.secondary)
                DiagnosticTextView(text: log.text.isEmpty ? L10n.text("日志文件为空。") : log.text)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .overlay(Rectangle().stroke(Color(nsColor: .separatorColor), lineWidth: 1))
            } else {
                ContentUnavailableView("暂无运行日志", systemImage: "doc.text", description: Text("运行游戏后点“刷新”，也可查看环境初始化记录。"))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if !message.isEmpty { Text(LocalizedStringKey(message)).font(.callout).foregroundStyle(.secondary) }
            Text("常见机台标识、卡号和认证字段已遮盖，请在分享前检查内容。")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("复制当前日志", systemImage: "doc.on.doc") {
                    guard let log else { return }
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(log.text, forType: .string)
                    message = "已复制当前日志"
                }.airmaiActionStyle().disabled(log == nil)
                Spacer()
                Button("导出诊断报告…", systemImage: "square.and.arrow.up") {
                    guard let snapshot else { return }
                    do { if try saveDiagnosticReport(snapshot) { message = "诊断报告已保存" } }
                    catch { message = error.localizedDescription }
                }.airmaiActionStyle(prominent: true).disabled(snapshot == nil || loading)
            }
        }.padding(24).frame(minWidth: 760, idealWidth: 940, minHeight: 540, idealHeight: 660)
            .task(id: gameID) { await refresh() }
    }
    private func refresh() async {
        loading = true; message = ""
        defer { loading = false }
        do {
            let result: DiagnosticSnapshot = try await model.worker.request("diagnostics", ["id": gameID])
            snapshot = result
            if !result.logs.contains(where: { $0.id == selected }) {
                let priorities = ["service-error.log", "configuration-check.log", "game-stdout.log", "AirmaiBootTrace.log"]
                selected = priorities.compactMap { name in
                    result.logs.first { $0.id.components(separatedBy: "/").last == name && !$0.text.isEmpty }
                }.first?.id ?? result.logs.first(where: { !$0.text.isEmpty })?.id ?? result.logs.first?.id ?? ""
            }
            if result.limitReached { message = "日志总读取量达到 1 MiB，导出报告会说明未包含的内容。" }
        } catch { message = error.localizedDescription }
    }
}

private struct DiagnosticTextView: NSViewRepresentable {
    @Environment(\.locale) private var locale
    let text: String
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = true
        let view = NSTextView()
        view.isEditable = false; view.isSelectable = true; view.isRichText = false
        view.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        view.textColor = .labelColor; view.backgroundColor = .textBackgroundColor
        view.textContainerInset = NSSize(width: 12, height: 12)
        view.isHorizontallyResizable = true; view.isVerticallyResizable = true
        view.minSize = .zero; view.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        view.textContainer?.widthTracksTextView = false
        view.textContainer?.containerSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        view.setAccessibilityLabel(L10n.text("日志内容"))
        scroll.documentView = view
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? NSTextView else { return }
        view.setAccessibilityLabel(L10n.text("日志内容"))
        guard view.string != text else { return }
        view.string = text
        view.sizeToFit()
    }
}

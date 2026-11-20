import SwiftUI
import AirmaiCore

enum SetupModal: String, Identifiable {
    case importer, guide
    var id: String { rawValue }
}

struct SetupRun {
    enum Intent { case imported, prepare, repair, launch }
    let gameID: String
    let intent: Intent
}

struct LaunchGuideIssue: Decodable, LocalizedError {
    enum Kind: String, Decodable {
        case keychipMissing, keychipInvalid, startupChecks, machineConfig, packageUnavailable, packageComponents
        case rosetta, reinstall, runtimeDownload, otherGame, importFailed, prepareFailed, launchFailed
    }

    let kind: Kind
    let message: String
    var checks: [StartupCheck]? = nil
    var otherGameID: String? = nil
    var errorDescription: String? { message }
}

struct LaunchGuideView: View {
    @EnvironmentObject private var model: AppModel
    @State private var keychip = ""
    @FocusState private var editingKeychip: Bool
    let issue: LaunchGuideIssue

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label(title, systemImage: symbol)
                .font(.title2.weight(.semibold))
                .labelStyle(GuideTitleStyle())
                .accessibilityAddTraits(.isHeader)
            if let name = model.setupGameName {
                Text(name).font(.callout.weight(.medium)).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle)
            }
            Text(verbatim: L10n.text(issue.message)).fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            details
            if let error = model.setupError {
                Label(L10n.text(error), systemImage: "exclamationmark.circle")
                    .font(.callout).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
            if model.busy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(L10n.text(model.progressMessage)).font(.callout)
                }.accessibilityAddTraits(.updatesFrequently)
            }
            HStack(spacing: 10) {
                Button("稍后", role: .cancel) { model.dismissSetup() }.keyboardShortcut(.cancelAction)
                Spacer()
                actions
            }.disabled(model.busy)
        }
        .padding(24)
        .frame(width: 520)
        .interactiveDismissDisabled(model.busy)
        .defaultFocus($editingKeychip, true)
    }

    @ViewBuilder private var details: some View {
        switch issue.kind {
        case .keychipMissing, .keychipInvalid:
            SecureField("Key Chip", text: $keychip)
                .focused($editingKeychip)
                .textFieldStyle(.roundedBorder)
                .disabled(model.busy)
            Text("请原样填写服务方提供的 Key Chip，最多 16 位英文字母、数字或连字符。")
                .font(.callout).foregroundStyle(.secondary)
        case .startupChecks:
            VStack(alignment: .leading, spacing: 7) {
                ForEach(issue.checks ?? []) { check in
                    Text(verbatim: "\(check.method)  \(check.url)")
                        .font(.callout.monospaced()).textSelection(.enabled)
                        .accessibilityLabel(Text(verbatim: check.url))
                }
            }
            if issue.checks?.allSatisfy({ !$0.sendsMachineData }) == true {
                Text("只读取启动状态，不发送机台标识、卡号或账号。")
                    .font(.callout).foregroundStyle(.secondary)
            }
        case .rosetta:
            if let url = URL(string: "https://support.apple.com/102527") {
                Link("查看 Apple 安装说明", destination: url).disabled(model.busy)
            }
        default: EmptyView()
        }
    }

    @ViewBuilder private var actions: some View {
        switch issue.kind {
        case .keychipMissing, .keychipInvalid:
            Button("保存并继续") { model.continueSetup(keychip: keychip) }
                .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                .disabled(keychip.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        case .startupChecks:
            Button("允许并继续") { model.continueSetup(approveChecks: true) }
                .buttonStyle(.borderedProminent)
                .disabled(issue.checks?.isEmpty != false)
        case .machineConfig:
            Button("诊断与恢复") { model.leaveSetup(for: .diagnostics) }
            Button("打开机台配置") { model.leaveSetup(for: .machine) }.buttonStyle(.borderedProminent)
        case .importFailed:
            Button("选择游戏文件夹…") { model.chooseReplacement() }.buttonStyle(.borderedProminent)
        case .packageUnavailable, .packageComponents:
            Button("选择游戏文件夹…") { model.chooseReplacement() }
            retryButton
        case .otherGame:
            Button("查看正在运行的游戏") { model.leaveSetup(for: .home, gameID: issue.otherGameID) }
                .buttonStyle(.borderedProminent)
        case .prepareFailed, .launchFailed:
            Button("诊断与恢复") { model.leaveSetup(for: .diagnostics) }
            retryButton
        case .reinstall:
            Button("诊断与恢复") { model.leaveSetup(for: .diagnostics) }.buttonStyle(.borderedProminent)
        case .runtimeDownload:
            Button("Download and Install") { model.continueSetup(installRuntime: true) }
                .buttonStyle(.borderedProminent)
        case .rosetta:
            retryButton
        }
    }

    private var retryButton: some View {
        Button("重试") { model.continueSetup() }.buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
    }

    private var title: LocalizedStringKey {
        switch issue.kind {
        case .keychipMissing: "填写 Key Chip"
        case .keychipInvalid: "检查 Key Chip"
        case .startupChecks: "允许启动检查"
        case .machineConfig: "检查机台配置"
        case .importFailed: "无法导入 HDD"
        case .packageUnavailable: "找不到 HDD"
        case .packageComponents: "检查 HDD 文件"
        case .rosetta: "安装 Rosetta"
        case .reinstall: "重新安装 AirmaiDX"
        case .runtimeDownload: "Install Runtime"
        case .otherGame: "已有游戏在运行"
        case .prepareFailed: "无法准备运行环境"
        case .launchFailed: "游戏启动失败"
        }
    }

    private var symbol: String {
        switch issue.kind {
        case .keychipMissing, .keychipInvalid: "key.horizontal"
        case .startupChecks: "network"
        case .machineConfig: "slider.horizontal.3"
        case .importFailed, .packageUnavailable, .packageComponents: "externaldrive"
        case .rosetta, .reinstall, .runtimeDownload: "shippingbox"
        case .otherGame: "play.circle"
        case .prepareFailed, .launchFailed: "exclamationmark.circle"
        }
    }
}

private struct GuideTitleStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 10) {
            configuration.icon.foregroundStyle(AirmaiTheme.accent).accessibilityHidden(true)
            configuration.title
        }
    }
}

#if os(iOS)
import SwiftUI
import AirmaiMobileCore

struct CardReaderView: View {
    @StateObject private var reader = CoreNFCCardReader()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("读卡器").font(.largeTitle.bold()).foregroundStyle(.white)
                MobilePanel(title: "读取实体卡", symbol: "wave.3.right.circle") {
                    stateContent
                    Button(action: reader.beginScanning) {
                        Label("扫描卡片", systemImage: "dot.radiowaves.left.and.right")
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isUnavailable || isScanning)
                }
                MobilePanel(title: "隐私与兼容性", symbol: "hand.raised") {
                    Text("仅读取 Core NFC 公开的卡片类型和标识；不写卡、不克隆、不模拟 Aime，也不会将完整标识写入日志。")
                    Text("Core NFC 能读取卡片并不代表能登录游戏账号。iPad 若没有 NFC，仍可正常使用其他功能。")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(20)
            .frame(maxWidth: 680)
            .frame(maxWidth: .infinity)
        }
        .background(MobileTheme.background.ignoresSafeArea())
        .navigationTitle("读卡器")
    }

    @ViewBuilder private var stateContent: some View {
        switch reader.state {
        case .idle:
            Label("点击后会打开系统扫描面板。", systemImage: "iphone.radiowaves.left.and.right")
        case .scanning:
            HStack { ProgressView(); Text("正在等待卡片…") }
        case .found(let card):
            Label(card.redactedDescription, systemImage: "checkmark.circle.fill").foregroundStyle(.green)
        case .unavailable(let message):
            Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(.secondary)
        case .failed(let message):
            Label(message, systemImage: "xmark.circle").foregroundStyle(.orange)
        }
    }

    private var isUnavailable: Bool { if case .unavailable = reader.state { true } else { false } }
    private var isScanning: Bool { if case .scanning = reader.state { true } else { false } }
}
#endif

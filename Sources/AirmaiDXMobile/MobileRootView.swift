#if os(iOS)
import SwiftUI

private enum MobilePage: String, CaseIterable, Identifiable {
    case touch = "触控"
    case cards = "读卡"
    case settings = "设置"
    var id: String { rawValue }
    var symbol: String {
        switch self { case .touch: "hand.tap"; case .cards: "wave.3.right.circle"; case .settings: "gearshape" }
    }
}

struct MobileRootView: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var selection: MobilePage? = .touch

    var body: some View {
        Group {
            if sizeClass == .regular {
                NavigationSplitView {
                    List(MobilePage.allCases, selection: $selection) { page in
                        Label(page.rawValue, systemImage: page.symbol).tag(page)
                    }
                    .navigationTitle("AirmaiDX")
                } detail: {
                    NavigationStack { destination(selection ?? .touch) }
                }
            } else {
                TabView {
                    NavigationStack { TouchPage() }.tabItem { Label("触控", systemImage: "hand.tap") }
                    NavigationStack { CardReaderView() }.tabItem { Label("读卡", systemImage: "wave.3.right.circle") }
                    NavigationStack { MobileSettingsView() }.tabItem { Label("设置", systemImage: "gearshape") }
                }
            }
        }
        .toolbarColorScheme(.dark, for: .navigationBar)
    }

    @ViewBuilder private func destination(_ page: MobilePage) -> some View {
        switch page { case .touch: TouchPage(); case .cards: CardReaderView(); case .settings: MobileSettingsView() }
    }
}

private struct TouchPage: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("触控区").font(.largeTitle.bold())
                    Text("支持多点输入；按下的区域会高亮。").foregroundStyle(.white.opacity(0.72))
                }.foregroundStyle(.white)
                TouchDeckView().frame(maxWidth: 760).frame(maxWidth: .infinity)
                Text("当前是原生输入与区域判定测试。iPhone/iPad 版不会在本机运行 Windows HDD。")
                    .font(.footnote).foregroundStyle(.white.opacity(0.65))
            }.padding(20).frame(maxWidth: 860).frame(maxWidth: .infinity)
        }
        .background(MobileTheme.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
    }
}

private struct MobileSettingsView: View {
    var body: some View {
        Form {
            Section("运行方式") {
                LabeledContent("当前模式", value: "原生移动端骨架")
                Text("后续可接入原生游戏内核或远程游戏会话，不会将 Wine/GPTK 打包到 iOS。")
                    .foregroundStyle(.secondary)
            }
            Section("输入") {
                LabeledContent("触控布局", value: "A/B/C/D/E")
                LabeledContent("多点采样", value: "UIKit 原生")
            }
        }.navigationTitle("设置")
    }
}
#endif

import SwiftUI
import AirmaiCore

@MainActor
public struct AirmaiEditorPreviewView: View {
    public let title: String
    public let ma2: MA2Chart
    @StateObject private var player = EditorChartPlayerModel()
    @StateObject private var answerSound = EditorPreviewHitSoundController()
    @State private var settings = SimaiPlaybackSettings()
    @State private var hiddenHeads: Set<Int> = []
    @State private var error: String?
    private static let media = EditorPlaybackMedia()

    public init(title: String, ma2: MA2Chart) {
        self.title = title
        self.ma2 = ma2
    }

    public var body: some View {
        VStack(spacing: 14) {
            VStack(spacing: 4) {
                Text(title).font(.title2.bold()).lineLimit(1)
                Text("\(ma2.totalNotes) 个音符 · \(ma2.slideCount) 段 Slide · Airmai Editor").foregroundStyle(.secondary)
            }
            if let chart = player.chart {
                EditorPlaybackClockReader(clock: player.clock) { time in
                    SimaiChartRenderer(chart: chart, currentTime: time, settings: settings,
                                       judgedEventIDs: [], resolvedHeadEventIDs: hiddenHeads,
                                       headFeedbackByEventID: [:], judgementFeedback: [], pressedHoldEventIDs: [],
                                       slideVisualProgress: [:], isGameplay: false)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .onChange(of: time) { _, newTime in
                            answerSound.update(currentTime: newTime, chart: chart, settings: settings, isPlaying: player.isPlaying)
                            if newTime >= player.duration, player.isPlaying { player.pause() }
                        }
                }
                .background(Color.black, in: RoundedRectangle(cornerRadius: 16))

                EditorPlaybackClockReader(clock: player.clock) { time in
                    VStack(spacing: 7) {
                        Slider(value: Binding(get: { time }, set: { player.seek(to: $0) }),
                               in: 0...player.duration)
                            .accessibilityLabel("预览进度")
                        HStack {
                            Text(String(format: "%.1f / %.1f 秒", time, player.duration))
                                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            Spacer()
                            Toggle("节拍提示音", isOn: $settings.answerSoundEnabled)
                                .toggleStyle(.checkbox)
                            Button(player.isPlaying ? "暂停" : "播放预览") {
                                player.togglePlayback()
                            }.keyboardShortcut(.space, modifiers: [])
                        }
                    }
                }
                Text("游戏音频使用 ACB/AWB。当前预览可播放节拍提示音。")
                    .font(.caption).foregroundStyle(.secondary)
                if ma2.slides.contains(where: \.connected) {
                    Text("连接 Slide 沿用 Editor 的整链速度，MA2 的逐段变速尚未保留。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if !ma2.warnings.isEmpty {
                    Text(ma2.warnings.joined(separator: "；")).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            } else if let error {
                ContentUnavailableView("谱面无法预览", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("正在通过 Airmai Editor 解析…").frame(maxHeight: .infinity)
            }
        }
        .padding(20)
        .task {
            do {
                settings.answerSoundEnabled = false
                let preview = try await Task.detached(priority: .userInitiated) { [ma2, title] in
                    try MA2EditorAdapter(ma2: ma2, title: title)
                }.value
                let (url, _) = try await Self.media.prepare(id: UUID(), data: nil, name: nil, duration: preview.chart.duration)
                try Task.checkCancellation()
                hiddenHeads = preview.hiddenHeadIDs
                try player.load(chart: preview.chart, musicURL: url, duration: preview.chart.duration, volume: 0)
            } catch is CancellationError {
                return
            } catch {
                self.error = error.localizedDescription
            }
        }
        .onChange(of: settings.answerSoundEnabled) { _, enabled in
            if enabled { answerSound.prepare(settings: settings) }
        }
        .onDisappear { player.stop() }
    }
}

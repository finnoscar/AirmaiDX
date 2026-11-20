import SwiftUI
import AppKit
import CryptoKit
import AirmaiCore
import AirmaiEditorPreview
import AVFoundation
import Combine
import UniformTypeIdentifiers

private struct MusicEditRequest: Identifiable {
    let id = UUID()
    let item: MusicItem
    var difficulty: Int? = nil
}

struct MusicLibraryView: View {
    @Environment(\.locale) private var locale
    @EnvironmentObject private var model: AppModel
    @State private var search = ""
    @State private var source = ""
    @State private var genre = ""
    @State private var version = ""
    @State private var kind = ""
    @State private var problemsOnly = false
    @State private var selection: String?
    @State private var sorting = [KeyPathComparator(\MusicItem.musicID)]
    @State private var editing: MusicEditRequest?
    @State private var showReadIssues = false
    // Only artwork cells observe image arrivals; do not rebuild/sort the
    // entire Table for each decoded thumbnail.
    @State private var artwork = MusicArtworkStore()
    @State private var transferring: MusicItem?
    @State private var transferError: String?

    private var catalog: MusicCatalog { model.musicCatalog }
    private var editable: Bool { !model.running && !model.busy && !model.scanning }

    var body: some View {
        let rows = filteredItems
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("谱面管理").font(.largeTitle.bold())
                    Text("\(catalog.items.count.formatted()) 首曲目 · \(Set(catalog.items.map(\.source)).count) 个资源包")
                        .foregroundStyle(.white.opacity(0.78))
                }
                Spacer()
                if model.scanning { ProgressView().controlSize(.small) }
                if let item = rows.first(where: { $0.id == selection }) {
                    Menu {
                        Button("复制到资源包…") { transferring = item }.disabled(!editable)
                        Button("导出曲目及关联资源…") { export(item) }.disabled(model.busy)
                        Divider()
                        Button("在 Finder 中显示") { reveal(item.xmlPath) }
                    } label: { Label("复制与导出", systemImage: "square.and.arrow.up") }
                    .fixedSize()
                }
                Button { model.scanMusic() } label: {
                    Label("重新扫描", systemImage: "arrow.clockwise")
                }
                .airmaiActionStyle()
                .disabled(model.game == nil || model.scanning)
            }
            .foregroundStyle(.white)

            HStack {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("搜索曲名、曲师、谱师或编号", text: $search)
                        .textFieldStyle(.plain)
                    if !search.isEmpty {
                        Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain).accessibilityLabel("清除搜索")
                    }
                }
                .padding(.horizontal, 9).padding(.vertical, 7)
                .background(.background, in: RoundedRectangle(cornerRadius: 7))
            }
            ScrollView(.horizontal) {
                HStack(spacing: 10) {
                    filter("资源包", selection: $source, choices: catalog.items.map(\.source))
                    filter("分类", selection: $genre, choices: catalog.items.map(\.genre))
                    filter("版本分类", selection: $version, choices: catalog.items.map(\.version))
                    Picker("谱面类型", selection: $kind) {
                        Text("全部类型").tag("")
                        ForEach(["标准", "DX", "宴"], id: \.self) { Text(LocalizedStringKey($0)).tag($0) }
                    }.fixedSize()
                    Toggle("仅问题", isOn: $problemsOnly).toggleStyle(.button)
                }.padding(.vertical, 2)
            }.scrollIndicators(.hidden)

            VStack(spacing: 0) {
                if model.scanning && catalog.items.isEmpty {
                    ProgressView("正在读取曲库…").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if model.game == nil {
                    ContentUnavailableView("请先导入游戏", systemImage: "opticaldisc")
                } else if rows.isEmpty {
                    ContentUnavailableView(
                        LocalizedStringKey(catalog.items.isEmpty ? "没有可读取的曲目" : "没有符合条件的曲目"),
                        systemImage: "music.note.list"
                    )
                } else {
                    GeometryReader { geometry in
                    let listWidth = max(340, min(geometry.size.width * 0.47, geometry.size.width - 321))
                    HStack(spacing: 0) {
                        Table(rows, selection: $selection, sortOrder: $sorting) {
                            TableColumn("编号", value: \.musicID) { item in
                                Text(item.number).monospacedDigit().foregroundStyle(.secondary)
                            }.width(min: 52, ideal: 64)
                            TableColumn("曲目", value: \.title) { item in
                                HStack(spacing: 10) {
                                    MusicArtwork(item: item, artwork: artwork, gameID: model.game?.id, worker: model.worker).frame(width: 48, height: 48)
                                    VStack(alignment: .leading, spacing: 3) {
                                        HStack(spacing: 5) {
                                            Text(item.title).fontWeight(.medium).lineLimit(1)
                                            Text(LocalizedStringKey(item.kind)).font(.system(size: 9, weight: .semibold)).foregroundStyle(.secondary)
                                        }
                                        Text(item.artist).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                        HStack(spacing: 4) {
                                            ForEach(item.charts.filter(\.enabled)) { chart in
                                                DifficultyBadge(chart: chart)
                                            }
                                        }
                                    }
                                }.padding(.vertical, 5)
                            }.width(min: 210, ideal: 275)
                            TableColumn("资源包", value: \.source).width(min: 58, ideal: 84)
                            TableColumn("检查") { item in
                                if !item.problems.isEmpty {
                                    Image(systemName: "exclamationmark.circle").foregroundStyle(.orange)
                                        .accessibilityLabel("有 \(item.problems.count) 项问题")
                                }
                            }.width(28)
                        }
                        .contextMenu(forSelectionType: String.self) { ids in
                            if let item = rows.first(where: { ids.contains($0.id) }) {
                                Button("编辑曲目…") { editing = MusicEditRequest(item: item) }.disabled(!editable)
                                Button("复制到资源包…") { transferring = item }.disabled(!editable)
                                Button("导出曲目及关联资源…") { export(item) }.disabled(model.busy)
                                Button("在 Finder 中显示") { reveal(item.xmlPath) }
                            }
                        } primaryAction: { ids in
                            if editable { editing = rows.first { ids.contains($0.id) }.map { MusicEditRequest(item: $0) } }
                        }
                        .frame(width: listWidth, height: geometry.size.height)

                        Divider()

                        Group {
                            if let item = rows.first(where: { $0.id == selection }) {
                                MusicInspector(item: item, editable: editable, artwork: artwork, gameID: model.game?.id, worker: model.worker) { index in
                                    editing = MusicEditRequest(item: item, difficulty: index)
                                }
                                    .id(item.id)
                            } else {
                                ContentUnavailableView("选择一首曲目", systemImage: "music.note")
                            }
                        }
                        .frame(width: max(0, geometry.size.width - listWidth - 1), height: geometry.size.height)
                    }
                    .frame(width: geometry.size.width, height: geometry.size.height)
                    }
                }
                Divider()
                HStack {
                    Text("显示 \(rows.count.formatted()) 首")
                    if problemsOnly { Text("· 仅显示有问题的曲目") }
                    Spacer()
                    if model.running { Label("游戏运行中，可浏览和预览", systemImage: "lock") }
                    if !catalog.readIssues.isEmpty {
                        Button {
                            showReadIssues = true
                        } label: {
                            Label("\(catalog.readIssues.count) 份资料无法读取", systemImage: "exclamationmark.triangle")
                        }
                        .buttonStyle(.borderless)
                    }
                }
                .font(.caption).foregroundStyle(.secondary).padding(12)
            }
            .frame(maxHeight: .infinity)
            .background(.background, in: RoundedRectangle(cornerRadius: 12))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .padding(20)
        .task(id: model.game?.id) { if catalog.items.isEmpty { model.scanMusic() } }
        .sheet(item: $editing) { request in
            if let game = model.game { MusicEditorView(item: request.item, gameID: game.id, initialDifficulty: request.difficulty) }
        }
        .sheet(isPresented: $showReadIssues) { MusicReadIssuesView(issues: catalog.readIssues, package: model.game?.packagePath) }
        .sheet(item: $transferring) { MusicCopySheet(item: $0) }
        .onChange(of: model.scanning) { _, scanning in if !scanning { artwork.reset() } }
        .alert("未能导出", isPresented: Binding(get: { transferError != nil }, set: { if !$0 { transferError = nil } })) {
            Button("好") { transferError = nil }
        } message: { Text(transferError ?? "") }
    }

    private var filteredItems: [MusicItem] {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
        return catalog.items.filter { item in
            guard source.isEmpty || item.source == source, genre.isEmpty || item.genre == genre,
                  version.isEmpty || item.version == version, kind.isEmpty || item.kind == kind,
                  !problemsOnly || !item.problems.isEmpty else { return false }
            if query.isEmpty { return true }
            return ([item.title, item.artist, item.number, String(item.musicID), item.sortName ?? ""] + item.charts.map(\.designer))
                .contains { $0.localizedStandardContains(query) }
        }.sorted(using: sorting)
    }

    private func filter(_ title: String, selection: Binding<String>, choices: [String]) -> some View {
        Picker(LocalizedStringKey(title), selection: selection) {
            Text("全部\(L10n.text(title))").tag("")
            ForEach(Set(choices).filter { !$0.isEmpty }.sorted(), id: \.self) { Text($0).tag($0) }
        }.labelsHidden().fixedSize().accessibilityLabel(Text(LocalizedStringKey(title)))
    }

    private func export(_ item: MusicItem) {
        guard let game = model.game else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.zip]
        panel.nameFieldStringValue = "\(item.number)-\(item.title.replacingOccurrences(of: "/", with: "_")).zip"
        panel.title = L10n.text("导出曲目及关联资源")
        panel.message = L10n.text("导出包含曲目资料、谱面及可找到的封面、音频和视频，保持资源包目录结构。")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        model.perform {
            do {
                let result: MusicTransferResult = try await model.worker.request("transferMusic", [
                    "id": game.id, "path": item.xmlPath, "action": "export", "destination": url.path
                ])
                model.notice = L10n.format("已导出 %lld 个文件。", result.files)
                reveal(result.path)
            } catch { transferError = error.localizedDescription }
        }
    }
}

private func reveal(_ path: String) {
    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
}

private struct MusicReadIssuesView: View {
    @Environment(\.dismiss) private var dismiss
    let issues: [MusicReadIssue]
    let package: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("无法读取的曲目资料").font(.title2.bold())
                Spacer()
                Button("完成") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            List(issues) { issue in
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(relativePath(issue.path)).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                        Text(LocalizedStringKey(issue.message)).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("在 Finder 中显示") { reveal(issue.path) }.buttonStyle(.borderless)
                }.padding(.vertical, 4)
            }
        }.padding(20).frame(width: 670, height: 420)
    }

    private func relativePath(_ path: String) -> String {
        guard let package, path.hasPrefix(package + "/") else { return path }
        return String(path.dropFirst(package.count + 1))
    }
}

private struct MusicInspector: View {
    @Environment(\.locale) private var locale
    let item: MusicItem
    let editable: Bool
    let artwork: MusicArtworkStore
    let gameID: String?
    let worker: WorkerClient
    let edit: (Int?) -> Void
    @State private var preview: ChartPreviewRequest?
    @State private var failure: String?
    @State private var difficulty = 0
    private var folder: URL { URL(fileURLWithPath: item.xmlPath).deletingLastPathComponent() }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 15) {
                HStack(alignment: .top, spacing: 16) {
                    MusicArtwork(item: item, artwork: artwork, gameID: gameID, worker: worker).frame(width: 104, height: 104)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(item.title).font(.title3.bold()).textSelection(.enabled)
                        Text(item.artist).foregroundStyle(.secondary).textSelection(.enabled)
                        Text("#\(item.number) · \(L10n.text(item.kind))").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        Text(item.source).font(.caption).foregroundStyle(.secondary)
                        if item.longMusic == true { Label("长乐曲", systemImage: "clock").font(.caption) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack {
                    Button("编辑曲目…") { edit(nil) }.airmaiActionStyle(prominent: true).disabled(!editable)
                    Button { reveal(item.xmlPath) } label: { Image(systemName: "folder") }.airmaiActionStyle().help("在 Finder 中显示").accessibilityLabel("在 Finder 中显示")
                }
                VStack(alignment: .leading, spacing: 8) {
                    metadata("排序名", item.sortName ?? "—")
                    metadata("分类", item.genre.isEmpty ? "—" : item.genre)
                    metadata("版本分类", item.version.isEmpty ? "—" : item.version)
                    metadata("版本值", item.versionValue.map(String.init) ?? "—")
                    metadata("BPM", item.bpm ?? "—")
                }.font(.callout)
                MusicAudioView(item: item)
                Divider()
                Text("难度").font(.headline)
                DifficultySelector(item: item, selection: $difficulty)
                if let chart = item.charts.first(where: { $0.id == difficulty }) {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(LocalizedStringKey(chart.enabled ? "已启用" : "未启用"), systemImage: chart.enabled ? "checkmark.circle.fill" : "minus.circle")
                            .foregroundStyle(chart.enabled ? .green : .secondary)
                        VStack(alignment: .leading, spacing: 8) {
                            metadata("显示等级", chart.displayLevel)
                            metadata("内部定数", chart.level)
                            metadata("谱师", chart.designer.isEmpty ? "—" : chart.designer)
                            metadata("音符数", chart.maxNotes.map(String.init) ?? "—")
                        }.font(.callout)
                        HStack {
                        if item.isDoubleUtage {
                            Menu("预览") {
                                Button("左侧") { showPreview(chart, side: "L") }
                                Button("右侧") { showPreview(chart, side: "R") }
                            }.fixedSize()
                        } else {
                            Button { showPreview(chart) } label: { Label("预览谱面", systemImage: "play.circle") }
                                .airmaiActionStyle()
                                .accessibilityLabel("预览 \(item.difficultyName(chart))")
                        }
                            Button("编辑与替换…") { edit(difficulty) }.airmaiActionStyle().disabled(!editable)
                        }
                    }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(difficultyColor(chart.id).opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }
                if !item.problems.isEmpty {
                    Divider()
                    Text("检查结果").font(.headline)
                    ForEach(Array(item.problems.enumerated()), id: \.offset) { _, problem in
                        Label(LocalizedStringKey(problem), systemImage: "exclamationmark.triangle").font(.caption)
                    }
                }
                Divider()
                Text("关联资源").font(.headline)
                ForEach(["封面", "音频", "视频"], id: \.self) { kind in
                    let files = item.assets.filter { $0.kind == kind }
                    HStack {
                        Text(LocalizedStringKey(kind))
                        Spacer()
                        if files.isEmpty {
                            Text("未找到").foregroundStyle(.secondary)
                        } else {
                            Menu("\(files.count) 个文件") {
                                ForEach(files) { asset in
                                    Button(URL(fileURLWithPath: asset.path).lastPathComponent) { reveal(asset.path) }
                                }
                            }.fixedSize()
                        }
                    }.font(.callout)
                }
            }.frame(maxWidth: .infinity, alignment: .leading).padding(16)
        }
        .sheet(item: $preview) { ChartPreviewSheet(request: $0) }
        .task(id: item.id) { difficulty = item.charts.first(where: \.enabled)?.id ?? item.charts.first?.id ?? 0 }
        .alert("无法预览", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("好") { failure = nil }
        } message: { Text(LocalizedStringKey(failure ?? "")) }
    }

    private func metadata(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(LocalizedStringKey(title)).foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
            Text(value).frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func showPreview(_ chart: ChartItem, side: String? = nil) {
        do {
            guard let url = MusicLibrary.chartURL(chart, in: folder, side: side),
                  MusicLibrary.isRegularFile(url, under: folder) else {
                throw AirmaiError.message("找不到该难度的 MA2 文件。")
            }
            preview = try ChartPreviewRequest(title: item.title, difficulty: item.difficultyName(chart), side: side, data: Data(contentsOf: url))
        } catch { failure = error.localizedDescription }
    }
}

private struct ChartSlot: Hashable {
    let level: Int
    let side: String
}

private struct StagedChart {
    let name: String
    let data: Data
    let replacedHash: String?
    let preview: ChartPreviewRequest
}

private struct MusicEditorView: View {
    @Environment(\.locale) private var locale
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State var item: MusicItem
    let gameID: String
    var initialDifficulty: Int? = nil
    @State private var base: MusicItem?
    @State private var original = Data()
    @State private var difficulty = 0
    @State private var staged: [ChartSlot: StagedChart] = [:]
    @State private var preview: ChartPreviewRequest?
    @State private var failure: String?
    @State private var saving = false
    @State private var discard = false

    private var dirty: Bool { base != item || !staged.isEmpty }
    private var folder: URL { URL(fileURLWithPath: item.xmlPath).deletingLastPathComponent() }
    private var canEdit: Bool { !saving && !model.busy && !model.running && model.game?.id == gameID }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("编辑曲目").font(.title2.bold())
                    Text("#\(item.number) · \(item.source) · \(L10n.text(item.kind))").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if !staged.isEmpty { Text("\(staged.count) 个谱面待保存").font(.caption).foregroundStyle(.secondary) }
                Button("取消") { if dirty && base != nil { discard = true } else { dismiss() } }.airmaiActionStyle().disabled(saving)
                    .keyboardShortcut(.cancelAction)
                Button("保存修改") { save() }.airmaiActionStyle(prominent: true).keyboardShortcut(.defaultAction)
                    .disabled(base == nil || !dirty || !canEdit)
            }.padding(20)
            Divider()
            if base == nil {
                ProgressView("正在读取曲目…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Form {
                    Section("曲目信息") {
                        TextField("曲名", text: $item.title)
                        TextField("曲师", text: $item.artist)
                        if item.sortName != nil { TextField("排序名", text: optionalText(\.sortName)) }
                        if item.bpm != nil { TextField("BPM", text: optionalText(\.bpm)) }
                        if item.longMusic != nil {
                            Toggle("长乐曲", isOn: Binding(get: { item.longMusic ?? false }, set: { item.longMusic = $0 }))
                        }
                        Picker("分类", selection: Binding(get: { item.genreID }, set: { id in
                            item.genreID = id
                            item.genre = genreChoices.first { $0.id == id }?.name ?? item.genre
                        })) { ForEach(genreChoices, id: \.id) { Text($0.name).tag($0.id) } }
                        Picker("版本分类", selection: Binding(get: { item.versionID }, set: { id in
                            item.versionID = id
                            item.version = versionChoices.first { $0.id == id }?.name ?? item.version
                        })) { ForEach(versionChoices, id: \.id) { Text($0.name).tag($0.id) } }
                        if item.versionValue != nil {
                            TextField("版本值", value: Binding(get: { item.versionValue ?? 0 }, set: { item.versionValue = $0 }), format: .number.grouping(.never))
                        }
                    }
                    Section("难度与谱面") {
                        if item.charts.isEmpty {
                            Text("曲目资料没有难度条目。").foregroundStyle(.secondary)
                        } else {
                            DifficultySelector(item: item, selection: $difficulty)
                            if item.charts.indices.contains(difficulty) {
                                chartEditor($item.charts[difficulty])
                            }
                        }
                    }
                }.formStyle(.grouped)
            }
        }
        .frame(minWidth: 640, idealWidth: 760, minHeight: 640, idealHeight: 760)
        .interactiveDismissDisabled(dirty || saving)
        .task { load() }
        .sheet(item: $preview) { ChartPreviewSheet(request: $0) }
        .confirmationDialog("放弃尚未保存的修改？", isPresented: $discard, titleVisibility: .visible) {
            Button("放弃修改", role: .destructive) { dismiss() }
            Button("继续编辑", role: .cancel) {}
        }
        .alert("未能完成", isPresented: Binding(get: { failure != nil }, set: { if !$0 { failure = nil } })) {
            Button("好") { failure = nil }
        } message: { Text(LocalizedStringKey(failure ?? "")) }
    }

    private func chartEditor(_ chart: Binding<ChartItem>) -> some View {
        let current = chart.wrappedValue
        return Group {
            Toggle("在游戏中启用", isOn: chart.enabled)
            TextField("内部定数", text: Binding(get: { chart.wrappedValue.level }, set: {
                chart.wrappedValue.level = $0
                chart.wrappedValue.displayLevelID = nil
            }))
            LabeledContent("显示等级", value: current.displayLevel)
            TextField("谱师", text: chart.designer)
            if let count = current.maxNotes { LabeledContent("当前音符数", value: "\(count)") }
            ForEach(MusicLibrary.sides(dual: item.isDoubleUtage), id: \.self) { side in
                let slot = ChartSlot(level: current.id, side: side ?? "")
                let replacement = staged[slot]
                let target = MusicLibrary.chartURL(current, in: folder, side: side)
                let existing = target.map { MusicLibrary.isRegularFile($0, under: folder) } ?? false
                VStack(alignment: .leading, spacing: 6) {
                    Text(LocalizedStringKey(side == "L" ? "左侧 MA2" : side == "R" ? "右侧 MA2" : "MA2 文件")).font(.callout.weight(.semibold))
                    Text(replacement.map { L10n.format("%@ · 待保存 · %lld 音符", $0.name, $0.preview.chart.totalNotes) }
                        ?? (existing ? target?.lastPathComponent ?? "" : L10n.text("暂无谱面文件")))
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    HStack {
                        Button("预览") { previewChart(slot, target: target) }.airmaiActionStyle().disabled(!existing && replacement == nil)
                        Button(LocalizedStringKey(existing ? "替换 MA2…" : "添加 MA2…")) { chooseChart(slot, chart: current) }.airmaiActionStyle().disabled(!canEdit)
                        if replacement != nil { Button("撤销导入") { staged.removeValue(forKey: slot) } }
                    }
                }.padding(.vertical, 5)
            }
        }
    }

    private var genreChoices: [(id: Int, name: String)] {
        choices(model.musicCatalog.items, definitions: model.musicCatalog.genres, id: \.genreID, name: \.genre)
    }

    private var versionChoices: [(id: Int, name: String)] {
        choices(model.musicCatalog.items, definitions: model.musicCatalog.versions, id: \.versionID, name: \.version)
    }

    private func choices(_ rows: [MusicItem], definitions: [MusicDefinition], id: KeyPath<MusicItem, Int>, name: KeyPath<MusicItem, String>) -> [(id: Int, name: String)] {
        var values: [Int: String] = [:]
        for row in rows where values[row[keyPath: id]] == nil { values[row[keyPath: id]] = row[keyPath: name] }
        for definition in definitions { values[definition.id] = definition.name }
        if values[item[keyPath: id]] == nil { values[item[keyPath: id]] = item[keyPath: name] }
        return values.sorted { $0.key < $1.key }.map { ($0.key, $0.value.isEmpty ? "未分类 (\($0.key))" : $0.value) }
    }

    private func optionalText(_ keyPath: WritableKeyPath<MusicItem, String?>) -> Binding<String> {
        Binding(get: { item[keyPath: keyPath] ?? "" }, set: { item[keyPath: keyPath] = $0 })
    }

    private func load() {
        guard base == nil else { return }
        do {
            let url = URL(fileURLWithPath: item.xmlPath)
            guard MusicLibrary.isRegularFile(url, under: folder) else { throw AirmaiError.message("曲目资料无法读取。") }
            original = try Data(contentsOf: url)
            var fresh = try MusicLibrary.read(url, data: original)
            fresh.source = item.source
            fresh.assets = item.assets
            item = fresh
            base = fresh
            difficulty = fresh.charts.first(where: { $0.id == initialDifficulty })?.id ?? fresh.charts.first(where: \.enabled)?.id ?? 0
        } catch { failure = error.localizedDescription }
    }

    private func chooseChart(_ slot: ChartSlot, chart: ChartItem) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.prompt = "添加到草稿"
        panel.message = L10n.format("选择 %@ 的 MA2 文件。", item.difficultyName(chart))
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            guard url.pathExtension.lowercased() == "ma2", let bytes = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
                  (1...16 * 1024 * 1024).contains(bytes) else { throw AirmaiError.message("请选择小于 16 MB 的 MA2 文件。") }
            let data = try Data(contentsOf: url)
            let parsed = try ChartPreviewRequest(title: item.title, difficulty: item.difficultyName(chart), side: slot.side, data: data)
            try parsed.chart.validateForImport()
            var destination = chart
            if destination.path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                destination.path = item.number + String(format: "_%02d.ma2", chart.id)
            }
            guard let target = MusicLibrary.chartURL(destination, in: folder, side: slot.side.isEmpty ? nil : slot.side) else {
                throw AirmaiError.message("曲目资料指定的 MA2 路径无效。")
            }
            let hash = MusicLibrary.isRegularFile(target, under: folder) ? sha(try Data(contentsOf: target)) : nil
            staged[slot] = StagedChart(name: url.lastPathComponent, data: data, replacedHash: hash, preview: parsed)
        } catch { failure = error.localizedDescription }
    }

    private func previewChart(_ slot: ChartSlot, target: URL?) {
        if let draft = staged[slot] { preview = draft.preview; return }
        guard let target, MusicLibrary.isRegularFile(target, under: folder) else { return }
        do {
            preview = try ChartPreviewRequest(title: item.title, difficulty: item.difficultyName(item.charts[slot.level]), side: slot.side, data: Data(contentsOf: target))
        } catch { failure = error.localizedDescription }
    }

    private func save() {
        guard canEdit else { return }
        saving = true
        model.perform {
            defer { saving = false }
            do {
                let xml = try MusicLibrary.editedXML(item: item, originalData: original)
                let charts: [[String: Any]] = staged.map { slot, draft in
                    ["level": slot.level, "side": slot.side, "sha256": draft.replacedHash as Any? ?? NSNull(), "data": draft.data.base64EncodedString()]
                }
                let _: Bool = try await model.worker.request("saveMusic", [
                    "id": gameID, "path": item.xmlPath, "sha256": sha(original), "data": xml.base64EncodedString(), "charts": charts
                ])
                model.notice = "曲目已保存，可以在「诊断与恢复」撤销。"
                if model.game?.id == gameID { model.scanMusic() }
                dismiss()
            } catch { failure = error.localizedDescription }
        }
    }

    private func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
}

private struct ChartPreviewRequest: Identifiable {
    let id = UUID()
    let title: String
    let detail: String
    let chart: MA2Chart

    init(title: String, difficulty: String, side: String?, data: Data) throws {
        guard let text = String(data: data, encoding: .utf8) else { throw AirmaiError.message("MA2 文字编码无法读取。") }
        self.title = title
        self.detail = difficulty + (side == "L" ? " · 左侧" : side == "R" ? " · 右侧" : "")
        self.chart = try MA2Chart(text: text)
    }
}

private struct ChartPreviewSheet: View {
    @Environment(\.dismiss) private var dismiss
    let request: ChartPreviewRequest
    var body: some View {
        VStack(alignment: .trailing, spacing: 0) {
            HStack {
                Text(request.detail).font(.headline)
                Spacer()
                Button("完成") { dismiss() }.keyboardShortcut(.cancelAction)
            }.padding(.horizontal, 20).padding(.top, 14)
            AirmaiEditorPreviewView(title: request.title, ma2: request.chart)
        }.frame(width: 570, height: 640)
    }
}

private func difficultyColor(_ index: Int) -> Color {
    [Color.green, .orange, .red, .purple, .indigo, .pink][min(max(index, 0), 5)]
}

private struct DifficultyBadge: View {
    let chart: ChartItem
    var body: some View {
        Text(chart.displayLevel).font(.system(size: 10, weight: .semibold, design: .rounded))
            .padding(.horizontal, 5).padding(.vertical, 2)
            .foregroundStyle(difficultyColor(chart.id))
            .background(difficultyColor(chart.id).opacity(0.14), in: Capsule())
            .accessibilityLabel("\(chart.name) \(chart.displayLevel)")
            .help("\(chart.name) · \(chart.level)")
    }
}

private struct DifficultySelector: View {
    let item: MusicItem
    @Binding var selection: Int
    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 6) {
                ForEach(item.charts) { chart in
                    Button { selection = chart.id } label: {
                        VStack(spacing: 4) {
                            Text(item.difficultyName(chart)).font(.system(size: 10, weight: .semibold))
                            Text(chart.displayLevel).font(.callout.bold().monospacedDigit())
                        }.padding(.horizontal, 10).padding(.vertical, 8)
                            .frame(minWidth: 62)
                            .foregroundStyle(selection == chart.id ? .white : difficultyColor(chart.id))
                            .background(selection == chart.id ? difficultyColor(chart.id) : difficultyColor(chart.id).opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
                            .overlay(alignment: .topTrailing) {
                                if !chart.enabled { Image(systemName: "minus.circle.fill").font(.system(size: 9)).padding(3) }
                            }
                    }.buttonStyle(.plain)
                        .accessibilityLabel("\(item.difficultyName(chart)) \(chart.displayLevel)")
                        .accessibilityAddTraits(selection == chart.id ? .isSelected : [])
                        .help(L10n.text(chart.enabled ? "已启用" : "未启用"))
                }
            }.padding(.vertical, 3)
        }.scrollIndicators(.hidden)
    }
}

private struct MusicMediaResult: Decodable { let path: String?; let issue: String? }
private struct MusicTransferResult: Decodable { let path: String; let files: Int }

@MainActor private final class MusicArtworkStore: ObservableObject {
    @Published private(set) var images: [String: NSImage] = [:]
    @Published private(set) var issues: [String: String] = [:]
    @Published private(set) var generation = 0
    private var waiting: [(MusicItem, String, WorkerClient)] = []
    private var pending = Set<String>()
    private var loading = false

    func reset() {
        generation += 1
        images.removeAll(); issues.removeAll(); waiting.removeAll(); pending.removeAll()
    }

    func load(_ item: MusicItem, game: String, worker: WorkerClient) {
        guard images[item.id] == nil, issues[item.id] == nil, pending.insert(item.id).inserted else { return }
        waiting.append((item, game, worker))
        guard !loading else { return }
        loading = true
        Task {
            while !waiting.isEmpty {
                let (next, gameID, client) = waiting.removeFirst()
                let token = generation
                do {
                    let result: MusicMediaResult = try await client.request("musicMedia", ["id": gameID, "path": next.xmlPath, "kind": "cover"])
                    guard generation == token else { continue }
                    if let path = result.path, let image = NSImage(contentsOfFile: path) {
                        if images.count >= 128, let first = images.keys.first { images.removeValue(forKey: first) }
                        images[next.id] = image
                    } else { issues[next.id] = result.issue ?? L10n.text("没有可读取的封面") }
                } catch { if generation == token { issues[next.id] = error.localizedDescription } }
                guard generation == token else { continue }
                pending.remove(next.id)
            }
            loading = false
        }
    }
}

private struct MusicArtwork: View {
    let item: MusicItem
    @ObservedObject var artwork: MusicArtworkStore
    let gameID: String?
    let worker: WorkerClient
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 7).fill(.quaternary)
            if let image = artwork.images[item.id] {
                Image(nsImage: image).resizable().scaledToFit()
            } else {
                Image(systemName: "music.note").font(.title2).foregroundStyle(.secondary)
            }
        }.clipShape(RoundedRectangle(cornerRadius: 7))
            .accessibilityLabel("\(item.title) 封面")
            .help(artwork.issues[item.id] ?? item.title)
            .task(id: item.id + String(artwork.generation)) {
                if let gameID { artwork.load(item, game: gameID, worker: worker) }
            }
    }
}

private struct MusicAudioView: View {
    @EnvironmentObject private var model: AppModel
    let item: MusicItem
    @State private var player: AVAudioPlayer?
    @State private var loading = false
    @State private var playing = false
    @State private var position = 0.0
    @State private var duration = 0.0
    @State private var dragging = false
    @State private var issue: String?
    @State private var generation = UUID()
    private let clock = Timer.publish(every: 0.25, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                if loading { ProgressView().controlSize(.small) }
                Button { toggle() } label: {
                    Label(LocalizedStringKey(playing ? "暂停原曲" : "试听原曲"), systemImage: playing ? "pause.fill" : "play.fill")
                }.disabled(loading)
                Spacer()
                Text("\(time(position)) / \(time(duration))").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            Slider(value: $position, in: 0...max(duration, 1), onEditingChanged: { editing in
                dragging = editing
                if !editing { player?.currentTime = position }
            }).disabled(player == nil).accessibilityLabel("原曲播放进度")
            if let issue { Text(issue).font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }
        }.padding(12).background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 10))
            .onReceive(clock) { _ in
                guard let player, !dragging else { return }
                position = player.currentTime
                playing = player.isPlaying
            }
            .onDisappear { generation = UUID(); player?.stop(); playing = false }
    }

    private func time(_ seconds: Double) -> String {
        let value = Int(max(0, seconds.isFinite ? seconds : 0))
        return String(format: "%d:%02d", value / 60, value % 60)
    }

    private func toggle() {
        if let player {
            if player.isPlaying { player.pause() } else { player.play() }
            playing = player.isPlaying
            return
        }
        guard let game = model.game else { return }
        loading = true; issue = nil
        let token = generation
        Task { @MainActor in
            defer { loading = false }
            do {
                let result: MusicMediaResult = try await model.worker.request("musicMedia", ["id": game.id, "path": item.xmlPath, "kind": "audio"])
                guard generation == token else { return }
                guard let path = result.path else { issue = result.issue; return }
                let audio = try AVAudioPlayer(contentsOf: URL(fileURLWithPath: path))
                guard audio.prepareToPlay() else { throw AirmaiError.message("无法播放该曲目的音频。") }
                duration = audio.duration; player = audio
                audio.play(); playing = audio.isPlaying
            } catch { if generation == token { issue = error.localizedDescription } }
        }
    }
}

private struct MusicCopySheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let item: MusicItem
    @State private var packs: [String] = []
    @State private var destination = ""
    @State private var saving = false
    @State private var issue: String?
    private var canCopy: Bool { !saving && !model.running && !model.busy && !destination.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("复制曲目及关联资源").font(.title2.bold())
            Text("#\(item.number) · \(item.title)").foregroundStyle(.secondary)
            Text("将复制曲目资料、所有谱面以及可找到的封面、音频和视频。目标中存在不同内容的同名文件时会停止，不覆盖现有资源。")
                .font(.callout)
            if packs.isEmpty {
                Text("没有其他可写入的扩展资源包，请先准备一个非 A000 的资源包。").foregroundStyle(.secondary)
            } else {
                Picker("目标资源包", selection: $destination) {
                    ForEach(packs, id: \.self) { Text($0).tag($0) }
                }
            }
            if let issue { Text(issue).font(.callout).foregroundStyle(.red).textSelection(.enabled) }
            HStack {
                if saving { ProgressView().controlSize(.small) }
                Spacer()
                Button("取消") { dismiss() }.airmaiActionStyle().disabled(saving).keyboardShortcut(.cancelAction)
                Button("复制") { copy() }.airmaiActionStyle(prominent: true).disabled(!canCopy).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 520)
            .interactiveDismissDisabled(saving)
            .task {
                guard let game = model.game else { return }
                let package = URL(fileURLWithPath: game.packagePath)
                packs = ["Sinmai_Data/StreamingAssets", "option", "options"].flatMap { root -> [String] in
                    let folder = package.appendingPathComponent(root)
                    return ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.isDirectoryKey])) ?? []).compactMap { url in
                        guard url.resolvingSymlinksInPath() == url, (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true,
                              url.lastPathComponent.uppercased() != "A000" else { return nil }
                        let name = root.hasSuffix("StreamingAssets") ? url.lastPathComponent : root + "/" + url.lastPathComponent
                        return name == item.source ? nil : name
                    }
                }.sorted()
                destination = packs.first ?? ""
            }
    }

    private func copy() {
        guard canCopy, let game = model.game else { return }
        saving = true
        let root = destination.contains("/") ? destination : "Sinmai_Data/StreamingAssets/" + destination
        model.perform {
            defer { saving = false }
            do {
                let result: MusicTransferResult = try await model.worker.request("transferMusic", [
                    "id": game.id, "path": item.xmlPath, "action": "copy", "destination": URL(fileURLWithPath: game.packagePath).appendingPathComponent(root).path
                ])
                model.notice = L10n.format("已复制 %lld 个文件，可在诊断与恢复中撤销。", result.files)
                model.scanMusic(); dismiss()
            } catch { issue = error.localizedDescription }
        }
    }
}

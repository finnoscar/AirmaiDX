import Foundation
#if canImport(FoundationXML)
import FoundationXML
#endif

public enum MusicLibrary {
    public static func scan(package: URL) throws -> [MusicItem] {
        try catalog(package: package).items
    }

    public static func catalog(package: URL) throws -> MusicCatalog {
        let package = package.resolvingSymlinksInPath()
        let roots = ["Sinmai_Data/StreamingAssets", "option", "options"]
        var sources: [(name: String, url: URL)] = []
        for root in roots {
            let folder = package.appendingPathComponent(root)
            for asset in folders(in: folder, under: package) {
                let origin = root.hasSuffix("StreamingAssets") ? asset.lastPathComponent : root + "/" + asset.lastPathComponent
                sources.append((origin, asset))
            }
        }

        // Index assets once. Standard and DX versions can share audio and artwork.
        var assets: [String: [MusicAsset]] = [:]
        for source in sources {
            for (folder, kinds) in [
                ("SoundData", ["acb": "音频", "awb": "音频"]),
                ("MovieData", ["dat": "视频", "usm": "视频", "mp4": "视频"]),
                ("AssetBundleImages/jacket", ["ab": "封面", "png": "封面", "jpg": "封面", "jpeg": "封面", "webp": "封面"])
            ] {
                let directory = source.url.appendingPathComponent(folder)
                guard isLocal(directory, under: package) else { continue }
                for file in entries(in: directory) {
                    let ext = file.pathExtension.lowercased()
                    guard let kind = kinds[ext], isRegularFile(file, under: package) else { continue }
                    let name = file.deletingPathExtension().lastPathComponent.lowercased()
                    assets[name, default: []].append(MusicAsset(kind: kind, path: file.path))
                }
            }
        }

        var items: [MusicItem] = []
        var issues: [MusicReadIssue] = []
        for source in sources {
            let music = source.url.appendingPathComponent("music")
            for directory in folders(in: music, under: package) {
                try Task.checkCancellation()
                let xml = directory.appendingPathComponent("Music.xml")
                guard isRegularFile(xml, under: package) else { continue }
                do {
                    let document = try parseDocument(Data(contentsOf: xml))
                    var item = try read(document, at: xml)
                    item.source = source.name
                    let root = document.rootElement()!
                    let mediaID = item.musicID % 10_000
                    let cue = Int(value(root, "cueName/id")) ?? mediaID
                    let movie = Int(value(root, "movieName/id")) ?? mediaID
                    item.assets = [
                        (String(format: "ui_jacket_%06d", mediaID), "封面"),
                        (String(format: "music%06d", cue), "音频"),
                        (String(format: "%06d", movie), "视频")
                    ].flatMap { key, kind in (assets[key] ?? []).filter { $0.kind == kind } }
                    items.append(item)
                } catch {
                    issues.append(MusicReadIssue(path: xml.path, message: error.localizedDescription))
                }
            }
        }

        let duplicates = Dictionary(grouping: items, by: \.musicID)
        for index in items.indices {
            guard let group = duplicates[items[index].musicID], group.count > 1 else { continue }
            let locations = group.map(\.source).joined(separator: "、")
            items[index].problems.append("编号在多个位置出现（\(locations)），编辑前请确认资源包。")
        }
        func definitions(_ folder: String, _ filename: String, _ rootName: String) -> [MusicDefinition] {
            var values: [Int: String] = [:]
            for source in sources {
                for directory in folders(in: source.url.appendingPathComponent(folder), under: package) {
                    let url = directory.appendingPathComponent(filename)
                    guard isRegularFile(url, under: package), let data = try? Data(contentsOf: url),
                          let doc = try? XMLDocument(data: data, options: [.nodeLoadExternalEntitiesNever]),
                          let root = doc.rootElement(), root.name == rootName,
                          let id = Int(value(root, "name/id")) else { continue }
                    values[id] = value(root, "name/str")
                }
            }
            return values.sorted { $0.key < $1.key }.map { MusicDefinition(id: $0.key, name: $0.value) }
        }
        return MusicCatalog(
            items: items.sorted { ($0.musicID, $0.source, $0.xmlPath) < ($1.musicID, $1.source, $1.xmlPath) },
            readIssues: issues.sorted { $0.path < $1.path },
            genres: definitions("musicGenre", "MusicGenre.xml", "MusicGenreData"),
            versions: definitions("musicVersion", "MusicVersion.xml", "MusicVersionData")
        )
    }

    public static func read(_ url: URL, data: Data? = nil) throws -> MusicItem {
        try read(parseDocument(data ?? Data(contentsOf: url)), at: url)
    }

    private static func read(_ doc: XMLDocument, at url: URL) throws -> MusicItem {
        guard let root = doc.rootElement(), let id = Int(value(root, "name/id")), id >= 0 else {
            throw AirmaiError.message("Music.xml 缺少有效的曲目编号。")
        }
        let dual = value(root, "utagePlayStyle") == "1"
        let charts = (element(root, "notesData")?.elements(forName: "Notes") ?? []).enumerated().map { index, node in
            let integer = value(node, "level")
            let decimal = value(node, "levelDecimal")
            return ChartItem(id: index, level: (integer.isEmpty ? "0" : integer) + "." + (decimal.isEmpty ? "0" : decimal),
                             designer: value(node, "notesDesigner/str"), path: value(node, "file/path"),
                             enabled: ["true", "1"].contains(value(node, "isEnable").lowercased()),
                             maxNotes: Int(value(node, "maxNotes")), displayLevelID: Int(value(node, "musicLevelID")))
        }
        let folder = url.deletingLastPathComponent()
        var problems: [String] = []
        if charts.isEmpty { problems.append("Music.xml 没有难度条目。") }
        for chart in charts where chart.enabled {
            for side in sides(dual: dual) {
                guard let target = chartURL(chart, in: folder, side: side),
                      isRegularFile(target, under: folder) else {
                    problems.append("缺少可读取的 \(chart.name)\(side.map { " " + $0 } ?? "") 谱面。")
                    continue
                }
            }
        }
        return MusicItem(
            id: url.path, musicID: id, title: value(root, "name/str"), artist: value(root, "artistName/str"),
            genre: value(root, "genreName/str"), genreID: Int(value(root, "genreName/id")) ?? 0,
            version: value(root, "AddVersion/str"), versionID: Int(value(root, "AddVersion/id")) ?? 0,
            directory: folder.deletingLastPathComponent().deletingLastPathComponent().lastPathComponent,
            xmlPath: url.path, charts: charts, problems: problems,
            bpm: element(root, "bpm")?.stringValue, sortName: element(root, "sortName")?.stringValue,
            isDoubleUtage: dual,
            longMusic: element(root, "longMusic").map { ["1", "true"].contains(($0.stringValue ?? "").lowercased()) },
            versionValue: Int(value(root, "version"))
        )
    }

    public static func sides(dual: Bool) -> [String?] { dual ? ["L", "R"] : [nil] }

    public static func chartURL(_ chart: ChartItem, in folder: URL, side: String? = nil) -> URL? {
        guard !chart.path.isEmpty, !chart.path.hasPrefix("/"), !chart.path.contains("\\"),
              !chart.path.split(separator: "/").contains("..") else { return nil }
        var file = folder.appendingPathComponent(chart.path).standardizedFileURL
        guard file.pathExtension.lowercased() == "ma2" else { return nil }
        if let side {
            file = file.deletingPathExtension()
            file = file.deletingLastPathComponent().appendingPathComponent(file.lastPathComponent + "_" + side + ".ma2")
        }
        return isLocal(file, under: folder) ? file : nil
    }

    public static func editedXML(item: MusicItem, originalData: Data? = nil) throws -> Data {
        let data = try originalData ?? Data(contentsOf: URL(fileURLWithPath: item.xmlPath))
        let doc = try parseDocument(data)
        guard let root = doc.rootElement() else { throw AirmaiError.message("曲目资料缺少 MusicData。") }
        func put(_ path: String, _ newValue: String, in base: XMLElement = root) throws {
            guard let node = element(base, path) else { throw AirmaiError.message(L10n.format("曲目文件缺少字段 %@", path)) }
            if node.stringValue != newValue { node.stringValue = newValue }
        }
        try put("name/str", item.title)
        try put("artistName/str", item.artist)
        try put("genreName/str", item.genre)
        try put("AddVersion/str", item.version)
        try put("genreName/id", String(item.genreID))
        try put("AddVersion/id", String(item.versionID))
        if let sortName = item.sortName { try put("sortName", sortName) }
        if let long = item.longMusic {
            let old = value(root, "longMusic")
            if ["1", "true"].contains(old.lowercased()) != long {
                try put("longMusic", ["0", "1"].contains(old) ? (long ? "1" : "0") : (long ? "true" : "false"))
            }
        }
        if let version = item.versionValue, version != Int(value(root, "version")) {
            guard version >= 0 else { throw AirmaiError.message("版本值不能小于零。") }
            try put("version", String(version))
        }
        if let bpm = item.bpm, bpm != value(root, "bpm") {
            guard let number = Double(bpm), number.isFinite, number > 0 else {
                throw AirmaiError.message("BPM 必须是大于零的数字。")
            }
            try put("bpm", bpm)
        }
        let nodes = element(root, "notesData")?.elements(forName: "Notes") ?? []
        for chart in item.charts {
            guard nodes.indices.contains(chart.id) else { throw AirmaiError.message("难度条目已变化。") }
            let node = nodes[chart.id]
            let originalLevel = value(node, "level")
            let originalDecimal = value(node, "levelDecimal")
            let levelText = (originalLevel.isEmpty ? "0" : originalLevel) + "." + (originalDecimal.isEmpty ? "0" : originalDecimal)
            if levelText != chart.level {
                let parts = chart.level.split(separator: ".", omittingEmptySubsequences: false)
                let decimal = parts.count == 2 ? String(parts[1]) : "0"
                guard (1...2).contains(parts.count), let level = Int(parts[0]), (0...20).contains(level),
                      decimal.count == 1, let fraction = Int(decimal), (0...9).contains(fraction) else {
                    throw AirmaiError.message(L10n.format("%@ 定数需在 0.0 至 20.9 之间，最多一位小数。", chart.name))
                }
                try put("level", String(level), in: node)
                try put("levelDecimal", decimal, in: node)
                let displayLevel = level < 7 ? level : level * 2 - 7 + (fraction >= 7 ? 1 : 0)
                try put("musicLevelID", String(displayLevel), in: node)
            }
            if chart.designer != value(node, "notesDesigner/str") {
                try put("notesDesigner/str", chart.designer, in: node)
            }
            let wasEnabled = ["true", "1"].contains(value(node, "isEnable").lowercased())
            if chart.enabled != wasEnabled {
                try put("isEnable", chart.enabled ? "true" : "false", in: node)
                if chart.id == 4, chart.enabled, element(root, "subLockType") != nil { try put("subLockType", "0") }
            }
        }
        return doc.xmlData(options: [.nodePreserveAll])
    }

    private static func parseDocument(_ data: Data) throws -> XMLDocument {
        let parser = XMLParser(data: data)
        parser.externalEntityResolvingPolicy = .never
        guard parser.parse() else {
            throw AirmaiError.message(L10n.format("Music.xml 无法解析（第 %lld 行）。", parser.lineNumber))
        }
        let document = try XMLDocument(data: data, options: [.nodePreserveAll, .nodeLoadExternalEntitiesNever])
        guard document.rootElement()?.name == "MusicData" else { throw AirmaiError.message("XML 根节点不是 MusicData。") }
        return document
    }

    private static func element(_ root: XMLElement, _ path: String) -> XMLElement? {
        path.split(separator: "/").reduce(Optional(root)) { node, name in
            node?.elements(forName: String(name)).first
        }
    }

    private static func value(_ node: XMLElement, _ path: String) -> String {
        element(node, path)?.stringValue ?? ""
    }

    private static func entries(in folder: URL) -> [URL] {
        (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.isRegularFileKey, .isDirectoryKey], options: [.skipsHiddenFiles])) ?? []
    }

    private static func folders(in folder: URL, under root: URL) -> [URL] {
        guard isLocal(folder, under: root) else { return [] }
        return entries(in: folder).filter {
            isLocal($0, under: root) && (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    public static func isRegularFile(_ file: URL, under root: URL) -> Bool {
        isLocal(file, under: root) && (try? file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true
    }

    private static func isLocal(_ file: URL, under root: URL) -> Bool {
        let path = file.standardizedFileURL.path
        return path.hasPrefix(root.standardizedFileURL.path + "/") && file.resolvingSymlinksInPath().path == path
    }
}

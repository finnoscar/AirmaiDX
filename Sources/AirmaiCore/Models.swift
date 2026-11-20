import Foundation

public struct GamePresentation: Codable {
    public var title: String
    public var region: String
    public var version: String?
    public var artworkPath: String?
    public var artworkSource: String?
}

public struct GameInstallation: Codable, Identifiable, Hashable {
    public var id: String
    public var name: String
    public var packagePath: String
    public var sourcePath: String
    public var storageMode: String?
    public var importedAt: String
    public var unityVersion: String
    public var ready: Bool
    public var settings: GameSettings
    public var hasAquaMai: Bool
    public var profileName: String?
    public var gameId: String?
    public var gameVersion: String?
    public var loaderVersion: String?
    public var modVersion: String?
    public var compatibilityState: String?
    public var compatibilityNote: String?
    public var startupChecks: [StartupCheck]?
    public var allowedStartupChecks: [String]?
}

public struct StartupCheck: Codable, Identifiable, Hashable {
    public var url: String
    public var method: String
    public var purpose: String
    public var sendsMachineData: Bool
    public var id: String { url }
}

public struct GameSettings: Codable, Hashable {
    public var displayUUID: String = ""
    public var width: Int = 1080
    public var height: Int = 1920
    public var fillDisplay: Bool = true
    public var metalHUD: Bool = true
    public var hdxEnabled: Bool = true
    public var adxEnabled: Bool = true
    public var phoneReaderEnabled: Bool = false
    public var mouseEnabled: Bool = true
    public var networkEnabled: Bool = true
    public var transportCompatibility: Bool = true
    public var networkInterface: String = ""
    public init() {}
    enum CodingKeys: String, CodingKey {
        case displayUUID, width, height, fillDisplay, metalHUD, hdxEnabled, adxEnabled
        case phoneReaderEnabled, mouseEnabled, networkEnabled, transportCompatibility, networkInterface
    }
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        displayUUID = try values.decodeIfPresent(String.self, forKey: .displayUUID) ?? ""
        width = try values.decodeIfPresent(Int.self, forKey: .width) ?? 1080
        height = try values.decodeIfPresent(Int.self, forKey: .height) ?? 1920
        fillDisplay = try values.decodeIfPresent(Bool.self, forKey: .fillDisplay) ?? true
        metalHUD = try values.decodeIfPresent(Bool.self, forKey: .metalHUD) ?? true
        hdxEnabled = try values.decodeIfPresent(Bool.self, forKey: .hdxEnabled) ?? true
        adxEnabled = try values.decodeIfPresent(Bool.self, forKey: .adxEnabled) ?? true
        phoneReaderEnabled = try values.decodeIfPresent(Bool.self, forKey: .phoneReaderEnabled) ?? false
        mouseEnabled = try values.decodeIfPresent(Bool.self, forKey: .mouseEnabled) ?? true
        networkEnabled = try values.decodeIfPresent(Bool.self, forKey: .networkEnabled) ?? true
        transportCompatibility = try values.decodeIfPresent(Bool.self, forKey: .transportCompatibility) ?? true
        networkInterface = try values.decodeIfPresent(String.self, forKey: .networkInterface) ?? ""
    }
}

public struct DisplayChoice: Identifiable, Hashable {
    public var id: String
    public var name: String
    public var width: Int
    public var height: Int
    public var scale: Double
    public var refresh: Double
    public var label: String { "\(name) · \(width) × \(height)" }
    public init(id: String, name: String, width: Int, height: Int, scale: Double, refresh: Double) {
        self.id = id; self.name = name; self.width = width; self.height = height
        self.scale = scale; self.refresh = refresh
    }
}

public struct ConfigFile: Codable {
    public var name: String
    public var text: String
    public var encoding: String
    public var sha256: String
}

public struct MusicItem: Codable, Identifiable, Hashable {
    public var id: String
    public var musicID: Int
    public var title: String
    public var artist: String
    public var genre: String
    public var genreID: Int
    public var version: String
    public var versionID: Int
    public var directory: String
    public var xmlPath: String
    public var charts: [ChartItem]
    public var problems: [String]
    public var source: String = ""
    public var bpm: String?
    public var sortName: String?
    public var isDoubleUtage: Bool = false
    public var assets: [MusicAsset] = []
    public var longMusic: Bool?
    public var versionValue: Int?

    public var number: String { String(format: "%06d", musicID) }
    public var kind: String { musicID >= 100_000 ? "宴" : musicID >= 10_000 ? "DX" : "标准" }
    public func difficultyName(_ chart: ChartItem) -> String {
        kind == "宴" && chart.id == 0 ? L10n.text("宴谱") : L10n.text(chart.name)
    }
}

public struct ChartItem: Codable, Identifiable, Hashable {
    public var id: Int
    public var level: String
    public var designer: String
    public var path: String
    public var enabled: Bool
    public var maxNotes: Int?
    public var displayLevelID: Int?

    public var displayLevel: String {
        if let id = displayLevelID, id >= 0 {
            return id < 7 ? String(id) : String((id + 7) / 2) + (id.isMultiple(of: 2) ? "+" : "")
        }
        guard let value = Double(level), value.isFinite, value >= 0 else { return level }
        let whole = Int(value)
        return String(whole) + (whole >= 7 && value - Double(whole) >= 0.6999 ? "+" : "")
    }

    public var name: String {
        let names = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "Re:MASTER", "宴"]
        return id < names.count ? names[id] : L10n.format("难度 %lld", id + 1)
    }
}

public struct MusicAsset: Codable, Hashable, Identifiable {
    public var kind: String
    public var path: String
    public var id: String { path }
}

public struct MusicReadIssue: Hashable, Identifiable {
    public var path: String
    public var message: String
    public var id: String { path }
}

public struct MusicCatalog {
    public var items: [MusicItem]
    public var readIssues: [MusicReadIssue]
    public var genres: [MusicDefinition]
    public var versions: [MusicDefinition]
    public init(items: [MusicItem] = [], readIssues: [MusicReadIssue] = [], genres: [MusicDefinition] = [], versions: [MusicDefinition] = []) {
        self.items = items
        self.readIssues = readIssues
        self.genres = genres
        self.versions = versions
    }
}

public struct MusicDefinition: Identifiable, Hashable {
    public var id: Int
    public var name: String
}

public struct ComponentStatus: Codable, Identifiable {
    public var id: String
    public var name: String
    public var status: String
    public var detail: String
}

public struct SessionStatus: Codable {
    public var running: Bool
    public var phase: String
    public var message: String
    public var pid: Int?
    public var fps: Double?
    public var gpuMS: Double?
    public var renderWidth: Int?
    public var renderHeight: Int?
    public var touch: Bool?
    public var led: Bool?
    public var reader: Bool?
    public var networkOnline: Bool?
    public var inputMode: String?
    public var controllerInput: Bool?
    public var controllerMessage: String?
    public var sessionPath: String?
}

public struct BackupItem: Codable, Identifiable {
    public var id: String
    public var file: String
    public var created: String
}

public struct DiagnosticLog: Codable, Identifiable {
    public var id: String
    public var title: String
    public var text: String
    public var modified: String
    public var truncated: Bool
}

public struct DiagnosticSnapshot: Codable {
    public var created: String
    public var system: String
    public var session: String?
    public var summary: String
    public var logs: [DiagnosticLog]
    public var limitReached: Bool

    public func report(appVersion: String) -> String {
        var parts = ["AirmaiDX \(appVersion)", "Created: \(created)", system,
                     "Session: \(session ?? "none")", summary,
                     L10n.text("常见机台标识、卡号和认证字段已遮盖；请在分享前检查内容。")]
        for log in logs {
            parts.append("\n===== \(L10n.text(log.title)) · \(log.id) =====\nUpdated: \(log.modified)" +
                         (log.truncated ? "\n" + L10n.text("仅包含文件末尾内容。") : "") + "\n\n" + log.text)
        }
        if limitReached { parts.append("\n" + L10n.text("诊断达到 1 MiB 读取上限，部分日志未包含。")) }
        return parts.joined(separator: "\n") + "\n"
    }
}

public enum AirmaiError: LocalizedError {
    case message(String)
    public var errorDescription: String? {
        switch self { case .message(let text): return L10n.text(text) }
    }
}

public struct ControllerInventory: Codable {
    public var devices: [ControllerDevice]
    public var errors: [String]
}

public struct ControllerDevice: Codable, Identifiable {
    public var id: String
    public var vendor: Int
    public var product: Int
    public var name: String
    public var profile: String
    public var player: Int?
    public var channels: [String]
    public var status: String
    public var detail: String
    public var identity: String { String(format: "%04X:%04X", vendor, product) }
}

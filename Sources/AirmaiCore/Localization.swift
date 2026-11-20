import Foundation

public enum AppLanguage: String, CaseIterable, Identifiable {
    case system, simplifiedChinese = "zh-Hans", english = "en", japanese = "ja"
    public var id: String { rawValue }
    public static let preferenceKey = "appLanguage"

    public func resolved(preferredLanguages: [String] = Locale.preferredLanguages) -> AppLanguage {
        guard self == .system else { return self }
        for identifier in preferredLanguages {
            if identifier.lowercased().hasPrefix("zh") { return .simplifiedChinese }
            if identifier.lowercased().hasPrefix("en") { return .english }
            if identifier.lowercased().hasPrefix("ja") { return .japanese }
        }
        return .english
    }

    public static var current: AppLanguage {
        (AppLanguage(rawValue: UserDefaults.standard.string(forKey: preferenceKey) ?? "system") ?? .system).resolved()
    }

    public var locale: Locale { Locale(identifier: resolved().rawValue) }
    public var label: String {
        switch self {
        case .system: return L10n.text("跟随系统")
        case .simplifiedChinese: return "简体中文"
        case .english: return "English"
        case .japanese: return "日本語"
        }
    }
}

public enum L10n {
    public static let bundle: Bundle = {
        #if SWIFT_PACKAGE
        return Bundle.module
        #else
        // Native tests have no app host. Their own bundle carries these resources.
        return ([Bundle.main] + Bundle.allBundles).first {
            $0.url(forResource: "AquaMaiMetadata", withExtension: "json") != nil
        } ?? Bundle.main
        #endif
    }()

    public static func text(_ key: String, language: AppLanguage? = nil) -> String {
        let language = (language ?? .current).resolved()
        guard let path = bundle.path(forResource: language.rawValue, ofType: "lproj"),
              let localized = Bundle(path: path) else { return key }
        let result = localized.localizedString(forKey: key, value: key, table: "Localizable")
        // A known service progress template; arbitrary log/config text stays verbatim.
        if result == key, key.hasPrefix("显示预览中，将在 "), key.hasSuffix(" 秒后自动恢复"),
           let seconds = Int(key.dropFirst("显示预览中，将在 ".count).dropLast(" 秒后自动恢复".count)) {
            return format("显示预览中，将在 %lld 秒后自动恢复", seconds, language: language)
        }
        return result
    }

    public static func format(_ key: String, _ arguments: CVarArg..., language: AppLanguage? = nil) -> String {
        let language = (language ?? .current).resolved()
        return String(format: text(key, language: language), locale: language.locale, arguments: arguments)
    }
}

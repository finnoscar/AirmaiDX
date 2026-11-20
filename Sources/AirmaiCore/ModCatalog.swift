import Foundation

public struct ModDescription: Codable {
    public var title: [String: String]
    public var help: [String: String]
}

public struct ModSectionDescription: Codable {
    public var title: [String: String]
    public var help: [String: String]
    public var entries: [String: ModDescription]
    public var alwaysEnabled: Bool
}

/// Documentation is a UI reference, never a source of runtime defaults or keys.
/// Only sections and entries present in the imported document are displayed.
public struct ModCatalog {
    private struct Reference: Decodable { var sections: [String: ModSectionDescription] }
    private struct Translations: Decodable {
        var sections: [String: ModDescription]
        var fields: [String: [String: String]]
        var entryHelp: [String: [String: String]]?
    }
    private let sections: [String: ModSectionDescription]
    private let translations: Translations
    public static let shared = ModCatalog()

    public init(bundle: Bundle = L10n.bundle) {
        sections = Self.load(Reference.self, "AquaMaiMetadata", bundle: bundle)?.sections ?? [:]
        translations = Self.load(Translations.self, "AquaMaiTranslations", bundle: bundle)
            ?? Translations(sections: [:], fields: [:])
    }
    private static func load<T: Decodable>(_ type: T.Type, _ name: String, bundle: Bundle) -> T? {
        guard let url = bundle.url(forResource: name, withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
    public var sectionPaths: Set<String> { Set(sections.keys) }
    public func isAlwaysEnabled(_ section: SettingsDocument.Section) -> Bool {
        section.line < 0 || section.name == "General" || sections[section.name]?.alwaysEnabled == true
    }
    public func isEnabled(_ section: SettingsDocument.Section) -> Bool {
        isAlwaysEnabled(section) || (!section.commented && section.entries.first { $0.key == "Disabled" && !$0.commented }?.boolValue != true)
    }
    public func title(_ section: SettingsDocument.Section, language: AppLanguage) -> String {
        if section.line < 0 { return L10n.text("配置格式", language: language) }
        let code = language.resolved().rawValue
        return translations.sections[section.name]?.title[code]
            ?? sections[section.name]?.title[code] ?? Self.humanize(section.name.components(separatedBy: ".").last ?? section.name)
    }
    public func help(_ section: SettingsDocument.Section, language: AppLanguage) -> String {
        if section.line < 0 { return L10n.text("配置文件的版本标识；通常无需修改。", language: language) }
        let code = language.resolved().rawValue
        if let text = translations.sections[section.name]?.help[code], !text.isEmpty { return text }
        if let text = sections[section.name]?.help[code], !text.isEmpty { return text }
        return L10n.text("此版本的选项尚无本地化说明，可展开查看文件中的原始说明。", language: language)
    }
    public func title(_ entry: SettingsDocument.Entry, language: AppLanguage) -> String {
        let code = language.resolved().rawValue
        if let pattern = patternedTitle(entry, language: language) { return pattern }
        if code == "zh-Hans", let native = sections[entry.section]?.entries[entry.key]?.title[code],
           native.contains(where: { $0.unicodeScalars.contains { (0x4E00...0x9FFF).contains($0.value) } }), native.count < 32 { return native }
        if let override = translations.fields[entry.key]?[code] { return override }
        if let title = sections[entry.section]?.entries[entry.key]?.title[code], !title.isEmpty { return title }
        return Self.humanize(entry.key)
    }
    public func help(_ entry: SettingsDocument.Entry, language: AppLanguage) -> String {
        let code = language.resolved().rawValue
        return translations.entryHelp?[entry.section + "." + entry.key]?[code]
            ?? sections[entry.section]?.entries[entry.key]?.help[code] ?? ""
    }
    public func matches(_ section: SettingsDocument.Section, query: String) -> Bool {
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return true }
        var texts = [section.name, section.help]
        for language in [AppLanguage.simplifiedChinese, .english, .japanese] {
            texts += [title(section, language: language), help(section, language: language)]
            for entry in section.entries { texts += [title(entry, language: language), help(entry, language: language)] }
        }
        texts += section.entries.flatMap { [$0.key, $0.help] }
        return texts.contains { $0.localizedStandardContains(query) }
    }
    private func patternedTitle(_ entry: SettingsDocument.Entry, language: AppLanguage) -> String? {
        let key = entry.key
        if entry.section == "GameSettings.TouchSensitivity", key.range(of: "^[ABCDE][1-8]$", options: .regularExpression) != nil {
            return L10n.format("%@ 区灵敏度", key, language: language)
        }
        if let range = key.range(of: "^Button[1-8]_[12]P$", options: .regularExpression), range == key.startIndex..<key.endIndex {
            return L10n.format("%@ · 按键 %@", String(key.suffix(2)), String(key.dropFirst(6).prefix(1)), language: language)
        }
        if key.range(of: "^P[12]Button[1-4]$", options: .regularExpression) != nil {
            return L10n.format("%@ · 功能键 %@", String(key.prefix(2)), String(key.suffix(1)), language: language)
        }
        return nil
    }
    public static func humanize(_ value: String) -> String {
        value.replacingOccurrences(of: "([a-z0-9])([A-Z])", with: "$1 $2", options: .regularExpression)
            .replacingOccurrences(of: "_", with: " ")
    }
}

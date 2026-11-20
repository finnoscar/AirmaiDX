import XCTest
@testable import AirmaiCore

final class LocalizationTests: XCTestCase {
    func testSystemLanguageAndUnsupportedFallback() {
        XCTAssertEqual(AppLanguage.system.resolved(preferredLanguages: ["ja-JP"]), .japanese)
        XCTAssertEqual(AppLanguage.system.resolved(preferredLanguages: ["zh-Hant-TW"]), .simplifiedChinese)
        XCTAssertEqual(AppLanguage.system.resolved(preferredLanguages: ["fr-FR", "en-GB"]), .english)
        XCTAssertEqual(AppLanguage.system.resolved(preferredLanguages: ["fr-FR"]), .english)
        XCTAssertEqual(AppLanguage.japanese.resolved(preferredLanguages: ["en"]), .japanese)
    }
    func testResourcesLoadInAllBuildSystemsAndPreservePlaceholders() throws {
        let languages: [AppLanguage] = [.simplifiedChinese, .english, .japanese]
        var tables: [[String: String]] = []
        for language in languages {
            let url = try XCTUnwrap(L10n.bundle.url(forResource: "Localizable", withExtension: "strings", subdirectory: language.rawValue + ".lproj"))
            let table = try XCTUnwrap(PropertyListSerialization.propertyList(from: Data(contentsOf: url), format: nil) as? [String: String])
            tables.append(table)
            for (key, value) in table {
                let pattern = #"%(?:\d+\$)?(?:lld|ld|d|@|f|llu)"#
                func tokens(_ text: String) -> [String] {
                    let regex = try! NSRegularExpression(pattern: pattern)
                    return regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).map {
                        String(text[Range($0.range, in: text)!])
                    }.sorted()
                }
                XCTAssertEqual(tokens(key), tokens(value), "\(language.rawValue): \(key)")
            }
        }
        XCTAssertEqual(Set(tables[0].keys), Set(tables[1].keys))
        XCTAssertEqual(Set(tables[0].keys), Set(tables[2].keys))
        XCTAssertEqual(L10n.text("模组配置", language: .japanese), "Mod 設定")
        XCTAssertEqual(L10n.text("游戏库", language: .english), "Game Library")
        XCTAssertEqual(L10n.text("显示预览中，将在 8 秒后自动恢复", language: .japanese), "表示プレビュー中：8 秒後に元に戻ります")
        XCTAssertEqual(L10n.format("%lld 个分组", 4, language: .japanese), "4 グループ")
        XCTAssertEqual(L10n.text("Unknown.Future.Key", language: .japanese), "Unknown.Future.Key")
    }
    func testKnownModNamesAndSearchAcrossLanguagesDoNotChangeDraft() throws {
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Fixtures/ModConfigurationKeys.json")
        let inventory = try JSONDecoder().decode([String: [String]].self, from: Data(contentsOf: fixture))
        let catalog = ModCatalog.shared
        XCTAssertGreaterThanOrEqual(catalog.sectionPaths.count, 139)
        for (path, keys) in inventory {
            let doc = SettingsDocument(text: "[\(path)]\n" + keys.map { "#\($0) = 1" }.joined(separator: "\n"), isTOML: true)
            let section = try XCTUnwrap(doc.sections.first)
            for language in [AppLanguage.simplifiedChinese, .english, .japanese] {
                XCTAssertFalse(catalog.title(section, language: language).isEmpty, path)
                if language != .english {
                    XCTAssertNotEqual(catalog.title(section, language: language), ModCatalog.humanize(path.components(separatedBy: ".").last!), path)
                }
                if language == .simplifiedChinese {
                    XCTAssertTrue(catalog.title(section, language: language).unicodeScalars.contains { (0x4E00...0x9FFF).contains($0.value) }, path)
                }
                XCTAssertFalse(catalog.help(section, language: language).isEmpty, path)
                for entry in section.entries where entry.key != "Disabled" {
                    XCTAssertFalse(catalog.title(entry, language: language).isEmpty, "\(path).\(entry.key)")
                    if language != .english && !["P1", "P2"].contains(entry.key) {
                        XCTAssertNotEqual(catalog.title(entry, language: language), ModCatalog.humanize(entry.key), "\(language): \(path).\(entry.key)")
                    }
                }
            }
        }
        var doc = SettingsDocument(text: "[GameSystem.Window]\n#Width = 1080\n", isTOML: true)
        let section = doc.sections[0]
        let original = doc.text
        XCTAssertTrue(catalog.matches(section, query: "窗口"))
        XCTAssertTrue(catalog.matches(section, query: "ウインドウ"))
        XCTAssertTrue(catalog.matches(section, query: "Window"))
        XCTAssertEqual(doc.text, original)
        // Resolving labels in all languages cannot activate a default value.
        for language in AppLanguage.allCases { _ = catalog.title(section.entries[0], language: language) }
        doc.set(section.entries[0], value: "2160", active: false)
        XCTAssertTrue(doc.sections[0].entries[0].commented)
    }
    func testUnknownModFallsBackToOriginalKeyAndDocumentation() {
        let section = SettingsDocument(text: "# Original vendor documentation\n[Future.NewModule]\n#NewOption = true\n", isTOML: true).sections[0]
        XCTAssertEqual(ModCatalog.shared.title(section, language: .japanese), "New Module")
        XCTAssertTrue(ModCatalog.shared.matches(section, query: "vendor"))
        XCTAssertEqual(section.entries[0].key, "NewOption")
    }
}

import XCTest
@testable import AirmaiCore

final class SettingsDocumentTests: XCTestCase {
    func testRoundTripPreservesUnknownCommentsDuplicateKeysAndCRLF() {
        let text = "; 注释\r\n[dns]\r\nDefault = original\r\nDefault=override\r\nunknown line\r\n"
        XCTAssertEqual(SettingsDocument(text: text).text, text)
        var doc = SettingsDocument(text: text)
        doc.set(section: "DNS", key: "default", value: "localhost")
        XCTAssertTrue(doc.text.contains("Default = original\r\nDefault = localhost"))
        XCTAssertTrue(doc.text.contains("unknown line"))
    }
    func testActivatingCommentedDefaultDoesNotEnableOtherSettings() {
        var doc = SettingsDocument(text: "[Render]\n#Width = 1080\n#Height = 1920\n", isTOML: true)
        let entry = doc.sections[0].entries[0]
        doc.set(entry, value: "2160")
        XCTAssertTrue(doc.text.contains("Width = 2160\n#Height = 1920"))
    }
    func testSectionDisableBelongsToCorrectSection() {
        var doc = SettingsDocument(text: "[First]\nX = 1\n\n[Second]\nY = 2\n", isTOML: true)
        doc.setSectionEnabled(doc.sections[0], enabled: false)
        XCTAssertEqual(doc.value(section: "First", key: "Disabled"), "true")
        XCTAssertEqual(doc.value(section: "Second", key: "Disabled"), "")
    }

    func testCommentedSectionCannotLeakKeysIntoPreviousTable() {
        let original = "[First]\nValue = 1\n#[Second]\n#Width = 1080\n"
        var doc = SettingsDocument(text: original, isTOML: true)
        doc.set(doc.sections[1].entries[0], value: "2160", active: true)
        doc.set(section: "Second", key: "Extra", value: "true")
        XCTAssertEqual(doc.text, original)
        doc.setSectionEnabled(doc.sections[1], enabled: true)
        doc.set(doc.sections[1].entries.first { $0.key == "Width" }!, value: "2160", active: true)
        XCTAssertEqual(doc.value(section: "Second", key: "Width"), "2160")
        XCTAssertEqual(doc.value(section: "First", key: "Width"), "")
    }
    func testGlobalAndGeneralCannotBeDisabled() {
        var doc = SettingsDocument(text: "Version = 2\n[General]\n#Locale = \"\"\n", isTOML: true)
        let original = doc.text
        for section in doc.sections { doc.setSectionEnabled(section, enabled: false) }
        XCTAssertEqual(doc.text, original)
    }
    func testAppendWithoutFinalNewlinePreservesLastValueAndUnknownKeys() {
        var doc = SettingsDocument(text: "[Window]\r\nUnknown = 'a#b'\r\nWidth = 1080", isTOML: true)
        doc.setSectionEnabled(doc.sections[0], enabled: false)
        XCTAssertEqual(doc.value(section: "Window", key: "Width"), "1080")
        XCTAssertTrue(doc.text.hasSuffix("Width = 1080\r\nDisabled = true"))
        XCTAssertTrue(doc.text.contains("Unknown = 'a#b'"))
    }
    func testInlineCommentsAndQuotedHashesSurviveEditing() {
        var doc = SettingsDocument(text: "[Window]\nDisabled = true # explanation\nName = \"x#y\" # custom\n", isTOML: true)
        XCTAssertFalse(ModCatalog.shared.isEnabled(doc.sections[0]))
        doc.setSectionEnabled(doc.sections[0], enabled: true)
        XCTAssertTrue(ModCatalog.shared.isEnabled(doc.sections[0]))
        XCTAssertTrue(doc.text.contains("Disabled = false # explanation"))
        let entry = doc.sections[0].entries.first { $0.key == "Name" }!
        XCTAssertEqual(entry.displayValue, "x#y")
        doc.set(entry, value: "\"new#value\"", active: false)
        XCTAssertTrue(doc.text.contains("#Name = \"new#value\" # custom"))
    }
    func testCommentedDisabledUsesModuleDefaultOnState() {
        let doc = SettingsDocument(text: "[Window]\n#Disabled = true\n#Width = 1080\n", isTOML: true)
        XCTAssertTrue(ModCatalog.shared.isEnabled(doc.sections[0]))
    }
}

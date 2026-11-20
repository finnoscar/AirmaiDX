import XCTest
@testable import AirmaiCore

final class MusicLibraryTests: XCTestCase {
    func testCatalogReportsBadOptionXMLAndFindsBothUtageFiles() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let song = root.appendingPathComponent("option/A007/music/music111359")
        let bad = root.appendingPathComponent("Sinmai_Data/StreamingAssets/A000/music/music000001")
        for folder in [song, bad] { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) }
        try """
        <MusicData><name><id>111359</id><str>Pair</str></name><utagePlayStyle>1</utagePlayStyle>
        <notesData><Notes><file><path>111359_00.ma2</path></file><isEnable>true</isEnable></Notes></notesData></MusicData>
        """.write(to: song.appendingPathComponent("Music.xml"), atomically: true, encoding: .utf8)
        try "<MusicData><name>".write(to: bad.appendingPathComponent("Music.xml"), atomically: true, encoding: .utf8)
        try Data().write(to: song.appendingPathComponent("111359_00_L.ma2"))
        var result = try MusicLibrary.catalog(package: root)
        XCTAssertEqual(result.items.map(\.source), ["option/A007"])
        XCTAssertEqual(result.readIssues.count, 1)
        XCTAssertEqual(result.items[0].problems, ["缺少可读取的 BASIC R 谱面。"])
        try Data().write(to: song.appendingPathComponent("111359_00_R.ma2"))
        result = try MusicLibrary.catalog(package: root)
        XCTAssertTrue(result.items[0].problems.isEmpty)
    }

    func testMetadataEditKeepsUnknownFieldsAndUpdatesRelatedLevelID() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let xml = root.appendingPathComponent("Music.xml")
        let fixture = """
        <?xml version="1.0" encoding="utf-8"?>
        <MusicData><name><id>900001</id><str>Test</str></name><artistName><str>Author</str></artistName>
        <genreName><id>1</id><str>Genre</str></genreName><AddVersion><id>2</id><str>Version</str></AddVersion>
        <longMusic>0</longMusic><version>10000</version>
        <!-- preserved --><customField flag="keep">opaque</customField>
        <notesData><Notes><file><path>test.ma2</path></file><level>12</level><levelDecimal>0</levelDecimal>
        <notesDesigner><str>Designer</str></notesDesigner><musicLevelID>17</musicLevelID><maxNotes>100</maxNotes><isEnable>false</isEnable>
        </Notes></notesData></MusicData>
        """
        try fixture.write(to: xml, atomically: true, encoding: .utf8)
        var item = try MusicLibrary.read(xml)
        item.title = "Changed"; item.genreID = 3; item.genre = "Another"; item.charts[0].level = "12.8"
        item.longMusic = true; item.versionValue = 20000
        let data = try MusicLibrary.editedXML(item: item)
        let result = String(decoding: data, as: UTF8.self)
        XCTAssertTrue(result.contains("<musicLevelID>18</musicLevelID>"))
        XCTAssertTrue(result.contains("<maxNotes>100</maxNotes>"))
        XCTAssertTrue(result.contains("<!-- preserved -->"))
        XCTAssertTrue(result.contains("flag=\"keep\""))
        try data.write(to: xml)
        let edited = try MusicLibrary.read(xml)
        XCTAssertEqual(edited.genreID, 3); XCTAssertEqual(edited.genre, "Another")
        XCTAssertEqual(edited.charts[0].level, "12.8")
        XCTAssertEqual(edited.charts[0].displayLevel, "12+")
        XCTAssertEqual(edited.longMusic, true)
        XCTAssertEqual(edited.versionValue, 20000)
    }

    func testCatalogReadsUnusedGenreAndVersionDefinitions() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        for (directory, file, type, id) in [("musicGenre/genre001", "MusicGenre.xml", "MusicGenreData", 77),
                                          ("musicVersion/ver001", "MusicVersion.xml", "MusicVersionData", 88)] {
            let folder = root.appendingPathComponent("Sinmai_Data/StreamingAssets/A000/" + directory)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try "<\(type)><name><id>\(id)</id><str>Unused definition</str></name></\(type)>"
                .write(to: folder.appendingPathComponent(file), atomically: true, encoding: .utf8)
        }
        let catalog = try MusicLibrary.catalog(package: root)
        XCTAssertTrue(catalog.items.isEmpty)
        XCTAssertEqual(catalog.genres.first?.id, 77)
        XCTAssertEqual(catalog.versions.first?.id, 88)
    }
}

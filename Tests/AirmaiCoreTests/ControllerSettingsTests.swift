import XCTest
@testable import AirmaiCore

final class ControllerSettingsTests: XCTestCase {
    func testOlderLibrarySettingsKeepHDXChoiceAndDefaultADXConnection() throws {
        let settings = try JSONDecoder().decode(GameSettings.self, from: Data(#"{"hdxEnabled":false,"width":2160,"height":3840}"#.utf8))
        XCTAssertFalse(settings.hdxEnabled)
        XCTAssertTrue(settings.adxEnabled)
        XCTAssertTrue(settings.mouseEnabled)
        XCTAssertTrue(settings.networkEnabled)
        XCTAssertEqual(settings.width, 2160)
        let saved = try JSONDecoder().decode(GameSettings.self, from: JSONEncoder().encode(settings))
        XCTAssertTrue(saved.adxEnabled)
    }
    func testADXOptOutPersistsAndInvalidSettingTypeIsRejected() throws {
        let settings = try JSONDecoder().decode(GameSettings.self, from: Data(#"{"adxEnabled":false}"#.utf8))
        XCTAssertFalse(settings.adxEnabled)
        XCTAssertThrowsError(try JSONDecoder().decode(GameSettings.self, from: Data(#"{"adxEnabled":"false"}"#.utf8)))
    }
    func testMouseAndNetworkingDefaultsAndExplicitChoicesRoundTrip() throws {
        XCTAssertTrue(GameSettings().mouseEnabled)
        XCTAssertTrue(GameSettings().networkEnabled)
        let data = Data(#"{"mouseEnabled":false,"networkEnabled":false}"#.utf8)
        let settings = try JSONDecoder().decode(GameSettings.self, from: data)
        let saved = try JSONDecoder().decode(GameSettings.self, from: JSONEncoder().encode(settings))
        XCTAssertFalse(saved.mouseEnabled); XCTAssertFalse(saved.networkEnabled)
        XCTAssertThrowsError(try JSONDecoder().decode(GameSettings.self, from: Data(#"{"mouseEnabled":"false"}"#.utf8)))
    }
}

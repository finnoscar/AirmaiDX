import XCTest
@testable import AirmaiCore

final class MA2ChartTests: XCTestCase {
    func testBothDialectsAndTempoChanges() throws {
        let chart = try MA2Chart(text: """
        VERSION 0.00.00 1.04.00
        RESOLUTION 384
        BPM_DEF 120 120 120 120
        BPM 0 0 120
        BPM 1 0 240
        NMTAP 0 96 2
        BXTAP 1 96 7
        NMHLD 0 288 1 192
        NMTTP 1 192 0 C 1 L1
        NMSTR 2 0 3
        NMSI_ 2 0 3 96 192 7
        TAP 2 96 4
        T_NUM_ALL 7
        """)
        XCTAssertEqual(chart.totalNotes, 7)
        XCTAssertEqual(chart.slideCount, 1)
        XCTAssertEqual(chart.notes.first!.seconds, 0.5, accuracy: 0.0001)
        let modified = try XCTUnwrap(chart.notes.first { $0.isBreak })
        XCTAssertTrue(modified.isEX)
        XCTAssertEqual(modified.seconds, 2.25, accuracy: 0.0001)
        let hold = try XCTUnwrap(chart.notes.first { $0.kind == "HLD" })
        XCTAssertEqual(hold.duration, 0.75, accuracy: 0.0001)
        XCTAssertEqual(chart.notes.first { $0.kind == "TTP" }?.touchArea, "C")
    }
    func testRejectsInvalidClock() {
        XCTAssertThrowsError(try MA2Chart(text: "RESOLUTION 0\nTAP 1 0 0"))
    }
    func testConnectedSlideExtendsPlaybackButCountsOnce() throws {
        let chart = try MA2Chart(text: """
        VERSION 0.00.00 1.04.00
        RESOLUTION 384
        BPM_DEF 120 120 120 120
        BPM 1 0 240
        NMSTR 0 288 0
        NMSI_ 0 288 0 96 96 3
        CNSI_ 1 96 3 0 192 6
        T_NUM_ALL 2
        """)
        XCTAssertEqual(chart.totalNotes, 2)
        XCTAssertEqual(chart.slideCount, 2)
        XCTAssertEqual(chart.slides[0].travelStart, 2, accuracy: 0.0001)
        XCTAssertEqual(chart.slides[1].end, 2.75, accuracy: 0.0001)
        XCTAssertEqual(chart.duration, 4.75, accuracy: 0.0001)
        try chart.validateForImport()
    }
}

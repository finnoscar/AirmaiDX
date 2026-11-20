import XCTest
import AirmaiCore
@testable import AirmaiEditorPreview

final class EditorPreviewAdapterTests: XCTestCase {
    func testNativeParserRetainsChainBranchesAndBPMChange() throws {
        let ma2 = try MA2Chart(text: """
        VERSION 0.00.00 1.05.00
        RESOLUTION 384
        BPM_DEF 120 120 120 120
        BPM 1 0 240
        BRSTR 0 288 0
        NMSCL 0 288 0 96 96 3
        CNSLL 1 96 3 0 192 6
        BRSF_ 0 288 0 96 192 4
        NMTHO 1 0 2 96 B 1 L1
        T_NUM_ALL 4
        """)
        let preview = try MA2EditorAdapter(ma2: ma2, title: "Adapter")
        let head = try XCTUnwrap(preview.chart.events.first)
        XCTAssertEqual(head.time, 1.5, accuracy: 0.0001)
        XCTAssertTrue(head.flags.contains(.breakNote))
        XCTAssertEqual(head.slidePaths.count, 2)
        let chain = try XCTUnwrap(head.slidePaths.first { $0.segments.count == 2 })
        XCTAssertEqual(chain.segments.map(\.shape), [.counterclockwise, .edgeFold])
        XCTAssertEqual(chain.segments.last?.via?.index, 2)
        XCTAssertEqual(chain.startTime, 2, accuracy: 0.0001)
        XCTAssertEqual(chain.endTime, 2.75, accuracy: 0.0001)
        XCTAssertTrue(head.slidePaths.contains { $0.containsFan && $0.isBreak })
        let touch = try XCTUnwrap(preview.chart.events.last)
        XCTAssertEqual(touch.kind, .touchHold)
        XCTAssertEqual(touch.location.ring, .b)
        XCTAssertTrue(touch.flags.contains(.fireworks))
        XCTAssertEqual(touch.duration, 0.25, accuracy: 0.0001)
    }
}

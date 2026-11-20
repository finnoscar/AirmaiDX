import XCTest
import AirmaiTouchKit
import AirmaiMobileCore

final class TouchSensorMeshTests: XCTestCase {
    func testSemanticLayoutHasThirtyThreeUniqueRegions() {
        XCTAssertEqual(TouchSensor.all.count, 33)
        XCTAssertEqual(Set(TouchSensor.all.map(\.id)).count, 33)
        XCTAssertEqual(Set(TouchSensor.all.map(\.semanticIndex)), Set(0..<33))
        XCTAssertEqual(TouchSensor.all.filter { $0.ring == .c }.map(\.label), ["C"])
    }

    func testEveryRepresentativePointHitsItsRegion() {
        for sensor in TouchSensor.all {
            XCTAssertEqual(
                TouchSensorMesh.sensor(at: TouchSensorMesh.representativePoint(for: sensor)),
                sensor,
                "Representative point for \(sensor.label) must use the same mesh as rendering"
            )
        }
    }

    func testOutsideDiscAndGapsDoNotHit() {
        XCTAssertNil(TouchSensorMesh.sensor(at: CGPoint(x: 1.5, y: 1.5)))
    }

    func testContactLifecycleAndCancellationReleaseState() {
        var state = TouchContactState()
        let a = TouchContact(id: 1, point: .zero, timestamp: 1)
        let b = TouchContact(id: 2, point: CGPoint(x: 0.5, y: 0.5), timestamp: 2)
        XCTAssertEqual(state.update([a], phase: .began).active.map(\.id), [1])
        XCTAssertEqual(state.update([b], phase: .began).active.map(\.id), [1, 2])
        XCTAssertEqual(state.update([a], phase: .ended).active.map(\.id), [2])
        let released = state.releaseAll()
        XCTAssertTrue(released.active.isEmpty)
        XCTAssertEqual(released.changed.map(\.id), [2])
        XCTAssertEqual(released.phase, .releasedAll)
    }

    @MainActor func testSimulatedReaderAndRedaction() {
        let reader = SimulatedCardReader()
        var states: [CardReaderState] = []
        reader.onStateChange = { states.append($0) }
        reader.beginScanning()
        XCTAssertEqual(states.first, .scanning)
        guard case .found(let card) = states.last else { return XCTFail("Expected a simulated card") }
        XCTAssertEqual(card.redactedDescription, "模拟卡片 · …5678")
        XCTAssertFalse(card.redactedDescription.contains("1234"))
    }
}

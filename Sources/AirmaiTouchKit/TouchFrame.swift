import Foundation
import CoreGraphics

public struct TouchContact: Hashable, Sendable {
    public let id: Int
    public let point: CGPoint
    public let timestamp: TimeInterval

    public init(id: Int, point: CGPoint, timestamp: TimeInterval) {
        self.id = id
        self.point = point
        self.timestamp = timestamp
    }
}

public struct TouchFrame: Sendable {
    public enum Phase: Equatable, Sendable { case began, moved, ended, cancelled, releasedAll }
    public let active: [TouchContact]
    public let changed: [TouchContact]
    public let phase: Phase

    public init(active: [TouchContact], changed: [TouchContact], phase: Phase) {
        self.active = active
        self.changed = changed
        self.phase = phase
    }

    public var activeSensors: Set<TouchSensor> {
        Set(active.compactMap { TouchSensorMesh.sensor(at: $0.point) })
    }
}

/// Platform-neutral state reducer used by UIKit input and tests.
public struct TouchContactState: Sendable {
    private var contacts: [Int: TouchContact] = [:]
    public init() {}

    public mutating func update(_ changed: [TouchContact], phase: TouchFrame.Phase) -> TouchFrame {
        switch phase {
        case .began, .moved:
            for contact in changed { contacts[contact.id] = contact }
        case .ended, .cancelled:
            for contact in changed { contacts.removeValue(forKey: contact.id) }
        case .releasedAll:
            contacts.removeAll(keepingCapacity: true)
        }
        return TouchFrame(active: contacts.values.sorted { $0.id < $1.id }, changed: changed, phase: phase)
    }

    public mutating func releaseAll() -> TouchFrame {
        let previous = contacts.values.sorted { $0.id < $1.id }
        return update(previous, phase: .releasedAll)
    }
}

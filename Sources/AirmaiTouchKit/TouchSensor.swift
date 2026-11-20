import Foundation

/// The chart-facing sensor layout. This is deliberately separate from any
/// controller's 34/35-bit wire format: Simai exposes one semantic C region,
/// while controller firmwares may report their centre electrodes separately.
public struct TouchSensor: Hashable, Identifiable, Sendable, Codable {
    public enum Ring: String, CaseIterable, Sendable, Codable {
        case a = "A"
        case b = "B"
        case c = "C"
        case d = "D"
        case e = "E"
    }

    public let ring: Ring
    public let index: Int

    public init?(ring: Ring, index: Int) {
        guard ring == .c ? index == 1 : (1...8).contains(index) else { return nil }
        self.ring = ring
        self.index = index
    }

    public var id: String { label }
    public var label: String { ring == .c ? "C" : "\(ring.rawValue)\(index)" }

    /// Stable index for the 33 chart-facing regions. It is not a hardware bit.
    public var semanticIndex: Int {
        switch ring {
        case .a: return index - 1
        case .b: return 8 + index - 1
        case .c: return 16
        case .d: return 17 + index - 1
        case .e: return 25 + index - 1
        }
    }

    public static let all: [TouchSensor] = Ring.allCases.flatMap { ring in
        let indices = ring == .c ? [1] : Array(1...8)
        return indices.compactMap { TouchSensor(ring: ring, index: $0) }
    }
}

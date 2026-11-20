import Foundation

public enum CardTechnology: String, Sendable, Codable {
    case feliCa = "FeliCa"
    case miFare = "MIFARE"
    case iso7816 = "ISO 7816"
    case iso15693 = "ISO 15693"
    case simulated = "模拟卡片"
}

public struct CardIdentity: Equatable, Sendable {
    public let technology: CardTechnology
    private let identifier: Data

    public init(technology: CardTechnology, identifier: Data) {
        self.technology = technology
        self.identifier = identifier
    }

    /// Safe for UI and diagnostics. The full card identifier is intentionally
    /// unavailable so callers cannot accidentally persist it.
    public var redactedDescription: String {
        let suffix = identifier.suffix(2).map { String(format: "%02X", $0) }.joined()
        return suffix.isEmpty ? "\(technology.rawValue) · 未提供标识" : "\(technology.rawValue) · …\(suffix)"
    }
}

public enum CardReaderState: Equatable, Sendable {
    case idle
    case unavailable(String)
    case scanning
    case found(CardIdentity)
    case failed(String)
}

@MainActor public protocol CardReader: AnyObject {
    var state: CardReaderState { get }
    var onStateChange: ((CardReaderState) -> Void)? { get set }
    func beginScanning()
    func cancel()
}

@MainActor public final class SimulatedCardReader: CardReader {
    public private(set) var state: CardReaderState = .idle { didSet { onStateChange?(state) } }
    public var onStateChange: ((CardReaderState) -> Void)?
    public init() {}
    public func beginScanning() {
        state = .scanning
        state = .found(CardIdentity(technology: .simulated, identifier: Data([0x12, 0x34, 0x56, 0x78])))
    }
    public func cancel() { state = .idle }
}

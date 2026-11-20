import Foundation

enum GameplayNoteType: String, CaseIterable, Codable, Hashable, Sendable {
    case tap
    case breakNote
    case hold
    case slide
    case touch
    case touchHold
    case unknown
}

enum GameplayJudge: String, CaseIterable, Codable, Hashable, Sendable {
    case criticalPerfect
    case perfect
    case great
    case good
    case miss
    case unknown
}

enum GameplayEventKind: String, CaseIterable, Codable, Hashable, Sendable {
    case noteArrival
    case noteHit
    case holdStart
    case holdEnd
    case holdBreak
    case slideStart
    case slideCheckpoint
    case slideComplete
    case touch
}

enum GameplayPositionRing: String, Codable, Hashable, Sendable {
    case lane
    case a
    case b
    case c
    case d
    case e
    case unknown
}

struct GameplayPosition: Codable, Hashable, Sendable {
    let ring: GameplayPositionRing
    let index: Int
}

/// A game-agnostic event emitted by the chart player. Consumers must not depend
/// on SimaiNoteEvent so replay, diagnostics and external integrations can evolve
/// independently from the gameplay model.
struct GameplayEvent: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    let sourceNoteID: Int?
    let timestamp: TimeInterval
    let emittedAtUptime: TimeInterval
    let kind: GameplayEventKind
    let noteType: GameplayNoteType
    /// The chart's actual note shape when `noteType` is the BREAK flag.
    let baseNoteType: GameplayNoteType?
    let lane: Int?
    let position: GameplayPosition?
    let judge: GameplayJudge?
    let timingOffsetMs: Double?
    let duration: TimeInterval?

    init(
        id: UUID = UUID(),
        sourceNoteID: Int? = nil,
        timestamp: TimeInterval,
        emittedAtUptime: TimeInterval = ProcessInfo.processInfo.systemUptime,
        kind: GameplayEventKind,
        noteType: GameplayNoteType,
        baseNoteType: GameplayNoteType? = nil,
        lane: Int?,
        position: GameplayPosition? = nil,
        judge: GameplayJudge?,
        timingOffsetMs: Double?,
        duration: TimeInterval?
    ) {
        self.id = id
        self.sourceNoteID = sourceNoteID
        self.timestamp = timestamp
        self.emittedAtUptime = emittedAtUptime
        self.kind = kind
        self.noteType = noteType
        self.baseNoteType = baseNoteType
        self.lane = lane
        self.position = position
        self.judge = judge
        self.timingOffsetMs = timingOffsetMs
        self.duration = duration
    }

    var debugLine: String {
        let laneText = lane.map { "Lane \($0)" }
            ?? position.map { "\($0.ring.rawValue.uppercased())\($0.index)" }
            ?? "No Lane"
        let judgeText = judge?.rawValue.uppercased() ?? "ARRIVAL"
        let offsetText = timingOffsetMs.map { String(format: "%+.1fms", $0) } ?? ""
        return String(
            format: "%.3f  %@  %@  %@ %@",
            timestamp,
            laneText,
            noteType.rawValue.uppercased(),
            judgeText,
            offsetText
        ).trimmingCharacters(in: .whitespaces)
    }
}

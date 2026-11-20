// Airmai Editor source: PlaybackSettingsBridge.swift, SHA256 909473194b691480be26e91e481be206d8d53c3536a92c4ee66410b147116fc6
// Extracted from Airmai SimaiChartExperienceView.swift; display labels use Editor localization.
// Regenerate only after reviewing upstream settings changes.
import SwiftUI
enum SimaiChartBackgroundStyle: String, CaseIterable, Identifiable {
    case artwork
    case gradient
    case black

    var id: String { rawValue }

    var title: String {
        switch self {
        case .artwork: return String(localized: "曲绘")
        case .gradient: return String(localized: "渐变")
        case .black: return String(localized: "纯黑")
        }
    }
}

enum SimaiCenterDisplayMode: String, CaseIterable, Identifiable {
    case achievement
    case achievementFrom101
    case combo
    case remaining

    var id: String { rawValue }

    var title: String {
        switch self {
        case .achievement: return String(localized: "达成率")
        case .achievementFrom101: return String(localized: "101% 递减")
        case .combo: return String(localized: "连击")
        case .remaining: return String(localized: "剩余音符")
        }
    }
}

struct SimaiPlaybackSettings: Equatable {
    var noteSpeed = 8.0
    var audioTimingOffset = 0.0
    var visualTimingOffset = 0.0
    var musicVolume = 0.78
    var hitSoundVolume = 0.2
    var hitSoundEnabled = true
    var answerSoundVolume = 0.2
    var answerSoundEnabled = true
    var judgementSoundVolume = 0.2
    var judgementSoundEnabled = true
    var showApproachLine = true
    var showEffects = true
    var rotateSlideStar = true
    var mirror: SimaiMirrorMode = .none
    var backgroundStyle: SimaiChartBackgroundStyle = .artwork
    var backgroundDim = 0.58
    var centerDisplay: SimaiCenterDisplayMode = .achievement

    var approachTime: TimeInterval {
        SimaiNoteMotion.approachTime(speed: noteSpeed)
    }
}


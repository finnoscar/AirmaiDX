// Airmai Editor source: EditorDocument.swift, SHA256 ce5554c99a0abdc2a1da85360ca92ce74100a64bebfc7d3d599ac859ee9eba3d
import Foundation

// Beat values are quarter notes. Offset is the audio time of beat zero, in seconds.
enum NoteKind: String, Codable, CaseIterable, Identifiable {
    case tap = "TAP", hold = "HOLD", slide = "SLIDE", touch = "TOUCH", touchHold = "TOUCH HOLD"
    var id: String { rawValue }
    var symbol: String {
        switch self { case .tap: return "circle"; case .hold: return "capsule"; case .slide: return "star"; case .touch: return "scope"; case .touchHold: return "smallcircle.filled.circle" }
    }
}
enum TouchRing: String, Codable, CaseIterable, Identifiable {
    case lane = "外键", a = "A", b = "B", c = "C", d = "D", e = "E"
    var id: String { rawValue }
    var simai: String { self == .lane ? "" : rawValue }
}
enum SlideShape: String, Codable, CaseIterable, Identifiable {
    case line = "-", arc = "^", clockwise = ">", counterclockwise = "<", left = "p", right = "q", zigLeft = "s", zigRight = "z", center = "v", fan = "w", edgeLeft = "pp", edgeRight = "qq"
    var id: String { rawValue }
    var reflected: Self {
        switch self { case .clockwise: return .counterclockwise; case .counterclockwise: return .clockwise; case .left: return .right; case .right: return .left; case .zigLeft: return .zigRight; case .zigRight: return .zigLeft; case .edgeLeft: return .edgeRight; case .edgeRight: return .edgeLeft; default: return self }
    }
}
struct EditorNote: Codable, Identifiable, Equatable {
    var id = UUID()
    var beat: Double
    var lane: Int
    var kind: NoteKind
    var ring: TouchRing = .lane
    var duration: Double = 1
    var isBreak = false
    var isEX = false
    var slideEnd = 5
    var slideShape: SlideShape = .line
    var slideDelay: Double = 1
    var nativeKind:NoteKind?
    var nativeFlags:Int?
    var nativeHoldHead:Bool?
    var nativePaths:[EditorNativeSlidePath]?
    var sourceToken: String?
    var sourceTime: Double?
    var isTouch: Bool { kind == .touch || kind == .touchHold }
    var location: String { isTouch ? (ring == .c ? "C" : "\(ring == .lane ? "A" : ring.simai)\(lane)") : String(lane) }
}
struct SheetMetadata: Codable, Equatable {
    var title = String(localized: "未命名谱面")
    var artist = ""
    var difficulty = "MASTER"
    var level = "12"
}
struct EditorDocument: Codable, Equatable {
    var version = 1
    var projectName:String?
    var importedMaidata:String?
    var importedDifficultyIndex:Int?
    var rawSimai: String?
    var rawDifficultyIndex: Int?
    var metadata = SheetMetadata()
    var bpm: Double = 120
    var offset: Double = 0
    var tempoChanges:[EditorTempoChange]?
    var notes: [EditorNote] = []
    var audioName: String?
    var coverName: String?
    var audioData: Data?
    var coverData: Data?
    var endBeat: Double { max(32, notes.map { $0.beat + ($0.kind == .slide ? $0.slideDelay : 0) + $0.duration + 4 }.max() ?? 32) }
    func bpm(at beat:Double)->Double {tempoChanges?.last(where:{$0.beat<=beat})?.bpm ?? bpm}
    func seconds(at beat:Double)->Double {
        var time=offset,previous=0.0,rate=bpm
        for change in tempoChanges ?? [] where change.beat<=beat {
            time+=(change.beat-previous)*60/rate;previous=change.beat;rate=change.bpm
        }
        return time+(beat-previous)*60/rate
    }
    func beat(at seconds:Double)->Double {
        var time=offset,previous=0.0,rate=bpm
        for change in tempoChanges ?? [] {
            let next=time+(change.beat-previous)*60/rate
            if seconds<next {return previous+(seconds-time)*rate/60}
            time=next;previous=change.beat;rate=change.bpm
        }
        return previous+(seconds-time)*rate/60
    }
    func relativeTempos(from beat:Double)->[EditorTempoChange]? {
        guard tempoChanges != nil else{return nil}
        return [EditorTempoChange(beat:0,bpm:bpm(at:beat))]+(tempoChanges ?? []).filter{$0.beat>beat}.map{EditorTempoChange(beat:$0.beat-beat,bpm:$0.bpm)}
    }
    func validate() throws {
        guard version == 1 else { throw EditorError.invalid(String(localized: "此文档版本较新，请使用支持的版本打开。")) }
        guard bpm.isFinite, (20...400).contains(bpm), offset.isFinite, abs(offset) <= 600 else { throw EditorError.invalid(String(localized: "BPM 或 Offset 超出支持范围。")) }
        guard notes.count <= 100_000, Set(notes.map(\.id)).count == notes.count else { throw EditorError.invalid(String(localized: "音符数量或标识无效。")) }
        var previousTempo = -1.0
        for t in tempoChanges ?? [] {
            guard t.beat.isFinite,t.beat>=0,t.beat<=100_000,t.beat>previousTempo,t.bpm.isFinite,(1...10000).contains(t.bpm) else {throw EditorError.invalid(String(localized: "变速信息无效。"))}
            previousTempo=t.beat
        }
        for n in notes {
            let minimumDuration:Double=n.kind == .hold || n.kind == .touchHold ? 0 : 1.0/192
            guard n.beat.isFinite, (0...100_000).contains(n.beat), n.duration.isFinite, (minimumDuration...1024).contains(n.duration), n.slideDelay.isFinite, (0...1024).contains(n.slideDelay), (1...8).contains(n.lane), (1...8).contains(n.slideEnd) else { throw EditorError.invalid(String(localized: "谱面包含无效音符。")) }
        }
    }
    static var demo: Self {
        var d = Self(); d.metadata = SheetMetadata(title: String(localized: "新的节拍"), artist: String(localized: "Airmai Editor · 示例"), difficulty: "MASTER", level: "12")
        d.notes = (0..<16).map { EditorNote(beat: Double($0), lane: $0 % 8 + 1, kind: .tap) }
        d.notes[2].isBreak = true; d.notes[6].isEX = true
        d.notes += [EditorNote(beat: 4, lane: 3, kind: .hold, duration: 2), EditorNote(beat: 8, lane: 4, kind: .slide, duration: 2, slideEnd: 5), EditorNote(beat: 12, lane: 1, kind: .touch, ring: .c), EditorNote(beat: 14, lane: 4, kind: .touchHold, ring: .b, duration: 2)]
        return d
    }
}
enum EditorError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case let .invalid(message) = self { return message }; return nil }
}
enum NoteTransform {
    case clockwise, counterclockwise, leftRight, upDown
    func apply(_ note: EditorNote) -> EditorNote {
        var n = note
        func mapped(_ index: Int, shifted: Bool) -> Int {
            let z = index - 1
            switch self {
            case .clockwise: return (z + 1) % 8 + 1
            case .counterclockwise: return (z + 7) % 8 + 1
            case .leftRight: return (shifted ? 7 - z : (8 - z) % 8) + 1
            case .upDown: return (shifted ? [3,2,1,0,7,6,5,4][z] : [4,3,2,1,0,7,6,5][z]) + 1
            }
        }
        if !n.isTouch || n.ring != .c { n.lane = mapped(n.lane, shifted: !n.isTouch || [.lane,.a,.b].contains(n.ring)) }
        if n.kind == .slide {
            if self == .leftRight || self == .upDown,let paths=note.nativePaths {
                n.nativePaths=paths.map {path in
                    var p=path;p.segments=path.segments.map {segment in
                        var s=segment
                        func reflected(_ delta:Int)->Int {(mapped((note.lane-1+delta+8)%8+1,shifted:true)-n.lane+8)%8}
                        s.endOffset=reflected(segment.endOffset);s.viaOffset=segment.viaOffset.map(reflected)
                        s.shape=[">":"<","<":">","p":"q","q":"p","pp":"qq","qq":"pp","s":"z","z":"s"][s.shape] ?? s.shape
                        return s
                    };return p
                }
            }
            n.slideEnd = mapped(n.slideEnd, shifted: true)
            if self == .leftRight || self == .upDown { n.slideShape = n.slideShape.reflected }
        }
        return n
    }
}
struct EditorHistory {
    private(set) var past: [EditorDocument] = []
    private(set) var future: [EditorDocument] = []
    mutating func record(_ document: EditorDocument) { past.append(document); if past.count > 100 { past.removeFirst() }; future.removeAll() }
    mutating func undo(_ current: EditorDocument) -> EditorDocument? { guard let d = past.popLast() else { return nil }; future.append(current); return d }
    mutating func redo(_ current: EditorDocument) -> EditorDocument? { guard let d = future.popLast() else { return nil }; past.append(current); return d }
}
struct NoteClipboard: Codable {
    var notes: [EditorNote]
    func pasted(at beat: Double) -> [EditorNote] {
        let first = notes.map(\.beat).min() ?? 0
        return notes.map { var n = $0; n.id = UUID(); n.sourceToken = nil; n.sourceTime = nil; n.beat = max(0, beat + n.beat - first); return n }
    }
}

struct EditorTempoChange:Codable,Equatable,Sendable {var beat:Double;var bpm:Double}
struct EditorNativeSlideSegment:Codable,Equatable,Sendable {var shape:String;var endOffset:Int;var viaOffset:Int?}
struct EditorNativeSlidePath:Codable,Equatable,Sendable {
    var segments:[EditorNativeSlideSegment]
    var startFraction:Double
    var durationFraction:Double
    var isBreak:Bool
}

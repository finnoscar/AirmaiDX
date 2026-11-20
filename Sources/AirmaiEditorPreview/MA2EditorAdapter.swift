import Foundation
import AirmaiCore

/// MA2 is a separate file format. Translate its record fields into the Editor
/// document and let the Editor's writer, parser and renderer handle the preview.
struct MA2EditorAdapter: Sendable {
    let chart: SimaiChart
    let hiddenHeadIDs: Set<Int>

    init(ma2: MA2Chart, title: String) throws {
        var document = EditorDocument()
        document.metadata.title = title
        document.tempoChanges = ma2.tempos.map { EditorTempoChange(beat: $0.beat, bpm: $0.bpm) }
        if let bpm = ma2.tempos.first?.bpm, (20...400).contains(bpm) { document.bpm = bpm }

        // A connected MA2 segment starts where the preceding segment ended.
        // Branches starting from the same star become paths on one Editor note.
        var chains: [[MA2Chart.Slide]] = []
        var tails: [Anchor: [Int]] = [:]
        for segment in ma2.slides {
            let start = Anchor(beat: segment.beat, lane: segment.lane)
            let end = Anchor(beat: segment.endBeat, lane: segment.endLane)
            let index: Int
            if segment.connected, let previous = tails[start]?.popLast() {
                index = previous
                chains[index].append(segment)
            } else {
                index = chains.count
                chains.append([segment])
            }
            tails[end, default: []].append(index)
        }
        var paths = Dictionary(grouping: chains) {
            Anchor(beat: $0[0].beat, lane: $0[0].lane)
        }
        var unpaired: [MA2Chart.Slide] = []
        var slideTokens: [UUID: String] = [:]
        for note in ma2.notes {
            let key = Anchor(beat: note.beat, lane: note.lane)
            if ["STR", "BST", "XST"].contains(note.kind), let branches = paths.removeValue(forKey: key) {
                let editor = Self.slideNote(branches: branches, isBreak: note.isBreak, isEX: note.isEX)
                document.notes.append(editor)
                slideTokens[editor.id] = Self.slideToken(editor, branches: branches)
            } else {
                document.notes.append(Self.editorNote(note))
            }
        }
        for branches in paths.values {
            let editor = Self.slideNote(branches: branches)
            document.notes.append(editor)
            slideTokens[editor.id] = Self.slideToken(editor, branches: branches)
            unpaired.append(branches[0][0])
        }

        let maidata = try SimaiWriter.write(document) { slideTokens[$0.id] }
        let chart = try SimaiChartParser.parse(maidata: maidata, levelIndex: SimaiWriter.levelIndex(document))
        guard chart.events.count == document.notes.count,
              chart.events.reduce(0, { $0 + $1.slidePaths.reduce(0, { $0 + $1.segments.count }) }) == ma2.slideCount else {
            throw AirmaiError.message("Airmai Editor 无法完整解析这份 MA2 的转换结果。")
        }
        hiddenHeadIDs = Set(chart.events.filter { event in
            event.kind == .slide && unpaired.contains {
                $0.lane + 1 == event.location.index && abs($0.seconds - event.time) < 0.0001
            }
        }.map(\.id))
        SimaiSlidePathGeometry.prepare(chart: chart, mirror: .none)
        self.chart = chart
    }

    private struct Anchor: Hashable {
        let tick: Int
        let lane: Int
        init(beat: Double, lane: Int) {
            tick = Int((beat * 1_000_000).rounded())
            self.lane = lane
        }
    }

    private static func editorNote(_ note: MA2Chart.Note) -> EditorNote {
        let hold = ["HLD", "XHO", "THO"].contains(note.kind) && note.holdBeats > 0
        let touch = !note.touchArea.isEmpty
        let kind: NoteKind = touch ? (hold ? .touchHold : .touch) : (hold ? .hold : .tap)
        var flags: SimaiNoteFlags = []
        if ["STR", "BST", "XST"].contains(note.kind) { flags.insert([.star, .spinningStar]) }
        if note.fireworks { flags.insert(.fireworks) }
        return EditorNote(beat: note.beat, lane: note.lane + 1, kind: kind,
                          ring: TouchRing(rawValue: note.touchArea) ?? .lane,
                          duration: hold ? note.holdBeats : 1,
                          isBreak: note.isBreak, isEX: note.isEX,
                          nativeKind: kind, nativeFlags: flags.rawValue)
    }

    private static func slideNote(branches: [[MA2Chart.Slide]], isBreak: Bool = false, isEX: Bool = false) -> EditorNote {
        let head = branches[0][0]
        let start = branches.map { $0[0].travelBeat }.min()!
        let end = branches.map { $0.last!.endBeat }.max()!
        let span = end - start
        return EditorNote(beat: head.beat, lane: head.lane + 1, kind: .slide,
                          duration: span, isBreak: isBreak, isEX: isEX,
                          slideEnd: branches[0].last!.endLane + 1, slideDelay: start - head.beat)
    }

    private static func slideToken(_ note: EditorNote, branches: [[MA2Chart.Slide]]) -> String {
        let head = note.location + (note.isBreak ? "b" : "") + (note.isEX ? "x" : "")
        let paths = branches.map { chain in
            let delay = SimaiWriter.number(chain[0].travelStart - chain[0].seconds)
            // The shared parser accepts explicit timing after each operator.
            // A single bracket at the end would be consumed by the first one.
            let segments = chain.enumerated().map { index, slide in
                let begin = index == 0 ? slide.travelStart : chain[index - 1].end
                let travel = SimaiWriter.number(slide.end - begin)
                return slideOperator(slide) + "[\(delay)##\(travel)]"
            }.joined()
            return segments + (chain.contains(where: \.isBreak) ? "b" : "")
        }
        return head + paths.joined(separator: "*")
    }

    private static func slideOperator(_ slide: MA2Chart.Slide) -> String {
        let shape: SimaiSlideShape
        var via: Int?
        switch slide.kind {
        case "SCL": shape = .counterclockwise
        case "SCR": shape = .clockwise
        case "SUL": shape = .curveLeft
        case "SUR": shape = .curveRight
        case "SSL": shape = .zigzagLeft
        case "SSR": shape = .zigzagRight
        case "SV_": shape = .centerFold
        case "SXL": shape = .edgeCurveLeft
        case "SXR": shape = .edgeCurveRight
        case "SLL": shape = .edgeFold; via = (slide.lane - 2 + 8) % 8
        case "SLR": shape = .edgeFold; via = (slide.lane + 2) % 8
        case "SF_": shape = .fan
        default: shape = .straight
        }
        let symbol = SimaiWriter.shape(shape.rawValue, startingAt: slide.lane + 1)
        return symbol + (via.map { String($0 + 1) } ?? "") + String(slide.endLane + 1)
    }
}

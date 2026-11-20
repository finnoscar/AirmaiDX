import Foundation

public struct MA2Chart: Sendable {
    public struct Note: Identifiable, Sendable {
        public let id: Int
        public let kind: String
        public let lane: Int
        public let beat: Double
        public let holdBeats: Double
        public let seconds: Double
        public let duration: Double
        public let touchArea: String
        public let isBreak: Bool
        public let isEX: Bool
        public let fireworks: Bool
    }

    public struct Slide: Identifiable, Sendable {
        public let id: Int
        public let kind: String
        public let lane: Int
        public let endLane: Int
        public let beat: Double
        public let travelBeat: Double
        public let endBeat: Double
        public let seconds: Double
        public let travelStart: Double
        public let end: Double
        public let connected: Bool
        public let isBreak: Bool
    }

    public struct Tempo: Sendable {
        public let beat: Double
        public let bpm: Double
    }

    public let notes: [Note]
    public let slides: [Slide]
    public let warnings: [String]
    public let duration: Double
    public let version: String?
    public let declaredNotes: Int?
    public let totalNotes: Int
    public let tempos: [Tempo]
    public var slideCount: Int { slides.count }

    public init(text: String) throws {
        let rows = text.trimmingCharacters(in: CharacterSet(charactersIn: "\u{FEFF}"))
            .split(whereSeparator: \.isNewline).map { $0.split(whereSeparator: \.isWhitespace) }
        func number(_ row: [Substring], _ index: Int) -> Double? {
            guard row.indices.contains(index), let value = Double(row[index]), value.isFinite else { return nil }
            return value
        }
        func int(_ row: [Substring], _ index: Int) -> Int? {
            row.indices.contains(index) ? Int(row[index]) : nil
        }

        let resolutionRow = rows.first { $0.first == "RESOLUTION" }
        let resolution = resolutionRow.map { number($0, 1) ?? 0 } ?? 384
        guard resolution > 0, resolution <= 1_000_000 else { throw AirmaiError.message("MA2 的时间精度无效。") }
        let bpmRow = rows.first { $0.first == "BPM_DEF" }
        let initialBPM = bpmRow.map { number($0, 1) ?? 0 } ?? 120
        guard initialBPM >= 1 else { throw AirmaiError.message("MA2 的 BPM 无效。") }

        func tick(_ row: [Substring]) -> Double? {
            guard let bar = int(row, 1), (0...100_000).contains(bar),
                  let offset = int(row, 2), offset >= 0, Double(offset) < resolution else { return nil }
            return Double(bar) * resolution + Double(offset)
        }
        var invalid = Set<String>()
        var tempoChanges: [Double: Double] = [0: initialBPM]
        for row in rows where row.first == "BPM" {
            guard let absolute = tick(row), let bpm = number(row, 3), bpm >= 1 else {
                invalid.insert("BPM"); continue
            }
            tempoChanges[absolute] = bpm
        }
        var clock: [(tick: Double, bpm: Double, elapsed: Double)] = []
        for point in tempoChanges.sorted(by: { $0.key < $1.key }) {
            let elapsed = clock.last.map { $0.elapsed + (point.key - $0.tick) / resolution * 240 / $0.bpm } ?? 0
            clock.append((point.key, point.value, elapsed))
        }
        tempos = clock.map { Tempo(beat: $0.tick * 4 / resolution, bpm: $0.bpm) }
        func seconds(_ absolute: Double) -> Double {
            var lower = 0
            var upper = clock.count
            while upper - lower > 1 {
                let middle = (lower + upper) / 2
                if clock[middle].tick <= absolute { lower = middle } else { upper = middle }
            }
            let point = clock[lower]
            return point.elapsed + (absolute - point.tick) / resolution * 240 / point.bpm
        }

        let ordinary: Set<String> = ["TAP", "BRK", "XTP", "HLD", "XHO", "STR", "BST", "XST", "TTP", "THO"]
        let slideCodes: Set<String> = ["SI_", "SCL", "SCR", "SUL", "SUR", "SSL", "SSR", "SV_", "SXL", "SXR", "SLL", "SLR", "SF_"]
        var notes: [Note] = []
        var slides: [Slide] = []
        for row in rows {
            guard let code = row.first else { continue }
            let prefix = code.count == 5 ? code.prefix(2) : ""
            let modifier = ["NM", "BR", "EX", "BX", "CN"].contains(prefix) ? prefix : ""
            let kind = String(modifier.isEmpty ? code : code.suffix(3))
            guard ordinary.contains(kind) || slideCodes.contains(kind) else { continue }
            guard let absolute = tick(row), let lane = int(row, 3), (0..<8).contains(lane) else {
                invalid.insert(String(code)); continue
            }
            let start = seconds(absolute)
            if slideCodes.contains(kind) {
                guard let wait = int(row, 4), (0...1_000_000).contains(wait),
                      let travel = int(row, 5), (1...1_000_000).contains(travel),
                      let endLane = int(row, 6), (0..<8).contains(endLane) else {
                    invalid.insert(String(code)); continue
                }
                let travelStart = absolute + Double(wait)
                slides.append(Slide(id: slides.count, kind: kind, lane: lane, endLane: endLane,
                                    beat: absolute * 4 / resolution, travelBeat: travelStart * 4 / resolution,
                                    endBeat: (travelStart + Double(travel)) * 4 / resolution, seconds: start,
                                    travelStart: seconds(travelStart), end: seconds(travelStart + Double(travel)),
                                    connected: modifier == "CN", isBreak: modifier == "BR" || modifier == "BX"))
                continue
            }
            var hold = 0
            if ["HLD", "XHO", "THO"].contains(kind) {
                guard let ticks = int(row, 4), (0...1_000_000).contains(ticks) else {
                    invalid.insert(String(code)); continue
                }
                hold = ticks
            }
            let areaIndex = kind == "THO" ? 5 : 4
            let isTouch = kind == "TTP" || kind == "THO"
            var area = ""
            if isTouch {
                guard row.indices.contains(areaIndex), ["A", "B", "C", "D", "E"].contains(row[areaIndex]) else {
                    invalid.insert(String(code)); continue
                }
                area = String(row[areaIndex])
            }
            notes.append(Note(id: notes.count, kind: kind, lane: lane,
                              beat: absolute * 4 / resolution, holdBeats: Double(hold) * 4 / resolution, seconds: start,
                              duration: seconds(absolute + Double(hold)) - start, touchArea: area,
                              isBreak: modifier == "BR" || modifier == "BX" || ["BRK", "BST"].contains(kind),
                              isEX: modifier == "EX" || modifier == "BX" || ["XTP", "XHO", "XST"].contains(kind),
                              fireworks: isTouch && int(row, areaIndex + 1) == 1))
        }
        let footer = rows.filter { $0.first == "T_NUM_ALL" }
        declaredNotes = footer.count == 1 ? int(footer[0], 1) : nil
        let header = rows.first { $0.first == "VERSION" }
        version = header.flatMap { $0.count >= 3 ? String($0[2]) : nil }
        self.notes = notes.sorted { ($0.beat, $0.id) < ($1.beat, $1.id) }
        self.slides = slides.sorted { ($0.beat, $0.id) < ($1.beat, $1.id) }
        duration = max(1, notes.map { $0.seconds + $0.duration }.max() ?? 0, slides.map(\.end).max() ?? 0) + 2
        // Connected sections belong to the original Slide for scoring totals.
        totalNotes = notes.count + slides.filter { !$0.connected }.count
        var warnings = invalid.sorted().map { L10n.format("无效的记录 %@", $0) }
        if let declaredNotes, declaredNotes != totalNotes {
            warnings.append(L10n.format("文件记录 %lld 个音符，解析到 %lld 个。", declaredNotes, totalNotes))
        }
        self.warnings = warnings
    }

    public func validateForImport() throws {
        guard let version, version.range(of: #"^1\.0[2-5]\.\d{2}$"#, options: .regularExpression) != nil else {
            throw AirmaiError.message("请选择 MA2 1.02 至 1.05 文件。")
        }
        guard let declaredNotes, declaredNotes == totalNotes, totalNotes > 0, totalNotes <= 100_000 else {
            throw AirmaiError.message("谱面音符与 T_NUM_ALL 统计不一致。")
        }
        guard warnings.isEmpty else { throw AirmaiError.message(warnings.joined(separator: "；")) }
    }
}

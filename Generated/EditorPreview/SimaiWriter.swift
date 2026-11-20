// Airmai Editor source: SimaiWriter.swift, SHA256 7c5c63149f38a59c595907c51e505276884b779ad9e9f060b73e244bceb31659
import Foundation

enum SimaiWriter {
    static func number(_ value: Double) -> String { String(format: "%.8f", locale: Locale(identifier: "en_US_POSIX"), value).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression) }
    static func field(_ text: String) -> String { text.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\r", with: " ").replacingOccurrences(of: "&", with: "＆") }
    static func token(_ note:EditorNote,bpm:Double)->String {
        var d=EditorDocument();d.bpm=bpm
        return token(note,in:d)
    }
    static func shape(_ physical:String,startingAt lane:Int)->String {
        let reversed=((lane-1+2)%8)>=4
        if physical==">" {return reversed ? "<" : ">"}
        if physical=="<" {return reversed ? ">" : "<"}
        return physical
    }
    static func token(_ n:EditorNote,in d:EditorDocument)->String {
        let preserved=n.nativeKind==n.kind ? SimaiNoteFlags(rawValue:n.nativeFlags ?? 0) : []
        var flags=(n.isBreak ? "b" : "")+(n.isEX ? "x" : "")
        if preserved.contains(.fireworks) {flags+="f"}
        if preserved.contains(.normalHead) {flags+="@"}
        else if preserved.contains(.spinningStar) {flags+="$$"}
        else if preserved.contains(.star) {flags+="$"}
        if preserved.contains(.fadeInSlide) {flags+="?"} else if preserved.contains(.invalidate) {flags+="!"}
        if preserved.contains(.mine) {flags+="m"}
        switch n.kind {
        case .tap,.touch:return n.location+flags
        case .hold,.touchHold:
            if n.duration==0 {return n.location+flags+"h"}
            if d.tempoChanges == nil {return n.location+flags+"h[4:\(number(n.duration))]"}
            return n.location+flags+"h[#\(number(d.seconds(at:n.beat+n.duration)-d.seconds(at:n.beat)))]"
        case .slide:
            let prefix=n.location+flags+(n.nativeHoldHead == true && n.nativeKind == .slide ? "h" : "")
            if let paths=n.nativePaths,!paths.isEmpty,n.nativeKind == .slide {
                return prefix+paths.enumerated().map {i,path in
                    var start=n.lane
                    let begin=n.beat+n.slideDelay+n.duration*path.startFraction
                    let end=begin+n.duration*path.durationFraction
                    let delay=number(d.seconds(at:begin)-d.seconds(at:n.beat))
                    let seconds=d.seconds(at:end)-d.seconds(at:begin)
                    let chain=path.segments.enumerated().map {j,segment in
                        let end=(n.lane-1+segment.endOffset+8)%8+1
                        let changed=i==0 && j==path.segments.count-1 ? n.slideEnd : end
                        let symbol=shape(segment.shape,startingAt:start);start=changed
                        let route=symbol+(segment.viaOffset.map{String((n.lane-1+$0+8)%8+1)} ?? "")+String(changed)
                        if path.segments.count==1 {return route+"[\(delay)##\(number(seconds))]"}
                        // The shared parser consumes the next bracket after
                        // each operator. A suffix-only bracket would swallow
                        // subsequent segments. Beat ratios also avoid applying
                        // its 50ms *per-segment* seconds clamp to fast chains.
                        let beats=seconds*d.bpm(at:n.beat)/60/Double(path.segments.count)
                        return route+"[\(delay)##4:\(number(beats))]"
                    }.joined()
                    return chain+(path.isBreak ? "b" : "")
                }.joined(separator:"*")
            }
            let begin=n.beat+n.slideDelay,end=begin+n.duration
            return prefix+shape(n.slideShape.rawValue,startingAt:n.lane)+String(n.slideEnd)+"[\(number(d.seconds(at:begin)-d.seconds(at:n.beat)))##\(number(d.seconds(at:end)-d.seconds(at:begin)))]"
        }
    }
    static func write(_ document: EditorDocument, tokenOverride: ((EditorNote) -> String?)? = nil) throws -> String {
        try document.validate()
        if let raw=document.rawSimai {return raw}
        let notes = document.notes.sorted { $0.beat == $1.beat ? $0.id.uuidString < $1.id.uuidString : $0.beat < $1.beat }
        let groups = Dictionary(grouping: notes, by: \.beat)
        let beats = Set(groups.keys).union((document.tempoChanges ?? []).map(\.beat)).sorted()
        var body = "(\(number(document.bpm)))"
        // Airmai clamps subdivisions below 1. Split long rests into <=4 beat
        // cells so notes entered after a long empty section keep their time.
        func rest(_ length:Double)->String {
            var remaining=length,result=""
            while remaining > 0.00000001 {
                let cell=min(4,remaining)
                result += "{\(number(4/cell))},";remaining -= cell
            }
            return result
        }
        if let first = beats.first, first > 0 { body += rest(first) }
        for (i, beat) in beats.enumerated() {
            let next = i + 1 < beats.count ? beats[i + 1] : beat + 1
            let cell=min(4,next-beat)
            if let tempo=document.tempoChanges?.first(where:{abs($0.beat-beat)<1e-9}) {body+="(\(number(tempo.bpm)))"}
            body += "{\(number(4 / cell))}" + (groups[beat] ?? []).map {tokenOverride?($0) ?? token($0,in:document)}.joined(separator:"/") + "," + rest(next-beat-cell) + "\n"
        }
        body += "E"
        let index = ["EASY":1,"BASIC":2,"ADVANCED":3,"EXPERT":4,"MASTER":5,"Re:MASTER":6][document.metadata.difficulty] ?? 5
        if let source=document.importedMaidata,let level=document.importedDifficultyIndex {
            let chartNumber=level+2
            return MaidataFields.replacing(source,fields:["title":field(document.metadata.title),"artist":field(document.metadata.artist),"first_\(chartNumber)":number(document.offset),"lv_\(chartNumber)":field(document.metadata.level),"inote_\(chartNumber)":"\n"+body])
        }
        return "&title=\(field(document.metadata.title))\n&artist=\(field(document.metadata.artist))\n&bpm=\(number(document.bpm))\n&first=\(number(document.offset))\n&lv_\(index)=\(field(document.metadata.level))\n&des_\(index)=Airmai Editor\n&inote_\(index)=\n\(body)\n"
    }
    static func levelIndex(_ document: EditorDocument) -> Int { document.importedDifficultyIndex ?? ["EASY":-1,"BASIC":0,"ADVANCED":1,"EXPERT":2,"MASTER":3,"Re:MASTER":4][document.metadata.difficulty] ?? 3 }
}

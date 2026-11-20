import Foundation

// File-package adapter only. Every note and timing value comes from Airmai's parser.
struct ChartImportOption:Identifiable,Sendable {
    let id:String
    let filename:String
    let difficulty:String
    let level:String
    let document:EditorDocument
    var isVisual:Bool {document.rawSimai == nil}
}

enum ChartFolderImport {
    static func read(_ url:URL) throws -> [ChartImportOption] {
        let fm=FileManager.default
        let isDirectory=(try url.resourceValues(forKeys:[.isDirectoryKey])).isDirectory == true
        let folder=isDirectory ? url : url.deletingLastPathComponent()
        let files=try fm.contentsOfDirectory(at:folder,includingPropertiesForKeys:[.isRegularFileKey,.isSymbolicLinkKey],options:[.skipsHiddenFiles])
            .filter { (try? $0.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey])).map{$0.isRegularFile == true && $0.isSymbolicLink != true} ?? false }
        let texts=isDirectory ? files.filter{["maidata.txt","maidata_dx.txt"].contains($0.lastPathComponent.lowercased())}.sorted{$0.lastPathComponent<$1.lastPathComponent} : [url]
        guard !texts.isEmpty else {throw EditorError.invalid(String(localized: "请选择歌曲文件夹本身，其中应包含 maidata.txt 或 maidata_dx.txt、track.mp3 和可选封面。"))}
        func preferred(_ names:[String])->URL? {names.lazy.compactMap{name in files.first{$0.lastPathComponent.lowercased()==name}}.first}
        let audio=preferred(["track.mp3","music.mp3","track.m4a","music.m4a","track.wav","music.wav","track.aac","track.aiff","track.flac","track.ogg"])
        let cover=preferred(["bg.png","bg.jpg","bg.jpeg","cover.png","cover.jpg","jacket.png","jacket.jpg"])
        let audioData=try audio.map{try boundedData($0,limit:256_000_000,label:String(localized: "音频"))}
        let coverData=try cover.map{try boundedData($0,limit:20_000_000,label:String(localized: "封面"))}
        var options:[ChartImportOption]=[]
        for text in texts {
            let data=try boundedData(text,limit:10_000_000,label:String(localized: "谱面文本"))
            let isUTF16=data.starts(with:[0xff,0xfe]) || data.starts(with:[0xfe,0xff])
            guard let decoded=isUTF16 ? String(data:data,encoding:.utf16) : (String(data:data,encoding:.utf8) ?? String(data:data,encoding:.shiftJIS)) else {throw EditorError.invalid(String(localized: "无法读取 \(text.lastPathComponent) 的文本编码。"))}
            let source=decoded.hasPrefix("\u{feff}") ? String(decoded.dropFirst()) : decoded
            for index in -1...4 {
                guard let chart=try? SimaiChartParser.parse(maidata:source,levelIndex:index) else {continue}
                var d=try document(source:source,index:index,chart:chart)
                d.projectName="\(chart.title) · \(d.metadata.difficulty)\(texts.count>1 ? " · \(text.deletingPathExtension().lastPathComponent)" : "")"
                d.audioName=audio?.lastPathComponent;d.audioData=audioData
                d.coverName=cover?.lastPathComponent;d.coverData=coverData
                options.append(ChartImportOption(id:"\(text.lastPathComponent)-\(index)",filename:text.lastPathComponent,difficulty:d.metadata.difficulty,level:chart.level,document:d))
            }
        }
        guard !options.isEmpty else {throw EditorError.invalid(String(localized: "Airmai 原生解析器没有找到可用的难度。请检查谱面文件。"))}
        return options
    }

    static func boundedData(_ url:URL,limit:Int,label:String) throws -> Data {
        guard let size=try url.resourceValues(forKeys:[.fileSizeKey]).fileSize,size<=limit else {throw EditorError.invalid(String(localized: "\(label)文件过大。"))}
        let data=try Data(contentsOf:url,options:.mappedIfSafe)
        guard data.count<=limit else {throw EditorError.invalid(String(localized: "\(label)文件过大。"))}
        return data
    }

    static func document(source:String,index:Int,chart:SimaiChart) throws -> EditorDocument {
        var d=EditorDocument()
        d.metadata=SheetMetadata(title:chart.title,artist:chart.artist,difficulty:["EASY","BASIC","ADVANCED","EXPERT","MASTER","Re:MASTER"][index+1],level:chart.level)
        let timing=try nativeTiming(source:source,index:index,body:chart.source)
        d.bpm=min(400,max(20,chart.bpm));d.offset=timing.offset;d.tempoChanges=timing.tempos
        for event in chart.events {
            let kind:NoteKind
            switch event.kind {case .tap:kind = .tap;case .hold:kind = .hold;case .slide:kind = .slide;case .touch:kind = .touch;case .touchHold:kind = .touchHold}
            let ring=TouchRing.allCases.first{$0.simai.lowercased()==event.location.ring.rawValue} ?? .lane
            let beat=timing.beatsByTime[event.time] ?? d.beat(at:event.time)
            // Bare h / Ch are valid native zero-duration holds. Preserve their
            // exact duration instead of lengthening them to the editor grid.
            let minimumDuration:Double=kind == .hold || kind == .touchHold ? 0 : 1.0/192
            let duration=event.duration==0 ? minimumDuration : max(minimumDuration,d.beat(at:event.time+event.duration)-d.beat(at:event.time))
            var n=EditorNote(beat:max(0,beat),lane:event.location.index,kind:kind,ring:ring,duration:duration,isBreak:event.flags.contains(.breakNote),isEX:event.flags.contains(.ex))
            n.nativeKind=kind;n.nativeFlags=event.flags.rawValue
            if kind == .slide,let first=event.slidePaths.first {
                let earliest=event.slidePaths.map(\.startTime).min()!,latest=event.slidePaths.map(\.endTime).max()!
                let begin=d.beat(at:earliest),end=d.beat(at:latest)
                n.slideDelay=max(0,begin-beat);n.duration=max(1.0/192,end-begin);n.slideEnd=first.end.index
                n.slideShape=SlideShape(rawValue:first.segments.first!.shape.rawValue) ?? .line
                n.nativeHoldHead=event.duration>0
                n.nativePaths=event.slidePaths.map {path in
                    EditorNativeSlidePath(segments:path.segments.map {segment in
                        EditorNativeSlideSegment(shape:segment.shape.rawValue,endOffset:(segment.end.index-event.location.index+8)%8,viaOffset:segment.via.map{($0.index-event.location.index+8)%8})
                    },startFraction:(d.beat(at:path.startTime)-begin)/n.duration,durationFraction:(d.beat(at:path.endTime)-d.beat(at:path.startTime))/n.duration,isBreak:path.isBreak)
                }
            }
            d.notes.append(n)
        }
        try d.validate()
        let exported=try SimaiChartParser.parse(maidata:SimaiWriter.write(d),levelIndex:index)
        guard equivalent(chart,exported) else {throw EditorError.invalid(String(localized: "此难度的原生往返校验未通过，未改写原文件。请保留该曲包用于兼容性检查。"))}
        d.importedMaidata=source;d.importedDifficultyIndex=index
        return d
    }

    static func editable(_ original:EditorDocument) throws -> EditorDocument {
        guard let source=original.rawSimai else{return original}
        let index=original.rawDifficultyIndex ?? SimaiWriter.levelIndex(original)
        var d=try document(source:source,index:index,chart:SimaiChartParser.parse(maidata:source,levelIndex:index))
        d.projectName=original.projectName;d.audioName=original.audioName;d.audioData=original.audioData;d.coverName=original.coverName;d.coverData=original.coverData
        return d
    }

    // Probe only cell boundaries through Airmai itself. No note, duration or BPM
    // syntax is interpreted here: the native parser supplies all clock values.
    static func nativeTiming(source:String,index:Int,body:String) throws -> (offset:Double,tempos:[EditorTempoChange],beatsByTime:[Double:Double]) {
        let marker="C"+String(repeating:"!",count:37)+"m"
        let cleaned=body.components(separatedBy:"\n").map{String($0.components(separatedBy:"||")[0])}.joined()
        var cells:[String]=[],cell="",depth=0
        for ch in cleaned {
            if ch=="," && depth==0 {cells.append(cell);cell="";continue}
            cell.append(ch)
            if "[({".contains(ch) {depth+=1};if "])}".contains(ch) {depth=max(0,depth-1)}
        }
        cells.append(cell)
        var instrumented=""
        for cell in cells {
            var rest=cell.trimmingCharacters(in:.whitespacesAndNewlines),prefix=""
            while let ch=rest.first,ch=="(" || ch=="{" {
                guard let end=rest.firstIndex(of:ch=="(" ? ")" : "}") else {break}
                prefix+=String(rest[...end]);rest=String(rest[rest.index(after:end)...]).trimmingCharacters(in:.whitespacesAndNewlines)
            }
            if let ch=rest.first,ch=="E" || ch=="e",rest.dropFirst().first?.isNumber != true {break}
            instrumented+=prefix+marker+(rest.isEmpty ? "" : "/"+rest)+"," 
        }
        let probe=MaidataFields.replacing(source,fields:["inote_\(index+2)":instrumented+"E"])
        let ticks=try SimaiChartParser.parse(maidata:probe,levelIndex:index).events.filter{$0.source==marker}
        guard let first=ticks.first else {throw EditorError.invalid(String(localized: "无法读取原生谱面的时间网格。"))}
        var tempos:[EditorTempoChange]=[],beat=0.0,beatsByTime:[Double:Double]=[:]
        for (i,tick) in ticks.enumerated() {
            if i>0 {beat+=(tick.time-ticks[i-1].time)*max(1,ticks[i-1].bpm)/60}
            let rate=max(1,tick.bpm)
            beatsByTime[tick.time]=beat
            if tempos.last?.bpm != rate {tempos.append(EditorTempoChange(beat:beat,bpm:rate))}
        }
        return (first.time,tempos,beatsByTime)
    }

    static func equivalent(_ a:SimaiChart,_ b:SimaiChart)->Bool {
        guard a.events.count==b.events.count else{return false}
        func key(_ e:SimaiNoteEvent)->String {
            let paths=e.slidePaths.map{p in "\(p.isBreak):"+p.segments.map{"\($0.shape.rawValue):\($0.start.index):\($0.end.index):\($0.via?.index ?? 0)"}.joined(separator:",")}.joined(separator:"*")
            return "\(e.kind.rawValue)|\(e.location.ring.rawValue)\(e.location.index)|\(e.flags.rawValue)|\(paths)"
        }
        let left=Dictionary(grouping:a.events,by:key),right=Dictionary(grouping:b.events,by:key)
        guard Set(left.keys)==Set(right.keys) else{return false}
        func ordered(_ values:[SimaiNoteEvent])->[SimaiNoteEvent] {values.sorted{abs($0.time-$1.time)<1e-8 ? $0.duration<$1.duration : $0.time<$1.time}}
        for k in left.keys {
            let x=ordered(left[k]!),y=ordered(right[k]!)
            guard x.count==y.count else{return false}
            for (u,v) in zip(x,y) {
                guard abs(u.time-v.time)<0.00001,abs(u.duration-v.duration)<0.00001 else{return false}
                for (p,q) in zip(u.slidePaths,v.slidePaths) {if abs(p.startTime-q.startTime)>=0.00001 || abs(p.duration-q.duration)>=0.00001 {return false}}
            }
        }
        return true
    }

}

// Preserves every unedited difficulty and unknown metadata field on export.
enum MaidataFields {
    static func entries(_ source:String)->[(key:String,value:String)] {
        let normalized=source.replacingOccurrences(of:"\r\n",with:"\n").replacingOccurrences(of:"\r",with:"\n")
        var result:[(key:String,value:String)]=[]
        for line in normalized.components(separatedBy:"\n") {
            if line.hasPrefix("&"),let equal=line.firstIndex(of:"=") {
                result.append((String(line[line.index(after:line.startIndex)..<equal]).lowercased(),String(line[line.index(after:equal)...])))
            } else if !result.isEmpty {result[result.count-1].value+="\n"+line}
        }
        return result
    }
    static func values(_ source:String)->[String:String] {Dictionary(entries(source).map{($0.key,$0.value)},uniquingKeysWith:{$1})}
    static func replacing(_ source:String,fields:[String:String])->String {
        let pattern="(?m)^&([^=\\r\\n]+)="
        let regex=try! NSRegularExpression(pattern:pattern)
        let ns=source as NSString,matches=regex.matches(in:source,range:NSRange(location:0,length:ns.length))
        var result="",cursor=0,remaining=fields
        for (i,match) in matches.enumerated() {
            let start=match.range.location,end=i+1<matches.count ? matches[i+1].range.location : ns.length
            result+=ns.substring(with:NSRange(location:cursor,length:start-cursor))
            let key=ns.substring(with:match.range(at:1)).lowercased()
            if let replacement=fields[key] {result+="&\(key)=\(replacement)\n";remaining.removeValue(forKey:key)}
            else {result+=ns.substring(with:NSRange(location:start,length:end-start))}
            cursor=end
        }
        if matches.isEmpty {result=source}
        if !result.hasSuffix("\n") {result+="\n"}
        for key in remaining.keys.sorted() {result+="&\(key)=\(remaining[key]!)\n"}
        return result
    }
}

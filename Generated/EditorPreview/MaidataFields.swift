// Airmai Editor source: ChartFolderImport.swift, SHA256 8b34564748c2be18832f0453e6c35a954d8e31e068f8d73827b5f78596b3b40b
import Foundation

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

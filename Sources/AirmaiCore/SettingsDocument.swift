import Foundation

/// A line-preserving editor for INI/TOML scalar settings. Unknown lines, duplicate
/// keys and comments survive. The worker preserves the original file encoding.
public struct SettingsDocument {
    public struct Entry: Identifiable, Hashable {
        public var id: Int { line }
        public var line: Int
        public var section: String
        public var key: String
        public var value: String
        public var commented: Bool
        public var help: String
        public var isBoolean: Bool {
            ["true", "false"].contains(value.lowercased())
            || (["0", "1"].contains(value) && ["enable", "disabled", "dummy", "fullscreen", "use", "freeplay"].contains { key.lowercased().contains($0) })
        }
        public var boolValue: Bool { ["1", "true"].contains(value.lowercased()) }
        public var displayValue: String {
            if value.hasPrefix("\""), value.hasSuffix("\""), value.count > 1 {
                return String(value.dropFirst().dropLast())
            }
            return value
        }
    }
    public struct Section: Identifiable, Hashable {
        public var id: String { name }
        public var name: String
        public var line: Int
        public var commented: Bool
        public var help: String
        public var entries: [Entry]
    }
    public private(set) var lines: [String]
    private var newline: String
    public var isTOML: Bool
    public init(text: String, isTOML: Bool = false) {
        self.isTOML = isTOML
        newline = text.contains("\r\n") ? "\r\n" : "\n"
        lines = text.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
    }
    public var text: String { lines.joined(separator: newline) }
    public var sections: [Section] {
        var sections = [Section(name: "", line: -1, commented: false, help: "", entries: [])]
        var comments: [String] = []
        for (i, raw) in lines.enumerated() {
            let trimmed = raw.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty { comments = []; continue }
            var body = trimmed
            let commented = body.hasPrefix("#") || body.hasPrefix(";")
            if commented { body = String(body.dropFirst()).trimmingCharacters(in: .whitespaces) }
            if body.hasPrefix("["), let end = body.firstIndex(of: "]") {
                let name = String(body[body.index(after: body.startIndex)..<end])
                sections.append(Section(name: name, line: i, commented: commented, help: comments.joined(separator: "\n"), entries: []))
                comments = []; continue
            }
            if let eq = body.firstIndex(of: "="), !body.hasPrefix("#") {
                let key = body[..<eq].trimmingCharacters(in: .whitespaces)
                if !key.isEmpty, key.rangeOfCharacter(from: .whitespaces) == nil {
                    let value = scalarAndComment(String(body[body.index(after: eq)...])).value
                    sections[sections.count-1].entries.append(Entry(line: i, section: sections.last!.name, key: key, value: value, commented: commented, help: comments.joined(separator: "\n")))
                    comments = []; continue
                }
            }
            if commented { comments.append(body.trimmingCharacters(in: CharacterSet(charactersIn: "# "))) }
            else { comments = [] }
        }
        return sections.filter { $0.line >= 0 || !$0.entries.isEmpty }
    }
    private func scalarAndComment(_ text: String) -> (value: String, comment: String) {
        var quote: Character?
        var escaped = false
        for index in text.indices {
            let char = text[index]
            if escaped { escaped = false; continue }
            if quote == "\"" && char == "\\" { escaped = true; continue }
            if let current = quote {
                if char == current { quote = nil }
            } else if char == "\"" || char == "'" {
                quote = char
            } else if char == "#" || (!isTOML && char == ";" && (index == text.startIndex || text[text.index(before: index)].isWhitespace)) {
                let before = String(text[..<index])
                let value = before.trimmingCharacters(in: .whitespaces)
                return (value, String(before.reversed().prefix(while: { $0.isWhitespace }).reversed()) + String(text[index...]))
            }
        }
        return (text.trimmingCharacters(in: .whitespaces), "")
    }
    public mutating func set(_ entry: Entry, value: String, active: Bool = true) {
        guard lines.indices.contains(entry.line), !value.contains("\n"), !value.contains("\r") else { return }
        // A live TOML key below a commented header belongs to the previous
        // table. Refuse that edit until the caller enables the section.
        if isTOML && active && sections.contains(where: { $0.name == entry.section && $0.commented }) { return }
        let raw = lines[entry.line]
        let prefix = String(raw.prefix { $0 == " " || $0 == "\t" })
        let suffix = raw.firstIndex(of: "=").map { scalarAndComment(String(raw[raw.index(after: $0)...])).comment } ?? ""
        lines[entry.line] = prefix + (active ? "" : isTOML ? "#" : ";") + entry.key + " = " + value + suffix
    }
    public mutating func set(section: String, key: String, value: String) {
        guard ![section, key, value].contains(where: { $0.contains("\n") || $0.contains("\r") }) else { return }
        if let found = sections.first(where: { $0.name.caseInsensitiveCompare(section) == .orderedSame }) {
            if isTOML && found.commented { return }
            if let e = found.entries.last(where: { $0.key.caseInsensitiveCompare(key) == .orderedSame && !$0.commented }) {
                set(e, value: value); return
            }
            let next = sections.first { $0.line > found.line }?.line ?? (lines.last == "" ? max(0, lines.count - 1) : lines.count)
            lines.insert(key + " = " + value, at: next); return
        }
        lines.append(contentsOf: ["", "[\(section)]", key + " = " + value])
    }
    public func value(section: String, key: String) -> String {
        sections.first { $0.name.caseInsensitiveCompare(section) == .orderedSame }?
            .entries.last { !$0.commented && $0.key.caseInsensitiveCompare(key) == .orderedSame }?.displayValue ?? ""
    }
    public mutating func setSectionEnabled(_ section: Section, enabled: Bool) {
        guard section.line >= 0, section.name != "General" else { return }
        if section.commented, lines.indices.contains(section.line) {
            lines[section.line] = enabled ? "[\(section.name)]" : "#[\(section.name)]"
            if !enabled { return }
        }
        set(section: section.name, key: "Disabled", value: enabled ? "false" : "true")
    }
}

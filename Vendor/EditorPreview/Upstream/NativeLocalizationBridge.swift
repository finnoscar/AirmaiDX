import Foundation
// Required by Airmai's native parser. Editor localization uses its own bundle.
func airMaiLocalized(_ text: String) -> String {
    // Keep the upstream parser read-only, but make its errors discoverable by
    // Xcode's String Catalog extraction rather than relying on dynamic keys.
    switch text {
    case "落雪没有提供所选难度的谱面": return String(localized: "落雪没有提供所选难度的谱面")
    case "谱面内容为空": return String(localized: "谱面内容为空")
    default: return NSLocalizedString(text, comment: "Airmai native chart framework")
    }
}

// Numeric fields follow the user's region without changing Simai/JSON syntax.
enum EditorNumberText {
    static func editable(_ value: Double, fractionDigits: Int? = nil, locale: Locale = .current) -> String {
        let style = FloatingPointFormatStyle<Double>.number.grouping(.never).locale(locale)
        if let digits = fractionDigits { return value.formatted(style.precision(.fractionLength(digits))) }
        return value.formatted(style.precision(.significantDigits(1...8)))
    }
    static func parse(_ text: String, locale: Locale = .current) -> Double? {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        // Foundation's number parser can accept a numeric prefix such as "137x".
        // Normalize localized decimal digits/signs, then require a whole-number
        // parse. Editable values never contain thousands separators.
        var normalized = text.unicodeScalars.compactMap { scalar -> String? in
            if scalar.properties.generalCategory == .format { return nil }
            if scalar.properties.generalCategory == .decimalNumber,
               let digit = Character(String(scalar)).wholeNumberValue { return String(digit) }
            return String(scalar)
        }.joined()
        if let separator = locale.decimalSeparator { normalized = normalized.replacingOccurrences(of: separator, with: ".") }
        normalized = normalized.replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: "−", with: "-")
        let value = Double(normalized)
        return value.flatMap { $0.isFinite ? $0 : nil }
    }
}

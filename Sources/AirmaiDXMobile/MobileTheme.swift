#if os(iOS)
import SwiftUI

enum MobileTheme {
    static let accent = Color(red: 0.25, green: 0.68, blue: 1)
    static let background = LinearGradient(
        colors: [Color(red: 0.02, green: 0.06, blue: 0.15), Color(red: 0.04, green: 0.16, blue: 0.31)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

struct MobilePanel<Content: View>: View {
    let title: LocalizedStringKey
    let symbol: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(title, systemImage: symbol).font(.headline)
            content
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}
#endif

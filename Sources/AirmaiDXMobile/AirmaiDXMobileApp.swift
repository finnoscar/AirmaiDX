#if os(iOS)
import SwiftUI

@main struct AirmaiDXMobileApp: App {
    var body: some Scene {
        WindowGroup { MobileRootView().tint(MobileTheme.accent) }
    }
}
#endif

import SwiftUI
import SwiftData

@main
struct AqsatiApp: App {
    @StateObject private var store = StoreManager()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
        }
        .modelContainer(for: Commitment.self)
    }
}

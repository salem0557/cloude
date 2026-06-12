import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            DashboardView()
                .tabItem { Label("tab.home", systemImage: "creditcard.fill") }
            SettingsView()
                .tabItem { Label("tab.settings", systemImage: "gearshape.fill") }
        }
        .task {
            await NotificationManager.shared.requestAuthorization()
        }
    }
}

#Preview {
    RootView()
        .environmentObject(StoreManager())
        .modelContainer(for: Commitment.self, inMemory: true)
}

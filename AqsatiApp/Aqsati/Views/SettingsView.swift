import SwiftUI
import SwiftData

struct SettingsView: View {
    @EnvironmentObject private var store: StoreManager
    @Query private var commitments: [Commitment]
    @AppStorage("reminderLeadDays") private var reminderLeadDays = 2

    @State private var showingPaywall = false

    private let leadDayOptions = [1, 2, 3, 7]

    var body: some View {
        NavigationStack {
            Form {
                Section("settings.premium") {
                    if store.isPremium {
                        Label("settings.premiumActive", systemImage: "crown.fill")
                            .foregroundStyle(.green)
                    } else {
                        Button {
                            showingPaywall = true
                        } label: {
                            Label("settings.upgrade", systemImage: "crown.fill")
                        }
                    }
                }

                Section("settings.reminders") {
                    Picker("settings.leadDays", selection: $reminderLeadDays) {
                        ForEach(leadDayOptions, id: \.self) { days in
                            Text(LocalizedStringKey("leadDays.\(days)")).tag(days)
                        }
                    }
                    .onChange(of: reminderLeadDays) {
                        NotificationManager.shared.rescheduleAll(
                            commitments.filter { !$0.isCompleted },
                            leadDays: reminderLeadDays
                        )
                    }
                }

                Section("settings.about") {
                    HStack {
                        Text("settings.version")
                        Spacer()
                        Text(appVersion)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("settings.title")
            .sheet(isPresented: $showingPaywall) {
                PaywallView()
            }
        }
    }

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
    }
}

#Preview {
    SettingsView()
        .environmentObject(StoreManager())
        .modelContainer(for: Commitment.self, inMemory: true)
}

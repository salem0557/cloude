import SwiftUI
import SwiftData

struct DashboardView: View {
    @Environment(\.modelContext) private var context
    @EnvironmentObject private var store: StoreManager
    @Query(sort: \Commitment.nextDueDate) private var commitments: [Commitment]
    @AppStorage("reminderLeadDays") private var reminderLeadDays = 2

    @State private var showingAdd = false
    @State private var showingPaywall = false

    private var active: [Commitment] { commitments.filter { !$0.isCompleted } }
    private var completed: [Commitment] { commitments.filter(\.isCompleted) }

    private var monthlyTotal: Decimal {
        active.reduce(Decimal.zero) { $0 + $1.monthlyEquivalent }
    }

    private var remainingDebt: Decimal {
        active.compactMap(\.remainingAmount).reduce(Decimal.zero, +)
    }

    var body: some View {
        NavigationStack {
            Group {
                if commitments.isEmpty {
                    emptyState
                } else {
                    commitmentList
                }
            }
            .navigationTitle("app.name")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        addTapped()
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("add.title")
                }
            }
            .sheet(isPresented: $showingAdd) {
                AddCommitmentView()
            }
            .sheet(isPresented: $showingPaywall) {
                PaywallView(showsLimitNotice: true)
            }
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("empty.title", systemImage: "creditcard")
        } description: {
            Text("empty.message")
        } actions: {
            Button("empty.addButton") { addTapped() }
                .buttonStyle(.borderedProminent)
        }
    }

    private var commitmentList: some View {
        List {
            Section {
                summaryCard
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
            }

            if !active.isEmpty {
                Section("section.active") {
                    ForEach(active) { commitment in
                        NavigationLink {
                            CommitmentDetailView(commitment: commitment)
                        } label: {
                            CommitmentRowView(commitment: commitment)
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                markPaid(commitment)
                            } label: {
                                Label("action.markPaid", systemImage: "checkmark.circle.fill")
                            }
                            .tint(.green)
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                delete(commitment)
                            } label: {
                                Label("action.delete", systemImage: "trash")
                            }
                        }
                    }
                }
            }

            if !completed.isEmpty {
                Section("section.completed") {
                    ForEach(completed) { commitment in
                        CommitmentRowView(commitment: commitment)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    delete(commitment)
                                } label: {
                                    Label("action.delete", systemImage: "trash")
                                }
                            }
                    }
                }
            }
        }
    }

    private var summaryCard: some View {
        VStack(spacing: 12) {
            VStack(spacing: 4) {
                Text("summary.monthlyTotal")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text(monthlyTotal.sarFormatted)
                    .font(.system(.largeTitle, design: .rounded, weight: .bold))
                    .foregroundStyle(Color.accentColor)
            }
            if remainingDebt > 0 {
                HStack {
                    Text("summary.remainingDebt")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(remainingDebt.sarFormatted)
                        .font(.footnote.weight(.semibold))
                }
                .padding(.horizontal)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 20)
        .background(Color.accentColor.opacity(0.1), in: RoundedRectangle(cornerRadius: 16))
    }

    private func addTapped() {
        if store.isPremium || active.count < FreeTier.maxActiveCommitments {
            showingAdd = true
        } else {
            showingPaywall = true
        }
    }

    private func markPaid(_ commitment: Commitment) {
        withAnimation {
            commitment.registerPayment()
        }
        NotificationManager.shared.scheduleReminder(for: commitment, leadDays: reminderLeadDays)
    }

    private func delete(_ commitment: Commitment) {
        NotificationManager.shared.cancelReminder(for: commitment)
        withAnimation {
            context.delete(commitment)
        }
    }
}

#Preview {
    DashboardView()
        .environmentObject(StoreManager())
        .modelContainer(for: Commitment.self, inMemory: true)
}

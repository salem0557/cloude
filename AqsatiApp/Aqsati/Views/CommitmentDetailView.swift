import SwiftUI
import SwiftData

struct CommitmentDetailView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @AppStorage("reminderLeadDays") private var reminderLeadDays = 2

    @Bindable var commitment: Commitment
    @State private var showingDeleteConfirm = false

    var body: some View {
        List {
            Section {
                row(titleKey: "add.kind") {
                    Text(LocalizedStringKey(commitment.kind.titleKey))
                }
                if !commitment.provider.isEmpty {
                    row(titleKey: "add.provider") {
                        Text(commitment.provider)
                    }
                }
                row(titleKey: "detail.amountPerPayment") {
                    Text(commitment.amount.sarFormatted)
                }
                row(titleKey: "add.frequency") {
                    Text(LocalizedStringKey(commitment.frequency.titleKey))
                }
            }

            Section {
                if commitment.isCompleted {
                    Label("detail.completed", systemImage: "checkmark.seal.fill")
                        .foregroundStyle(.green)
                } else {
                    row(titleKey: "detail.nextDue") {
                        Text(commitment.nextDueDate, format: .dateTime.day().month().year())
                            .foregroundStyle(commitment.isOverdue ? .red : .secondary)
                    }
                    if commitment.kind == .installment {
                        row(titleKey: "detail.progress") {
                            Text(String(
                                format: NSLocalizedString("row.progress", comment: ""),
                                commitment.paidPayments,
                                commitment.totalPayments
                            ))
                        }
                        if let remaining = commitment.remainingAmount {
                            row(titleKey: "detail.remaining") {
                                Text(remaining.sarFormatted)
                            }
                        }
                    }
                    Toggle("add.reminder", isOn: $commitment.reminderEnabled)
                        .onChange(of: commitment.reminderEnabled) {
                            NotificationManager.shared.scheduleReminder(
                                for: commitment, leadDays: reminderLeadDays
                            )
                        }
                }
            }

            if !commitment.isCompleted {
                Section {
                    Button {
                        markPaid()
                    } label: {
                        Label("detail.markPaid", systemImage: "checkmark.circle.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }
            }

            Section {
                Button(role: .destructive) {
                    showingDeleteConfirm = true
                } label: {
                    Label("action.delete", systemImage: "trash")
                        .frame(maxWidth: .infinity)
                }
            }
        }
        .navigationTitle(commitment.name)
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("detail.deleteConfirm", isPresented: $showingDeleteConfirm, titleVisibility: .visible) {
            Button("action.delete", role: .destructive) { delete() }
        }
    }

    private func row(titleKey: String, @ViewBuilder value: () -> some View) -> some View {
        HStack {
            Text(LocalizedStringKey(titleKey))
            Spacer()
            value()
                .foregroundStyle(.secondary)
        }
    }

    private func markPaid() {
        withAnimation {
            commitment.registerPayment()
        }
        NotificationManager.shared.scheduleReminder(for: commitment, leadDays: reminderLeadDays)
    }

    private func delete() {
        NotificationManager.shared.cancelReminder(for: commitment)
        context.delete(commitment)
        dismiss()
    }
}

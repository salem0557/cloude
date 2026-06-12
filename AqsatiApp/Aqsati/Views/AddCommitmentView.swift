import SwiftUI
import SwiftData

struct AddCommitmentView: View {
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss
    @AppStorage("reminderLeadDays") private var reminderLeadDays = 2

    @State private var name = ""
    @State private var provider = ""
    @State private var kind: CommitmentKind = .installment
    @State private var frequency: PaymentFrequency = .monthly
    @State private var amount: Decimal = 0
    @State private var nextDueDate = Date.now
    @State private var totalPayments = 4
    @State private var alreadyPaid = 0
    @State private var reminderEnabled = true

    private let providerSuggestionKeys = [
        "provider.tabby", "provider.tamara", "provider.bank", "provider.store"
    ]

    private var isValid: Bool {
        let trimmedName = name.trimmingCharacters(in: .whitespaces)
        guard !trimmedName.isEmpty, amount > 0 else { return false }
        if kind == .installment {
            return totalPayments >= 1 && alreadyPaid < totalPayments
        }
        return true
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("add.namePlaceholder", text: $name)

                    Picker("add.kind", selection: $kind) {
                        ForEach(CommitmentKind.allCases) { kind in
                            Text(LocalizedStringKey(kind.titleKey)).tag(kind)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("add.provider") {
                    TextField("add.providerPlaceholder", text: $provider)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(providerSuggestionKeys, id: \.self) { key in
                                Button {
                                    provider = NSLocalizedString(key, comment: "")
                                } label: {
                                    Text(LocalizedStringKey(key))
                                        .font(.footnote)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 6)
                                        .background(Color.accentColor.opacity(0.12), in: Capsule())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }

                Section("add.payment") {
                    HStack {
                        Text("add.amount")
                        Spacer()
                        TextField("0", value: $amount, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 140)
                        Text(verbatim: "SAR")
                            .foregroundStyle(.secondary)
                    }

                    Picker("add.frequency", selection: $frequency) {
                        ForEach(PaymentFrequency.allCases) { frequency in
                            Text(LocalizedStringKey(frequency.titleKey)).tag(frequency)
                        }
                    }

                    DatePicker("add.nextDue", selection: $nextDueDate, displayedComponents: .date)
                }

                if kind == .installment {
                    Section("add.installmentDetails") {
                        Stepper(value: $totalPayments, in: 1...120) {
                            HStack {
                                Text("add.totalPayments")
                                Spacer()
                                Text("\(totalPayments)")
                                    .foregroundStyle(.secondary)
                            }
                        }
                        Stepper(value: $alreadyPaid, in: 0...max(totalPayments - 1, 0)) {
                            HStack {
                                Text("add.paidPayments")
                                Spacer()
                                Text("\(alreadyPaid)")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                Section {
                    Toggle("add.reminder", isOn: $reminderEnabled)
                }
            }
            .navigationTitle("add.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("add.cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("add.save") { save() }
                        .disabled(!isValid)
                }
            }
        }
    }

    private func save() {
        let commitment = Commitment(
            name: name.trimmingCharacters(in: .whitespaces),
            provider: provider.trimmingCharacters(in: .whitespaces),
            kind: kind,
            frequency: frequency,
            amount: amount,
            nextDueDate: nextDueDate,
            totalPayments: kind == .installment ? totalPayments : 0,
            paidPayments: kind == .installment ? alreadyPaid : 0,
            reminderEnabled: reminderEnabled
        )
        context.insert(commitment)
        NotificationManager.shared.scheduleReminder(for: commitment, leadDays: reminderLeadDays)
        dismiss()
    }
}

#Preview {
    AddCommitmentView()
        .modelContainer(for: Commitment.self, inMemory: true)
}

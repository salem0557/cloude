import Foundation
import SwiftData

enum CommitmentKind: String, Codable, CaseIterable, Identifiable {
    case installment
    case subscription

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .installment: "kind.installment"
        case .subscription: "kind.subscription"
        }
    }
}

enum PaymentFrequency: String, Codable, CaseIterable, Identifiable {
    case weekly
    case monthly
    case quarterly
    case yearly

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .weekly: "frequency.weekly"
        case .monthly: "frequency.monthly"
        case .quarterly: "frequency.quarterly"
        case .yearly: "frequency.yearly"
        }
    }

    func nextDate(after date: Date) -> Date {
        let calendar = Calendar.current
        switch self {
        case .weekly:
            return calendar.date(byAdding: .weekOfYear, value: 1, to: date) ?? date
        case .monthly:
            return calendar.date(byAdding: .month, value: 1, to: date) ?? date
        case .quarterly:
            return calendar.date(byAdding: .month, value: 3, to: date) ?? date
        case .yearly:
            return calendar.date(byAdding: .year, value: 1, to: date) ?? date
        }
    }

    func monthlyEquivalent(of amount: Decimal) -> Decimal {
        switch self {
        case .weekly: amount * Decimal(52) / Decimal(12)
        case .monthly: amount
        case .quarterly: amount / Decimal(3)
        case .yearly: amount / Decimal(12)
        }
    }
}

@Model
final class Commitment {
    var id: UUID
    var name: String
    var provider: String
    var kindRaw: String
    var frequencyRaw: String
    var amount: Decimal
    var nextDueDate: Date
    /// Total number of payments for installments; 0 means open-ended (subscription).
    var totalPayments: Int
    var paidPayments: Int
    var reminderEnabled: Bool
    var createdAt: Date
    var completedAt: Date?

    init(
        name: String,
        provider: String,
        kind: CommitmentKind,
        frequency: PaymentFrequency,
        amount: Decimal,
        nextDueDate: Date,
        totalPayments: Int = 0,
        paidPayments: Int = 0,
        reminderEnabled: Bool = true
    ) {
        self.id = UUID()
        self.name = name
        self.provider = provider
        self.kindRaw = kind.rawValue
        self.frequencyRaw = frequency.rawValue
        self.amount = amount
        self.nextDueDate = nextDueDate
        self.totalPayments = totalPayments
        self.paidPayments = paidPayments
        self.reminderEnabled = reminderEnabled
        self.createdAt = .now
        self.completedAt = nil
    }

    var kind: CommitmentKind {
        get { CommitmentKind(rawValue: kindRaw) ?? .installment }
        set { kindRaw = newValue.rawValue }
    }

    var frequency: PaymentFrequency {
        get { PaymentFrequency(rawValue: frequencyRaw) ?? .monthly }
        set { frequencyRaw = newValue.rawValue }
    }

    var isCompleted: Bool { completedAt != nil }

    var isOverdue: Bool {
        !isCompleted && nextDueDate < Calendar.current.startOfDay(for: .now)
    }

    /// Remaining payment count; nil for open-ended subscriptions.
    var remainingPayments: Int? {
        kind == .installment ? max(totalPayments - paidPayments, 0) : nil
    }

    /// Remaining money owed; nil for open-ended subscriptions.
    var remainingAmount: Decimal? {
        remainingPayments.map { amount * Decimal($0) }
    }

    var monthlyEquivalent: Decimal {
        frequency.monthlyEquivalent(of: amount)
    }

    func registerPayment() {
        guard !isCompleted else { return }
        paidPayments += 1
        if kind == .installment, paidPayments >= totalPayments {
            completedAt = .now
        } else {
            nextDueDate = frequency.nextDate(after: nextDueDate)
        }
    }
}

enum FreeTier {
    static let maxActiveCommitments = 5
}

extension Decimal {
    var sarFormatted: String {
        formatted(.currency(code: "SAR").precision(.fractionLength(0...2)))
    }
}

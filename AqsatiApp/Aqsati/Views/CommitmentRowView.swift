import SwiftUI

struct CommitmentRowView: View {
    let commitment: Commitment

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(commitment.name)
                    .font(.headline)
                if !commitment.provider.isEmpty {
                    Text(commitment.provider)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if commitment.kind == .installment, commitment.totalPayments > 0 {
                    progressLabel
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                Text(commitment.amount.sarFormatted)
                    .font(.headline)
                if commitment.isCompleted {
                    Label("detail.completed", systemImage: "checkmark.seal.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                } else if commitment.isOverdue {
                    Text("row.overdue")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.red)
                } else {
                    Text(commitment.nextDueDate, format: .dateTime.day().month())
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var progressLabel: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(String(
                format: NSLocalizedString("row.progress", comment: ""),
                commitment.paidPayments,
                commitment.totalPayments
            ))
            .font(.caption2)
            .foregroundStyle(.secondary)

            ProgressView(
                value: Double(commitment.paidPayments),
                total: Double(max(commitment.totalPayments, 1))
            )
            .frame(maxWidth: 120)
        }
    }
}

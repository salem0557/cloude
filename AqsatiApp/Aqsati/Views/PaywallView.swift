import SwiftUI
import StoreKit

struct PaywallView: View {
    @EnvironmentObject private var store: StoreManager
    @Environment(\.dismiss) private var dismiss

    var showsLimitNotice = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer(minLength: 0)

                Image(systemName: "crown.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(.yellow)

                VStack(spacing: 8) {
                    Text("paywall.title")
                        .font(.title.bold())
                    Text("paywall.subtitle")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                if showsLimitNotice {
                    Text("paywall.limitMessage")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.orange)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }

                VStack(alignment: .leading, spacing: 12) {
                    feature("paywall.feature1", icon: "infinity")
                    feature("paywall.feature2", icon: "bell.badge.fill")
                    feature("paywall.feature3", icon: "heart.fill")
                }
                .padding(.horizontal, 32)

                Spacer(minLength: 0)

                if store.products.isEmpty {
                    Text("paywall.unavailable")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                } else {
                    VStack(spacing: 12) {
                        ForEach(store.products, id: \.id) { product in
                            Button {
                                Task {
                                    await store.purchase(product)
                                    if store.isPremium { dismiss() }
                                }
                            } label: {
                                VStack(spacing: 2) {
                                    Text(product.displayName)
                                        .font(.headline)
                                    Text(product.displayPrice)
                                        .font(.subheadline)
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 6)
                            }
                            .buttonStyle(.borderedProminent)
                        }
                    }
                    .padding(.horizontal)
                }

                Button("paywall.restore") {
                    Task { await store.restorePurchases() }
                }
                .font(.footnote)
                .padding(.bottom)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func feature(_ titleKey: LocalizedStringKey, icon: String) -> some View {
        Label {
            Text(titleKey)
        } icon: {
            Image(systemName: icon)
                .foregroundStyle(Color.accentColor)
        }
    }
}

#Preview {
    PaywallView(showsLimitNotice: true)
        .environmentObject(StoreManager())
}

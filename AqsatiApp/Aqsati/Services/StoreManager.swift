import Foundation
import StoreKit

/// StoreKit 2 manager for the premium subscription.
/// Product IDs must match the subscriptions created in App Store Connect.
@MainActor
final class StoreManager: ObservableObject {
    static let monthlyID = "aqsati.premium.monthly"
    static let yearlyID = "aqsati.premium.yearly"
    static let allProductIDs: Set<String> = [monthlyID, yearlyID]

    @Published private(set) var isPremium = false
    @Published private(set) var products: [Product] = []

    private var updatesTask: Task<Void, Never>?

    init() {
        updatesTask = Task { [weak self] in
            for await result in Transaction.updates {
                if case .verified(let transaction) = result {
                    await transaction.finish()
                    await self?.refreshEntitlements()
                }
            }
        }
        Task {
            await loadProducts()
            await refreshEntitlements()
        }
    }

    deinit {
        updatesTask?.cancel()
    }

    func loadProducts() async {
        do {
            products = try await Product.products(for: Self.allProductIDs)
                .sorted { $0.price < $1.price }
        } catch {
            products = []
        }
    }

    func purchase(_ product: Product) async {
        guard let result = try? await product.purchase() else { return }
        if case .success(let verification) = result,
           case .verified(let transaction) = verification {
            await transaction.finish()
            await refreshEntitlements()
        }
    }

    func restorePurchases() async {
        try? await AppStore.sync()
        await refreshEntitlements()
    }

    func refreshEntitlements() async {
        var premium = false
        for await result in Transaction.currentEntitlements {
            if case .verified(let transaction) = result,
               Self.allProductIDs.contains(transaction.productID) {
                premium = true
            }
        }
        isPremium = premium
    }
}

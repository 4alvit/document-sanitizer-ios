import Foundation
import StoreKit

/// The only adapter that turns Apple's verification results into entitlement
/// evidence. The store consumes this interface so ordering can be tested without
/// an App Store account or a synthetic StoreKit service.
@MainActor
protocol StoreKitSource: AnyObject {
    func currentEntitlements() -> StoreTransactionIterator
    func updates() -> StoreTransactionIterator
    func products(for identifiers: [String]) async throws -> [StoreProduct]
    func purchase(_ product: StoreProduct) async throws -> StorePurchaseResult
    func sync() async throws
    func finish(_ transaction: StoreTransaction) async
}

/// Demand-driven erasure: advancing a store iterator advances exactly one
/// underlying iterator. There is no buffering task that changes event ordering.
struct StoreTransactionIterator {
    let next: @MainActor () async -> StoreVerification?
}

struct StoreTransaction {
    let id: UInt64
    let originalID: UInt64
    let environment: String
    let productID: String
    let productType: Product.ProductType
    let purchaseDate: Date
    let signedDate: Date
    let revocationDate: Date?
    let isUpgraded: Bool
    let native: Transaction?

    init(id: UInt64, originalID: UInt64? = nil, productID: String,
         environment: String = "controlled", productType: Product.ProductType = .nonConsumable,
         purchaseDate: Date, signedDate: Date, revocationDate: Date? = nil,
         isUpgraded: Bool = false, native: Transaction? = nil) {
        self.id = id
        self.originalID = originalID ?? id
        self.environment = environment
        self.productID = productID
        self.productType = productType
        self.purchaseDate = purchaseDate
        self.signedDate = signedDate
        self.revocationDate = revocationDate
        self.isUpgraded = isUpgraded
        self.native = native
    }

    init(_ transaction: Transaction) {
        self.init(id: transaction.id, originalID: transaction.originalID,
                  productID: transaction.productID, environment: transaction.environment.rawValue, productType: transaction.productType,
                  purchaseDate: transaction.purchaseDate, signedDate: transaction.signedDate,
                  revocationDate: transaction.revocationDate, isUpgraded: transaction.isUpgraded,
                  native: transaction)
    }
}

enum StoreVerification {
    case verified(StoreTransaction)
    case unverified(StoreTransaction)

    init(_ result: VerificationResult<Transaction>) {
        switch result {
        case .verified(let transaction): self = .verified(StoreTransaction(transaction))
        case .unverified(let transaction, _): self = .unverified(StoreTransaction(transaction))
        }
    }
}

struct StoreProduct {
    let id: String
    let type: Product.ProductType
    let displayPrice: String
    let native: Product?

    init(id: String, type: Product.ProductType = .nonConsumable,
         displayPrice: String, native: Product? = nil) {
        self.id = id
        self.type = type
        self.displayPrice = displayPrice
        self.native = native
    }
}

enum StorePurchaseResult {
    case success(StoreVerification)
    case pending
    case userCancelled
    case unknown
}

@MainActor
final class AppleStoreKitSource: StoreKitSource {
    func currentEntitlements() -> StoreTransactionIterator {
        var iterator = Transaction.currentEntitlements.makeAsyncIterator()
        return StoreTransactionIterator {
            guard let result = await iterator.next() else { return nil }
            return StoreVerification(result)
        }
    }

    func updates() -> StoreTransactionIterator {
        var iterator = Transaction.updates.makeAsyncIterator()
        return StoreTransactionIterator {
            guard let result = await iterator.next() else { return nil }
            return StoreVerification(result)
        }
    }

    func products(for identifiers: [String]) async throws -> [StoreProduct] {
        try await Product.products(for: identifiers).map {
            StoreProduct(id: $0.id, type: $0.type, displayPrice: $0.displayPrice, native: $0)
        }
    }

    func purchase(_ product: StoreProduct) async throws -> StorePurchaseResult {
        guard let native = product.native else { throw StoreKitError.notAvailableInStorefront }
        switch try await native.purchase() {
        case .success(let result): return .success(StoreVerification(result))
        case .pending: return .pending
        case .userCancelled: return .userCancelled
        @unknown default: return .unknown
        }
    }

    func sync() async throws {
        try await AppStore.sync()
    }

    func finish(_ transaction: StoreTransaction) async {
        await transaction.native?.finish()
    }
}

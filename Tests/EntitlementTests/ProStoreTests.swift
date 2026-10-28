import StoreKit
import StoreKitTest
import XCTest
@testable import CleanSend

/// Run serially in a hosted iOS test target. These exercise Apple's local
/// StoreKit service, not a fake entitlement backend or production App Store.
@MainActor
final class ProStoreTests: XCTestCase {
    func testPurchaseAndNewStoreRestoreFromVerifiedHistory() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        let store = ProStore()
        await store.load()
        XCTAssertFalse(store.isPro)
        let products = try await Product.products(for: [ProStore.productID])
        XCTAssertEqual(store.displayPrice, try XCTUnwrap(products.first).displayPrice)

        await store.purchase()
        XCTAssertTrue(store.isPro)
        try await waitForLocalEntitlement(present: true)
        XCTAssertFalse(store.isBusy)

        let relaunched = ProStore()
        await relaunched.load()
        XCTAssertTrue(relaunched.isPro, "A finished non-consumable must survive a new store instance.")
        await relaunched.restore()
        XCTAssertTrue(relaunched.isPro)
        XCTAssertEqual(relaunched.message, "Pro purchase restored.")
    }

    func testRefundRevokesThroughListenerAndOnNextLaunch() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        let store = ProStore()
        await store.load()
        await store.purchase()
        XCTAssertTrue(store.isPro)
        let transaction = try XCTUnwrap(session.allTransactions().first)
        try session.refundTransaction(identifier: transaction.identifier)
        try await eventually { !store.isPro }

        let relaunched = ProStore()
        await relaunched.load()
        XCTAssertFalse(relaunched.isPro)
    }

    func testUserCancellationNeverUnlocksPro() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        let store = ProStore()
        await store.load()
        try await session.setSimulatedError(.generic(.userCancelled), forAPI: .purchase)
        await store.purchase()
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertEqual(store.message, "Purchase cancelled.")
    }

    func testPendingPurchaseUnlocksOnlyAfterApproval() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        session.askToBuyEnabled = true
        let store = ProStore()
        await store.load()
        await store.purchase()
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertTrue(store.message?.contains("awaiting approval") == true)
        let pending = try XCTUnwrap(session.allTransactions().first(where: \.pendingAskToBuyConfirmation))
        try await observePendingBeforeApproval(store, session: session)
        try session.approveAskToBuyTransaction(identifier: pending.identifier)
        try await eventually { store.isPro }
    }

    func testUnverifiedTransactionNeverUnlocksPro() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        let store = ProStore()
        await store.load()
        try await session.setSimulatedError(.verification(.invalidSignature), forAPI: .verification)
        await store.purchase()
        XCTAssertFalse(store.isPro)
        XCTAssertTrue(store.message?.contains("verified") == true)
        await store.load()
        XCTAssertFalse(store.isPro)
    }

    func testCachedEntitlementSurvivesProductNetworkFailure() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        _ = try await session.buyProduct(identifier: ProStore.productID)
        try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .loadProducts)
        let store = ProStore()
        await store.load()
        XCTAssertTrue(store.isPro, "Product availability must not control an existing entitlement.")
        XCTAssertNil(store.displayPrice)
        XCTAssertFalse(store.isBusy)
    }

    func testFailedRestoreKeepsVerifiedEntitlement() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        _ = try await session.buyProduct(identifier: ProStore.productID)
        let store = ProStore()
        await store.load()
        XCTAssertTrue(store.isPro)
        try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .appStoreSync)
        await store.restore()
        XCTAssertTrue(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertTrue(store.message?.contains("could not reach") == true)
    }

    func testRestoreWithoutPurchaseDoesNotUnlockPro() async throws {
        let session = try await makeSession()
        defer { clean(session) }
        let store = ProStore()
        await store.restore()
        XCTAssertFalse(store.isPro)
        XCTAssertTrue(store.message?.contains("No active Pro purchase") == true)
    }

    /// Observe the existing production listener and native entitlement stream
    /// while the synthetic transaction remains unapproved. This is evidence for
    /// this finite window, not a guarantee about every possible future delivery.
    private func observePendingBeforeApproval(_ store: ProStore, session: SKTestSession) async throws {
        let clock = ContinuousClock()
        let started = clock.now
        let deadline = started.advanced(by: .seconds(10))
        var observations: [[String: String]] = []
        defer {
            if let data = try? JSONSerialization.data(withJSONObject: observations, options: [.sortedKeys]) {
                let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
                attachment.name = "native-pending-before-approval"
                attachment.lifetime = .keepAlways
                add(attachment)
            }
        }
        while clock.now < deadline {
            var active = 0
            var outsideXcode = false
            for await result in Transaction.currentEntitlements {
                guard case .verified(let value) = result,
                      value.productID == ProStore.productID else { continue }
                outsideXcode = outsideXcode || value.environment != .xcode
                if value.revocationDate == nil && value.productType == .nonConsumable { active += 1 }
            }
            let ledger = session.allTransactions()
            let pending = ledger.filter(\.pendingAskToBuyConfirmation).count
            let elapsed = started.duration(to: clock.now).components
            observations.append([
                "elapsedSeconds": String(elapsed.seconds),
                "matchingActiveVerifiedEntitlements": String(active),
                "outsideXcodeEnvironment": String(outsideXcode),
                "proAccess": String(store.isPro),
                "syntheticLedgerCount": String(ledger.count),
                "syntheticPendingCount": String(pending)
            ])
            guard observations.count <= 101, !outsideXcode, pending == 1,
                  active == 0, !store.isPro else {
                XCTFail("Native state changed before approval; stop without approving. See bounded synthetic-state attachment.")
                throw NSError(domain: "CleanSendStoreKitTests", code: 4,
                    userInfo: [NSLocalizedDescriptionKey: "Pre-approval native entitlement observation failed."])
            }
            try await Task.sleep(for: .milliseconds(100))
        }
    }

    private func makeSession() async throws -> SKTestSession {
        let url = Bundle(for: Self.self).url(forResource: "CleanSend", withExtension: "storekit")
            ?? Bundle.main.url(forResource: "CleanSend", withExtension: "storekit")
        let session = try SKTestSession(contentsOf: XCTUnwrap(url, "Copy App/CleanSend.storekit into the test bundle."))
        session.resetToDefaultState()
        session.clearTransactions()
        session.disableDialogs = true
        do {
            // SKTestSession can control the Xcode service while an app that
            // queried StoreKit before test setup is still routed to Sandbox.
            // Verify local history before exercising the app. This detects
            // history misrouting, but is not proof that purchase()/sync() uses
            // the same environment; see MONETIZATION.md for the CLI limitation.
            let purchase = try await session.buyProduct(identifier: ProStore.productID)
            XCTAssertEqual(purchase.environment, .xcode)
            XCTAssertEqual(purchase.productID, ProStore.productID)
            XCTAssertEqual(purchase.productType, .nonConsumable)
            XCTAssertEqual(purchase.appBundleID, Bundle.main.bundleIdentifier)
            try await waitForLocalEntitlement(present: true)
            await purchase.finish()
            session.clearTransactions()
            try await waitForLocalEntitlement(present: false)
            return session
        } catch {
            clean(session)
            throw error
        }
    }

    private func waitForLocalEntitlement(present: Bool) async throws {
        var lastSummary = "No query completed."
        for _ in 0..<100 {
            var found = false
            var verifiedCount = 0
            var unverifiedCount = 0
            for await result in Transaction.currentEntitlements {
                let transaction: Transaction
                switch result {
                case .verified(let value):
                    verifiedCount += 1
                    transaction = value
                case .unverified(let value, let error):
                    unverifiedCount += 1
                    guard value.productID == ProStore.productID else { continue }
                    throw NSError(domain: "CleanSendStoreKitTests", code: 3, userInfo: [
                        NSLocalizedDescriptionKey: "The local entitlement is unverified: \(error), environment=\(value.environment.rawValue). No receipt or account data was logged."
                    ])
                }
                guard transaction.productID == ProStore.productID else { continue }
                guard transaction.environment == .xcode else {
                    throw NSError(domain: "CleanSendStoreKitTests", code: 2, userInfo: [
                        NSLocalizedDescriptionKey: "The entitlement stream is outside Xcode StoreKit. Local tests must not sign in to the App Store."
                    ])
                }
                if transaction.revocationDate == nil && transaction.productType == .nonConsumable {
                    found = true
                }
            }
            lastSummary = "verified=\(verifiedCount), unverified=\(unverifiedCount), matchingActiveProduct=\(found)"
            if found == present { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw NSError(domain: "CleanSendStoreKitTests", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "The app is not receiving clean verified Xcode StoreKit history (\(lastSummary)). Activate the StoreKit configuration in the test plan before host app launch; never sign in to fix local tests."
        ])
    }

    private func clean(_ session: SKTestSession) {
        session.resetToDefaultState()
        session.clearTransactions()
    }

    private func eventually(_ predicate: @escaping @MainActor () -> Bool) async throws {
        for _ in 0..<100 {
            if predicate() { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTFail("StoreKit update was not delivered within 10 seconds.")
    }
}

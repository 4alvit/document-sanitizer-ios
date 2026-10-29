import Darwin
import Foundation
import StoreKit
import StoreKitTest
import XCTest
@testable import CleanSend

/// Run serially in a hosted iOS test target. These exercise Apple's local
/// StoreKit service, not a fake entitlement backend or production App Store.
@MainActor
final class ProStoreTests: XCTestCase {
    func testPurchaseAndNewStoreRestoreFromVerifiedHistory() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        XCTAssertFalse(store.isPro)
        tracePhase("Product.products", "begin")
        let products = try await Product.products(for: [ProStore.productID])
        tracePhase("Product.products", "end")
        XCTAssertEqual(store.displayPrice, try XCTUnwrap(products.first).displayPrice)

        tracePhase("store.purchase", "begin")
        await store.purchase()
        tracePhase("store.purchase", "end")
        XCTAssertTrue(store.isPro)
        tracePhase("waitForLocalEntitlement.present", "begin")
        try await waitForLocalEntitlement(present: true)
        tracePhase("waitForLocalEntitlement.present", "end")
        XCTAssertFalse(store.isBusy)

        let relaunched = ProStore()
        tracePhase("relaunched.load", "begin")
        await relaunched.load()
        tracePhase("relaunched.load", "end")
        XCTAssertTrue(relaunched.isPro, "A finished non-consumable must survive a new store instance.")
        tracePhase("relaunched.restore", "begin")
        await relaunched.restore()
        tracePhase("relaunched.restore", "end")
        XCTAssertTrue(relaunched.isPro)
        XCTAssertEqual(relaunched.message, "Pro purchase restored.")
    }

    func testRefundRevokesThroughListenerAndOnNextLaunch() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        tracePhase("store.purchase", "begin")
        await store.purchase()
        tracePhase("store.purchase", "end")
        XCTAssertTrue(store.isPro)
        let transaction = try XCTUnwrap(session.allTransactions().first)
        try session.refundTransaction(identifier: transaction.identifier)
        tracePhase("eventually.revoked", "begin")
        try await eventually { !store.isPro }
        tracePhase("eventually.revoked", "end")

        let relaunched = ProStore()
        tracePhase("relaunched.load", "begin")
        await relaunched.load()
        tracePhase("relaunched.load", "end")
        XCTAssertFalse(relaunched.isPro)
    }

    func testUserCancellationNeverUnlocksPro() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        tracePhase("setSimulatedError.purchase", "begin")
        try await session.setSimulatedError(.generic(.userCancelled), forAPI: .purchase)
        tracePhase("setSimulatedError.purchase", "end")
        tracePhase("store.purchase", "begin")
        await store.purchase()
        tracePhase("store.purchase", "end")
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertEqual(store.message, "Purchase cancelled.")
    }

    func testPendingPurchaseUnlocksOnlyAfterApproval() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        session.askToBuyEnabled = true
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        tracePhase("store.purchase", "begin")
        await store.purchase()
        tracePhase("store.purchase", "end")
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertTrue(store.message?.contains("awaiting approval") == true)
        let pending = try XCTUnwrap(session.allTransactions().first(where: \.pendingAskToBuyConfirmation))
        tracePhase("observePendingBeforeApproval", "begin")
        try await observePendingBeforeApproval(store, session: session)
        tracePhase("observePendingBeforeApproval", "end")
        try session.approveAskToBuyTransaction(identifier: pending.identifier)
        tracePhase("eventually.approved", "begin")
        try await eventually { store.isPro }
        tracePhase("eventually.approved", "end")
    }

    func testUnverifiedTransactionNeverUnlocksPro() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        tracePhase("setSimulatedError.verification", "begin")
        try await session.setSimulatedError(.verification(.invalidSignature), forAPI: .verification)
        tracePhase("setSimulatedError.verification", "end")
        tracePhase("store.purchase", "begin")
        await store.purchase()
        tracePhase("store.purchase", "end")
        XCTAssertFalse(store.isPro)
        XCTAssertTrue(store.message?.contains("verified") == true)
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        XCTAssertFalse(store.isPro)
    }

    func testCachedEntitlementSurvivesProductNetworkFailure() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        tracePhase("session.buyProduct.body", "begin")
        let purchase = try await session.buyProduct(identifier: ProStore.productID)
        tracePhase("session.buyProduct.body", "end")
        XCTAssertEqual(purchase.environment, .xcode)
        XCTAssertEqual(purchase.productID, ProStore.productID)
        XCTAssertEqual(purchase.productType, .nonConsumable)
        XCTAssertEqual(purchase.appBundleID, Bundle.main.bundleIdentifier)
        // makeSession cleared its preflight purchase. Establish this purchase
        // in the app-facing verified history before testing a catalog failure.
        tracePhase("waitForLocalEntitlement.body", "begin")
        try await waitForLocalEntitlement(present: true)
        tracePhase("waitForLocalEntitlement.body", "end")
        tracePhase("setSimulatedError.loadProducts", "begin")
        try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .loadProducts)
        tracePhase("setSimulatedError.loadProducts", "end")
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        XCTAssertTrue(store.isPro, "Product availability must not control an existing entitlement.")
        XCTAssertNil(store.displayPrice)
        XCTAssertFalse(store.isBusy)
    }

    func testFailedRestoreKeepsVerifiedEntitlement() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        tracePhase("session.buyProduct.body", "begin")
        _ = try await session.buyProduct(identifier: ProStore.productID)
        tracePhase("session.buyProduct.body", "end")
        let store = ProStore()
        tracePhase("store.load", "begin")
        await store.load()
        tracePhase("store.load", "end")
        XCTAssertTrue(store.isPro)
        tracePhase("setSimulatedError.appStoreSync", "begin")
        try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .appStoreSync)
        tracePhase("setSimulatedError.appStoreSync", "end")
        tracePhase("store.restore", "begin")
        await store.restore()
        tracePhase("store.restore", "end")
        XCTAssertTrue(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertTrue(store.message?.contains("could not reach") == true)
    }

    func testRestoreWithoutPurchaseDoesNotUnlockPro() async throws {
        beginPhaseTrace(#function)
        defer { tracePhase("test", "exit") }
        tracePhase("makeSession", "begin")
        let session = try await makeSession()
        tracePhase("makeSession", "end")
        defer { clean(session) }
        let store = ProStore()
        tracePhase("store.restore", "begin")
        await store.restore()
        tracePhase("store.restore", "end")
        XCTAssertFalse(store.isPro)
        XCTAssertTrue(store.message?.contains("No active Pro purchase") == true)
    }

    // Fixed synthetic phase labels only: no account, receipt, transaction or error data.
    // fwrite + fflush makes a stalled await visible before XCTest terminates the host.
    // At most 2048 lines of 512 bytes per case, within the existing 16 MiB test log cap.
    private var phaseCase = "unassigned"
    private var phaseSequence = 0
    private let phaseClock = ContinuousClock()
    private var phaseStarted = ContinuousClock().now

    private func beginPhaseTrace(_ test: String) {
        phaseCase = test
        phaseSequence = 0
        phaseStarted = phaseClock.now
        tracePhase("test", "begin")
    }

    private func tracePhase(_ phase: StaticString, _ boundary: StaticString) {
        guard phaseSequence < 2048 else {
            if phaseSequence == 2048 {
                phaseSequence += 1
                XCTFail("Synthetic native phase marker limit exceeded.")
            }
            return
        }
        phaseSequence += 1
        let elapsed = phaseStarted.duration(to: phaseClock.now).components
        let event: [String: Any] = [
            "case": phaseCase, "phase": String(describing: phase),
            "boundary": String(describing: boundary), "sequence": phaseSequence,
            "elapsedMilliseconds": elapsed.seconds * 1000 + elapsed.attoseconds / 1_000_000_000_000_000
        ]
        guard let json = try? JSONSerialization.data(withJSONObject: event, options: [.sortedKeys]) else {
            XCTFail("Synthetic native phase marker encoding failed.")
            return
        }
        var line = Data("NATIVE_STOREKIT_PHASE ".utf8)
        line.append(json)
        line.append(10)
        guard line.count <= 512 else {
            XCTFail("Synthetic native phase marker byte limit exceeded.")
            return
        }
        let written = line.withUnsafeBytes { bytes in
            fwrite(bytes.baseAddress, 1, bytes.count, stdout)
        }
        let flushed = fflush(stdout)
        XCTAssertEqual(written, line.count, "Synthetic native phase marker write failed.")
        XCTAssertEqual(flushed, 0, "Synthetic native phase marker flush failed.")
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
            tracePhase("Transaction.currentEntitlements", "begin")
            for await result in Transaction.currentEntitlements {
                guard case .verified(let value) = result,
                      value.productID == ProStore.productID else { continue }
                outsideXcode = outsideXcode || value.environment != .xcode
                if value.revocationDate == nil && value.productType == .nonConsumable { active += 1 }
            }
            tracePhase("Transaction.currentEntitlements", "end")
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
            tracePhase("Task.sleep100ms", "begin")
            try await Task.sleep(for: .milliseconds(100))
            tracePhase("Task.sleep100ms", "end")
        }
    }

    private func makeSession() async throws -> SKTestSession {
        #if DEBUG && targetEnvironment(simulator)
        if NativeUnitTestHost.explicit {
            guard NativeUnitTestHost.firstSessionIsInert() else {
                XCTFail("The explicit unit host constructed production state before the first local StoreKit session.")
                throw NSError(domain: "CleanSendStoreKitTests", code: 5)
            }
        }
        #endif
        let url = Bundle(for: Self.self).url(forResource: "CleanSend", withExtension: "storekit")
            ?? Bundle.main.url(forResource: "CleanSend", withExtension: "storekit")
        tracePhase("SKTestSession.init", "begin")
        let session = try SKTestSession(contentsOf: XCTUnwrap(url, "Copy App/CleanSend.storekit into the test bundle."))
        tracePhase("SKTestSession.init", "end")
        tracePhase("session.resetToDefaultState", "begin")
        session.resetToDefaultState()
        tracePhase("session.resetToDefaultState", "end")
        tracePhase("session.clearTransactions", "begin")
        session.clearTransactions()
        tracePhase("session.clearTransactions", "end")
        tracePhase("session.disableDialogs", "begin")
        session.disableDialogs = true
        tracePhase("session.disableDialogs", "end")
        do {
            // Observe the reset ledger independently before the app-facing query.
            tracePhase("session.allTransactions.afterClear", "begin")
            let resetTransactionCount = session.allTransactions().count
            tracePhase("session.allTransactions.afterClear", "end")
            guard resetTransactionCount == 0 else {
                XCTFail("The local StoreKit ledger is not empty after reset and clear: \(resetTransactionCount) transactions.")
                throw NSError(domain: "CleanSendStoreKitTests", code: 6)
            }
            // A session reset is not an app-facing observation barrier. Require
            // both histories to be empty before creating this case's purchase.
            tracePhase("waitForCleanStoreKitSession", "begin")
            try await waitForLocalEntitlement(present: false, resetSession: session)
            tracePhase("waitForCleanStoreKitSession", "end")
            // SKTestSession can control the Xcode service while an app that
            // queried StoreKit before test setup is still routed to Sandbox.
            // Verify local history before exercising the app. This detects
            // history misrouting, but is not proof that purchase()/sync() uses
            // the same environment; see MONETIZATION.md for the CLI limitation.
            tracePhase("session.buyProduct.preflight", "begin")
            let purchase = try await session.buyProduct(identifier: ProStore.productID)
            tracePhase("session.buyProduct.preflight", "end")
            XCTAssertEqual(purchase.environment, .xcode)
            XCTAssertEqual(purchase.productID, ProStore.productID)
            XCTAssertEqual(purchase.productType, .nonConsumable)
            XCTAssertEqual(purchase.appBundleID, Bundle.main.bundleIdentifier)
            tracePhase("waitForLocalEntitlement.present", "begin")
            try await waitForLocalEntitlement(present: true)
            tracePhase("waitForLocalEntitlement.present", "end")
            tracePhase("purchase.finish.preflight", "begin")
            await purchase.finish()
            tracePhase("purchase.finish.preflight", "end")
            tracePhase("session.clearTransactions", "begin")
            session.clearTransactions()
            tracePhase("session.clearTransactions", "end")
            tracePhase("waitForLocalEntitlement.absent", "begin")
            try await waitForLocalEntitlement(present: false, resetSession: session)
            tracePhase("waitForLocalEntitlement.absent", "end")
            return session
        } catch {
            clean(session)
            throw error
        }
    }

    private func waitForLocalEntitlement(present: Bool, resetSession: SKTestSession? = nil) async throws {
        var lastSummary = "No query completed."
        for _ in 0..<100 {
            var found = false
            var verifiedCount = 0
            var unverifiedCount = 0
            tracePhase("Transaction.currentEntitlements", "begin")
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
            tracePhase("Transaction.currentEntitlements", "end")
            let ledgerCount = resetSession?.allTransactions().count
            let resetIsObserved = ledgerCount.map {
                $0 == 0 && verifiedCount == 0 && unverifiedCount == 0
            } ?? true
            lastSummary = "verified=\(verifiedCount), unverified=\(unverifiedCount), matchingActiveProduct=\(found), resetLedgerCount=\(ledgerCount.map(String.init) ?? "not requested")"
            if found == present && resetIsObserved { return }
            tracePhase("Task.sleep100ms", "begin")
            try await Task.sleep(for: .milliseconds(100))
            tracePhase("Task.sleep100ms", "end")
        }
        throw NSError(domain: "CleanSendStoreKitTests", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "The app-facing entitlement sequence and requested session ledger did not reach the expected state (\(lastSummary)). Local tests must not sign in to the App Store."
        ])
    }

    private func clean(_ session: SKTestSession) {
        tracePhase("session.resetToDefaultState", "begin")
        session.resetToDefaultState()
        tracePhase("session.resetToDefaultState", "end")
        tracePhase("session.clearTransactions", "begin")
        session.clearTransactions()
        tracePhase("session.clearTransactions", "end")
    }

    private func eventually(_ predicate: @escaping @MainActor () -> Bool) async throws {
        for _ in 0..<100 {
            if predicate() { return }
            tracePhase("Task.sleep100ms", "begin")
            try await Task.sleep(for: .milliseconds(100))
            tracePhase("Task.sleep100ms", "end")
        }
        XCTFail("StoreKit update was not delivered within 10 seconds.")
    }
}

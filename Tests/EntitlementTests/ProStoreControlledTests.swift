import StoreKit
import XCTest
@testable import CleanSend

/// These tests execute the real store and control only Apple's asynchronous
/// boundary. Every ordering edge is a continuation handshake, never a timer.
@MainActor
final class ProStoreControlledTests: XCTestCase {
    private var sources: [ControlledStoreKitSource] = []

    override func tearDown() async throws {
        for source in sources { source.closeUpdates() }
        sources.removeAll()
        try await super.tearDown()
    }

    func testForegroundRefreshIsNotDroppedWhileProductLookupIsBusy() async {
        let (store, source) = makeStore()
        source.suspendProducts = true
        source.automaticSnapshotResponses = [[.verified(transaction(1))], []]
        let firstLoad = Task { await store.load() }
        let productRequest = await source.productRequests.next()
        XCTAssertTrue(store.isPro)
        XCTAssertTrue(store.isBusy)

        await store.load()
        XCTAssertEqual(source.snapshotCount, 2, "Foreground activation must refresh rights even while the older product lookup is suspended.")
        XCTAssertFalse(store.isPro, "The completed foreground snapshot no longer has an entitlement.")
        productRequest.succeed(source.availableProducts)
        await firstLoad.value
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
    }

    func testBusyForegroundRefreshKeepsUnchangedVerifiedEntitlement() async {
        let (store, source) = makeStore()
        source.suspendProducts = true
        source.automaticSnapshotResponses = [[.verified(transaction(1))], [.verified(transaction(1))]]
        let firstLoad = Task { await store.load() }
        let productRequest = await source.productRequests.next()
        await store.load()
        XCTAssertTrue(store.isPro)
        productRequest.succeed(source.availableProducts)
        await firstLoad.value
        XCTAssertTrue(store.isPro)
    }

    func testCancelledBusyRefreshDoesNotApplyEmptySnapshot() async {
        let (store, source) = makeStore()
        source.suspendProducts = true
        source.automaticSnapshotResponses = [[.verified(transaction(1))], []]
        let firstLoad = Task { await store.load() }
        let productRequest = await source.productRequests.next()
        let cancelledRefresh = Task { await store.load() }
        cancelledRefresh.cancel()
        await cancelledRefresh.value
        XCTAssertTrue(store.isPro)
        productRequest.succeed(source.availableProducts)
        await firstLoad.value
        XCTAssertTrue(store.isPro)
    }

    func testEarlierActiveSnapshotCannotOverwriteRefund() async {
        let (store, source) = makeStore()
        let earlierLoad = Task { await store.load() }
        let earlierSnapshot = await source.snapshots.next()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1, revoked: true)))
        let refundSnapshot = await source.snapshots.next()
        refundSnapshot.complete([])
        _ = await source.finished.next()
        earlierSnapshot.complete([.verified(transaction(1))])
        await earlierLoad.value
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
    }

    func testEarlierEmptySnapshotCannotOverwriteNewVerifiedEntitlement() async {
        let (store, source) = makeStore()
        let earlierLoad = Task { await store.load() }
        let earlierSnapshot = await source.snapshots.next()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(2)))
        let newerSnapshot = await source.snapshots.next()
        newerSnapshot.complete([.verified(transaction(2))])
        _ = await source.finished.next()
        earlierSnapshot.complete([])
        await earlierLoad.value
        XCTAssertTrue(store.isPro)
    }

    func testRefundRejectsOlderActiveSnapshotForSameTransaction() async {
        let (store, source) = makeStore()
        await load(store, source, [.verified(transaction(1))])
        XCTAssertTrue(store.isPro)
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
        let staleSnapshot = await source.snapshots.next()
        XCTAssertFalse(store.isPro, "A verified refund takes effect before the asynchronous refresh.")
        staleSnapshot.complete([.verified(transaction(1, signed: 10))])
        _ = await source.finished.next()
        XCTAssertFalse(store.isPro, "An older active snapshot must not undo a newer verified refund of the same transaction.")
    }

    func testVerifiedUpdateIsReconciledWithInjectedEmptySnapshot() async {
        let (store, source) = makeStore()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(2)))
        let staleSnapshot = await source.snapshots.next()
        staleSnapshot.complete([])
        _ = await source.finished.next()
        XCTAssertTrue(store.isPro, "A verified non-revoked purchase is evidence when the controlled snapshot conflicts with it.")
    }

    func testVerifiedPurchaseIsReconciledWithInjectedEmptySnapshot() async {
        let (store, source) = makeStore()
        let purchase = Task { await store.purchase() }
        let request = await source.purchases.next()
        request.succeed(.success(.verified(transaction(2))))
        let staleSnapshot = await source.snapshots.next()
        staleSnapshot.complete([])
        await purchase.value
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(source.finishedIDs, [2])
        XCTAssertFalse(store.isBusy)
    }

    func testVerifiedEventDoesNotOverrideLaterIndependentEmptyRefresh() async {
        let (store, source) = makeStore()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(2)))
        let eventSnapshot = await source.snapshots.next()
        eventSnapshot.complete([])
        _ = await source.finished.next()
        XCTAssertTrue(store.isPro)
        await load(store, source, [])
        XCTAssertFalse(store.isPro, "Event reconciliation must not create an indefinite local entitlement.")
    }

    func testRefundDuringPurchaseRefreshWinsOverEarlierVerifiedPurchase() async {
        let (store, source) = makeStore()
        let purchase = Task { await store.purchase() }
        let request = await source.purchases.next()
        request.succeed(.success(.verified(transaction(1))))
        let purchaseSnapshot = await source.snapshots.next()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
        let refundSnapshot = await source.snapshots.next()
        refundSnapshot.complete([])
        _ = await source.finished.next()
        purchaseSnapshot.complete([.verified(transaction(1))])
        await purchase.value
        XCTAssertFalse(store.isPro, "A suspended purchase refresh cannot undo a newer refund.")
    }

    func testOlderRevocationDoesNotRevokeNewerSameIdentityOrDifferentActiveIdentity() async {
        for active in [transaction(1, signed: 40), transaction(2, signed: 5)] {
            let (store, source) = makeStore()
            await load(store, source, [.verified(active)])
            await source.updateRequests.next()
            source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
            let snapshot = await source.snapshots.next()
            XCTAssertTrue(store.isPro, "Do not briefly revoke an unaffected active transaction before awaiting the snapshot.")
            snapshot.complete([])
            _ = await source.finished.next()
            XCTAssertTrue(store.isPro)
        }
    }

    func testSameTimeRevocationWinsAgainstConflictingActiveSnapshot() async {
        let (store, source) = makeStore()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
        let snapshot = await source.snapshots.next()
        snapshot.complete([.verified(transaction(1, signed: 30))])
        _ = await source.finished.next()
        XCTAssertFalse(store.isPro)
    }

    func testConflictIdentityIncludesEnvironmentAndDoesNotRequireOriginalIDEquality() async {
        let (store, source) = makeStore()
        let restored = StoreTransaction(id: 8, originalID: 1, productID: ProStore.productID,
                                        environment: "Sandbox", purchaseDate: Date(timeIntervalSince1970: 1),
                                        signedDate: Date(timeIntervalSince1970: 10))
        await load(store, source, [.verified(restored)])
        XCTAssertTrue(store.isPro)
        await source.updateRequests.next()
        let unrelated = StoreTransaction(id: 8, originalID: 1, productID: ProStore.productID,
                                         environment: "Xcode", purchaseDate: Date(timeIntervalSince1970: 1),
                                         signedDate: Date(timeIntervalSince1970: 30),
                                         revocationDate: Date(timeIntervalSince1970: 20))
        source.updateValues.send(.verified(unrelated))
        let snapshot = await source.snapshots.next()
        XCTAssertTrue(store.isPro)
        snapshot.complete([])
        _ = await source.finished.next()
        XCTAssertTrue(store.isPro)
    }

    func testSuccessfulRestoreFeedbackSurvivesAutomaticRefreshUntilRevocation() async {
        let (store, source) = makeStore()
        let restore = Task { await store.restore() }
        let sync = await source.syncs.next()
        sync.succeed(())
        let restoredSnapshot = await source.snapshots.next()
        restoredSnapshot.complete([.verified(transaction(1))])
        await restore.value
        XCTAssertEqual(store.message, "Pro purchase restored.")
        await load(store, source, [.verified(transaction(1))])
        XCTAssertEqual(store.message, "Pro purchase restored.")
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
        let revokedSnapshot = await source.snapshots.next()
        revokedSnapshot.complete([])
        _ = await source.finished.next()
        XCTAssertTrue(store.message?.contains("refunded or revoked") == true)
        XCTAssertFalse(store.isPro)
    }

    func testRecoveredAutomaticErrorDoesNotLeaveStaleFeedback() async {
        let (store, source) = makeStore()
        source.productError = URLError(.notConnectedToInternet)
        await load(store, source, [])
        XCTAssertTrue(store.message?.contains("unavailable") == true)
        source.productError = nil
        await load(store, source, [])
        XCTAssertNil(store.message)
        XCTAssertEqual(store.displayPrice, "$19.99")
    }

    func testSnapshotStatusChangesReplacePendingAndReadyFeedback() async {
        let (store, source) = makeStore()
        let purchase = Task { await store.purchase() }
        let request = await source.purchases.next()
        request.succeed(.pending)
        await purchase.value
        XCTAssertTrue(store.message?.contains("awaiting approval") == true)

        await load(store, source, [.verified(transaction(2))])
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, "Pro is ready.")

        await load(store, source, [])
        XCTAssertFalse(store.isPro)
        XCTAssertEqual(store.message, "No active Pro purchase was found. Loaded documents remain available for export.")
    }

    func testNewerVerifiedSnapshotReplacesOldRevocationFeedback() async {
        let (store, source) = makeStore()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
        let revokedSnapshot = await source.snapshots.next()
        revokedSnapshot.complete([])
        _ = await source.finished.next()
        XCTAssertTrue(store.message?.contains("refunded or revoked") == true)

        await load(store, source, [.verified(transaction(1, signed: 40))])
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, "Pro is ready.")
    }

    func testAutomaticRefreshPreservesPendingAndCancelledPurchaseFeedback() async {
        for outcome in [StorePurchaseResult.pending, .userCancelled] {
            let (store, source) = makeStore()
            let purchase = Task { await store.purchase() }
            let request = await source.purchases.next()
            request.succeed(outcome)
            await purchase.value
            let purchaseMessage = store.message
            XCTAssertNotNil(purchaseMessage)
            await load(store, source, [])
            XCTAssertEqual(store.message, purchaseMessage, "A normal foreground refresh must not erase the result of the user's purchase action.")
        }
    }

    func testAutomaticRefreshPreservesRestoreFeedbackUntilNewError() async {
        let (store, source) = makeStore()
        let restore = Task { await store.restore() }
        let sync = await source.syncs.next()
        sync.succeed(())
        let restoredSnapshot = await source.snapshots.next()
        restoredSnapshot.complete([])
        await restore.value
        let restoreMessage = store.message
        XCTAssertNotNil(restoreMessage)
        await load(store, source, [])
        XCTAssertEqual(store.message, restoreMessage)

        source.productError = URLError(.notConnectedToInternet)
        await load(store, source, [])
        XCTAssertNotEqual(store.message, restoreMessage)
        XCTAssertTrue(store.message?.contains("unavailable") == true)
    }

    func testPendingDoesNotGrantWithoutVerifiedEvidence() async {
        let (store, source) = makeStore()
        let purchase = Task { await store.purchase() }
        let request = await source.purchases.next()
        request.succeed(.pending)
        await purchase.value
        XCTAssertFalse(store.isPro)
        XCTAssertFalse(store.isBusy)
        XCTAssertTrue(store.message?.contains("awaiting approval") == true)
        XCTAssertEqual(source.finishedIDs, [])
    }

    func testPendingDoesNotEraseExistingVerifiedPurchaseDeliveredDuringRequest() async {
        let (store, source) = makeStore()
        let purchase = Task { await store.purchase() }
        let request = await source.purchases.next()
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(1)))
        let snapshot = await source.snapshots.next()
        snapshot.complete([.verified(transaction(1))])
        _ = await source.finished.next()
        request.succeed(.pending)
        await purchase.value
        XCTAssertTrue(store.isPro, "Pending is not a revocation of independent verified rights.")
        XCTAssertFalse(store.isBusy)
        XCTAssertEqual(store.message, "Purchase awaiting approval. Your existing Pro access remains available.")
        await load(store, source, [.verified(transaction(1))])
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, "Purchase awaiting approval. Your existing Pro access remains available.")
    }

    func testPendingAllowsVerifiedApprovalWithInjectedEmptySnapshot() async {
        let (store, source) = makeStore()
        let purchase = Task { await store.purchase() }
        let request = await source.purchases.next()
        request.succeed(.pending)
        await purchase.value
        XCTAssertFalse(store.isPro)
        await source.updateRequests.next()
        source.updateValues.send(.verified(transaction(3)))
        let snapshot = await source.snapshots.next()
        snapshot.complete([])
        _ = await source.finished.next()
        XCTAssertTrue(store.isPro)
    }

    func testRefundDoesNotPermanentlyBlockNewIdentityOrNewerSameIdentityEvidence() async {
        for newEvidence in [transaction(2, signed: 5), transaction(1, signed: 40)] {
            let (store, source) = makeStore()
            await source.updateRequests.next()
            source.updateValues.send(.verified(transaction(1, signed: 30, revoked: true)))
            let revokedSnapshot = await source.snapshots.next()
            revokedSnapshot.complete([])
            _ = await source.finished.next()
            XCTAssertFalse(store.isPro)

            await source.updateRequests.next()
            source.updateValues.send(.verified(newEvidence))
            let restoredSnapshot = await source.snapshots.next()
            restoredSnapshot.complete([.verified(newEvidence)])
            _ = await source.finished.next()
            XCTAssertTrue(store.isPro, "A refund is not a permanent deny list for this product or transaction identity.")
        }
    }

    func testExistingVerifiedPurchaseDoesNotStartAnotherPurchase() async {
        let (store, source) = makeStore()
        await load(store, source, [.verified(transaction(1))])
        await store.purchase()
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(source.purchaseCount, 0)
        XCTAssertFalse(store.isBusy)
    }

    func testRestoreGrantsVerifiedEntitlementAndEmptyRestoreDoesNotGrant() async {
        let (store, source) = makeStore()
        let restored = Task { await store.restore() }
        let sync = await source.syncs.next()
        sync.succeed(())
        let snapshot = await source.snapshots.next()
        snapshot.complete([.verified(transaction(1))])
        await restored.value
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(store.message, "Pro purchase restored.")

        let emptyRestore = Task { await store.restore() }
        let nextSync = await source.syncs.next()
        nextSync.succeed(())
        let emptySnapshot = await source.snapshots.next()
        emptySnapshot.complete([])
        await emptyRestore.value
        XCTAssertFalse(store.isPro, "A completed, later empty entitlement refresh removes an old snapshot grant.")
        XCTAssertFalse(store.isBusy)
    }

    func testFailedRestoreAndUnavailableProductsKeepVerifiedEntitlement() async {
        let (store, source) = makeStore()
        source.productError = URLError(.notConnectedToInternet)
        await load(store, source, [.verified(transaction(1))])
        XCTAssertTrue(store.isPro)
        XCTAssertNil(store.displayPrice)
        let restore = Task { await store.restore() }
        let sync = await source.syncs.next()
        sync.fail(URLError(.notConnectedToInternet))
        await restore.value
        XCTAssertTrue(store.isPro)
        XCTAssertFalse(store.isBusy)
    }

    func testCancelledAndFailedPurchasesNeverGrant() async {
        let outcomes: [Result<StorePurchaseResult, Error>] = [
            .success(.userCancelled), .failure(StoreKitError.userCancelled),
            .failure(CancellationError()), .failure(URLError(.notConnectedToInternet))
        ]
        for outcome in outcomes {
            let (store, source) = makeStore()
            let purchase = Task { await store.purchase() }
            let request = await source.purchases.next()
            request.complete(outcome)
            await purchase.value
            XCTAssertFalse(store.isPro)
            XCTAssertFalse(store.isBusy)
            XCTAssertEqual(source.finishedIDs, [])
            XCTAssertNotNil(store.message)
        }
    }

    func testUnverifiedAndWrongProductPurchasesNeverGrantOrFinish() async {
        let wrongProduct = StoreTransaction(id: 5, productID: "other.product", purchaseDate: Date(), signedDate: Date())
        for evidence in [StoreVerification.unverified(transaction(1)), .verified(wrongProduct)] {
            let (store, source) = makeStore()
            let purchase = Task { await store.purchase() }
            let request = await source.purchases.next()
            request.succeed(.success(evidence))
            await purchase.value
            XCTAssertFalse(store.isPro)
            XCTAssertFalse(store.isBusy)
            XCTAssertEqual(source.finishedIDs, [])
            XCTAssertEqual(store.message, "This purchase could not be verified. Try Restore Purchases.")
        }
    }

    func testUnverifiedUpdateCannotRevokeExistingVerifiedEntitlement() async {
        let (store, source) = makeStore()
        await load(store, source, [.verified(transaction(1))])
        await source.updateRequests.next()
        source.updateValues.send(.unverified(transaction(1, revoked: true)))
        await source.updateRequests.next()
        XCTAssertTrue(store.isPro)
        XCTAssertEqual(source.finishedIDs, [])
    }

    func testUnverifiedSnapshotDoesNotGrant() async {
        let (store, source) = makeStore()
        await load(store, source, [.unverified(transaction(1))])
        XCTAssertFalse(store.isPro)
        XCTAssertTrue(store.message?.contains("could not be verified") == true)
    }

    private func makeStore() -> (ProStore, ControlledStoreKitSource) {
        let source = ControlledStoreKitSource()
        sources.append(source)
        return (ProStore(source: source), source)
    }

    private func load(_ store: ProStore, _ source: ControlledStoreKitSource, _ values: [StoreVerification]) async {
        let task = Task { await store.load() }
        let snapshot = await source.snapshots.next()
        snapshot.complete(values)
        await task.value
    }

    private func transaction(_ id: UInt64, signed: TimeInterval = 10, revoked: Bool = false) -> StoreTransaction {
        StoreTransaction(id: id, productID: ProStore.productID,
                         purchaseDate: Date(timeIntervalSince1970: 1),
                         signedDate: Date(timeIntervalSince1970: signed),
                         revocationDate: revoked ? Date(timeIntervalSince1970: 20) : nil)
    }
}

@MainActor
private final class ControlledStoreKitSource: StoreKitSource {
    let snapshots = ControlledChannel<ControlledSnapshot>()
    let updateRequests = ControlledChannel<Void>()
    let updateValues = ControlledChannel<StoreVerification?>()
    let purchases = ControlledChannel<ControlledRequest<StorePurchaseResult>>()
    let syncs = ControlledChannel<ControlledRequest<Void>>()
    let productRequests = ControlledChannel<ControlledRequest<[StoreProduct]>>()
    let finished = ControlledChannel<UInt64>()
    var finishedIDs: [UInt64] = []
    var purchaseCount = 0
    var productError: Error?
    var suspendProducts = false
    var snapshotCount = 0
    var automaticSnapshotResponses: [[StoreVerification]] = []
    var availableProducts: [StoreProduct] { [StoreProduct(id: ProStore.productID, displayPrice: "$19.99")] }

    func currentEntitlements() -> StoreTransactionIterator {
        let snapshot = ControlledSnapshot()
        snapshotCount += 1
        if !automaticSnapshotResponses.isEmpty {
            snapshot.complete(automaticSnapshotResponses.removeFirst())
        }
        snapshots.send(snapshot)
        return StoreTransactionIterator { await snapshot.values.next() }
    }

    func updates() -> StoreTransactionIterator {
        StoreTransactionIterator { [self] in
            updateRequests.send(())
            return await updateValues.next()
        }
    }

    func products(for identifiers: [String]) async throws -> [StoreProduct] {
        if let productError { throw productError }
        if suspendProducts {
            return try await withCheckedThrowingContinuation { continuation in
                productRequests.send(ControlledRequest(continuation))
            }
        }
        return availableProducts
    }

    func purchase(_ product: StoreProduct) async throws -> StorePurchaseResult {
        purchaseCount += 1
        return try await withCheckedThrowingContinuation { continuation in
            purchases.send(ControlledRequest(continuation))
        }
    }

    func sync() async throws {
        try await withCheckedThrowingContinuation { continuation in
            syncs.send(ControlledRequest(continuation))
        }
    }

    func finish(_ transaction: StoreTransaction) async {
        finishedIDs.append(transaction.id)
        finished.send(transaction.id)
    }

    func closeUpdates() { updateValues.send(nil) }
}

@MainActor
private final class ControlledSnapshot {
    let values = ControlledChannel<StoreVerification?>()
    func complete(_ evidence: [StoreVerification]) {
        for value in evidence { values.send(value) }
        values.send(nil)
    }
}

@MainActor
private final class ControlledRequest<Value> {
    private let continuation: CheckedContinuation<Value, Error>
    init(_ continuation: CheckedContinuation<Value, Error>) { self.continuation = continuation }
    func complete(_ result: Result<Value, Error>) { continuation.resume(with: result) }
    func succeed(_ value: Value) { complete(.success(value)) }
    func fail(_ error: Error) { complete(.failure(error)) }
}

@MainActor
private final class ControlledChannel<Value> {
    private var values: [Value] = []
    private var waiters: [CheckedContinuation<Value, Never>] = []
    func send(_ value: Value) {
        if waiters.isEmpty { values.append(value) }
        else { waiters.removeFirst().resume(returning: value) }
    }
    func next() async -> Value {
        if !values.isEmpty { return values.removeFirst() }
        return await withCheckedContinuation { waiters.append($0) }
    }
}

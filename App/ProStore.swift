import Combine
import Foundation
import StoreKit

/// Own one instance for the app lifetime. Refresh when the app becomes active.
/// Entitlements authorize committing new paid work, never access to a loaded document.
@MainActor
final class ProStore: ObservableObject {
    static let productID = "io.github.4alvit.cleansend.pro"

    @Published private(set) var isPro = false
    @Published private(set) var displayPrice: String?
    @Published private(set) var isBusy = false
    @Published private(set) var message: String?

    private let source: StoreKitSource
    private var product: StoreProduct?
    private var updatesTask: Task<Void, Never>?
    private var entitlementGeneration = 0
    private var activeTransactions: [TransactionIdentity: StoreTransaction] = [:]
    private var latestEvidence: [TransactionIdentity: StoreTransaction] = [:]
    private var messageKind: MessageKind?

    private struct TransactionIdentity: Hashable {
        let environment: String
        let id: UInt64
        init(_ transaction: StoreTransaction) {
            environment = transaction.environment
            id = transaction.id
        }
    }

    private enum MessageKind { case action, refresh, transaction }
    #if DEBUG && targetEnvironment(simulator)
    private let diagnostic = LocalStoreKitDiagnostic()
    #endif

    convenience init() {
        self.init(source: AppleStoreKitSource())
    }

    init(source: StoreKitSource) {
        #if DEBUG && targetEnvironment(simulator)
        NativeUnitTestHost.recordStoreConstruction()
        #endif
        self.source = source
        // Start before requesting products so interrupted/Ask to Buy purchases
        // can be delivered even while the paywall is closed.
        updatesTask = Task { [weak self] in
            let updates = source.updates()
            while let update = await updates.next() {
                guard !Task.isCancelled else { break }
                // Do not retain self across the next indefinite sequence wait.
                await self?.receive(update)
            }
        }
    }

    deinit {
        updatesTask?.cancel()
    }

    func load() async {
        // Foreground entitlement checks must not be dropped just because a
        // product lookup, purchase sheet or explicit restore is still busy.
        guard !isBusy else {
            await refreshEntitlements()
            return
        }
        isBusy = true
        if messageKind == .refresh { showMessage(nil, kind: .refresh) }
        defer { isBusy = false }

        // StoreKit has an on-device verified transaction cache. Product lookup
        // failing offline must not erase an otherwise valid entitlement.
        await refreshEntitlements()
        guard !Task.isCancelled else { return }
        do {
            try await fetchProduct()
        } catch is CancellationError {
            return
        } catch {
            product = nil
            displayPrice = nil
            showMessage(L10n.text("The App Store is unavailable. Try again when connected. Your loaded documents can still be exported."), kind: .refresh)
        }
    }

    func purchase() async {
        guard !isBusy else { return }
        guard !isPro else {
            showMessage(L10n.text("Pro is already available."))
            return
        }
        isBusy = true
        showMessage(nil)
        defer { isBusy = false }

        do {
            if product == nil { try await fetchProduct() }
            guard let product else { return }
            try Task.checkCancellation()
            #if DEBUG && targetEnvironment(simulator)
            trace("purchase.begin")
            #endif
            switch try await source.purchase(product) {
            case .success(let result):
                #if DEBUG && targetEnvironment(simulator)
                traceTransaction("purchase.result.success", result)
                #endif
                guard case .verified(let transaction) = result,
                      transaction.productID == Self.productID,
                      transaction.productType == .nonConsumable else {
                    showMessage(L10n.text("This purchase could not be verified. Try Restore Purchases."))
                    return
                }
                applyVerifiedEvent(transaction)
                await refreshEntitlements(preserving: Array(activeTransactions.values))
                #if DEBUG && targetEnvironment(simulator)
                trace("finish.before", ["source": "purchase", "transactionID": String(transaction.id)])
                #endif
                await source.finish(transaction)
                #if DEBUG && targetEnvironment(simulator)
                trace("finish.after", ["source": "purchase", "transactionID": String(transaction.id)])
                #endif
                showMessage(isPro
                    ? L10n.text("Pro is ready. Thank you for supporting RedactLeaf.")
                    : L10n.text("No active Pro purchase was found. Your loaded documents can still be exported."))
            case .pending:
                #if DEBUG && targetEnvironment(simulator)
                trace("purchase.result.pending")
                #endif
                showMessage(isPro
                    ? L10n.text("Purchase awaiting approval. Your existing Pro access remains available.")
                    : L10n.text("Purchase awaiting approval. Pro will unlock after the App Store confirms it."))
            case .userCancelled:
                #if DEBUG && targetEnvironment(simulator)
                trace("purchase.result.userCancelled")
                #endif
                showMessage(L10n.text("Purchase cancelled."))
            case .unknown:
                #if DEBUG && targetEnvironment(simulator)
                trace("purchase.result.unknown")
                #endif
                showMessage(L10n.text("The purchase has not been confirmed. Please try again later."))
            }
        } catch is CancellationError {
            #if DEBUG && targetEnvironment(simulator)
            trace("purchase.throw.cancellation")
            #endif
            showMessage(L10n.text("Purchase interrupted. A confirmed purchase will be restored automatically."))
        } catch {
            #if DEBUG && targetEnvironment(simulator)
            trace("purchase.throw", ["isUserCancellation": Self.isUserCancellation(error)])
            #endif
            showMessage(Self.isUserCancellation(error)
                ? L10n.text("Purchase cancelled.")
                : L10n.text("The purchase could not be completed. Check your connection and try again."))
        }
    }

    /// Only call in response to the person's explicit Restore Purchases action.
    func restore() async {
        guard !isBusy else { return }
        isBusy = true
        showMessage(nil)
        defer { isBusy = false }

        do {
            try await source.sync()
            await refreshEntitlements()
            showMessage(isPro ? L10n.text("Pro purchase restored.") : L10n.text("No active Pro purchase was found for this App Store account."))
        } catch {
            // A failed sync is not evidence of a refund. Keep any previously
            // verified entitlement; updates/next activation will refresh it.
            showMessage(Self.isUserCancellation(error)
                ? L10n.text("Restore cancelled.")
                : L10n.text("Restore could not reach the App Store. Try again when connected."))
        }
    }

    private func fetchProduct() async throws {
        let products = try await source.products(for: [Self.productID])
        try Task.checkCancellation()
        product = products.first { $0.id == Self.productID && $0.type == .nonConsumable }
        displayPrice = product?.displayPrice
        if product == nil {
            showMessage(L10n.text("Pro is not available in this App Store yet. You can still use the free tools and export loaded documents."), kind: .refresh)
        }
    }

    private func receive(_ result: StoreVerification) async {
        #if DEBUG && targetEnvironment(simulator)
        traceTransaction("receive.begin", result)
        defer { trace("receive.end") }
        #endif
        guard case .verified(let transaction) = result else {
            // Never use an unverified payload to grant or revoke access.
            showMessage(L10n.text("An App Store update could not be verified. Try Restore Purchases when connected."), kind: .transaction)
            return
        }
        guard transaction.productID == Self.productID,
              transaction.productType == .nonConsumable else { return }

        let applied = applyVerifiedEvent(transaction)
        if applied && transaction.revocationDate != nil {
            showMessage(L10n.text("Pro was refunded or revoked. Loaded documents remain available for export."), kind: .transaction)
        }
        // Carry the currently accepted events through this event's own read.
        // A later independent load/restore remains authoritative, including an
        // empty snapshot. Nothing here persists a local entitlement grant.
        await refreshEntitlements(preserving: Array(activeTransactions.values))
        #if DEBUG && targetEnvironment(simulator)
        trace("finish.before", ["source": "receive", "transactionID": String(transaction.id)])
        #endif
        await source.finish(transaction)
        #if DEBUG && targetEnvironment(simulator)
        trace("finish.after", ["source": "receive", "transactionID": String(transaction.id)])
        #endif
        if isPro { showMessage(L10n.text("Pro is ready."), kind: .transaction) }
    }

    private func refreshEntitlements(preserving events: [StoreTransaction] = [], reason: StaticString = #function) async {
        guard !Task.isCancelled else { return }
        entitlementGeneration += 1
        let generation = entitlementGeneration
        #if DEBUG && targetEnvironment(simulator)
        var acceptedIDs: [String] = []
        var outcome = "cancelledDuringIteration"
        trace("refresh.begin", ["reason": String(describing: reason), "snapshotGeneration": generation])
        defer { trace("refresh.end", ["reason": String(describing: reason), "snapshotGeneration": generation, "outcome": outcome]) }
        #endif
        var candidates: [StoreTransaction] = []
        var unverified = false
        let entitlements = source.currentEntitlements()
        while let result = await entitlements.next() {
            #if DEBUG && targetEnvironment(simulator)
            traceTransaction("refresh.element", result, ["reason": String(describing: reason), "snapshotGeneration": generation])
            #endif
            guard !Task.isCancelled else { return }
            switch result {
            case .verified(let transaction):
                if matchesProduct(transaction) { candidates.append(transaction) }
            case .unverified:
                unverified = true
            }
        }
        // A later update must not be overwritten by an earlier async snapshot.
        guard generation == entitlementGeneration, !Task.isCancelled else {
            #if DEBUG && targetEnvironment(simulator)
            outcome = "discarded"
            trace("refresh.snapshot.discarded", ["snapshotGeneration": generation, "cancelled": Task.isCancelled, "acceptedIDs": acceptedIDs])
            #endif
            return
        }
        var nextActive: [TransactionIdentity: StoreTransaction] = [:]
        for transaction in candidates + events {
            let identity = TransactionIdentity(transaction)
            remember(transaction)
            guard let accepted = latestEvidence[identity] else { continue }
            if isActive(accepted) { nextActive[identity] = accepted }
            else { nextActive.removeValue(forKey: identity) }
        }
        activeTransactions = nextActive
        let entitled = !nextActive.isEmpty
        #if DEBUG && targetEnvironment(simulator)
        acceptedIDs = nextActive.values.map { String($0.id) }.sorted()
        outcome = "applied"
        trace("refresh.snapshot.applied", ["snapshotGeneration": generation, "entitled": entitled, "unverified": unverified, "acceptedIDs": acceptedIDs])
        trace("isPro.assignment", ["source": "snapshot", "snapshotGeneration": generation, "previous": isPro, "next": entitled])
        #endif
        let changed = isPro != entitled
        isPro = entitled
        #if DEBUG && targetEnvironment(simulator)
        trace("isPro.assigned", ["source": "snapshot", "snapshotGeneration": generation])
        #endif
        if changed {
            showMessage(entitled
                ? L10n.text("Pro is ready.")
                : L10n.text("No active Pro purchase was found. Loaded documents remain available for export."), kind: .transaction)
        }
        if unverified && !entitled {
            showMessage(L10n.text("The App Store purchase could not be verified. Try Restore Purchases. Loaded documents remain available."), kind: .refresh)
        }
    }

    private func showMessage(_ value: String?, kind: MessageKind = .action) {
        message = value
        messageKind = value == nil ? nil : kind
    }

    private func matchesProduct(_ transaction: StoreTransaction) -> Bool {
        transaction.productID == Self.productID && transaction.productType == .nonConsumable
    }

    private func isActive(_ transaction: StoreTransaction) -> Bool {
        transaction.revocationDate == nil && !transaction.isUpgraded
    }

    /// Process-local conflict policy scoped to the exact environment and ID,
    /// not an Apple version guarantee:
    /// signedDate is the JWS signing time. An already observed newer signed
    /// state wins for the exact environment/transaction ID; a revocation wins
    /// an equal-time conflict. A newer signed non-revoked state is allowed
    /// (including a refund reversal). IDs and originalIDs are never clocks.
    @discardableResult
    private func remember(_ transaction: StoreTransaction) -> Bool {
        let identity = TransactionIdentity(transaction)
        if let previous = latestEvidence[identity] {
            guard transaction.signedDate >= previous.signedDate else { return false }
            if transaction.signedDate == previous.signedDate,
               previous.revocationDate != nil, transaction.revocationDate == nil { return false }
        }
        latestEvidence[identity] = transaction
        return true
    }

    @discardableResult
    private func applyVerifiedEvent(_ transaction: StoreTransaction) -> Bool {
        guard remember(transaction) else { return false }
        let identity = TransactionIdentity(transaction)
        if isActive(transaction) { activeTransactions[identity] = transaction }
        else { activeTransactions.removeValue(forKey: identity) }
        #if DEBUG && targetEnvironment(simulator)
        trace("isPro.assignment", ["source": "verifiedEvent", "transactionID": String(transaction.id), "previous": isPro, "next": !activeTransactions.isEmpty])
        #endif
        isPro = !activeTransactions.isEmpty
        #if DEBUG && targetEnvironment(simulator)
        trace("isPro.assigned", ["source": "verifiedEvent", "transactionID": String(transaction.id)])
        #endif
        return true
    }

    #if DEBUG && targetEnvironment(simulator)
    /// Records this process's already accepted state; never queries StoreKit.
    func recordImportCommit(addedPages: Int, totalPages: Int, liveIsPro: Bool) {
        let identities = activeTransactions.keys.sorted {
            $0.environment == $1.environment ? $0.id < $1.id : $0.environment < $1.environment
        }.map { ["environment": $0.environment, "transactionID": String($0.id)] }
        trace("workspace.import.committed", [
            "addedPages": addedPages,
            "totalPages": totalPages,
            "liveIsPro": liveIsPro,
            "acceptedIdentities": identities
        ])
    }

    private func trace(_ event: String, _ fields: [String: Any] = [:]) {
        var values = fields
        values["isPro"] = isPro
        values["entitlementGeneration"] = entitlementGeneration
        diagnostic.record(event, values)
    }

    private func traceTransaction(_ event: String, _ result: StoreVerification, _ fields: [String: Any] = [:]) {
        let evidence: StoreTransaction
        let verified: Bool
        switch result {
        case .verified(let value): evidence = value; verified = true
        case .unverified(let value): evidence = value; verified = false
        }
        guard let transaction = evidence.native else { return }
        // A nonlocal transaction permanently disables this diagnostic session.
        // No payload, receipt, JWS, account token or error description is logged.
        guard transaction.environment == .xcode else { diagnostic.disable(); return }
        if verified { diagnostic.confirmLocalEnvironment() }
        var values = fields
        values["verification"] = verified ? "verified" : "unverified"
        values["transactionID"] = String(transaction.id)
        values["originalID"] = String(transaction.originalID)
        values["productID"] = transaction.productID
        values["productType"] = transaction.productType.rawValue
        values["environment"] = transaction.environment.rawValue
        values["purchaseDate"] = transaction.purchaseDate.timeIntervalSince1970
        values["signedDate"] = transaction.signedDate.timeIntervalSince1970
        if let date = transaction.revocationDate {
            values["revocationDate"] = date.timeIntervalSince1970
        } else {
            values["revocationDate"] = NSNull()
        }
        values["isUpgraded"] = transaction.isUpgraded
        trace(event, values)
    }
    #endif

    private static func isUserCancellation(_ error: Error) -> Bool {
        if let error = error as? StoreKitError, case .userCancelled = error { return true }
        return (error as? SKError)?.code == .paymentCancelled
    }
}

#if DEBUG && targetEnvironment(simulator)
/// Bounded, ordered observation only. No tasks, awaits, StoreKit requests or
/// access decisions. Startup events stay in memory until a verified .xcode
/// transaction confirms the local environment. Logging failures are discarded.
@MainActor
private final class LocalStoreKitDiagnostic {
    private var sequence = 0
    private var buffer: [Data] = []
    private var handle: FileHandle?
    private var disabled = false
    private var confirmed = false
    private let session = UUID().uuidString

    func disable() {
        disabled = true
        buffer.removeAll()
        try? handle?.close()
        handle = nil
    }

    func confirmLocalEnvironment() {
        guard !disabled, !confirmed else { return }
        confirmed = true
        do {
            let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("LocalStoreKitDiagnostic", isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let url = directory.appendingPathComponent("\(session).jsonl")
            guard FileManager.default.createFile(atPath: url.path, contents: nil) else { disable(); return }
            handle = try FileHandle(forWritingTo: url)
            for data in buffer { try handle?.write(contentsOf: data) }
            buffer.removeAll()
        } catch { disable() }
    }

    func record(_ event: String, _ fields: [String: Any]) {
        guard !disabled else { return }
        sequence += 1
        // Bound diagnostic storage even if a local service produces a loop.
        guard sequence <= 10000 else { disable(); return }
        var row = fields
        row["sequence"] = sequence
        row["event"] = event
        row["session"] = session
        row["time"] = Date().timeIntervalSince1970
        row["uptime"] = ProcessInfo.processInfo.systemUptime
        guard var data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) else { return }
        data.append(0x0A)
        if confirmed {
            do { try handle?.write(contentsOf: data) } catch { disable() }
        } else if buffer.count < 256 {
            buffer.append(data)
        }
    }
}
#endif

import CoreGraphics
import XCTest
import SanitizerCore
@testable import CleanSend

/// Uses real PDF decoding and a continuation at the worker boundary. No sleep,
/// product delay, injected pages, or fake production entitlement is involved.
@MainActor
final class ImportAuthorizationTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("ImportAuthorizationTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    func testRevocationDuringOrdinaryImportPreservesLoadedPagesMasksReviewAndExport() async throws {
        let arrived = expectation(description: "Real additional page decoded")
        let gate = ImportWorkerGate(arrived: arrived)
        let access = ImportAccess()
        let workspace = makeWorkspace(gate: gate)
        workspace.importURLs([try makePDF("existing.pdf", pages: 4)], currentIsPro: { access.isPro })
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 4)
        let first = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(NormalizedRect(x: 0.1, y: 0.2, width: 0.4, height: 0.3), pageID: first.id)
        workspace.prepareReview()
        await workspace.runningTask?.value
        let review = try XCTUnwrap(workspace.review)
        workspace.export(review, format: .png)
        await workspace.runningTask?.value
        let existingExport = try XCTUnwrap(workspace.exported)
        let pageIDs = workspace.pages.map(\.id)
        let maskIDs = workspace.pages.flatMap(\.redactions).map(\.id)
        let source = try makePDF("additional.pdf", pages: 1)
        let original = try Data(contentsOf: source)

        await gate.arm()
        workspace.importURLs([source], currentIsPro: { access.isPro })
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        // This models the already-delivered revoked state on the main actor,
        // not an eventual StoreKit event that Workspace has not received yet.
        access.isPro = false
        await gate.release()
        await task?.value

        XCTAssertEqual(workspace.pages.map(\.id), pageIDs, "A delivered downgrade must reject new paid-capacity pages.")
        XCTAssertEqual(workspace.pages.flatMap(\.redactions).map(\.id), maskIDs)
        XCTAssertEqual(workspace.review?.id, review.id, "Rejected additions must preserve the existing review.")
        XCTAssertEqual(workspace.exported?.id, existingExport.id)
        XCTAssertTrue(existingExport.urls.allSatisfy { FileManager.default.fileExists(atPath: $0.path) })
        XCTAssertNotNil(workspace.errorMessage)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertEqual(try Data(contentsOf: source), original)
        try assertNoImportStaging()

        workspace.cleanExport(existingExport)
        workspace.errorMessage = nil
        workspace.export(review, format: .pdf)
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.exported?.urls.count, 1, "Already loaded paid pages must remain exportable after downgrade.")
        XCTAssertNil(workspace.errorMessage)
    }

    func testRevocationDuringSharedImportRetainsBatchForAuthorizedRetry() async throws {
        let arrived = expectation(description: "Real shared PDF decoded")
        let gate = ImportWorkerGate(arrived: arrived)
        let access = ImportAccess()
        let (batch, source) = try makeBatch(pages: 4)
        let original = try Data(contentsOf: source)
        let workspace = makeWorkspace(gate: gate, sharedInbox: batch.deletingLastPathComponent())
        await gate.arm()
        workspace.importShared(currentIsPro: { access.isPro })
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        access.isPro = false
        await gate.release()
        await task?.value

        XCTAssertTrue(workspace.pages.isEmpty, "A stale Pro snapshot must not publish four shared pages.")
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(try? Data(contentsOf: source), original, "Rejected work must not consume the queued originals.")
        XCTAssertNotNil(workspace.errorMessage)
        XCTAssertFalse(workspace.isBusy)
        try assertNoImportStaging()

        access.isPro = true
        workspace.errorMessage = nil
        workspace.importShared(currentIsPro: { access.isPro })
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 4)
        XCTAssertNil(workspace.errorMessage)
        XCTAssertEqual(workspace.sharedBatchCount, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: batch.path))
    }

    func testRevocationStillAllowsSharedImportWithinFreeCapacity() async throws {
        let arrived = expectation(description: "Real free-capacity PDF decoded")
        let gate = ImportWorkerGate(arrived: arrived)
        let access = ImportAccess()
        let (batch, _) = try makeBatch(pages: 3)
        let workspace = makeWorkspace(gate: gate, sharedInbox: batch.deletingLastPathComponent())
        await gate.arm()
        workspace.importShared(currentIsPro: { access.isPro })
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        access.isPro = false
        await gate.release()
        await task?.value
        XCTAssertEqual(workspace.pages.count, 3)
        XCTAssertNil(workspace.errorMessage)
        XCTAssertEqual(workspace.sharedBatchCount, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: batch.path))
        try assertNoImportStaging()
    }

    func testCancellationAfterSharedDecodeRetainsBatchAndCleansStaging() async throws {
        let arrived = expectation(description: "Real cancellable PDF decoded")
        let gate = ImportWorkerGate(arrived: arrived)
        let (batch, source) = try makeBatch(pages: 2)
        let original = try Data(contentsOf: source)
        let workspace = makeWorkspace(gate: gate, sharedInbox: batch.deletingLastPathComponent())
        await gate.arm()
        workspace.importShared()
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        workspace.cancel()
        await gate.release()
        await task?.value
        XCTAssertTrue(workspace.pages.isEmpty)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertNil(workspace.errorMessage)
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(try Data(contentsOf: source), original)
        try assertNoImportStaging()

        workspace.importShared()
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 2)
        XCTAssertFalse(FileManager.default.fileExists(atPath: batch.path))
    }

    func testWorkerFailureKeepsSharedOriginalsAndExistingReview() async throws {
        let (batch, source) = try makeBatch(pages: 2)
        let original = try Data(contentsOf: source)
        let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("workspace"),
                                  sharedInbox: batch.deletingLastPathComponent(),
                                  importPageLoader: { url in
            _ = try RasterImporter.load(url: url)
            throw ImportFailure.afterDecode
        })
        workspace.loadDemo()
        let page = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(NormalizedRect(x: 0, y: 0, width: 0.2, height: 0.2), pageID: page.id)
        workspace.searchQuery = "practice search"
        workspace.prepareReview()
        await workspace.runningTask?.value
        let review = try XCTUnwrap(workspace.review)
        workspace.importShared()
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.map(\.id), [page.id])
        XCTAssertEqual(workspace.redactionCount, 1)
        XCTAssertTrue(workspace.isSynthetic)
        XCTAssertEqual(workspace.searchQuery, "practice search")
        XCTAssertEqual(workspace.review?.id, review.id)
        XCTAssertNotNil(workspace.errorMessage)
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(try Data(contentsOf: source), original)
        try assertNoImportStaging()
    }

    func testCancelledDemoReplacementKeepsPracticeEditsAndQuery() async throws {
        let arrived = expectation(description: "Replacement decoded before cancellation")
        let gate = ImportWorkerGate(arrived: arrived)
        let workspace = makeWorkspace(gate: gate)
        workspace.loadDemo()
        let page = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(.init(x: 0, y: 0, width: 0.2, height: 0.2), pageID: page.id)
        workspace.searchQuery = "practice search"
        workspace.prepareReview(); await workspace.runningTask?.value
        let reviewID = try XCTUnwrap(workspace.review?.id)
        let source = try makePDF("replacement.pdf", pages: 3)
        let original = try Data(contentsOf: source)
        await gate.arm()
        workspace.importURLs([source])
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        workspace.cancel()
        await gate.release(); await task?.value
        XCTAssertEqual(workspace.pages.map(\.id), [page.id])
        XCTAssertTrue(workspace.isSynthetic)
        XCTAssertEqual(workspace.redactionCount, 1)
        XCTAssertEqual(workspace.review?.id, reviewID)
        XCTAssertEqual(workspace.searchQuery, "practice search")
        XCTAssertNil(workspace.errorMessage)
        XCTAssertEqual(try Data(contentsOf: source), original)
        try assertNoImportStaging()
    }

    func testDemoReplacementStillChecksLiveAuthorizationBeforeDiscardingPractice() async throws {
        let arrived = expectation(description: "Four replacement pages decoded")
        let gate = ImportWorkerGate(arrived: arrived)
        let access = ImportAccess()
        let (batch, source) = try makeBatch(pages: 4)
        let original = try Data(contentsOf: source)
        let workspace = makeWorkspace(gate: gate, sharedInbox: batch.deletingLastPathComponent())
        workspace.loadDemo()
        let page = try XCTUnwrap(workspace.pages.first)
        workspace.searchQuery = "practice search"
        await gate.arm()
        workspace.importShared(currentIsPro: { access.isPro })
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        access.isPro = false
        await gate.release(); await task?.value
        XCTAssertEqual(workspace.pages.map(\.id), [page.id])
        XCTAssertTrue(workspace.isSynthetic)
        XCTAssertEqual(workspace.searchQuery, "practice search")
        XCTAssertNotNil(workspace.errorMessage)
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(try Data(contentsOf: source), original)
        try assertNoImportStaging()
    }

    func testRefreshDoesNotPruneActiveSharedBatchBeforeCancellationCompletes() async throws {
        let arrived = expectation(description: "Real PDF decoded before queue refresh")
        let gate = ImportWorkerGate(arrived: arrived)
        let (batch, source) = try makeBatch(pages: 2)
        let original = try Data(contentsOf: source)
        let workspace = makeWorkspace(gate: gate, sharedInbox: batch.deletingLastPathComponent())
        await gate.arm()
        workspace.importShared()
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        // Simulate crossing the documented expiry boundary during this active
        // operation, then an unrelated scene/list refresh. No clock sleep.
        do {
            try FileManager.default.setAttributes([.creationDate: Date().addingTimeInterval(-90_000)], ofItemAtPath: batch.path)
        } catch {
            workspace.cancel()
            await gate.release()
            await task?.value
            throw error
        }
        workspace.checkSharedImports()
        XCTAssertEqual(try? Data(contentsOf: source), original, "TTL refresh must not delete sources owned by an active import.")
        XCTAssertEqual(workspace.sharedBatchCount, 1)

        workspace.cancel()
        await gate.release()
        await task?.value
        XCTAssertTrue(workspace.pages.isEmpty)
        XCTAssertEqual(try? Data(contentsOf: source), original)
        try assertNoImportStaging()

        // Protection ends with the operation. This is not an indefinite retry
        // promise for already-expired queue items.
        workspace.checkSharedImports()
        XCTAssertFalse(FileManager.default.fileExists(atPath: batch.path))
        XCTAssertEqual(workspace.sharedBatchCount, 0)
    }

    func testCancelledWorkerUnwindCannotDisturbNewImportOrItsQueueProtection() async throws {
        let oldArrived = expectation(description: "Old import decoded and suspended")
        let newArrived = expectation(description: "New import decoded while old worker remains alive")
        let oldGate = ImportWorkerGate(arrived: oldArrived)
        let newGate = ImportWorkerGate(arrived: newArrived)
        let sequence = ImportWorkerSequence([oldGate, newGate])
        let (batch, source) = try makeBatch(pages: 2)
        let original = try Data(contentsOf: source)
        let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("workspace"),
                                  sharedInbox: batch.deletingLastPathComponent(),
                                  importPageLoader: { url in
            let pages = try RasterImporter.load(url: url)
            await sequence.pauseNext()
            return pages
        })
        workspace.loadDemo()
        let existing = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(NormalizedRect(x: 0, y: 0, width: 0.2, height: 0.2), pageID: existing.id)
        workspace.prepareReview()
        await workspace.runningTask?.value
        let review = try XCTUnwrap(workspace.review)
        await oldGate.arm()
        await newGate.arm()

        workspace.importShared()
        let oldTask = workspace.runningTask
        await fulfillment(of: [oldArrived], timeout: 5)
        workspace.cancel()
        // Start another import of the same batch before the cancelled worker
        // is released. Both workers now own staging files and queue protection.
        workspace.importShared()
        let newTask = workspace.runningTask
        await fulfillment(of: [newArrived], timeout: 5)
        do {
            try FileManager.default.setAttributes([.creationDate: Date().addingTimeInterval(-90_000)], ofItemAtPath: batch.path)
        } catch {
            workspace.cancel()
            await oldGate.release()
            await newGate.release()
            await oldTask?.value
            await newTask?.value
            throw error
        }

        await oldGate.release()
        await oldTask?.value
        XCTAssertTrue(workspace.isBusy, "The old worker must not finish the new operation.")
        XCTAssertNotNil(workspace.runningTask)
        XCTAssertEqual(workspace.busyLabel, "Importing clean working copies…")
        XCTAssertEqual(workspace.pages.map(\.id), [existing.id], "The cancelled worker must not publish its decoded pages.")
        XCTAssertEqual(workspace.redactionCount, 1)
        XCTAssertEqual(workspace.review?.id, review.id)
        XCTAssertNil(workspace.errorMessage)
        workspace.checkSharedImports()
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(try? Data(contentsOf: source), original,
                       "Old cleanup must not remove the new worker's protection from TTL pruning.")

        await newGate.release()
        await newTask?.value
        XCTAssertFalse(workspace.isBusy)
        XCTAssertNil(workspace.runningTask)
        XCTAssertNil(workspace.errorMessage)
        XCTAssertEqual(workspace.pages.count, 2, "Only the new import may replace the practice page.")
        XCTAssertFalse(workspace.pages.contains { $0.id == existing.id })
        XCTAssertEqual(workspace.redactionCount, 0)
        XCTAssertFalse(workspace.isSynthetic)
        XCTAssertNil(workspace.review, "A successful new addition must invalidate the former review.")
        XCTAssertEqual(workspace.sharedBatchCount, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: batch.path))
        try assertNoImportStaging()
    }

    private func makeWorkspace(gate: ImportWorkerGate, sharedInbox: URL? = nil) -> Workspace {
        Workspace(temporaryRoot: directory.appendingPathComponent("workspace"), sharedInbox: sharedInbox,
                  importPageLoader: { url in
            let pages = try RasterImporter.load(url: url)
            await gate.pauseIfArmed()
            return pages
        })
    }

    private func makePDF(_ name: String, pages: Int) throws -> URL {
        let url = directory.appendingPathComponent(name)
        var media = CGRect(x: 0, y: 0, width: 100, height: 120)
        let consumer = try XCTUnwrap(CGDataConsumer(url: url as CFURL))
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &media, nil))
        for _ in 0..<pages {
            context.beginPDFPage(nil)
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(media)
            context.endPDFPage()
        }
        context.closePDF()
        return url
    }

    private func makeBatch(pages: Int) throws -> (URL, URL) {
        let source = try makePDF("source.pdf", pages: pages)
        let batch = directory.appendingPathComponent("inbox/batch.ready", isDirectory: true)
        try FileManager.default.createDirectory(at: batch, withIntermediateDirectories: true)
        let queued = batch.appendingPathComponent("source.pdf")
        try FileManager.default.copyItem(at: source, to: queued)
        return (batch, queued)
    }

    private func assertNoImportStaging(file: StaticString = #filePath, line: UInt = #line) throws {
        let children = try FileManager.default.contentsOfDirectory(at: directory.appendingPathComponent("workspace"), includingPropertiesForKeys: nil)
        XCTAssertTrue(children.filter { !$0.lastPathComponent.hasPrefix("export-") }.isEmpty,
                      "No source staging copies may survive import completion.", file: file, line: line)
    }
}

@MainActor
private final class ImportAccess {
    var isPro = true
}

private enum ImportFailure: Error { case afterDecode }

private actor ImportWorkerGate {
    private let arrived: XCTestExpectation
    private var armed = false
    private var continuation: CheckedContinuation<Void, Never>?

    init(arrived: XCTestExpectation) { self.arrived = arrived }
    func arm() { armed = true }

    func pauseIfArmed() async {
        guard armed else { return }
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            arrived.fulfill()
        }
    }

    func release() {
        armed = false
        continuation?.resume()
        continuation = nil
    }
}

private actor ImportWorkerSequence {
    private var gates: [ImportWorkerGate]
    init(_ gates: [ImportWorkerGate]) { self.gates = gates }

    func pauseNext() async {
        guard !gates.isEmpty else { return }
        let gate = gates.removeFirst()
        await gate.pauseIfArmed()
    }
}

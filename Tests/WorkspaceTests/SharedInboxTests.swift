import CoreGraphics
import XCTest
import SanitizerCore
@testable import CleanSend

@MainActor
final class SharedInboxTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("SharedInboxTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    func testLegacyAttachmentPositionsForTenTwelveAndThirtyFiles() {
        for count in [10, 12, 30] {
            let expected = (1...count).map { directory.appendingPathComponent("\($0)-Document.pdf") }
            let shuffled = expected.sorted { $0.lastPathComponent > $1.lastPathComponent }
            XCTAssertEqual(SharedInbox.ordered(shuffled), expected, "Preserve selection order for \(count) legacy files.")
        }
    }

    func testMixedPaddingHugeNumbersAndStableFallback() {
        let names = ["abc.pdf", "10-z.pdf", "0002-b.pdf", "2-a.pdf", "1-a.pdf",
                     "100000000000000000000-c.pdf", "99999999999999999999-c.pdf",
                     "02-a.pdf", "2x-a.pdf", "-1-a.pdf", "٣-a.pdf", "0-zero.pdf"]
        let expected = ["0-zero.pdf", "1-a.pdf", "0002-b.pdf", "02-a.pdf", "2-a.pdf", "10-z.pdf",
                        "99999999999999999999-c.pdf", "100000000000000000000-c.pdf",
                        "-1-a.pdf", "2x-a.pdf", "abc.pdf", "٣-a.pdf"]
        XCTAssertEqual(SharedInbox.ordered(names.map { directory.appendingPathComponent($0) }).map(\.lastPathComponent), expected)
        let first = directory.appendingPathComponent("first/2-same.pdf")
        let second = directory.appendingPathComponent("second/2-same.pdf")
        XCTAssertEqual(SharedInbox.ordered([second, first]), [second, first], "Identical names retain input order.")
    }

    func testListingAndRealImportShareSelectionOrderForTenTwelveAndThirtyFiles() async throws {
        for count in [10, 12, 30] {
            let inbox = directory.appendingPathComponent("inbox-\(count)")
            let batch = inbox.appendingPathComponent("documents.ready")
            try FileManager.default.createDirectory(at: batch, withIntermediateDirectories: true)
            // Reverse creation order; rely on neither directory enumeration nor filenames' lexical order.
            for index in (1...count).reversed() {
                try writePDF(batch.appendingPathComponent("\(index)-Document.pdf"), width: 40 + index)
            }
            let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("workspace-\(count)"), sharedInbox: inbox)
            workspace.checkSharedImports()
            XCTAssertEqual(try XCTUnwrap(workspace.sharedBatches.first).filenames,
                           (1...count).map { "\($0)-Document.pdf" })
            workspace.importShared(currentIsPro: { true })
            await workspace.runningTask?.value
            XCTAssertNil(workspace.errorMessage)
            XCTAssertEqual(workspace.pages.map(\.sourceName), (1...count).map { "\($0)-Document" })
            XCTAssertEqual(workspace.pages.map { $0.image.width }, (1...count).map { 2 * (40 + $0) },
                           "Different actual page widths independently identify the decoded order.")
            XCTAssertFalse(FileManager.default.fileExists(atPath: batch.path))
            workspace.prepareReview()
            await workspace.runningTask?.value
            let review = try XCTUnwrap(workspace.review)
            workspace.export(review, format: .pdf)
            await workspace.runningTask?.value
            XCTAssertNil(workspace.errorMessage)
            let export = try XCTUnwrap(workspace.exported)
            XCTAssertEqual(export.urls.count, 1)
            let reloaded = try RasterImporter.load(url: XCTUnwrap(export.urls.first))
            XCTAssertEqual(reloaded.map { $0.image.width }, (1...count).map { 2 * (40 + $0) },
                           "The exported PDF must retain the selected attachment order.")
            workspace.cleanExport(export)
        }
    }

    func testClearRemovesDisplayedReadyOnlyAndKeepsConcurrentWriterAndArrival() throws {
        let inbox = directory.appendingPathComponent("inbox")
        let displayed = try makeBatch(inbox, name: "displayed.ready")
        let incomplete = try makeBatch(inbox, name: "writer.incomplete")
        let incompleteBytes = try Data(contentsOf: incomplete.appendingPathComponent("1-Document.pdf"))
        let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("workspace"), sharedInbox: inbox)
        workspace.checkSharedImports()
        XCTAssertEqual(workspace.sharedBatches.map(\.id), [displayed])
        let arrived = try makeBatch(inbox, name: "arrived.ready")
        let arrivedBytes = try Data(contentsOf: arrived.appendingPathComponent("1-Document.pdf"))

        workspace.clearShared()

        XCTAssertFalse(FileManager.default.fileExists(atPath: displayed.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: inbox.path))
        XCTAssertEqual(try Data(contentsOf: incomplete.appendingPathComponent("1-Document.pdf")), incompleteBytes)
        XCTAssertEqual(try Data(contentsOf: arrived.appendingPathComponent("1-Document.pdf")), arrivedBytes)
        XCTAssertEqual(workspace.sharedBatches.map(\.id), [arrived])
    }

    func testClearCannotDeleteCancelledImportWhileItsWorkerIsStillReading() async throws {
        let inbox = directory.appendingPathComponent("inbox")
        let reading = try makeBatch(inbox, name: "reading.ready")
        let other = try makeBatch(inbox, name: "other.ready")
        let source = reading.appendingPathComponent("1-Document.pdf")
        let original = try Data(contentsOf: source)
        let arrived = expectation(description: "Real PDF decoded; worker remains active")
        let gate = SharedInboxReadGate(arrived: arrived)
        let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("workspace"), sharedInbox: inbox,
                                  importPageLoader: { url in
            let pages = try RasterImporter.load(url: url)
            await gate.pause()
            return pages
        })
        workspace.checkSharedImports()
        let readingBatch = try XCTUnwrap(workspace.sharedBatches.first { $0.id == reading })
        workspace.importShared(readingBatch)
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        workspace.cancel()
        workspace.discardShared(readingBatch)
        XCTAssertEqual(try? Data(contentsOf: source), original, "Discard must wait until the cancelled worker finishes.")
        XCTAssertNotNil(workspace.errorMessage)
        workspace.clearShared()
        XCTAssertEqual(try? Data(contentsOf: source), original, "Cancellation does not finish the worker synchronously.")
        XCTAssertFalse(FileManager.default.fileExists(atPath: other.path))
        await gate.release()
        await task?.value
        XCTAssertTrue(workspace.pages.isEmpty)
        workspace.clearShared()
        XCTAssertFalse(FileManager.default.fileExists(atPath: reading.path), "The next explicit clear may remove the completed cancelled batch.")
    }

    private func makeBatch(_ inbox: URL, name: String) throws -> URL {
        let batch = inbox.appendingPathComponent(name, isDirectory: true)
        try FileManager.default.createDirectory(at: batch, withIntermediateDirectories: true)
        try writePDF(batch.appendingPathComponent("1-Document.pdf"), width: 60)
        return batch
    }

    private func writePDF(_ url: URL, width: Int) throws {
        var media = CGRect(x: 0, y: 0, width: width, height: 80)
        let consumer = try XCTUnwrap(CGDataConsumer(url: url as CFURL))
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &media, nil))
        context.beginPDFPage(nil)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(media)
        context.endPDFPage()
        context.closePDF()
    }
}

private actor SharedInboxReadGate {
    private let arrived: XCTestExpectation
    private var continuation: CheckedContinuation<Void, Never>?
    private var released = false
    init(arrived: XCTestExpectation) { self.arrived = arrived }
    func pause() async {
        guard !released else { return }
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            arrived.fulfill()
        }
    }
    func release() { released = true; continuation?.resume(); continuation = nil }
}

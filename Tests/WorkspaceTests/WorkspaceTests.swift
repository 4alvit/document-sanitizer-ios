import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
import SanitizerCore
@testable import CleanSend

final class MaskGeometryTests: XCTestCase {
    func testPortraitPageInWideViewAccountsForHorizontalLetterbox() throws {
        let frame = MaskGeometry.fittedFrame(imageSize: CGSize(width: 200, height: 400), in: CGSize(width: 600, height: 400))
        XCTAssertEqual(frame, CGRect(x: 200, y: 0, width: 200, height: 400))
        let rect = try XCTUnwrap(MaskGeometry.normalizedRect(start: CGPoint(x: 220, y: 80), end: CGPoint(x: 320, y: 120), in: frame))
        XCTAssertEqual(rect.x, 0.1, accuracy: 0.000001)
        XCTAssertEqual(rect.y, 0.2, accuracy: 0.000001)
        XCTAssertEqual(rect.width, 0.5, accuracy: 0.000001)
        XCTAssertEqual(rect.height, 0.1, accuracy: 0.000001)
    }

    func testLandscapePageInTallViewAccountsForVerticalLetterbox() throws {
        let frame = MaskGeometry.fittedFrame(imageSize: CGSize(width: 600, height: 200), in: CGSize(width: 300, height: 400))
        XCTAssertEqual(frame, CGRect(x: 0, y: 150, width: 300, height: 100))
        let rect = try XCTUnwrap(MaskGeometry.normalizedRect(start: CGPoint(x: 240, y: 230), end: CGPoint(x: -30, y: 120), in: frame))
        XCTAssertEqual(rect.x, 0, accuracy: 0.000001)
        XCTAssertEqual(rect.y, 0, accuracy: 0.000001)
        XCTAssertEqual(rect.width, 0.8, accuracy: 0.000001)
        XCTAssertEqual(rect.height, 0.8, accuracy: 0.000001)
    }

    func testEdgeDragNeverRoundsBeyondNormalizedPageBounds() throws {
        let frame = CGRect(x: 0, y: 0, width: 288, height: 288)
        let rect = try XCTUnwrap(MaskGeometry.normalizedRect(start: CGPoint(x: 3.3333333333333335, y: 3.3333333333333335), end: CGPoint(x: 288, y: 288), in: frame))
        XCTAssertLessThanOrEqual(rect.x + rect.width, 1)
        XCTAssertLessThanOrEqual(rect.y + rect.height, 1)
    }

    func testLetterboxStartAndTinyOrNonfiniteDragDoNotCreateMask() {
        let frame = CGRect(x: 100, y: 100, width: 100, height: 100)
        XCTAssertNil(MaskGeometry.normalizedRect(start: .zero, end: CGPoint(x: 160, y: 160), in: frame))
        XCTAssertNil(MaskGeometry.normalizedRect(start: CGPoint(x: 120, y: 120), end: CGPoint(x: 122, y: 180), in: frame))
        XCTAssertNil(MaskGeometry.normalizedRect(start: CGPoint(x: 120, y: 120), end: CGPoint(x: CGFloat.infinity, y: 180), in: frame))
        XCTAssertEqual(MaskGeometry.fittedFrame(imageSize: .zero, in: CGSize(width: 100, height: 100)), .zero)
    }
}

@MainActor
final class WorkspaceTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("CleanSendTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: directory) }

    func testExportCreatesItsDirectoryAndPreservesOriginal() async throws {
        let source = try makeSource("original.png")
        let before = try Data(contentsOf: source)
        let workspace = makeWorkspace()
        workspace.importURLs([source], currentIsPro: { false })
        await workspace.runningTask?.value
        XCTAssertNil(workspace.errorMessage)
        let page = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(NormalizedRect(x: 0.1, y: 0.2, width: 0.4, height: 0.3), pageID: page.id)
        workspace.prepareReview(); await workspace.runningTask?.value
        let review = try XCTUnwrap(workspace.review)
        for format in [ExportFormat.png, .jpeg, .pdf] {
            workspace.export(review, format: format); await workspace.runningTask?.value
            XCTAssertNil(workspace.errorMessage, "Failed to export \(format.rawValue)")
            let export = try XCTUnwrap(workspace.exported)
            XCTAssertEqual(export.urls.count, 1)
            let output = try XCTUnwrap(export.urls.first)
            XCTAssertTrue(FileManager.default.fileExists(atPath: output.path))
            XCTAssertEqual(try Data(contentsOf: source), before)
            // Preserve the real iOS encoder output for an independent parser /
            // renderer. Synthetic source: 100x120 white pixels; normalized mask
            // (0.1, 0.2, 0.4, 0.3), corresponding to x10,y24,w40,h36.
            let attachment = XCTAttachment(contentsOfFile: output)
            attachment.name = "ios-encoder-output.\(output.pathExtension)"
            attachment.lifetime = .keepAlways
            add(attachment)
            workspace.cleanExport(export)
            XCTAssertFalse(FileManager.default.fileExists(atPath: export.directory.path))
        }
    }

    func testRejectedFreeAdditionKeepsLargeLoadedPacketExportable() async throws {
        let source = try makeSource("source.png")
        let workspace = makeWorkspace()
        workspace.importURLs(Array(repeating: source, count: 4), currentIsPro: { true })
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 4)
        workspace.importURLs([source], currentIsPro: { false })
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 4)
        XCTAssertNotNil(workspace.errorMessage)
        workspace.errorMessage = nil
        workspace.prepareReview(); await workspace.runningTask?.value
        let review = try XCTUnwrap(workspace.review)
        // Export accepts the reviewed content, with no entitlement precondition.
        workspace.export(review, format: .png); await workspace.runningTask?.value
        XCTAssertEqual(workspace.exported?.urls.count, 4)
        XCTAssertNil(workspace.errorMessage)
    }

    func testEditingInvalidatesAFormerlyReviewedPacket() async throws {
        let workspace = makeWorkspace()
        workspace.loadDemo()
        workspace.prepareReview(); await workspace.runningTask?.value
        let staleReview = try XCTUnwrap(workspace.review)
        let page = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(NormalizedRect(x: 0, y: 0, width: 0.5, height: 0.5), pageID: page.id)
        workspace.export(staleReview, format: .png)
        XCTAssertNil(workspace.exported)
        XCTAssertFalse(workspace.isBusy)
    }

    func testClearCancelsImportWithoutPublishingLatePages() async throws {
        let source = try makeSource("source.png")
        let workspace = makeWorkspace()
        workspace.importURLs([source], currentIsPro: { false })
        let task = workspace.runningTask
        workspace.clear()
        await task?.value
        XCTAssertTrue(workspace.pages.isEmpty)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertNil(workspace.errorMessage)
        let children = try FileManager.default.contentsOfDirectory(at: directory.appendingPathComponent("workspace"), includingPropertiesForKeys: nil)
        XCTAssertTrue(children.isEmpty, "Cancelled imports must remove staged copies.")
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
    }

    func testCancelReviewDoesNotPublishLatePreview() async throws {
        let workspace = makeWorkspace()
        workspace.loadDemo()
        workspace.prepareReview()
        let task = workspace.runningTask
        workspace.cancel()
        await task?.value
        XCTAssertNil(workspace.review)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertEqual(workspace.pages.count, 1)
    }

    func testSharedBatchSuccessConsumesQueueAndFailureRetainsIt() async throws {
        let source = try makeSource("source.png")
        let inbox = directory.appendingPathComponent("inbox", isDirectory: true)
        let good = inbox.appendingPathComponent("good.ready", isDirectory: true)
        try FileManager.default.createDirectory(at: good, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: source, to: good.appendingPathComponent("source.png"))
        let workspace = makeWorkspace(sharedInbox: inbox)
        workspace.checkSharedImports()
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        workspace.importShared(currentIsPro: { false }); await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 1)
        XCTAssertEqual(workspace.sharedBatchCount, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: good.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
        let rejected = inbox.appendingPathComponent("rejected.ready", isDirectory: true)
        try FileManager.default.createDirectory(at: rejected, withIntermediateDirectories: true)
        for index in 0..<3 { try FileManager.default.copyItem(at: source, to: rejected.appendingPathComponent("\(index).png")) }
        workspace.importShared(currentIsPro: { false }); await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 1, "Failed imports must not partially append pages.")
        XCTAssertTrue(FileManager.default.fileExists(atPath: rejected.path), "A failed shared import must remain retryable.")
        workspace.clear()
        XCTAssertTrue(FileManager.default.fileExists(atPath: rejected.path), "Clearing current edits must preserve unrelated queued copies.")
        workspace.clearShared()
        XCTAssertTrue(FileManager.default.fileExists(atPath: inbox.path), "The shared root must survive so another extension can finish writing.")
        XCTAssertFalse(FileManager.default.fileExists(atPath: rejected.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: source.path))
    }

    func testIndependentSharedBatchesDoNotBlockOneAnother() async throws {
        let source = try makeSource("source.png")
        let inbox = directory.appendingPathComponent("inbox", isDirectory: true)
        for name in ["a.ready", "b.ready"] {
            let batch = inbox.appendingPathComponent(name, isDirectory: true)
            try FileManager.default.createDirectory(at: batch, withIntermediateDirectories: true)
            for index in 0..<2 { try FileManager.default.copyItem(at: source, to: batch.appendingPathComponent("\(index).png")) }
        }
        let corrupt = inbox.appendingPathComponent("bad.ready", isDirectory: true)
        try FileManager.default.createDirectory(at: corrupt, withIntermediateDirectories: true)
        try Data("not an image".utf8).write(to: corrupt.appendingPathComponent("broken.png"))
        let workspace = makeWorkspace(sharedInbox: inbox)
        workspace.checkSharedImports()
        let badBatch = try XCTUnwrap(workspace.sharedBatches.first { $0.id.lastPathComponent == "bad.ready" })
        workspace.importShared(badBatch, currentIsPro: { false }); await workspace.runningTask?.value
        XCTAssertTrue(workspace.pages.isEmpty)
        XCTAssertEqual(workspace.sharedBatchCount, 3)
        workspace.errorMessage = nil
        let first = try XCTUnwrap(workspace.sharedBatches.first { $0.id.lastPathComponent == "a.ready" })
        workspace.importShared(first, currentIsPro: { false }); await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 2)
        XCTAssertEqual(workspace.sharedBatchCount, 2)
        workspace.clear()
        let second = try XCTUnwrap(workspace.sharedBatches.first { $0.id.lastPathComponent == "b.ready" })
        workspace.importShared(second, currentIsPro: { false }); await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 2)
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        workspace.discardShared(badBatch)
        XCTAssertEqual(workspace.sharedBatchCount, 0)
    }

    func testListingPrunesExpiredSharedBatches() throws {
        let inbox = directory.appendingPathComponent("inbox", isDirectory: true)
        let expired = inbox.appendingPathComponent("old.ready", isDirectory: true)
        try FileManager.default.createDirectory(at: expired, withIntermediateDirectories: true)
        let workspace = makeWorkspace(sharedInbox: inbox)
        try FileManager.default.setAttributes([.creationDate: Date().addingTimeInterval(-90_000)], ofItemAtPath: expired.path)
        workspace.checkSharedImports()
        XCTAssertEqual(workspace.sharedBatchCount, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: expired.path))
    }

    private func makeWorkspace(sharedInbox: URL? = nil) -> Workspace {
        Workspace(temporaryRoot: directory.appendingPathComponent("workspace", isDirectory: true), sharedInbox: sharedInbox)
    }
    private func makeSource(_ name: String) throws -> URL {
        let context = try XCTUnwrap(CGContext(data: nil, width: 100, height: 120, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue))
        context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 100, height: 120))
        let url = directory.appendingPathComponent(name)
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try XCTUnwrap(context.makeImage()), nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return url
    }
}

import CoreGraphics
import PDFKit
import SanitizerCore
import XCTest
@testable import CleanSend

@MainActor
final class WorkspaceErrorTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("WorkspaceErrors-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: directory) }

    func testLockedPDFExplainsUnlockAndPreservesCurrentReview() async throws {
        let source = try makePDF(pages: 1, locked: true)
        XCTAssertTrue(try XCTUnwrap(PDFDocument(url: source)).isLocked)
        try await assertRejectedImport(source, expected: SanitizerError.lockedPDF.errorDescription)
    }

    func testPageLimitExplainsWhySmallButLongPDFWasRejected() async throws {
        let source = try makePDF(pages: 31)
        XCTAssertEqual(try XCTUnwrap(PDFDocument(url: source)).pageCount, 31)
        try await assertRejectedImport(source, expected: SanitizerError.tooManyPages.errorDescription)
    }

    func testUnknownProviderFailureDoesNotExposeItsDescription() async throws {
        let source = try makePDF(pages: 1)
        let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("workspace"), sharedInbox: nil,
                                  importPageLoader: { _ in
            throw NSError(domain: "private-provider", code: 19, userInfo: [NSLocalizedDescriptionKey: "SENSITIVE_DOCUMENT_NAME_AND_CONTENT"])
        })
        workspace.loadDemo()
        let before = workspace.pages.map(\.id)
        workspace.importURLs([source])
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.map(\.id), before)
        let message = try XCTUnwrap(workspace.errorMessage)
        XCTAssertTrue(message.contains("Could not complete"))
        XCTAssertFalse(message.contains("SENSITIVE"))
        XCTAssertFalse(message.contains("private-provider"))
    }

    private func assertRejectedImport(_ source: URL, expected: String?) async throws {
        let original = try Data(contentsOf: source)
        let root = directory.appendingPathComponent("workspace")
        let workspace = Workspace(temporaryRoot: root, sharedInbox: nil)
        workspace.loadDemo()
        let existing = try XCTUnwrap(workspace.pages.first)
        workspace.addMask(.init(x: 0.1, y: 0.1, width: 0.2, height: 0.1), pageID: existing.id)
        workspace.prepareReview()
        await workspace.runningTask?.value
        let review = try XCTUnwrap(workspace.review)
        workspace.importURLs([source])
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.errorMessage, expected)
        XCTAssertEqual(workspace.pages.map(\.id), [existing.id])
        XCTAssertEqual(workspace.redactionCount, 1)
        XCTAssertEqual(workspace.review?.id, review.id)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertEqual(try Data(contentsOf: source), original)
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: root.path).isEmpty)
    }

    private func makePDF(pages: Int, locked: Bool = false) throws -> URL {
        let source = directory.appendingPathComponent("synthetic-\(UUID().uuidString).pdf")
        var box = CGRect(x: 0, y: 0, width: 20, height: 20)
        let consumer = try XCTUnwrap(CGDataConsumer(url: source as CFURL))
        let options: [CFString: Any] = locked ? [kCGPDFContextUserPassword: "synthetic-password", kCGPDFContextOwnerPassword: "synthetic-owner"] : [:]
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &box, options as CFDictionary))
        for _ in 0..<pages {
            context.beginPDFPage(nil)
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(box)
            context.endPDFPage()
        }
        context.closePDF()
        return source
    }
}

import XCTest
import UIKit
import UniformTypeIdentifiers
@testable import CleanSend

@MainActor
final class ShareCompletionTests: XCTestCase {
    func testSharePreviewKeepsExactFileURLForEveryActivity() throws {
        // No file is created: preparing metadata and returning an item must not
        // require reading, rendering, or rewriting the exported file.
        let url = URL(fileURLWithPath: "/not-created/RedactLeaf-export.pdf")
        let item = ExportActivityItemSource(url: url)
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        XCTAssertEqual(item.activityViewControllerPlaceholderItem(controller) as? URL, url)
        let types: [UIActivity.ActivityType?] = [nil, .copyToPasteboard, .mail, .message, .print,
            UIActivity.ActivityType(rawValue: "test.third-party.share")]
        for type in types {
            XCTAssertEqual(item.activityViewController(controller, itemForActivityType: type) as? URL, url)
        }
        let metadata = try XCTUnwrap(item.activityViewControllerLinkMetadata(controller))
        XCTAssertEqual(metadata.originalURL, url)
        XCTAssertEqual(metadata.url, url)
        XCTAssertTrue(try XCTUnwrap(metadata.url).isFileURL)
        XCTAssertEqual(metadata.title, url.lastPathComponent)
        XCTAssertNil(metadata.remoteVideoURL)
        XCTAssertNil(metadata.videoProvider)
        XCTAssertTrue(metadata === item.activityViewControllerLinkMetadata(controller))
    }

    func testSharePreviewPreservesMultipleFileOrderAndIdentity() throws {
        let urls = ["RedactLeaf-page-3.png", "RedactLeaf-page-1.jpeg", "RedactLeaf-export.pdf"]
            .map { URL(fileURLWithPath: "/not-created/\($0)") }
        let items = ExportActivityItemSource.items(for: urls)
        let controller = UIActivityViewController(activityItems: [urls[0]], applicationActivities: nil)
        XCTAssertEqual(items.count, urls.count)
        XCTAssertTrue(ExportActivityItemSource.items(for: []).isEmpty)
        for (index, item) in items.enumerated() {
            XCTAssertEqual(item.activityViewControllerPlaceholderItem(controller) as? URL, urls[index])
            XCTAssertEqual(item.activityViewController(controller, itemForActivityType: nil) as? URL, urls[index])
            let metadata = try XCTUnwrap(item.activityViewControllerLinkMetadata(controller))
            XCTAssertEqual(metadata.originalURL, urls[index])
            XCTAssertEqual(metadata.url, urls[index])
            XCTAssertEqual(metadata.title, urls[index].lastPathComponent)
        }
    }

    func testSharePreviewProvidesSmallGenericPNGWithoutDocumentAccess() async throws {
        let controller = UIActivityViewController(activityItems: [URL(fileURLWithPath: "/not-created/RedactLeaf-export.pdf")], applicationActivities: nil)
        let completed = expectation(description: "Prepared PNG representations")
        completed.expectedFulfillmentCount = 2
        for name in ["RedactLeaf-export.pdf", "RedactLeaf-page-1.png"] {
            let item = ExportActivityItemSource(url: URL(fileURLWithPath: "/not-created/\(name)"))
            let metadata = try XCTUnwrap(item.activityViewControllerLinkMetadata(controller))
            let provider = try XCTUnwrap(metadata.imageProvider)
            XCTAssertTrue(provider === metadata.iconProvider)
            XCTAssertTrue(provider.hasItemConformingToTypeIdentifier(UTType.png.identifier))
            provider.loadDataRepresentation(forTypeIdentifier: UTType.png.identifier) { data, error in
                XCTAssertNil(error)
                if let data, let image = UIImage(data: data) {
                    XCTAssertGreaterThan(data.count, 0)
                    XCTAssertLessThanOrEqual(data.count, 32 * 1024)
                    XCTAssertEqual(image.cgImage?.width, 64)
                    XCTAssertEqual(image.cgImage?.height, 64)
                } else {
                    XCTFail("Missing prepared PNG preview")
                }
                completed.fulfill()
            }
        }
        await fulfillment(of: [completed], timeout: 3)
    }

    func testShareCompletionRefreshesNewQueueWithoutConsumingIt() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ShareCompletionTests-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        let inbox = root.appendingPathComponent("SharedInbox")
        let workspace = Workspace(temporaryRoot: root.appendingPathComponent("workspace"), sharedInbox: inbox)
        workspace.checkSharedImports()
        XCTAssertEqual(workspace.sharedBatchCount, 0)

        let exportDirectory = root.appendingPathComponent("export")
        try FileManager.default.createDirectory(at: exportDirectory, withIntermediateDirectories: true)
        let exportedFile = exportDirectory.appendingPathComponent("synthetic.pdf")
        let bytes = Data("Synthetic share-completion fixture".utf8)
        try bytes.write(to: exportedFile)
        let packet = ExportPacket(directory: exportDirectory, urls: [exportedFile])
        workspace.exported = packet

        // The extension finishes after the app's initial queue read, while
        // its scene remains active. Completion must discover this new batch.
        let batch = inbox.appendingPathComponent("new.ready", isDirectory: true)
        try FileManager.default.createDirectory(at: batch, withIntermediateDirectories: true)
        let queuedFile = batch.appendingPathComponent("synthetic.pdf")
        try bytes.write(to: queuedFile)
        XCTAssertEqual(workspace.sharedBatchCount, 0)

        workspace.cleanExport(packet)
        XCTAssertNil(workspace.exported)
        XCTAssertFalse(FileManager.default.fileExists(atPath: exportDirectory.path))
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(workspace.sharedBatches.first?.id, batch)
        XCTAssertEqual(try Data(contentsOf: queuedFile), bytes)

        // Completion and sheet disappearance may both deliver cleanup.
        workspace.cleanExport(packet)
        XCTAssertEqual(workspace.sharedBatchCount, 1)
        XCTAssertEqual(try Data(contentsOf: queuedFile), bytes)
    }
}

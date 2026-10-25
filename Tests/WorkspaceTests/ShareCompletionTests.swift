import XCTest
@testable import CleanSend

@MainActor
final class ShareCompletionTests: XCTestCase {
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

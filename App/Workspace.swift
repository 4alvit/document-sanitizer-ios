import SwiftUI
import UniformTypeIdentifiers
import SanitizerCore

struct ProposedMask: Identifiable {
    let id = UUID()
    let pageID: UUID
    let pageNumber: Int
    let match: OCRMatch
}

struct ReviewedPage: Identifiable {
    let id: UUID
    let label: String
    let image: CGImage
}

struct ReviewPacket: Identifiable {
    let id = UUID()
    let revision: UUID
    let pages: [ReviewedPage]
}

struct PresetApplicationPreview: Identifiable {
    let id = UUID()
    let presetID: UUID
    let presetName: String
    let targetPageID: UUID
    let targetPageNumber: Int
    let image: CGImage
    var addedAreaCount: Int { additions.count }
    fileprivate let revision: UUID
    fileprivate let additions: [NormalizedRect]
}

struct SharedBatch: Identifiable {
    let id: URL
    let filenames: [String]
}

struct ExportPacket: Identifiable {
    let id = UUID()
    let directory: URL
    let urls: [URL]
}

@MainActor
final class Workspace: ObservableObject {
    typealias ImportPageLoader = @Sendable (URL) async throws -> [RasterPage]
    typealias PresetRenderer = @Sendable (RasterPage) async throws -> CGImage

    @Published private(set) var pages: [RasterPage] = []
    @Published var selectedPageID: UUID?
    @Published private(set) var isBusy = false
    @Published private(set) var busyLabel = ""
    @Published var errorMessage: String?
    @Published var proposals: [ProposedMask] = []
    @Published var review: ReviewPacket?
    @Published private(set) var presetPreview: PresetApplicationPreview?
    @Published var exported: ExportPacket?
    @Published private(set) var sharedBatches: [SharedBatch] = []
    var sharedBatchCount: Int { sharedBatches.count }
    @Published private(set) var isSynthetic = false
    private var revision = UUID()
    private var operationID = UUID()
    private(set) var runningTask: Task<Void, Never>?
    #if DEBUG && targetEnvironment(simulator)
    /// Observation only: added pages, total pages, and the authorization used.
    var importCommitDiagnostic: (@MainActor (Int, Int, Bool) -> Void)?
    #endif
    private let pixelLimit = 24_000_000
    private let pageLimit = 30
    private let root: URL
    private let sharedRoot: URL?
    private let importPageLoader: ImportPageLoader
    private let presetRenderer: PresetRenderer
    private var presetOperationID: UUID?
    // A cancelled worker can still be unwinding when another import starts.
    // Keep protection per operation until each worker has finished cleanup.
    private var inFlightSharedBatches: [UUID: Set<URL>] = [:]

    init(temporaryRoot: URL = FileManager.default.temporaryDirectory.appendingPathComponent("CleanSend", isDirectory: true),
         sharedInbox: URL? = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.io.github.4alvit.cleansend")?.appendingPathComponent("SharedInbox", isDirectory: true),
         importPageLoader: @escaping ImportPageLoader = { try RasterImporter.load(url: $0) },
         presetRenderer: @escaping PresetRenderer = { try RasterSanitizer.render($0) }) {
        root = temporaryRoot
        sharedRoot = sharedInbox
        self.importPageLoader = importPageLoader
        self.presetRenderer = presetRenderer
        // This app has one ephemeral workspace. Clean leftovers from interrupted prior runs.
        try? FileManager.default.removeItem(at: root)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        pruneExpiredSharedFiles()
    }

    var selectedPage: RasterPage? { pages.first { $0.id == selectedPageID } ?? pages.first }
    var redactionCount: Int { pages.reduce(0) { $0 + $1.redactions.count } }

    func checkSharedImports() {
        pruneExpiredSharedFiles()
        sharedBatches = sharedDirectories().map { url in
            let names = SharedInbox.orderedFiles(in: url).map(\.lastPathComponent)
            return SharedBatch(id: url, filenames: names)
        }
    }

    private func sharedDirectories() -> [URL] {
        guard let sharedRoot else { return [] }
        return ((try? FileManager.default.contentsOfDirectory(at: sharedRoot, includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey])) ?? [])
            .filter { url in
                guard url.pathExtension == "ready",
                      let values = try? url.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey]) else { return false }
                return values.isDirectory == true && values.isSymbolicLink != true
            }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    private func pruneExpiredSharedFiles() {
        guard let sharedRoot, let children = try? FileManager.default.contentsOfDirectory(at: sharedRoot, includingPropertiesForKeys: [.creationDateKey]) else { return }
        for url in children {
            guard ["ready", "incomplete"].contains(url.pathExtension) else { continue }
            guard !inFlightSharedBatches.values.contains(where: { $0.contains(url) }) else { continue }
            guard let created = (try? url.resourceValues(forKeys: [.creationDateKey]))?.creationDate else { continue }
            if Date().timeIntervalSince(created) > 86_400 { try? FileManager.default.removeItem(at: url) }
        }
    }

    func importShared(_ batch: SharedBatch? = nil, currentIsPro: @escaping @MainActor () -> Bool = { false }) {
        checkSharedImports()
        guard let selected = batch ?? sharedBatches.first,
              sharedBatches.contains(where: { $0.id == selected.id }) else { return }
        let urls = SharedInbox.orderedFiles(in: selected.id)
        guard !urls.isEmpty else { errorMessage = L10n.text("This shared batch is empty. Discard it and share the files again."); return }
        importURLs(urls, currentIsPro: currentIsPro, consumedBatches: [selected.id])
    }

    func discardShared(_ batch: SharedBatch) {
        guard !isBusy, sharedDirectories().contains(batch.id) else { return }
        guard !inFlightSharedBatches.values.contains(where: { $0.contains(batch.id) }) else {
            errorMessage = L10n.text("These queued files are still in use. Try discarding them again after the current operation finishes.")
            return
        }
        do { try FileManager.default.removeItem(at: batch.id) }
        catch { errorMessage = L10n.text("The queued files could not be removed. Try again after closing other operations.") }
        checkSharedImports()
    }

    func clearShared() {
        guard !isBusy else { return }
        // Clear the displayed, completed batches only. Removing the queue root
        // can destroy a different process's in-progress Share Extension copy,
        // or a newly committed batch that the person has never seen.
        let displayed = Set(sharedBatches.map(\.id))
        let protected = inFlightSharedBatches.values.reduce(into: Set<URL>()) { $0.formUnion($1) }
        var couldNotRemove = false
        for url in sharedDirectories() where displayed.contains(url) {
            guard !protected.contains(url) else { couldNotRemove = true; continue }
            do { try FileManager.default.removeItem(at: url) }
            catch { couldNotRemove = true }
        }
        checkSharedImports()
        if couldNotRemove { errorMessage = L10n.text("Some queued files are still in use or could not be removed. Try clearing them again after the current operation finishes.") }
    }

    func importURLs(_ urls: [URL], currentIsPro: @escaping @MainActor () -> Bool = { false }, consumedBatches: [URL] = []) {
        guard !isBusy, !urls.isEmpty else { return }
        guard urls.count <= 30 else { errorMessage = L10n.text("Choose at most 30 files at a time."); return }
        let existingPages = pages.count
        let existingPixels = pages.reduce(0) { $0 + $1.image.width * $1.image.height }
        let isPro = currentIsPro()
        let permittedPages = permittedImportPages(isPro: isPro)
        let pixelLimit = pixelLimit
        let importPageLoader = importPageLoader
        let operation = begin(L10n.text("Importing clean working copies…"))
        let staging = root.appendingPathComponent(UUID().uuidString, isDirectory: true)
        inFlightSharedBatches[operation] = Set(consumedBatches)
        runningTask = Task {
            defer { inFlightSharedBatches[operation] = nil }
            do {
                let imported = try await offMain {
                    try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true, attributes: [.protectionKey: FileProtectionType.complete])
                    defer { try? FileManager.default.removeItem(at: staging) }
                    var result: [RasterPage] = []
                    var pixels = existingPixels
                    for url in urls {
                        try Task.checkCancellation()
                        let scoped = url.startAccessingSecurityScopedResource()
                        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .isSymbolicLinkKey])
                        guard values.isRegularFile == true, values.isSymbolicLink != true,
                              let size = values.fileSize, size <= 50 * 1024 * 1024 else {
                            throw WorkspaceError.message(L10n.text("Each source must be a regular PDF or image file up to 50 MB."))
                        }
                        let local = staging.appendingPathComponent(UUID().uuidString).appendingPathExtension(url.pathExtension)
                        try FileManager.default.copyItem(at: url, to: local)
                        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: local.path)
                        var incoming = try await importPageLoader(local)
                        for index in incoming.indices { incoming[index].sourceName = url.deletingPathExtension().lastPathComponent }
                        try FileManager.default.removeItem(at: local)
                        guard existingPages + result.count + incoming.count <= permittedPages else {
                            throw WorkspaceError.pageCapacity(isPro: isPro)
                        }
                        pixels += incoming.reduce(0) { $0 + $1.image.width * $1.image.height }
                        guard pixels <= pixelLimit else { throw WorkspaceError.message(L10n.text("This batch is too large for safe processing. Split it into smaller batches (24 million working pixels maximum).")) }
                        result.append(contentsOf: incoming)
                    }
                    try Task.checkCancellation()
                    return result
                }
                guard operationID == operation else { return }
                // The worker's initial capacity is only an early rejection.
                // Read the delivered entitlement again on the main actor, with
                // no suspension between authorization, publication and consume.
                let liveIsPro = currentIsPro()
                guard pages.count + imported.count <= permittedImportPages(isPro: liveIsPro) else {
                    throw WorkspaceError.pageCapacity(isPro: liveIsPro)
                }
                pages.append(contentsOf: imported)
                #if DEBUG && targetEnvironment(simulator)
                importCommitDiagnostic?(imported.count, pages.count, liveIsPro)
                #endif
                if selectedPageID == nil { selectedPageID = pages.first?.id }
                isSynthetic = false
                changed()
                for batch in consumedBatches { try? FileManager.default.removeItem(at: batch) }
                checkSharedImports()
                finish(operation)
            } catch { fail(error, operation) }
        }
    }

    func loadDemo() {
        guard !isBusy, pages.isEmpty else { return }
        let format = UIGraphicsImageRendererFormat(); format.scale = 1; format.opaque = true
        let image = UIGraphicsImageRenderer(size: CGSize(width: 900, height: 1200), format: format).image { context in
            UIColor.white.setFill(); context.fill(CGRect(x: 0, y: 0, width: 900, height: 1200))
            let title: [NSAttributedString.Key: Any] = [.font: UIFont.boldSystemFont(ofSize: 44), .foregroundColor: UIColor.black]
            let body: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 30), .foregroundColor: UIColor.black]
            L10n.text("SYNTHETIC SAMPLE").draw(in: CGRect(x: 70, y: 80, width: 760, height: 60), withAttributes: title)
            L10n.text("No real personal information").draw(in: CGRect(x: 70, y: 150, width: 760, height: 80), withAttributes: body)
            let lines = [
                L10n.text("SERVICE RECEIPT"),
                L10n.format("Customer: %@", "Alex Example"),
                L10n.format("Email: %@", "alex@example.invalid"),
                L10n.format("Address: %@", "123 Example Street"),
                L10n.format("Reference: %@", "DEMO-2048"),
                L10n.text("Service: Window repair"),
                L10n.format("Total: %@", L10n.currency(125, code: "USD")),
                L10n.text("Try hiding the customer and email.")
            ]
            for (index, line) in lines.enumerated() { line.draw(in: CGRect(x: 70, y: 270 + index * 80, width: 760, height: 80), withAttributes: body) }
        }
        guard let cgImage = image.cgImage else { return }
        let page = RasterPage(image: cgImage, sourceName: L10n.text("Synthetic receipt"), sourcePageNumber: 1)
        pages = [page]; selectedPageID = page.id; isSynthetic = true; changed()
    }

    func addMask(_ rect: NormalizedRect, pageID: UUID) {
        guard !isBusy, let index = pages.firstIndex(where: { $0.id == pageID }) else { return }
        pages[index].redactions.append(Redaction(rect: rect)); changed()
    }

    func removeMask(_ id: UUID, pageID: UUID) {
        guard !isBusy, let index = pages.firstIndex(where: { $0.id == pageID }) else { return }
        pages[index].redactions.removeAll { $0.id == id }; changed()
    }

    func removePage(_ id: UUID) {
        guard !isBusy else { return }
        pages.removeAll { $0.id == id }; selectedPageID = pages.first?.id; changed()
    }

    func search(_ query: String) {
        guard !isBusy, !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let snapshot = pages
        let operation = begin(L10n.text("Finding text across this batch…"))
        runningTask = Task {
            do {
                let matches = try await offMain {
                    var result: [ProposedMask] = []
                    for (index, page) in snapshot.enumerated() {
                        try Task.checkCancellation()
                        for match in try await TextRecognizer.matches(in: page.image, query: query) {
                            result.append(ProposedMask(pageID: page.id, pageNumber: index + 1, match: match))
                        }
                    }
                    return result
                }
                guard operationID == operation else { return }
                proposals = matches
                finish(operation)
                if matches.isEmpty { errorMessage = L10n.text("No matching text was found. OCR can miss text; inspect the pages and add masks manually.") }
            } catch { fail(error, operation) }
        }
    }

    func acceptProposals(_ ids: Set<UUID>) {
        for proposed in proposals where ids.contains(proposed.id) {
            guard let index = pages.firstIndex(where: { $0.id == proposed.pageID }) else { continue }
            pages[index].redactions.append(Redaction(rect: proposed.match.rect))
        }
        proposals = []; changed()
    }

    func preparePresetApplication(_ preset: MaskPreset, pageID: UUID) {
        // Choosing another preset may supersede a preset render, but must never
        // cancel an unrelated import, OCR, review or export operation.
        guard !isBusy || presetOperationID == operationID else { return }
        cancelPresetApplication()
        guard let index = pages.firstIndex(where: { $0.id == pageID }) else {
            errorMessage = L10n.text("The target page is no longer available. Choose a page and try again.")
            return
        }
        guard !preset.rectangles.isEmpty, preset.rectangles.count <= MaskPresetStore.maximumRectangles,
              preset.rectangles.allSatisfy(\.isValid) else {
            errorMessage = L10n.text("This saved preset has invalid areas and cannot be applied.")
            return
        }
        var seen = Set(pages[index].redactions.map(\.rect))
        let additions = preset.rectangles.filter { seen.insert($0).inserted }
        var provisional = pages[index]
        provisional.redactions.append(contentsOf: additions.map { Redaction(rect: $0) })
        let previewPage = provisional
        let capturedRevision = revision
        let render = presetRenderer
        let operation = begin(L10n.text("Preparing preset placement…"))
        presetOperationID = operation
        runningTask = Task {
            do {
                let image = try await offMain { try await render(previewPage) }
                guard operationID == operation else { return }
                guard revision == capturedRevision, pages.contains(where: { $0.id == pageID }) else {
                    finish(operation)
                    return
                }
                presetPreview = PresetApplicationPreview(presetID: preset.id, presetName: preset.name,
                    targetPageID: pageID, targetPageNumber: index + 1, image: image,
                    revision: capturedRevision, additions: additions)
                finish(operation)
            } catch { fail(error, operation) }
        }
    }

    @discardableResult
    func commitPresetApplication(_ preview: PresetApplicationPreview) -> Bool {
        guard !isBusy, presetPreview?.id == preview.id,
              preview.revision == revision,
              let index = pages.firstIndex(where: { $0.id == preview.targetPageID }) else {
            errorMessage = L10n.text("This placement preview is no longer current. Preview the preset again before applying it.")
            return false
        }
        guard preview.additions.allSatisfy(\.isValid) else {
            errorMessage = L10n.text("This saved preset has invalid areas and cannot be applied.")
            return false
        }
        // Keep both existing masks and their identities. Exact geometry alone
        // defines a duplicate; overlapping rectangles remain distinct masks.
        var seen = Set(pages[index].redactions.map(\.rect))
        let additions = preview.additions.filter { seen.insert($0).inserted }
        presetPreview = nil
        guard !additions.isEmpty else { return true }
        pages[index].redactions.append(contentsOf: additions.map { Redaction(rect: $0) })
        changed()
        return true
    }

    func cancelPresetApplication() {
        presetPreview = nil
        if presetOperationID == operationID { cancel() }
    }

    func prepareReview() {
        guard !isBusy, !pages.isEmpty else { return }
        let snapshot = pages, currentRevision = revision
        let operation = begin(L10n.text("Rendering the export preview…"))
        runningTask = Task {
            do {
                let rendered = try await offMain {
                    try snapshot.enumerated().map { index, page in
                        try Task.checkCancellation()
                        return ReviewedPage(id: page.id, label: L10n.format("Page %@", L10n.number(index + 1)), image: try RasterSanitizer.render(page))
                    }
                }
                guard operationID == operation else { return }
                review = ReviewPacket(revision: currentRevision, pages: rendered); finish(operation)
            } catch { fail(error, operation) }
        }
    }

    func export(_ packet: ReviewPacket, format: ExportFormat) {
        guard !isBusy, packet.revision == revision else { return }
        let snapshot = pages
        let operation = begin(L10n.text("Writing clean copies…"))
        let directory = root.appendingPathComponent("export-\(UUID().uuidString)", isDirectory: true)
        runningTask = Task {
            do {
                let urls = try await offMain {
                    do {
                        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.protectionKey: FileProtectionType.complete])
                        let urls = try RasterExporter.export(pages: snapshot, format: format, to: directory)
                        for url in urls { try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: url.path) }
                        try Task.checkCancellation()
                        return urls
                    } catch {
                        try? FileManager.default.removeItem(at: directory)
                        throw error
                    }
                }
                guard operationID == operation else { try? FileManager.default.removeItem(at: directory); return }
                exported = ExportPacket(directory: directory, urls: urls); finish(operation)
            } catch { fail(error, operation) }
        }
    }

    func cleanExport(_ packet: ExportPacket) {
        try? FileManager.default.removeItem(at: packet.directory)
        if exported?.id == packet.id { exported = nil }
        // A share extension can queue files without the containing scene
        // leaving its active phase. Refresh after the activity completes too.
        checkSharedImports()
    }

    func clear() {
        cancel()
        pages = []; selectedPageID = nil; proposals = []; review = nil; isSynthetic = false
        if let exported { cleanExport(exported) }
        changed()
    }

    func cancel() {
        runningTask?.cancel(); runningTask = nil; operationID = UUID(); isBusy = false
        presetOperationID = nil; presetPreview = nil
    }

    private func changed() { revision = UUID(); proposals = []; review = nil; presetPreview = nil }
    private func permittedImportPages(isPro: Bool) -> Int { isPro ? pageLimit : max(3, pages.count) }
    private func begin(_ label: String) -> UUID { operationID = UUID(); busyLabel = label; isBusy = true; presetPreview = nil; return operationID }
    private func finish(_ id: UUID) {
        guard operationID == id else { return }
        isBusy = false; runningTask = nil
        if presetOperationID == id { presetOperationID = nil }
    }
    private func fail(_ error: Error, _ id: UUID) {
        guard operationID == id else { return }
        finish(id)
        guard !(error is CancellationError) else { return }
        // These are fixed application messages, never provider descriptions
        // that may disclose paths or document contents. Keep useful recovery
        // instructions for a locked PDF, a size limit or an invalid mask.
        errorMessage = (error as? WorkspaceError)?.errorDescription
            ?? (error as? SanitizerError)?.errorDescription
            ?? L10n.text("Could not complete this operation. The source may be unsupported, encrypted, damaged, too large, or storage may be full. Your originals and current workspace were not changed.")
    }
}

private enum WorkspaceError: LocalizedError {
    case message(String)
    case pageCapacity(isPro: Bool)

    var errorDescription: String? {
        switch self {
        case .message(let text): return text
        case .pageCapacity(let isPro):
            return isPro ? L10n.text("A workspace holds up to 30 pages.") : L10n.text("Free workspaces hold up to 3 pages. Clear this workspace to start a new one, or unlock Pro for larger batches. Your current pages can still be exported.")
        }
    }
}

private func offMain<T>(_ body: @escaping @Sendable () async throws -> T) async throws -> T {
    let worker = Task.detached(priority: .userInitiated, operation: body)
    return try await withTaskCancellationHandler(operation: { try await worker.value }, onCancel: { worker.cancel() })
}

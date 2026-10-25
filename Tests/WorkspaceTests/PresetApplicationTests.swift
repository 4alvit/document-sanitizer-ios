import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
import SanitizerCore
@testable import CleanSend

@MainActor
final class PresetApplicationTests: XCTestCase {
    private var directory: URL!
    private let a = NormalizedRect(x: 0.1, y: 0.2, width: 0.3, height: 0.4)
    private let b = NormalizedRect(x: 0.6, y: 0.1, width: 0.2, height: 0.2)

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("PresetApplicationTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: directory) }

    func testPreviewAndCancelPreserveManualMasksAndFinalReview() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace)
        workspace.addMask(a, pageID: page.id)
        let review = try await prepareReview(in: workspace)
        let masks = workspace.pages[0].redactions
        let preview = try await prepare(MaskPreset(name: "More areas", rectangles: [b]), in: workspace, pageID: page.id)
        XCTAssertEqual(preview.targetPageID, page.id)
        XCTAssertEqual(preview.targetPageNumber, 1)
        XCTAssertEqual(preview.presetName, "More areas")
        XCTAssertEqual(preview.addedAreaCount, 1)
        XCTAssertEqual(workspace.pages[0].redactions, masks)
        XCTAssertEqual(workspace.review?.id, review.id)
        workspace.cancelPresetApplication()
        XCTAssertNil(workspace.presetPreview)
        XCTAssertEqual(workspace.pages[0].redactions, masks)
        XCTAssertEqual(workspace.review?.id, review.id)
        XCTAssertFalse(workspace.commitPresetApplication(preview))
        XCTAssertEqual(workspace.pages[0].redactions, masks)
    }

    func testApplyIsAdditiveExactIdempotentAndRestoresOnlyMissingGeometry() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace)
        workspace.addMask(a, pageID: page.id)
        let oldMask = workspace.pages[0].redactions[0]
        let oldReview = try await prepareReview(in: workspace)
        // Merely overlapping rectangles must remain distinct; exact duplicates
        // in both the document and the preset are the only ones omitted.
        let overlap = NormalizedRect(x: 0.11, y: 0.2, width: 0.3, height: 0.4)
        let preset = MaskPreset(name: "Exact areas", rectangles: [a, b, b, overlap])
        let preview = try await prepare(preset, in: workspace, pageID: page.id)
        XCTAssertEqual(preview.addedAreaCount, 2)
        XCTAssertTrue(workspace.commitPresetApplication(preview))
        XCTAssertEqual(workspace.pages[0].redactions.map(\.rect), [a, b, overlap])
        XCTAssertEqual(workspace.pages[0].redactions[0], oldMask)
        XCTAssertEqual(Set(workspace.pages[0].redactions.map(\.id)).count, 3)
        XCTAssertNil(workspace.review)
        workspace.export(oldReview, format: .png)
        XCTAssertNil(workspace.exported, "A new mask must invalidate the entire former review packet.")

        let currentReview = try await prepareReview(in: workspace)
        let currentMasks = workspace.pages[0].redactions
        let repeated = try await prepare(preset, in: workspace, pageID: page.id)
        XCTAssertEqual(repeated.addedAreaCount, 0)
        XCTAssertTrue(workspace.commitPresetApplication(repeated))
        XCTAssertEqual(workspace.review?.id, currentReview.id)
        XCTAssertEqual(workspace.pages[0].redactions, currentMasks)
        XCTAssertFalse(workspace.commitPresetApplication(repeated), "A consumed packet cannot be committed twice.")
        XCTAssertEqual(workspace.pages[0].redactions, currentMasks)

        let removed = currentMasks[1]
        workspace.removeMask(removed.id, pageID: page.id)
        let restore = try await prepare(preset, in: workspace, pageID: page.id)
        XCTAssertEqual(restore.addedAreaCount, 1)
        XCTAssertTrue(workspace.commitPresetApplication(restore))
        XCTAssertEqual(workspace.pages[0].redactions.map(\.rect), [a, overlap, b])
        XCTAssertNotEqual(workspace.pages[0].redactions.last?.id, removed.id)
        XCTAssertEqual(workspace.pages[0].redactions.first?.id, oldMask.id)
    }

    func testPreviewNeverRetargetsWhenSelectedPageChanges() async throws {
        let workspace = makeWorkspace()
        let source = try makeImage(width: 100, height: 200)
        workspace.importURLs([source, source])
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 2)
        let target = workspace.pages[0].id
        let other = workspace.pages[1].id
        let preview = try await prepare(MaskPreset(name: "Targeted", rectangles: [a]), in: workspace, pageID: target)
        workspace.selectedPageID = other
        XCTAssertTrue(workspace.commitPresetApplication(preview))
        XCTAssertEqual(workspace.pages[0].redactions.map(\.rect), [a])
        XCTAssertTrue(workspace.pages[1].redactions.isEmpty)
        XCTAssertEqual(workspace.selectedPageID, other)
    }

    func testStalePreviewAfterEditRemovalOrClearCannotApply() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace)
        let preset = MaskPreset(name: "Stale", rectangles: [a])
        let edited = try await prepare(preset, in: workspace, pageID: page.id)
        workspace.addMask(b, pageID: page.id)
        XCTAssertFalse(workspace.commitPresetApplication(edited))
        XCTAssertEqual(workspace.pages[0].redactions.map(\.rect), [b])
        let removed = try await prepare(preset, in: workspace, pageID: page.id)
        workspace.removePage(page.id)
        XCTAssertFalse(workspace.commitPresetApplication(removed))
        XCTAssertTrue(workspace.pages.isEmpty)
        let newPage = try await loadPage(in: workspace)
        let cleared = try await prepare(preset, in: workspace, pageID: newPage.id)
        workspace.clear()
        XCTAssertFalse(workspace.commitPresetApplication(cleared))
        XCTAssertTrue(workspace.pages.isEmpty)
    }

    func testCancelledRenderCannotPublishLatePreviewOrChangeFinalReview() async throws {
        let arrived = expectation(description: "Real preset pixels rendered")
        let gate = PresetRenderGate(arrived)
        let workspace = makeWorkspace(renderer: { page in
            let image = try RasterSanitizer.render(page)
            await gate.pause()
            return image
        })
        let page = try await loadPage(in: workspace)
        let review = try await prepareReview(in: workspace)
        workspace.preparePresetApplication(MaskPreset(name: "Cancelled", rectangles: [a]), pageID: page.id)
        let task = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        workspace.cancelPresetApplication()
        await gate.release()
        await task?.value
        XCTAssertNil(workspace.presetPreview)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertTrue(workspace.pages[0].redactions.isEmpty)
        XCTAssertEqual(workspace.review?.id, review.id)
        XCTAssertNil(workspace.errorMessage)
    }

    func testNewerPreviewSurvivesOlderRendererFinishingLast() async throws {
        let oldArrived = expectation(description: "Old preset rendered")
        let newArrived = expectation(description: "New preset rendered")
        let oldGate = PresetRenderGate(oldArrived), newGate = PresetRenderGate(newArrived)
        let sequence = PresetRenderSequence([oldGate, newGate])
        let workspace = makeWorkspace(renderer: { page in
            let image = try RasterSanitizer.render(page)
            await sequence.pauseNext()
            return image
        })
        let page = try await loadPage(in: workspace)
        workspace.preparePresetApplication(MaskPreset(name: "Old", rectangles: [a]), pageID: page.id)
        let oldTask = workspace.runningTask
        await fulfillment(of: [oldArrived], timeout: 5)
        workspace.preparePresetApplication(MaskPreset(name: "New", rectangles: [b]), pageID: page.id)
        let newTask = workspace.runningTask
        await fulfillment(of: [newArrived], timeout: 5)
        await newGate.release()
        await newTask?.value
        let preview = try XCTUnwrap(workspace.presetPreview)
        XCTAssertEqual(preview.presetName, "New")
        await oldGate.release()
        await oldTask?.value
        XCTAssertEqual(workspace.presetPreview?.id, preview.id)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertNil(workspace.errorMessage)
        XCTAssertTrue(workspace.commitPresetApplication(preview))
        XCTAssertEqual(workspace.pages[0].redactions.map(\.rect), [b])
    }

    func testLateRenderCannotResurrectClearedOrRemovedPage() async throws {
        for clear in [true, false] {
            let arrived = expectation(description: "Preset rendered before page removal \(clear)")
            let gate = PresetRenderGate(arrived)
            let workspace = makeWorkspace(renderer: { page in
                let image = try RasterSanitizer.render(page)
                await gate.pause()
                return image
            })
            let page = try await loadPage(in: workspace)
            workspace.preparePresetApplication(MaskPreset(name: "Removed", rectangles: [a]), pageID: page.id)
            let task = workspace.runningTask
            await fulfillment(of: [arrived], timeout: 5)
            if clear { workspace.clear() }
            else { workspace.cancelPresetApplication(); workspace.removePage(page.id) }
            await gate.release()
            await task?.value
            XCTAssertTrue(workspace.pages.isEmpty)
            XCTAssertNil(workspace.presetPreview)
            XCTAssertNil(workspace.review)
            XCTAssertFalse(workspace.isBusy)
        }
    }

    func testPreviewAndExportMatchIndependentPixelOracleAtDifferentAspectRatios() async throws {
        // Binary-exact fractions separate the placement oracle from decimal
        // floating-point rounding at an otherwise integral pixel boundary.
        let exact = NormalizedRect(x: 0.125, y: 0.25, width: 0.25, height: 0.5)
        for (width, height, black) in [
            (80, 160, CGRect(x: 10, y: 40, width: 20, height: 80)),
            (160, 80, CGRect(x: 20, y: 20, width: 40, height: 40))
        ] {
            let workspace = makeWorkspace()
            let page = try await loadPage(in: workspace, width: width, height: height)
            let preview = try await prepare(MaskPreset(name: "Fractions", rectangles: [exact]), in: workspace, pageID: page.id)
            try assertPixels(preview.image, blackRects: [black])
            XCTAssertTrue(workspace.pages[0].redactions.isEmpty)
            XCTAssertTrue(workspace.commitPresetApplication(preview))
            XCTAssertEqual(workspace.pages[0].redactions.map(\.rect), [exact])
            let review = try await prepareReview(in: workspace)
            try assertPixels(review.pages[0].image, blackRects: [black])
            workspace.export(review, format: .png)
            await workspace.runningTask?.value
            let url = try XCTUnwrap(workspace.exported?.urls.first)
            let source = try XCTUnwrap(CGImageSourceCreateWithURL(url as CFURL, nil))
            let output = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
            try assertPixels(output, blackRects: [black])
        }
    }

    func testDecimalPixelBoundaryRoundsOutwardWithoutUnderMasking() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace, width: 100, height: 200)
        let preview = try await prepare(MaskPreset(name: "Decimal boundary", rectangles: [a]), in: workspace, pageID: page.id)
        // 0.2 + 0.4 is 0.6000000000000001 as Double. The existing strict
        // outward renderer conservatively includes row 120 instead of risking
        // under-masking. Exactly one extra bottom row is allowed by this oracle;
        // the decimal-ideal rectangle is x10..<40, y40..<120.
        try assertPixels(preview.image, blackRects: [CGRect(x: 10, y: 40, width: 30, height: 81)])
    }

    func testUprightExifOrientationAndOutwardSubpixelRounding() async throws {
        let workspace = makeWorkspace()
        let source = try makeImage(width: 100, height: 200, orientation: 6)
        workspace.importURLs([source])
        await workspace.runningTask?.value
        let page = try XCTUnwrap(workspace.pages.first)
        XCTAssertEqual(page.image.width, 200)
        XCTAssertEqual(page.image.height, 100)
        let exact = NormalizedRect(x: 0.125, y: 0.25, width: 0.25, height: 0.5)
        let preview = try await prepare(MaskPreset(name: "Upright", rectangles: [exact]), in: workspace, pageID: page.id)
        try assertPixels(preview.image, blackRects: [CGRect(x: 25, y: 25, width: 50, height: 50)])
        workspace.cancelPresetApplication()

        let tiny = NormalizedRect(x: 0.051, y: 0.401, width: 0.001, height: 0.001)
        let edge = NormalizedRect(x: 0.995, y: 0.99, width: 0.005, height: 0.01)
        let subpixel = try await prepare(MaskPreset(name: "Edges", rectangles: [tiny, edge]), in: workspace, pageID: page.id)
        try assertPixels(subpixel.image, blackRects: [CGRect(x: 10, y: 40, width: 1, height: 1), CGRect(x: 199, y: 99, width: 1, height: 1)])
    }

    func testInvalidAndOversizedPresetsFailWithoutWeakeningExistingMasks() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace)
        workspace.addMask(a, pageID: page.id)
        let review = try await prepareReview(in: workspace)
        let masks = workspace.pages[0].redactions
        let bad = [
            NormalizedRect(x: .nan, y: 0, width: 0.1, height: 0.1),
            NormalizedRect(x: -0.1, y: 0, width: 0.1, height: 0.1),
            NormalizedRect(x: 0.9, y: 0, width: 0.2, height: 0.1),
            NormalizedRect(x: 0, y: 0, width: 0, height: 0.1),
            NormalizedRect(x: 0, y: 0, width: .infinity, height: 0.1)
        ]
        for rectangles in bad.map({ [b, $0] }) + [[], Array(repeating: b, count: 201)] {
            workspace.errorMessage = nil
            workspace.preparePresetApplication(MaskPreset(name: "Invalid", rectangles: rectangles), pageID: page.id)
            await workspace.runningTask?.value
            XCTAssertNil(workspace.presetPreview)
            XCTAssertNotNil(workspace.errorMessage)
            XCTAssertEqual(workspace.pages[0].redactions, masks)
            XCTAssertEqual(workspace.review?.id, review.id)
        }
    }

    func testCollapsedPositiveExtentsAreRejectedBeforeStartingPresetRender() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace)
        workspace.addMask(a, pageID: page.id)
        let review = try await prepareReview(in: workspace)
        let masks = workspace.pages[0].redactions
        let invalid = [
            NormalizedRect(x: 1, y: 0, width: .leastNonzeroMagnitude, height: 0.1),
            NormalizedRect(x: 0, y: 1, width: 0.1, height: .leastNonzeroMagnitude),
            NormalizedRect(x: 0.5, y: 0, width: .leastNonzeroMagnitude, height: 0.1),
            NormalizedRect(x: 0, y: 0.5, width: 0.1, height: .leastNonzeroMagnitude)
        ]
        for geometry in invalid {
            workspace.errorMessage = nil
            workspace.preparePresetApplication(MaskPreset(name: "Collapsed", rectangles: [b, geometry]), pageID: page.id)
            XCTAssertFalse(workspace.isBusy, "Reject the whole preset before rendering even its valid areas.")
            XCTAssertNil(workspace.runningTask)
            XCTAssertNil(workspace.presetPreview)
            XCTAssertEqual(workspace.errorMessage, "This saved preset has invalid areas and cannot be applied.")
            XCTAssertEqual(workspace.pages[0].redactions, masks)
            XCTAssertEqual(workspace.review?.id, review.id)
        }
    }

    func testRepresentableTinyAreasStillProduceNonemptyPlacementPixels() async throws {
        let workspace = makeWorkspace()
        let page = try await loadPage(in: workspace, width: 100, height: 100)
        let increment = Double(0.5).nextUp - 0.5
        let cases: [(NormalizedRect, CGRect)] = [
            (NormalizedRect(x: 0.5, y: 0.5, width: increment, height: increment), CGRect(x: 50, y: 50, width: 1, height: 1)),
            (NormalizedRect(x: 0, y: 0, width: .leastNonzeroMagnitude, height: .leastNonzeroMagnitude), CGRect(x: 0, y: 0, width: 1, height: 1))
        ]
        for (geometry, expected) in cases {
            let preview = try await prepare(MaskPreset(name: "Tiny", rectangles: [geometry]), in: workspace, pageID: page.id)
            try assertPixels(preview.image, blackRects: [expected])
            XCTAssertTrue(workspace.pages[0].redactions.isEmpty)
            workspace.cancelPresetApplication()
        }
    }

    func testExistingPresetAppliesAndExportsLoadedPaidCapacityWithoutNewGrant() async throws {
        let workspace = makeWorkspace()
        let source = try makeImage(width: 100, height: 200)
        workspace.importURLs(Array(repeating: source, count: 4), currentIsPro: { true })
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 4)
        // The default is free. A downgrade blocks extra pages, not use of
        // existing documents, existing preset geometry, or reviewed exports.
        workspace.importURLs([source])
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.pages.count, 4)
        XCTAssertNotNil(workspace.errorMessage)
        workspace.errorMessage = nil
        let page = try XCTUnwrap(workspace.pages.last)
        let preview = try await prepare(MaskPreset(name: "Existing", rectangles: [a]), in: workspace, pageID: page.id)
        XCTAssertTrue(workspace.commitPresetApplication(preview))
        XCTAssertTrue(workspace.pages.prefix(3).allSatisfy { $0.redactions.isEmpty })
        let review = try await prepareReview(in: workspace)
        XCTAssertEqual(review.pages.count, 4)
        workspace.export(review, format: .png)
        await workspace.runningTask?.value
        XCTAssertEqual(workspace.exported?.urls.count, 4)
        XCTAssertNil(workspace.errorMessage)
    }

    func testPresetActionsCannotCancelAnUnrelatedImport() async throws {
        let arrived = expectation(description: "Additional import decoded")
        let gate = PresetRenderGate(arrived)
        let workspace = Workspace(temporaryRoot: directory.appendingPathComponent("import-workspace"), sharedInbox: nil,
                                  importPageLoader: { url in
            let pages = try RasterImporter.load(url: url)
            await gate.pause()
            return pages
        })
        workspace.loadDemo()
        let page = try XCTUnwrap(workspace.pages.first)
        workspace.importURLs([try makeImage(width: 100, height: 200)])
        let importTask = workspace.runningTask
        await fulfillment(of: [arrived], timeout: 5)
        workspace.preparePresetApplication(MaskPreset(name: "Wait", rectangles: [a]), pageID: page.id)
        workspace.cancelPresetApplication()
        XCTAssertTrue(workspace.isBusy)
        XCTAssertEqual(workspace.busyLabel, "Importing clean working copies…")
        XCTAssertNil(workspace.presetPreview)
        await gate.release()
        await importTask?.value
        XCTAssertEqual(workspace.pages.count, 2)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertNil(workspace.errorMessage)
    }

    func testFailedPreviewRenderingPreservesMasksAndReview() async throws {
        let workspace = makeWorkspace(renderer: { page in
            _ = try RasterSanitizer.render(page)
            throw SanitizerError.renderingFailed
        })
        let page = try await loadPage(in: workspace)
        workspace.addMask(a, pageID: page.id)
        let masks = workspace.pages[0].redactions
        let review = try await prepareReview(in: workspace)
        workspace.preparePresetApplication(MaskPreset(name: "Failure", rectangles: [b]), pageID: page.id)
        await workspace.runningTask?.value
        XCTAssertNil(workspace.presetPreview)
        XCTAssertFalse(workspace.isBusy)
        XCTAssertNotNil(workspace.errorMessage)
        XCTAssertEqual(workspace.pages[0].redactions, masks)
        XCTAssertEqual(workspace.review?.id, review.id)
    }

    private func makeWorkspace(renderer: @escaping Workspace.PresetRenderer = { try RasterSanitizer.render($0) }) -> Workspace {
        Workspace(temporaryRoot: directory.appendingPathComponent("workspace-\(UUID().uuidString)"),
                  sharedInbox: nil, presetRenderer: renderer)
    }

    private func loadPage(in workspace: Workspace, width: Int = 100, height: Int = 200) async throws -> RasterPage {
        workspace.importURLs([try makeImage(width: width, height: height)])
        await workspace.runningTask?.value
        return try XCTUnwrap(workspace.pages.last)
    }

    private func prepareReview(in workspace: Workspace) async throws -> ReviewPacket {
        workspace.prepareReview()
        await workspace.runningTask?.value
        return try XCTUnwrap(workspace.review)
    }

    private func prepare(_ preset: MaskPreset, in workspace: Workspace, pageID: UUID) async throws -> PresetApplicationPreview {
        workspace.preparePresetApplication(preset, pageID: pageID)
        await workspace.runningTask?.value
        return try XCTUnwrap(workspace.presetPreview)
    }

    private func makeImage(width: Int, height: Int, orientation: Int = 1) throws -> URL {
        let context = try makeContext(width: width, height: height)
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let url = directory.appendingPathComponent(UUID().uuidString).appendingPathExtension(orientation == 1 ? "png" : "tiff")
        let type = orientation == 1 ? UTType.png : UTType.tiff
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try XCTUnwrap(context.makeImage()), [kCGImagePropertyOrientation: orientation] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return url
    }

    private func makeContext(width: Int, height: Int) throws -> CGContext {
        try XCTUnwrap(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
            space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue))
    }

    /// Integer, top-left rectangles are an independent oracle. This helper does
    /// not call NormalizedRect validation/mapping or infer bounds from output.
    private func assertPixels(_ image: CGImage, blackRects: [CGRect], file: StaticString = #filePath, line: UInt = #line) throws {
        let context = try makeContext(width: image.width, height: image.height)
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        let bytes = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
        for y in 0..<image.height {
            for x in 0..<image.width {
                let expected: UInt8 = blackRects.contains { $0.contains(CGPoint(x: Double(x) + 0.5, y: Double(y) + 0.5)) } ? 0 : 255
                let offset = y * context.bytesPerRow + x * 4
                if bytes[offset] != expected || bytes[offset + 1] != expected || bytes[offset + 2] != expected {
                    XCTFail("Unexpected pixel at top-left (\(x), \(y)); expected \(expected), got \(bytes[offset]),\(bytes[offset + 1]),\(bytes[offset + 2])", file: file, line: line)
                    return
                }
            }
        }
    }
}

private actor PresetRenderGate {
    private let arrived: XCTestExpectation
    private var released = false
    private var continuation: CheckedContinuation<Void, Never>?
    init(_ arrived: XCTestExpectation) { self.arrived = arrived }
    func pause() async {
        guard !released else { return }
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            arrived.fulfill()
        }
    }
    func release() { released = true; continuation?.resume(); continuation = nil }
}

private actor PresetRenderSequence {
    private var gates: [PresetRenderGate]
    init(_ gates: [PresetRenderGate]) { self.gates = gates }
    func pauseNext() async {
        guard !gates.isEmpty else { return }
        let gate = gates.removeFirst()
        await gate.pause()
    }
}

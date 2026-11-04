import XCTest
import UIKit

/// Sends only the built-in synthetic sample through the real system activity
/// controller and installed share extension. No test writes to SharedInbox.
final class ShareExtensionEntryTests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    @MainActor
    func testPDFReceivedByExtensionThenImported() throws {
        let app = try openSyntheticExport(format: "PDF")
        try openExtension(in: app)
        saveAndFinishExtension(in: app)
        returnToWorkspace(in: app)
        let batch = app.buttons["Import this batch"].firstMatch
        reveal(batch, in: app.scrollViews["workspace-scroll"])
        capture("share-pdf-queued-before-import")
        batch.tap()
        let imported = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Temporary workspace · export to keep your edits"), object: app.staticTexts["workspace-mode"])
        XCTAssertEqual(XCTWaiter.wait(for: [imported], timeout: 15), .completed)
        XCTAssertTrue(app.staticTexts["workspace-status"].label.hasPrefix("1 page"))
        XCTAssertFalse(app.buttons["Import this batch"].exists)
        capture("share-pdf-imported-queue-cleared")
    }

    @MainActor
    func testPNGReceivedByExtensionThenDiscarded() throws {
        let app = try openSyntheticExport(format: "PNG")
        try openExtension(in: app)
        saveAndFinishExtension(in: app)
        returnToWorkspace(in: app)
        let discard = app.buttons["Discard"].firstMatch
        reveal(discard, in: app.scrollViews["workspace-scroll"])
        capture("share-png-queued-before-discard")
        discard.tap()
        XCTAssertFalse(app.buttons["Discard"].exists)
        XCTAssertFalse(app.buttons["Import this batch"].exists)
        XCTAssertEqual(app.staticTexts["workspace-status"].label, "1 page · 0 hidden areas")
        capture("share-png-discarded-queue-cleared")
        let review = app.buttons["review-button"]
        waitForStableControl(review)
        let settledAt = Date().addingTimeInterval(2)
        let settled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            Date() >= settledAt
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 4), .completed)
        capture("share-png-settled-review-action")
        review.tap()
        let back = app.buttons["back-to-editing"]
        XCTAssertTrue(back.waitForExistence(timeout: 10))
        capture("share-png-review-reopened")
        back.tap()
    }

    @MainActor
    func testExtensionCancelBeforeCopyLeavesNoQueue() throws {
        let app = try openSyntheticExport(format: "PDF")
        try openExtension(in: app)
        let cancel = app.buttons["Cancel"].firstMatch
        reveal(cancel, in: extensionScroll(in: app))
        capture("share-extension-cancel-control")
        waitForStableControl(cancel)
        cancel.tap()
        returnToWorkspace(in: app)
        XCTAssertFalse(app.buttons["Import this batch"].exists)
        capture("share-extension-cancelled-no-queue")
    }

    @MainActor
    private func openSyntheticExport(format: String) throws -> XCUIApplication {
        executionTimeAllowance = 240
        try XCTSkipUnless(UIApplication.shared.preferredContentSizeCategory == .accessibilityExtraExtraExtraLarge,
            "Requires the largest system content size. Set CLEANSEND_TEST_CONTENT_SIZE=accessibility-extra-extra-extra-large and CLEANSEND_EXPECT_TEST_COUNT=3 with scripts/check-ios-tests.sh for this suite.")
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        #if CLEANSEND_SHARE_TRACE && targetEnvironment(simulator)
        if ProcessInfo.processInfo.environment["CLEANSEND_SHARE_TRACE"] == "1" {
            app.launchEnvironment["CLEANSEND_SHARE_TRACE"] = "1"
        }
        #endif
        app.launch()
        guard app.buttons["sample-button"].waitForExistence(timeout: 10) else {
            XCTFail("The initial workspace did not become ready after launch.")
            throw NSError(domain: "CleanSendShareEntryTests", code: 1)
        }
        // The external exact-package observer must bind after this launch has
        // recreated Workspace's temporary directory, and before any export.
        FileHandle.standardOutput.write(Data("REDACT_PACKAGE_WORKSPACE_READY format=\(format)\n".utf8))
        reveal(app.buttons["sample-button"], in: app.scrollViews["workspace-scroll"])
        app.buttons["sample-button"].tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 10))
        app.buttons["review-button"].tap()
        let review = app.scrollViews["review-scroll"]
        let checked = app.buttons["confirm-page-reviewed"]
        reveal(checked, in: review)
        checked.tap()
        let picker = app.segmentedControls["export-format"]
        reveal(picker, in: review)
        picker.buttons[format].tap()
        XCTAssertTrue(picker.buttons[format].isSelected)
        let export = app.buttons["export-button"]
        reveal(export, in: review)
        export.tap()
        try waitForSystemShareSheet(in: app)
        capture("share-\(format.lowercased())-system-sheet")
        return app
    }

    @MainActor
    private func waitForSystemShareSheet(in app: XCUIApplication) throws {
        let started = ProcessInfo.processInfo.systemUptime
        #if CLEANSEND_SHARE_TRACE && targetEnvironment(simulator)
        if ProcessInfo.processInfo.environment["CLEANSEND_SHARE_TRACE"] == "1" {
            FileHandle.standardOutput.write(Data("REDACT_SHARE_TRACE_WAIT uptime_us=\(UInt64(started * 1_000_000))\n".utf8))
        }
        #endif
        let ready = app.buttons["Close"].waitForExistence(timeout: 10)
        func record(_ phase: String, appeared: Bool) {
            let elapsed = ProcessInfo.processInfo.systemUptime - started
            FileHandle.standardOutput.write(Data(
                "REDACT_SHARE_SHEET phase=\(phase) elapsed=\(elapsed) appeared=\(appeared)\n".utf8))
        }
        record("required-wait", appeared: ready)
        if ready { return }

        // Preserve the ten-second acceptance requirement. The extra wait only
        // distinguishes a delayed system sheet from one that never populates;
        // a late appearance must still fail this test.
        attachTree(app, name: "share-system-sheet-missing-after-required-wait")
        let remaining = max(0, started + 60 - ProcessInfo.processInfo.systemUptime)
        let appearedLate = remaining > 0
            ? app.buttons["Close"].waitForExistence(timeout: remaining)
            : app.buttons["Close"].exists
        record("failure-observation", appeared: appearedLate)
        attachTree(app, name: "share-system-sheet-after-failure-observation")
        XCTFail("The system activity sheet did not expose Close within 10 seconds; later diagnostic visibility does not satisfy acceptance.")
        throw NSError(domain: "CleanSendShareEntryTests", code: 2)
    }

    @MainActor
    private func openExtension(in app: XCUIApplication) throws {
        var destination = activity("RedactLeaf", in: app)
        if !destination.exists {
            let more = activity("More", in: app)
            if !more.isHittable {
                // The horizontal app row is a collection view in the native activity sheet.
                let row = app.collectionViews.firstMatch
                if row.exists { row.swipeLeft() }
            }
            guard more.waitForExistence(timeout: 5) else {
                attachTree(app, name: "missing-extension-activity-row")
                XCTFail("The system activity sheet did not expose RedactLeaf or More."); return
            }
            more.tap()
            destination = app.buttons["RedactLeaf"].firstMatch
            if !destination.exists { destination = app.cells.containing(.staticText, identifier: "RedactLeaf").firstMatch }
        }
        guard destination.waitForExistence(timeout: 5) else {
            attachTree(app, name: "missing-extension-in-activities")
            XCTFail("The real RedactLeaf extension is absent from system activities."); return
        }
        destination.tap()
        XCTAssertTrue(app.staticTexts["Send to RedactLeaf"].waitForExistence(timeout: 10), "The installed extension must actually open.")
        capture("share-extension-received-attachment")
    }

    @MainActor
    private func activity(_ label: String, in app: XCUIApplication) -> XCUIElement {
        let cell = app.cells.matching(NSPredicate(format: "label == %@", label)).firstMatch
        return cell.exists ? cell : app.buttons[label].firstMatch
    }

    @MainActor
    private func extensionScroll(in app: XCUIApplication) -> XCUIElement {
        app.scrollViews.containing(.staticText, identifier: "Send to RedactLeaf").firstMatch
    }

    @MainActor
    private func saveAndFinishExtension(in app: XCUIApplication) {
        let save = app.buttons["Save to RedactLeaf"].firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        reveal(save, in: extensionScroll(in: app))
        capture("share-extension-save-control")
        waitForStableControl(save)
        save.tap()
        let done = app.buttons["Done"].firstMatch
        XCTAssertTrue(done.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Files are queued.")).firstMatch.exists)
        reveal(done, in: extensionScroll(in: app))
        capture("share-extension-copy-complete")
        waitForStableControl(done)
        done.tap()
    }

    @MainActor
    private func returnToWorkspace(in app: XCUIApplication) {
        let extensionClosed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !app.staticTexts["Send to RedactLeaf"].exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [extensionClosed], timeout: 10), .completed)
        let close = app.buttons["Close"].firstMatch
        if close.waitForExistence(timeout: 2) {
            waitForStableControl(close)
            close.tap()
        }
        let activityClosed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !app.collectionViews["activityCollectionView"].exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [activityClosed], timeout: 5), .completed)
        // Do not activate or relaunch: the refreshed queue must be visible in
        // the same containing-app scene after the activity completes.
        let back = app.buttons["back-to-editing"]
        XCTAssertTrue(back.waitForExistence(timeout: 10))
        waitForStableControl(back)
        back.tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement) {
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        let app = XCUIApplication()
        for _ in 0..<20 {
            var viewport = scroll.frame.intersection(app.frame).insetBy(dx: 0, dy: 16)
            for bar in app.navigationBars.allElementsBoundByIndex where bar.isHittable {
                let top = max(viewport.minY, bar.frame.maxY + 10)
                viewport = CGRect(x: viewport.minX, y: top, width: viewport.width, height: max(0, viewport.maxY - top))
            }
            let footer = app.buttons["review-button"]
            if footer.exists && footer.isHittable { viewport.size.height = max(0, min(viewport.maxY, footer.frame.minY - 10) - viewport.minY) }
            if element.exists && element.isHittable && viewport.contains(CGPoint(x: element.frame.midX, y: element.frame.midY)) { return }
            let up = !element.exists || element.frame.midY > viewport.midY
            let canvas = scroll.descendants(matching: .any)["document-canvas"].firstMatch
            let preview = scroll.descendants(matching: .any)["preview-image"].firstMatch
            let image = canvas.exists ? canvas : preview
            let x = image.exists ? max(8, image.frame.minX - scroll.frame.minX - 8) : scroll.frame.width / 2
            let origin = scroll.coordinate(withNormalizedOffset: .zero)
            let top = viewport.minY - scroll.frame.minY
            origin.withOffset(CGVector(dx: x, dy: top + viewport.height * (up ? 0.8 : 0.2)))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(CGVector(dx: x, dy: top + viewport.height * (up ? 0.2 : 0.8))))
        }
        attachTree(app, name: "could-not-reveal-\(element.identifier)")
        XCTFail("Could not reveal \(element.identifier)")
    }

    @MainActor
    private func waitForStableControl(_ element: XCUIElement) {
        var sampler = StableControlSampler(started: ProcessInfo.processInfo.systemUptime)
        let stable = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            sampler.poll(
                now: { ProcessInfo.processInfo.systemUptime },
                snapshot: {
                    guard let value = try? element.snapshot() else { return nil }
                    return StableControlGeometry(frame: value.frame, enabled: value.isEnabled)
                },
                isHittable: { element.isHittable })
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [stable], timeout: 6), .completed)
    }

    @MainActor
    private func attachTree(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(string: app.debugDescription)
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
        capture(name)
    }

    @MainActor
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}

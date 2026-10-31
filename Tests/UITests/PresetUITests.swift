import XCTest
import UIKit

/// The dedicated preset runner seeds a geometry-only library in the app's
/// Application Support directory before launch. There is no entitlement flag.
final class PresetUITests: XCTestCase {
    private let seedID = "11111111-2222-3333-4444-555555555555"

    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    @MainActor
    func testFreeCreationGateKeepsNameAndExistingPage() throws {
        executionTimeAllowance = 240
        let app = launch()
        defer { app.terminate() }
        loadSampleAndManualArea(app)
        openLibrary(app)
        let create = app.buttons["create-preset-button"]
        reveal(create, in: app.scrollViews["preset-library-scroll"], app: app)
        XCTAssertTrue(create.isEnabled)
        create.tap()
        let name = app.textFields["preset-name"]
        let saveForm = app.scrollViews["save-preset-scroll"]
        XCTAssertTrue(saveForm.waitForExistence(timeout: 5))
        let explanation = app.staticTexts["preset-requires-pro"]
        try XCTSkipUnless(explanation.exists,
            "This case requires an account with no active Pro entitlement. It never changes purchase state.")
        reveal(name, in: saveForm, app: app)
        name.tap(); name.typeText("QA personal layout\n")
        let save = app.buttons["save-preset-button"]
        reveal(save, in: app.scrollViews["save-preset-scroll"], app: app)
        XCTAssertFalse(save.isEnabled, "A name and page masks must not bypass the live Pro gate.")
        capture("preset-free-creation-gate")
        XCTAssertEqual(name.value as? String, "QA personal layout")
        // Leave without creating or deleting any seed needed by the other case.
        app.buttons["cancel-create-preset"].tap()
        XCTAssertTrue(app.buttons["close-saved-areas"].waitForExistence(timeout: 5))
        app.buttons["close-saved-areas"].tap()
        waitForAreaCount(1, app: app)
        openLibrary(app)
        XCTAssertFalse(app.staticTexts["QA personal layout"].exists)
        app.buttons["close-saved-areas"].tap()
        waitForAreaCount(1, app: app)
    }

    @MainActor
    func testExistingPresetCancelApplyRepeatDeleteAndFinalReview() throws {
        executionTimeAllowance = 300
        let app = launch()
        defer { app.terminate() }
        openLibrary(app)
        let preview = app.buttons["preview-preset-\(seedID)"]
        try XCTSkipUnless(preview.exists,
            "Run scripts/check-ios-presets.sh: seed the documented geometry-only QA preset before app launch. No production injection is used.")

        // A relaunch proves the library is durable; the workspace remains temporary.
        app.terminate(); app.launch()
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 10))
        loadSampleAndManualArea(app)
        openLibrary(app)
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        openPreview(app, expectedAdded: 1)
        capture("preset-placement-before-cancel")
        app.buttons["cancel-preset-preview"].tap()
        XCTAssertTrue(app.scrollViews["preset-library-scroll"].waitForExistence(timeout: 5))
        app.buttons["close-saved-areas"].tap()
        waitForAreaCount(1, app: app)

        // A final preview checked before applying must not authorize later edits.
        openFinalReview(app)
        checkFinalPage(app)
        XCTAssertTrue(revealFinalExport(app).isEnabled)
        app.buttons["back-to-editing"].tap()
        openLibrary(app)
        openPreview(app, expectedAdded: 1)
        applyPreview(app)
        waitForAreaCount(2, app: app)

        openFinalReview(app)
        XCTAssertFalse(revealFinalExport(app).isEnabled,
            "Applying a preset must require a fresh explicit final page review.")
        capture("preset-applied-final-review-required")
        checkFinalPage(app)
        XCTAssertTrue(revealFinalExport(app).isEnabled)
        app.buttons["back-to-editing"].tap()

        // Reapplying exact geometry is a no-op; existing manual areas survive.
        openLibrary(app)
        openPreview(app, expectedAdded: 0)
        capture("preset-repeat-zero-new-areas")
        applyPreview(app)
        waitForAreaCount(2, app: app)
        openLibrary(app)
        let delete = app.buttons["delete-preset-\(seedID)"]
        reveal(delete, in: app.scrollViews["preset-library-scroll"], app: app)
        delete.tap()
        let confirm = app.buttons["confirm-delete-preset"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        XCTAssertFalse(preview.exists)
        capture("preset-deleted-library")
        app.buttons["close-saved-areas"].tap()
        waitForAreaCount(2, app: app)
    }

    @MainActor
    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 10))
        return app
    }

    @MainActor
    private func loadSampleAndManualArea(_ app: XCUIApplication) {
        let scroll = app.scrollViews["workspace-scroll"]
        let sample = app.buttons["sample-button"]
        reveal(sample, in: scroll, app: app); sample.tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
        let accessible = app.buttons["accessible-mask-button"]
        reveal(accessible, in: scroll, app: app); accessible.tap()
        XCTAssertTrue(app.navigationBars["Hidden area"].waitForExistence(timeout: 5))
        let add = app.buttons["add-mask-button"]
        let form = app.collectionViews.firstMatch.exists ? app.collectionViews.firstMatch : app.scrollViews.firstMatch
        // Form cells below the viewport are not in the accessibility tree yet.
        // Establish the presented screen, then scroll until its action exists.
        reveal(add, in: form, app: app); add.tap()
        waitForAreaCount(1, app: app)
    }

    @MainActor
    private func openLibrary(_ app: XCUIApplication) {
        let actions = app.buttons["workspace-actions"]
        XCTAssertTrue(actions.waitForExistence(timeout: 5)); actions.tap()
        let saved = app.buttons["saved-areas-menu"]
        XCTAssertTrue(saved.waitForExistence(timeout: 5)); saved.tap()
        XCTAssertTrue(app.scrollViews["preset-library-scroll"].waitForExistence(timeout: 5))
    }

    @MainActor
    private func openPreview(_ app: XCUIApplication, expectedAdded: Int) {
        let preview = app.buttons["preview-preset-\(seedID)"]
        reveal(preview, in: app.scrollViews["preset-library-scroll"], app: app); preview.tap()
        let summary = app.staticTexts["preset-preview-summary"]
        XCTAssertTrue(summary.waitForExistence(timeout: 10))
        XCTAssertEqual(summary.label, "Page 1 · \(expectedAdded) new \(expectedAdded == 1 ? "area" : "areas")")
        let image = app.descendants(matching: .any)["preset-placement-image"].firstMatch
        reveal(image, in: app.scrollViews["preset-preview-scroll"], app: app)
        XCTAssertTrue(image.exists,
            "Application must show a rendered target preview before Apply.")
        capture("preset-target-image-\(expectedAdded)-new-areas")
        let apply = app.buttons["apply-preset-button"]
        reveal(apply, in: app.scrollViews["preset-preview-scroll"], app: app)
        XCTAssertTrue(apply.isEnabled)
    }

    @MainActor
    private func applyPreview(_ app: XCUIApplication) {
        let apply = app.buttons["apply-preset-button"]
        reveal(apply, in: app.scrollViews["preset-preview-scroll"], app: app); apply.tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
    }

    @MainActor
    private func openFinalReview(_ app: XCUIApplication) {
        let review = app.buttons["review-button"]
        XCTAssertTrue(review.waitForExistence(timeout: 5)); review.tap()
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 10))
    }

    @MainActor
    private func checkFinalPage(_ app: XCUIApplication) {
        let checked = app.buttons["confirm-page-reviewed"]
        reveal(checked, in: app.scrollViews["review-scroll"], app: app); checked.tap()
        let changed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Page checked"), object: checked)
        XCTAssertEqual(XCTWaiter.wait(for: [changed], timeout: 5), .completed)
    }

    @MainActor
    private func revealFinalExport(_ app: XCUIApplication) -> XCUIElement {
        let export = app.buttons["export-button"]
        reveal(export, in: app.scrollViews["review-scroll"], app: app)
        return export
    }

    @MainActor
    private func waitForAreaCount(_ count: Int, app: XCUIApplication) {
        let expected = "1 page · \(count) hidden \(count == 1 ? "area" : "areas")"
        let condition = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", expected), object: app.staticTexts["workspace-status"])
        XCTAssertEqual(XCTWaiter.wait(for: [condition], timeout: 5), .completed)
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement, app: XCUIApplication) {
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        for _ in 0..<24 {
            var visible = scroll.frame
            for bar in app.navigationBars.allElementsBoundByIndex where bar.isHittable {
                let top = max(visible.minY, bar.frame.maxY)
                visible = CGRect(x: visible.minX, y: top, width: visible.width, height: max(0, visible.maxY - top))
            }
            let footer = app.buttons["review-button"]
            if footer.exists && footer.isHittable {
                visible.size.height = max(0, min(visible.maxY, footer.frame.minY) - visible.minY)
            }
            visible = visible.insetBy(dx: 4, dy: 12)
            if element.exists && element.isHittable && visible.contains(CGPoint(x: element.frame.midX, y: element.frame.midY)) { return }
            let upwards = !element.exists || element.frame.midY >= visible.midY
            let origin = scroll.coordinate(withNormalizedOffset: .zero)
            let top = visible.minY - scroll.frame.minY
            // Scroll through padding, away from sliders, canvases and zoomable previews.
            origin.withOffset(CGVector(dx: 8, dy: top + visible.height * (upwards ? 0.8 : 0.25)))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(CGVector(dx: 8, dy: top + visible.height * (upwards ? 0.25 : 0.8))))
        }
        capture("preset-unreachable-control")
        XCTFail("Could not reveal the preset test control inside its usable viewport.")
    }

    @MainActor
    private func capture(_ name: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name; screenshot.lifetime = .keepAlways; add(screenshot)
        let hierarchy = XCTAttachment(string: XCUIApplication().debugDescription)
        hierarchy.name = "\(name)-hierarchy"; hierarchy.lifetime = .keepAlways; add(hierarchy)
    }
}

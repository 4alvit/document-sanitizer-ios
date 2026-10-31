import XCTest
import UIKit

/// All documents come from the app's clearly labelled synthetic sample.
/// No share destination is activated and no purchase button is pressed.
final class CleanSendUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    @MainActor
    func testSyntheticDocumentDrawReviewExportAndClear() throws {
        let app = launch()
        capture("01-empty-workspace")
        loadSample(in: app)
        XCTAssertEqual(app.staticTexts["workspace-status"].label, "1 page · 0 hidden areas")

        let canvas = app.descendants(matching: .any)["document-canvas"].firstMatch
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        drawMask(on: canvas, in: app)
        waitForLabel(app.staticTexts["workspace-status"], containing: "1 hidden area")
        capture("02-manual-mask-editor")

        app.buttons["review-button"].tap()
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 10))
        let reviewScroll = app.scrollViews["review-scroll"]
        let export = app.buttons["export-button"]
        reveal(export, in: reviewScroll)
        XCTAssertFalse(export.isEnabled, "Export must stay disabled until each page is explicitly checked.")
        let checked = app.buttons["confirm-page-reviewed"]
        reveal(checked, in: reviewScroll, direction: .down)
        checked.tap()
        waitForLabel(checked, containing: "Page checked")
        capture("03-reviewed-raster-preview")
        reveal(export, in: reviewScroll)
        XCTAssertTrue(export.isEnabled)
        XCTAssertTrue(app.segmentedControls["export-format"].buttons["PDF"].isSelected)
        export.tap()
        XCTAssertTrue(waitForShareSheet(in: app), "A real native share sheet should appear after writing the PDF.")
        capture("04-pdf-share-sheet")
        dismissShareSheet(in: app)
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 5))
        app.buttons["back-to-editing"].tap()
        clearWorkspace(in: app)
        capture("05-cleared-workspace")
    }

    @MainActor
    func testLargestDynamicTypeAllowsAccessibleMaskAndReview() throws {
        let app = launch(extra: ["--uitest-largest-type"])
        capture("06-largest-type-start")
        loadSample(in: app)
        let scroll = app.scrollViews["workspace-scroll"]
        let accessibleMask = app.buttons["accessible-mask-button"]
        reveal(accessibleMask, in: scroll)
        accessibleMask.tap()
        let add = app.buttons["add-mask-button"]
        XCTAssertTrue(app.navigationBars["Hidden area"].waitForExistence(timeout: 5))
        let left = app.sliders["Left"]
        XCTAssertTrue(left.exists)
        let standardBodyHeight = UIFont.preferredFont(forTextStyle: .body,
            compatibleWith: UITraitCollection(preferredContentSizeCategory: .large)).lineHeight
        XCTAssertGreaterThan(app.staticTexts["mask-left-value"].frame.height, standardBodyHeight * 1.5,
            "The presented mask editor must inherit the largest accessibility text size.")
        capture("06b-largest-type-mask-controls")
        left.adjust(toNormalizedSliderPosition: 0.2)
        let form = app.collectionViews.firstMatch.exists ? app.collectionViews.firstMatch : app.scrollViews.firstMatch
        reveal(add, in: form)
        add.tap()
        waitForLabel(app.staticTexts["workspace-status"], containing: "1 hidden area")
        app.buttons["review-button"].tap()
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 10))
        let standardHeadlineHeight = UIFont.preferredFont(forTextStyle: .headline,
            compatibleWith: UITraitCollection(preferredContentSizeCategory: .large)).lineHeight
        XCTAssertGreaterThan(app.staticTexts["review-copies-heading"].frame.height, standardHeadlineHeight * 1.5,
            "The presented review must inherit the largest accessibility text size.")
        let reviewed = app.buttons["confirm-page-reviewed"]
        reveal(reviewed, in: app.scrollViews["review-scroll"])
        reviewed.tap()
        waitForLabel(reviewed, containing: "Page checked")
        let export = app.buttons["export-button"]
        reveal(export, in: app.scrollViews["review-scroll"])
        XCTAssertTrue(export.isEnabled)
        capture("07-largest-type-export-controls")
        app.buttons["back-to-editing"].tap()
        clearWorkspace(in: app)
    }

    @MainActor
    func testLandscapeLayoutCanReviewAndReturnToEditing() throws {
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch()
        loadSample(in: app)
        XCTAssertTrue(app.buttons["review-button"].isHittable)
        capture(UIDevice.current.userInterfaceIdiom == .pad ? "08-ipad-landscape-editor" : "08-landscape-editor")
        app.buttons["review-button"].tap()
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 10))
        let reviewed = app.buttons["confirm-page-reviewed"]
        reveal(reviewed, in: app.scrollViews["review-scroll"])
        reviewed.tap()
        waitForLabel(reviewed, containing: "Page checked")
        reveal(app.buttons["export-button"], in: app.scrollViews["review-scroll"])
        XCTAssertTrue(app.buttons["export-button"].isHittable)
        capture(UIDevice.current.userInterfaceIdiom == .pad ? "09-ipad-landscape-review" : "09-landscape-review")
        app.buttons["back-to-editing"].tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testPageRemovalCanBeCancelledAndNewWorkspaceForgetsSearch() throws {
        let app = launch()
        loadSample(in: app)
        let scroll = app.scrollViews["workspace-scroll"]
        let canvas = app.descendants(matching: .any)["document-canvas"].firstMatch
        drawMask(on: canvas, in: app)
        waitForLabel(app.staticTexts["workspace-status"], containing: "1 hidden area")
        let remove = app.buttons["remove-page-button"]
        reveal(remove, in: scroll)
        remove.tap()
        let confirm = app.buttons.matching(identifier: "confirm-remove-page").firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        let cancel = app.buttons["Cancel"].firstMatch
        if cancel.exists {
            cancel.tap()
        } else {
            let outside = app.otherElements["PopoverDismissRegion"]
            XCTAssertTrue(outside.exists)
            outside.coordinate(withNormalizedOffset: CGVector(dx: 0.01, dy: 0.5)).tap()
        }
        XCTAssertFalse(confirm.exists)
        XCTAssertEqual(app.staticTexts["workspace-status"].label, "1 page · 1 hidden area")

        remove.tap()
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        confirm.tap()
        XCTAssertTrue(app.buttons["sample-button"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["review-button"].exists)
        loadSample(in: app)
        let query = app.textFields["text-search-query"]
        reveal(query, in: scroll)
        query.tap()
        query.typeText("private@example.invalid")
        XCTAssertEqual(query.value as? String, "private@example.invalid")
        clearWorkspace(in: app)
        loadSample(in: app)
        reveal(query, in: scroll)
        XCTAssertEqual(query.value as? String, "Name, email or phrase")
    }

    @MainActor
    private func launch(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"] + extra
        app.launch()
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.navigationBars["RedactLeaf"].exists, "The app must show its consumer brand on launch.")
        return app
    }

    @MainActor
    private func loadSample(in app: XCUIApplication) {
        let sample = app.buttons["sample-button"]
        reveal(sample, in: app.scrollViews["workspace-scroll"])
        sample.tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
    }

    @MainActor
    private func drawMask(on canvas: XCUIElement, in app: XCUIApplication) {
        let scroll = app.scrollViews["workspace-scroll"]
        reveal(canvas, in: scroll)
        // The synthetic page is 900x1200. Compute its aspect-fit frame rather than
        // assuming a phone width; the same gesture works on iPads and phones.
        let frame = canvas.frame
        let imageHeight = min(frame.height, frame.width / 0.75)
        let imageWidth = imageHeight * 0.75
        let pageTop = frame.minY + (frame.height - imageHeight) / 2
        let visibleTop = max(pageTop + 12, scroll.frame.minY + 12)
        let visibleBottom = min(pageTop + imageHeight - 12, app.frame.maxY - 130)
        XCTAssertGreaterThan(visibleBottom - visibleTop, 36, "A usable portion of the page must be visible for a drag.")
        let startY = (visibleTop + visibleBottom) / 2 - 15 - frame.minY
        let start = canvas.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: (frame.width - imageWidth) / 2 + imageWidth * 0.2, dy: startY))
        let end = canvas.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: (frame.width - imageWidth) / 2 + imageWidth * 0.8, dy: startY + 30))
        start.press(forDuration: 0.1, thenDragTo: end)
    }

    @MainActor
    private func clearWorkspace(in app: XCUIApplication) {
        app.buttons["workspace-actions"].tap()
        let menuItem = app.buttons["clear-workspace-menu"]
        XCTAssertTrue(menuItem.waitForExistence(timeout: 5))
        menuItem.tap()
        // iOS can expose both the confirmation button and its nested SwiftUI
        // label as Button nodes with the same identifier.
        let confirm = app.buttons.matching(identifier: "confirm-clear-workspace").firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 5))
        XCTAssertEqual(confirm.label, "Clear workspace")
        XCTAssertTrue(confirm.isHittable)
        confirm.tap()
        XCTAssertTrue(app.buttons["sample-button"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["review-button"].exists)
    }

    private enum Direction { case up, down }

    @MainActor
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement, direction: Direction = .up) {
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        let app = XCUIApplication()
        for _ in 0..<18 {
            // SwiftUI may report a partially covered control as hittable even
            // when its center is behind the navigation bar or pinned footer.
            var visible = scroll.frame
            for bar in app.navigationBars.allElementsBoundByIndex where bar.isHittable {
                let top = max(visible.minY, bar.frame.maxY)
                visible = CGRect(x: visible.minX, y: top, width: visible.width,
                    height: max(0, visible.maxY - top))
            }
            let footer = app.buttons["review-button"].firstMatch
            if footer.exists && footer.isHittable {
                visible.size.height = max(0, min(visible.maxY, footer.frame.minY) - visible.minY)
            }
            visible = visible.insetBy(dx: 0, dy: 12)
            let frame = element.exists ? element.frame : .zero
            let centerIsVisible = visible.contains(CGPoint(x: frame.midX, y: frame.midY))
            // A large canvas can exceed the viewport; a safely visible center
            // is sufficient for both it and the control XCTest will tap.
            if element.exists && element.isHittable && centerIsVisible { return }
            // The scroll view's accessibility frame includes the landscape
            // safe-area strip. A fixed 2% x position can land outside its content.
            // Use the content center on the welcome/form screens. If a document
            // is present, derive its padding gutter from the actual image frame
            // so a navigation swipe cannot draw a mask or pan the preview.
            let actualDirection: Direction = element.exists
                ? (frame.midY < visible.midY ? .down : .up) : direction
            let from = actualDirection == .up ? 0.8 : 0.25
            let to = actualDirection == .up ? 0.25 : 0.8
            let canvas = scroll.descendants(matching: .any)["document-canvas"].firstMatch
            let preview = scroll.descendants(matching: .any)["preview-image"].firstMatch
            let image = canvas.exists ? canvas : preview
            let x = image.exists
                ? max(8, min(scroll.frame.width - 8, image.frame.minX - scroll.frame.minX - 8))
                : scroll.frame.width / 2
            let origin = scroll.coordinate(withNormalizedOffset: .zero)
            let visibleTop = visible.minY - scroll.frame.minY
            origin.withOffset(CGVector(dx: x, dy: visibleTop + visible.height * from))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(CGVector(dx: x, dy: visibleTop + visible.height * to)))
        }
        capture("could-not-reveal-\(element.identifier)")
        XCTFail("Could not reveal \(element.identifier).")
    }

    @MainActor
    private func waitForLabel(_ element: XCUIElement, containing value: String) {
        let predicate = NSPredicate(format: "label CONTAINS %@", value)
        expectation(for: predicate, evaluatedWith: element)
        waitForExpectations(timeout: 5)
    }

    @MainActor
    private func waitForShareSheet(in app: XCUIApplication) -> Bool {
        let predicate = NSPredicate { _, _ in
            app.descendants(matching: .any)["export-share-sheet"].firstMatch.exists ||
            app.buttons["Copy"].exists || app.buttons["Save to Files"].exists || app.buttons["Close"].exists
        }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: nil)
        return XCTWaiter.wait(for: [expectation], timeout: 10) == .completed
    }

    @MainActor
    private func dismissShareSheet(in app: XCUIApplication) {
        if app.buttons["Close"].firstMatch.exists { app.buttons["Close"].firstMatch.tap() }
        else if app.buttons["Cancel"].firstMatch.exists { app.buttons["Cancel"].firstMatch.tap() }
        else {
            let sheet = app.descendants(matching: .any)["export-share-sheet"].firstMatch
            XCTAssertTrue(sheet.exists)
            sheet.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.03))
                .press(forDuration: 0.1, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.98)))
        }
        let hidden = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !app.descendants(matching: .any)["export-share-sheet"].firstMatch.exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [hidden], timeout: 5), .completed)
    }

    @MainActor
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}

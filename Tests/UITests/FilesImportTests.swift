import XCTest
import UIKit

/// Uses a synthetic PDF seeded into this private simulator's real Files
/// provider by scripts/check-ios-accessibility.sh. No document is injected into
/// the app's workspace or container.
final class FilesImportTests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor
    func testSystemLargestTypeFilesImportRequiresEveryPageReview() throws {
        try XCTSkipUnless(UIApplication.shared.preferredContentSizeCategory == .accessibilityExtraExtraExtraLarge,
            "Run scripts/check-ios-accessibility.sh [iPhone|iPad] to configure the system text size and synthetic Files fixture.")
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        defer { app.terminate() }
        XCTAssertTrue(app.navigationBars["RedactLeaf"].waitForExistence(timeout: 10))
        app.buttons["workspace-actions"].tap()
        app.buttons["Import PDF or images"].tap()
        XCTAssertTrue(app.buttons["Cancel"].firstMatch.waitForExistence(timeout: 10))
        capture("files-import-initial-picker", app: app)

        let fixture = app.descendants(matching: .any).matching(
            NSPredicate(format: "label BEGINSWITH %@", "RedactLeaf-QA-Two-Pages")).firstMatch
        // Native Files may initially show Recents or the last browsed location.
        // Select the named location only when the seeded fixture is absent.
        if !fixture.exists {
            let browse = app.buttons["Browse"].firstMatch
            if browse.exists && browse.isHittable { browse.tap() }
            let location = app.descendants(matching: .any).matching(
                NSPredicate(format: "label == %@ OR label == %@", "On My iPhone", "On My iPad")).firstMatch
            XCTAssertTrue(location.waitForExistence(timeout: 5), "The local Files location must be available.")
            XCTAssertTrue(location.isHittable)
            location.tap()
        }
        XCTAssertTrue(fixture.waitForExistence(timeout: 5), "The named synthetic PDF must be visible in the real Files provider.")
        XCTAssertTrue(fixture.isHittable)
        capture("files-import-fixture-visible", app: app)
        fixture.tap()
        // Multiple-selection importers may require an explicit Open action.
        let open = app.buttons["Open"].firstMatch
        if open.waitForExistence(timeout: 2) && open.isHittable { open.tap() }
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["workspace-status"].label, "2 pages · 0 hidden areas")
        capture("files-import-two-pages-loaded", app: app)

        app.buttons["review-button"].tap()
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 10))
        let scroll = app.scrollViews["review-scroll"]
        let export = app.buttons["export-button"]
        reveal(export, in: scroll, app: app)
        XCTAssertFalse(export.isEnabled)
        let check = app.buttons["confirm-page-reviewed"]
        reveal(check, in: scroll, app: app)
        check.tap()
        XCTAssertTrue(app.staticTexts["Pages checked: 1 / 2"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Page 2 of 2"].exists)
        reveal(export, in: scroll, app: app)
        XCTAssertFalse(export.isEnabled, "Checking only one page must not unlock a two-page export.")
        capture("files-import-first-page-only-export-disabled", app: app)
        reveal(check, in: scroll, app: app)
        check.tap()
        XCTAssertTrue(app.staticTexts["Pages checked: 2 / 2"].waitForExistence(timeout: 5))
        reveal(export, in: scroll, app: app)
        XCTAssertTrue(export.isEnabled)
        capture("files-import-both-pages-export-enabled", app: app)
        export.tap()
        let share = app.collectionViews["activityCollectionView"].firstMatch
        XCTAssertTrue(share.waitForExistence(timeout: 10))
        XCTAssertTrue(app.otherElements["LP.CaptionBar.BottomCaption"].firstMatch.label.contains("PDF Document"))
        let close = app.buttons["Close"].firstMatch
        XCTAssertTrue(close.isHittable)
        capture("files-import-two-page-pdf-share", app: app)
        close.tap()
        let hidden = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in !share.exists }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [hidden], timeout: 5), .completed)
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement, app: XCUIApplication) {
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        for _ in 0..<24 {
            var visible = scroll.frame.intersection(app.frame)
            for bar in app.navigationBars.allElementsBoundByIndex where bar.isHittable {
                let top = max(visible.minY, bar.frame.maxY)
                visible = CGRect(x: visible.minX, y: top, width: visible.width, height: max(0, visible.maxY - top))
            }
            visible = visible.insetBy(dx: 4, dy: 12)
            let frame = element.exists ? element.frame : .zero
            if element.exists && element.isHittable && visible.contains(CGPoint(x: frame.midX, y: frame.midY)) { return }
            let up = !element.exists || frame.midY >= visible.midY
            let image = scroll.descendants(matching: .any)["preview-image"].firstMatch
            let x = image.exists
                ? max(8, min(scroll.frame.width - 8, image.frame.minX - scroll.frame.minX - 8))
                : scroll.frame.width / 2
            let origin = scroll.coordinate(withNormalizedOffset: .zero)
            let top = visible.minY - scroll.frame.minY
            origin.withOffset(CGVector(dx: x, dy: top + visible.height * (up ? 0.8 : 0.25)))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(CGVector(dx: x, dy: top + visible.height * (up ? 0.25 : 0.8))))
        }
        capture("files-import-could-not-reveal-\(element.identifier)", app: app)
        XCTFail("Could not reveal \(element.identifier) inside the usable viewport.")
    }

    @MainActor
    private func capture(_ name: String, app: XCUIApplication) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "\(name)-hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }
}

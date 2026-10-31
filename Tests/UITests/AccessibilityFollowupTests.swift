import XCTest
import UIKit

/// Run only after setting this private simulator's system content size to
/// accessibility-extra-extra-extra-large. The app receives no font-size flag.
/// These tests use synthetic content and never activate a share destination.
final class AccessibilityFollowupTests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testSystemLargestTypePortraitFilesCancelAndImageExports() throws {
        executionTimeAllowance = 180
        try runFilesAndImageExports(orientation: .portrait, name: "portrait")
    }

    @MainActor
    func testSystemLargestTypeLandscapeFilesCancelAndImageExports() throws {
        executionTimeAllowance = 180
        try runFilesAndImageExports(orientation: .landscapeLeft, name: "landscape")
    }

    @MainActor
    private func runFilesAndImageExports(orientation: UIDeviceOrientation, name: String) throws {
        try XCTSkipUnless(UIApplication.shared.preferredContentSizeCategory == .accessibilityExtraExtraExtraLarge,
            "Requires the largest system content size. Run scripts/check-ios-accessibility.sh [iPhone|iPad]; it configures a private simulator and rejects skipped tests. An app-only SwiftUI override does not cover native sheets.")
        XCUIDevice.shared.orientation = orientation
        defer { XCUIDevice.shared.orientation = .portrait }

        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        defer { app.terminate() }
        XCTAssertTrue(app.navigationBars["RedactLeaf"].waitForExistence(timeout: 10))
        capture("system-largest-\(name)-launch")

        // Use the toolbar action so the test covers the real system importer
        // without relying on where the enlarged welcome screen ends.
        app.buttons["workspace-actions"].tap()
        let importAction = app.buttons["Import PDF or images"]
        XCTAssertTrue(importAction.waitForExistence(timeout: 5))
        importAction.tap()
        let cancelImporter = app.buttons["Cancel"].firstMatch
        XCTAssertTrue(cancelImporter.waitForExistence(timeout: 10), "The native Files importer must be presented.")
        waitForStableFrame(cancelImporter)
        XCTAssertTrue(cancelImporter.isHittable, "Files cancellation must remain usable at the system's largest text size.")
        capture("system-largest-\(name)-files-importer")
        cancelImporter.tap()
        let importerClosed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in !cancelImporter.exists }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [importerClosed], timeout: 5), .completed,
            "Files must actually close before attempting to interact with the workspace.")
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["review-button"].exists, "Cancelling Files must not append a document.")

        let sample = app.buttons["sample-button"]
        reveal(sample, in: app.scrollViews["workspace-scroll"], app: app)
        sample.tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
        let addAccessible = app.buttons["accessible-mask-button"]
        reveal(addAccessible, in: app.scrollViews["workspace-scroll"], app: app)
        addAccessible.tap()
        XCTAssertTrue(app.navigationBars["Hidden area"].waitForExistence(timeout: 5))
        let form = app.collectionViews.firstMatch.exists ? app.collectionViews.firstMatch : app.scrollViews.firstMatch
        let left = app.sliders["Left"]
        reveal(left, in: form, app: app)
        let standardBodyHeight = UIFont.preferredFont(forTextStyle: .body,
            compatibleWith: UITraitCollection(preferredContentSizeCategory: .large)).lineHeight
        XCTAssertGreaterThan(app.staticTexts["mask-left-value"].frame.height, standardBodyHeight * 1.5,
            "The mask form must inherit the actual system text size without an app-only override.")
        left.adjust(toNormalizedSliderPosition: 0.2)
        capture("system-largest-\(name)-mask-form")
        let add = app.buttons["add-mask-button"]
        reveal(add, in: form, app: app)
        add.tap()
        waitForLabel(app.staticTexts["workspace-status"], containing: "1 hidden area")

        app.buttons["review-button"].tap()
        XCTAssertTrue(app.buttons["back-to-editing"].waitForExistence(timeout: 10))
        let reviewScroll = app.scrollViews["review-scroll"]
        let export = app.buttons["export-button"]
        reveal(export, in: reviewScroll, app: app)
        XCTAssertFalse(export.isEnabled, "Export must remain unavailable before the page is checked.")
        let checked = app.buttons["confirm-page-reviewed"]
        reveal(checked, in: reviewScroll, app: app)
        checked.tap()
        waitForLabel(checked, containing: "Page checked")

        for format in ["PNG", "JPEG"] {
            let formatControl = app.segmentedControls["export-format"]
            reveal(formatControl, in: reviewScroll, app: app)
            let option = formatControl.buttons[format]
            XCTAssertTrue(option.isHittable)
            option.tap()
            XCTAssertTrue(option.isSelected)
            XCTAssertTrue(app.staticTexts["One \(format) image per page."].exists)
            reveal(export, in: reviewScroll, app: app)
            XCTAssertTrue(export.isEnabled)
            capture("system-largest-\(name)-\(format.lowercased())-export")
            export.tap()
            // The system activity controller is hosted in another process and
            // does not preserve the representable's root view identifier.
            let share = app.collectionViews["activityCollectionView"].firstMatch
            XCTAssertTrue(share.waitForExistence(timeout: 10), "\(format) export must write a file and present the native share sheet.")
            let typeCaption = app.otherElements["LP.CaptionBar.BottomCaption"].firstMatch
            let captionLoaded = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                typeCaption.exists && typeCaption.label.localizedCaseInsensitiveContains("\(format) Image")
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [captionLoaded], timeout: 10), .completed,
                "The system share sheet must finish loading the selected image format caption.")
            let close = app.buttons["Close"].firstMatch
            XCTAssertTrue(close.waitForExistence(timeout: 5))
            XCTAssertTrue(close.isHittable, "Native share-sheet dismissal must be usable at the largest system text size.")
            capture("system-largest-\(name)-\(format.lowercased())-share")
            close.tap()
            let hidden = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in !share.exists }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [hidden], timeout: 5), .completed)
        }

        XCTAssertTrue(app.buttons["back-to-editing"].isHittable)
        app.buttons["back-to-editing"].tap()
        XCTAssertTrue(app.buttons["review-button"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["review-button"].isHittable)
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement, app: XCUIApplication) {
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        for _ in 0..<24 {
            var visible = scroll.frame.intersection(app.frame)
            for bar in app.navigationBars.allElementsBoundByIndex where bar.isHittable {
                let top = max(visible.minY, bar.frame.maxY)
                visible = CGRect(x: visible.minX, y: top, width: visible.width,
                    height: max(0, visible.maxY - top))
            }
            let footer = app.buttons["review-button"].firstMatch
            if footer.exists && footer.isHittable {
                visible.size.height = max(0, min(visible.maxY, footer.frame.minY) - visible.minY)
            }
            visible = visible.insetBy(dx: 4, dy: 12)
            let frame = element.exists ? element.frame : .zero
            if element.exists && element.isHittable && visible.contains(CGPoint(x: frame.midX, y: frame.midY)) { return }
            let upwards = !element.exists || frame.midY >= visible.midY
            let canvas = scroll.descendants(matching: .any)["document-canvas"].firstMatch
            let preview = scroll.descendants(matching: .any)["preview-image"].firstMatch
            let image = canvas.exists ? canvas : preview
            let cell = scroll.cells.firstMatch
            let contentLeft = image.exists ? image.frame.minX : (cell.exists ? cell.frame.minX : nil)
            // Form sliders intercept gestures through the center of a cell.
            // Its visible padding gutter scrolls the form without moving a slider.
            let x = contentLeft.map { max(8, min(scroll.frame.width - 8, $0 - scroll.frame.minX - 8)) }
                ?? scroll.frame.width / 2
            let origin = scroll.coordinate(withNormalizedOffset: .zero)
            let visibleTop = visible.minY - scroll.frame.minY
            origin.withOffset(CGVector(dx: x, dy: visibleTop + visible.height * (upwards ? 0.8 : 0.25)))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(CGVector(dx: x,
                    dy: visibleTop + visible.height * (upwards ? 0.25 : 0.8))))
        }
        capture("system-largest-unreachable-control")
        XCTFail("Could not reveal the requested control inside the usable viewport.")
    }

    @MainActor
    private func waitForLabel(_ element: XCUIElement, containing value: String) {
        expectation(for: NSPredicate(format: "label CONTAINS %@", value), evaluatedWith: element)
        waitForExpectations(timeout: 5)
    }

    @MainActor
    private func waitForStableFrame(_ element: XCUIElement) {
        var previous = CGRect.null
        var stableSince = Date()
        let stable = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard element.exists, element.isHittable else {
                previous = .null
                stableSince = Date()
                return false
            }
            let frame = element.frame
            if frame != previous {
                previous = frame
                stableSince = Date()
                return false
            }
            return Date().timeIntervalSince(stableSince) >= 1
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [stable], timeout: 6), .completed,
            "Wait for the native Files toolbar to finish adapting to the orientation.")
    }

    @MainActor
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        let hierarchy = XCTAttachment(string: XCUIApplication().debugDescription)
        hierarchy.name = "\(name)-hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }
}

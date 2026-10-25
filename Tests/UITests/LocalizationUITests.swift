import XCTest
import UIKit

/// Sends only the built-in synthetic sample through the real system activity
/// controller and installed share extension. No test writes to SharedInbox.
final class LocalizationUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    @MainActor
    func testRussianPDFExtensionThenImport() throws {
        let app = try openSyntheticExport(format: "PDF")
        try openExtension(in: app)
        saveAndFinishExtension(in: app)
        returnToWorkspace(in: app)
        let batch = app.buttons["Импортировать пакет"].firstMatch
        reveal(batch, in: app.scrollViews["workspace-scroll"])
        capture("share-pdf-queued-before-import")
        batch.tap()
        let imported = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label BEGINSWITH %@", "2 страницы"), object: app.staticTexts["workspace-status"])
        XCTAssertEqual(XCTWaiter.wait(for: [imported], timeout: 15), .completed)
        XCTAssertFalse(app.buttons["Импортировать пакет"].exists)
        capture("share-pdf-imported-queue-cleared")
    }

    @MainActor
    func testSupportedLanguageSelectionAndEnglishFallback() {
        let app = XCUIApplication()
        for (languages, expected) in [("(ru-RU,en-US)", "Открыть учебный пример"),
                                      ("(en-GB,ru-RU)", "Try a synthetic sample"),
                                      ("(fr-FR,ru-RU,en-US)", "Открыть учебный пример"),
                                      ("(fr-FR)", "Try a synthetic sample")] {
            app.launchArguments = ["-AppleLanguages", languages, "-AppleLocale", "en_US"]
            app.launch()
            XCTAssertTrue(app.buttons["sample-button"].waitForExistence(timeout: 10))
            XCTAssertEqual(app.buttons["sample-button"].label, expected)
            app.terminate()
        }
    }

    @MainActor
    func testRussianEditorPresetGateAndConfirmation() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(ru,en)", "-AppleLocale", "en_US"]
        app.launch()
        let workspace = app.scrollViews["workspace-scroll"]
        let sample = app.buttons["sample-button"]
        reveal(sample, in: workspace); sample.tap()
        let manual = app.buttons["accessible-mask-button"]
        reveal(manual, in: workspace); manual.tap()
        XCTAssertTrue(app.navigationBars["Область скрытия"].waitForExistence(timeout: 5))
        capture("ru-manual-coordinates")
        let form = app.collectionViews.firstMatch.exists ? app.collectionViews.firstMatch : app.scrollViews.firstMatch
        let add = app.buttons["add-mask-button"]
        reveal(add, in: form); add.tap()
        let query = app.textFields["Имя, электронная почта или фраза"]
        reveal(query, in: workspace)
        query.tap(); query.typeText("ZZZNoMatchingPrivateText\n")
        let noMatch = app.alerts.staticTexts["Совпадений не найдено. Распознавание может пропустить текст. Проверьте страницы и добавьте области скрытия вручную."]
        XCTAssertTrue(noMatch.waitForExistence(timeout: 20))
        waitForStableControl(app.alerts.buttons.firstMatch)
        capture("ru-ocr-no-match-error")
        app.alerts.buttons.firstMatch.tap()
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 5))
        app.buttons["workspace-actions"].tap(); app.buttons["saved-areas-menu"].tap()
        let create = app.buttons["create-preset-button"]
        reveal(create, in: app.scrollViews["preset-library-scroll"])
        capture("ru-preset-library"); create.tap()
        let name = app.textFields["preset-name"]
        reveal(name, in: app.scrollViews["save-preset-scroll"])
        name.tap(); name.typeText("Cancel 100%\n")
        let save = app.buttons["save-preset-button"]
        reveal(save, in: app.scrollViews["save-preset-scroll"])
        XCTAssertFalse(save.isEnabled)
        XCTAssertEqual(name.value as? String, "Cancel 100%")
        capture("ru-preset-free-gate")
        let pro = app.buttons["preset-pro-button"]
        reveal(pro, in: app.scrollViews["save-preset-scroll"]); pro.tap()
        XCTAssertTrue(app.navigationBars["RedactLeaf Pro"].waitForExistence(timeout: 5))
        capture("ru-pro-information")
        app.navigationBars["RedactLeaf Pro"].buttons["Готово"].tap()
        app.buttons["cancel-create-preset"].tap(); app.buttons["close-saved-areas"].tap()
        app.buttons["workspace-actions"].tap(); app.buttons["clear-workspace-menu"].tap()
        XCTAssertTrue(app.buttons["confirm-clear-workspace"].waitForExistence(timeout: 5))
        capture("ru-clear-confirmation")
        let cancel = app.buttons["Отмена"].firstMatch
        if cancel.exists {
            cancel.tap()
        } else {
            // iOS can present a popover without a Cancel row. Its outside
            // dismiss region is the native non-destructive action.
            let outside = app.otherElements["PopoverDismissRegion"]
            XCTAssertTrue(outside.exists)
            outside.coordinate(withNormalizedOffset: CGVector(dx: 0.01, dy: 0.5)).tap()
        }
        XCTAssertFalse(app.buttons["confirm-clear-workspace"].exists)
        XCTAssertTrue(app.buttons["review-button"].exists)
    }

    @MainActor
    private func openSyntheticExport(format: String) throws -> XCUIApplication {
        executionTimeAllowance = 240
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(ru,en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.buttons["sample-button"].waitForExistence(timeout: 10))
        capture("ru-onboarding")
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
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label IN %@", ["Close", "Закрыть"])).firstMatch.waitForExistence(timeout: 10))
        capture("share-\(format.lowercased())-system-sheet")
        return app
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
        XCTAssertTrue(app.staticTexts["Отправить в RedactLeaf"].waitForExistence(timeout: 10), "The installed extension must actually open.")
        capture("share-extension-received-attachment")
    }

    @MainActor
    private func activity(_ label: String, in app: XCUIApplication) -> XCUIElement {
        let labels = label == "More" ? ["More", "Ещё", "Еще"] : [label]
        let cell = app.cells.matching(NSPredicate(format: "label IN %@", labels)).firstMatch
        return cell.exists ? cell : app.buttons.matching(NSPredicate(format: "label IN %@", labels)).firstMatch
    }

    @MainActor
    private func extensionScroll(in app: XCUIApplication) -> XCUIElement {
        app.scrollViews.containing(.staticText, identifier: "Отправить в RedactLeaf").firstMatch
    }

    @MainActor
    private func saveAndFinishExtension(in app: XCUIApplication) {
        let save = app.buttons["Сохранить в RedactLeaf"].firstMatch
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        reveal(save, in: extensionScroll(in: app))
        capture("share-extension-save-control")
        waitForStableControl(save)
        save.tap()
        let done = app.buttons["Готово"].firstMatch
        XCTAssertTrue(done.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Файлы добавлены в очередь.")).firstMatch.exists)
        reveal(done, in: extensionScroll(in: app))
        capture("share-extension-copy-complete")
        waitForStableControl(done)
        done.tap()
    }

    @MainActor
    private func returnToWorkspace(in app: XCUIApplication) {
        let extensionClosed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            !app.staticTexts["Отправить в RedactLeaf"].exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [extensionClosed], timeout: 10), .completed)
        let close = app.buttons.matching(NSPredicate(format: "label IN %@", ["Close", "Закрыть"])).firstMatch
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
        let tree = XCTAttachment(string: XCUIApplication().debugDescription)
        tree.name = name + "-hierarchy"; tree.lifetime = .keepAlways; add(tree)
    }
}

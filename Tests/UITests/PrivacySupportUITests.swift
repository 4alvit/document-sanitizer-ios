import XCTest
import UIKit

/// Requires a free workspace on the selected device. Reads bundled information
/// and a synthetic document only; never presses an online, purchase or restore link.
final class PrivacySupportUITests: XCTestCase {
    private var remainingScrollGestures = 80
    private var remainingWorkspaceContextSamples = 2
    private let paragraphIDs = [
        "privacy-text-overview-0", "privacy-text-overview-1",
        "privacy-text-files-0", "privacy-text-files-1",
        "privacy-text-queue-0", "privacy-text-queue-1",
        "privacy-text-presets-0", "privacy-text-presets-1", "privacy-text-presets-2",
        "privacy-text-sharing-0", "privacy-text-sharing-1", "privacy-text-sharing-2",
        "privacy-text-apple-0",
        "privacy-text-support-0", "privacy-text-support-1", "privacy-text-support-2"
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
        executionTimeAllowance = 180
        remainingScrollGestures = 80
        remainingWorkspaceContextSamples = 2
    }

    @MainActor
    func testEnglishOfflineInformationFromWorkspaceAndProPreservesDocument() {
        verifyWorkspaceAndPro(language: "en")
    }

    @MainActor
    func testRussianOfflineInformationFromWorkspaceAndProPreservesDocument() {
        verifyWorkspaceAndPro(language: "ru")
    }

    @MainActor
    func testRussianOfflineInformationAtSystemAX5OnLandscapeIPad() throws {
        try XCTSkipUnless(UIDevice.current.userInterfaceIdiom == .pad,
                          "Select an iPad for this dedicated accessibility case; its scoped run must reject skips.")
        try XCTSkipUnless(UIApplication.shared.preferredContentSizeCategory == .accessibilityExtraExtraExtraLarge,
                          "Set the simulator's actual system content size to AX5 before this case; no app-only size flag is accepted.")
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launch(language: "ru")
        defer { app.terminate() }
        waitUntil("The application must be in landscape") { app.frame.width > app.frame.height }
        guard openFromWorkspace(in: app, language: "ru") else { return }
        _ = readEverySectionAndFooter(in: app, language: "ru")
        dismissInformation(in: app)
        XCTAssertTrue(app.buttons["sample-button"].exists)
        XCTAssertFalse(app.buttons["review-button"].exists)
        XCTAssertEqual(app.buttons["open-pro"].label, "Открыть Pro")
    }

    @MainActor
    private func verifyWorkspaceAndPro(language: String) {
        XCUIDevice.shared.orientation = .portrait
        let app = launch(language: language)
        defer { app.terminate() }
        // The free entry point must work before there is a document or a Pro sheet.
        guard openFromWorkspace(in: app, language: language) else { return }
        let firstRead = readEverySectionAndFooter(in: app, language: language)
        dismissInformation(in: app)
        XCTAssertTrue(app.buttons["sample-button"].exists)
        XCTAssertFalse(app.buttons["review-button"].exists)

        let workspace = app.scrollViews["workspace-scroll"]
        let sample = app.buttons["sample-button"]
        reveal(sample, in: workspace, app: app, needsCenter: true)
        sample.tap()
        let status = app.staticTexts["workspace-status"]
        let expectedStatus = language == "ru" ? "1 страница · 0 скрытых областей" : "1 page · 0 hidden areas"
        waitUntil("The synthetic page must be loaded") { status.exists && status.label == expectedStatus }
        let canvas = app.descendants(matching: .any)["document-canvas"].firstMatch
        XCTAssertTrue(canvas.exists)
        let documentLabel = canvas.label
        let documentName = app.staticTexts[language == "ru" ? "Пример квитанции" : "Synthetic receipt"]
        XCTAssertTrue(documentName.exists)

        guard openFromWorkspace(in: app, language: language) else { return }
        verifySameOpeningParagraph(in: app, expected: firstRead[paragraphIDs[0]])
        dismissInformation(in: app)
        XCTAssertEqual(status.label, expectedStatus)
        XCTAssertEqual(canvas.label, documentLabel)
        XCTAssertTrue(documentName.exists)

        app.buttons["open-pro"].tap()
        let pro = app.scrollViews["pro-scroll"]
        XCTAssertTrue(pro.waitForExistence(timeout: 5))
        let information = app.buttons["pro-privacy-support"]
        reveal(information, in: pro, app: app, needsCenter: true)
        information.tap()
        waitForInformation(in: app, language: language)
        verifySameOpeningParagraph(in: app, expected: firstRead[paragraphIDs[0]])
        waitForStableFrame(app.staticTexts[paragraphIDs[0]])
        capture(app, name: "privacy-\(language)-opened-from-pro")
        dismissInformation(in: app)
        XCTAssertTrue(pro.waitForExistence(timeout: 5), "Closing information opened from Pro must return to Pro.")
        waitUntil("Closing information must return to the Pro controls") { information.isHittable }
        let done = app.navigationBars["RedactLeaf Pro"].buttons[language == "ru" ? "Готово" : "Done"].firstMatch
        XCTAssertTrue(done.isHittable)
        done.tap()
        waitUntil("The Pro sheet must close") { !pro.exists }
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 5))
        XCTAssertEqual(status.label, expectedStatus, "Reading either entry point must preserve the page and its masks.")
        XCTAssertEqual(canvas.label, documentLabel)
        XCTAssertTrue(documentName.exists)
        XCTAssertEqual(app.state, .runningForeground)
    }

    @MainActor
    private func launch(language: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(\(language),en)", "-AppleLocale", language == "ru" ? "ru_RU" : "en_US"]
        app.launch()
        XCTAssertTrue(app.buttons["workspace-actions"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.buttons["sample-button"].label, language == "ru" ? "Открыть учебный пример" : "Try a synthetic sample")
        XCTAssertEqual(app.buttons["open-pro"].label, language == "ru" ? "Открыть Pro" : "Unlock Pro",
                       "Run this case in the free state; do not create or restore a purchase to prepare it.")
        return app
    }

    @MainActor
    private func openFromWorkspace(in app: XCUIApplication, language: String) -> Bool {
        guard let actions = readyWorkspaceActions(in: app) else { return false }
        actions.tap()
        let entry = app.buttons["privacy-support-menu"].firstMatch
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        XCTAssertEqual(entry.label, language == "ru" ? "Конфиденциальность и поддержка" : "Privacy and support")
        revealMenuEntry(entry, in: app)
        XCTAssertTrue(entry.isHittable)
        entry.tap()
        waitForInformation(in: app, language: language)
        return true
    }

    @MainActor
    private func readyWorkspaceActions(in app: XCUIApplication) -> XCUIElement? {
        let matches = app.buttons.matching(identifier: "workspace-actions")
        let actions = app.buttons["workspace-actions"]
        var previous = CGRect.null
        var previousAppFrame = CGRect.null
        var stableSince = ProcessInfo.processInfo.systemUptime

        func isActionable() -> Bool {
            guard matches.count == 1, app.state == .runningForeground,
                  actions.exists, actions.isEnabled, actions.isHittable else { return false }
            return !actions.frame.isEmpty && app.frame.contains(actions.frame)
        }

        captureWorkspaceActions(in: app, stage: "before-wait")
        // Use the existing stable-frame wait pattern without changing reading-position waits.
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard isActionable() else {
                previous = .null
                previousAppFrame = .null
                stableSince = ProcessInfo.processInfo.systemUptime
                return false
            }
            let frame = actions.frame
            let appFrame = app.frame
            if frame != previous || appFrame != previousAppFrame {
                previous = frame
                previousAppFrame = appFrame
                stableSince = ProcessInfo.processInfo.systemUptime
                return false
            }
            return ProcessInfo.processInfo.systemUptime - stableSince >= 0.5
        }, object: nil)
        let result = XCTWaiter.wait(for: [ready], timeout: 6)
        let waitState = "waiterResult=\(result.rawValue) secondsSinceReset=\(ProcessInfo.processInfo.systemUptime - stableSince) "
            + "lastEligibleFrame=\(previous) lastEligibleAppFrame=\(previousAppFrame)"
        captureWorkspaceActions(in: app, stage: result == .completed ? "ready-before-tap" : "not-ready", detail: waitState)
        guard result == .completed else {
            XCTFail("Workspace actions did not become uniquely enabled, hittable and stable within the readiness wait.")
            return nil
        }
        // Capturing evidence can change timing; reject stale readiness rather than retrying.
        guard isActionable(), actions.frame == previous, app.frame == previousAppFrame else {
            captureWorkspaceActions(in: app, stage: "changed-after-capture")
            XCTFail("Workspace actions readiness changed while capturing pre-tap evidence.")
            return nil
        }
        return actions
    }

    @MainActor
    private func captureWorkspaceActions(in app: XCUIApplication, stage: String, detail: String = "") {
        // Bound all workspace diagnostic captures, including the existing stale-readiness call.
        guard remainingWorkspaceContextSamples > 0,
              ["before-wait", "ready-before-tap", "not-ready"].contains(stage) else { return }
        remainingWorkspaceContextSamples -= 1
        let name = "privacy-workspace-actions-" + stage
        var state = "diagnostic=toolbar-reference-v3 binding=identified-button stage=\(stage) capture=\(2 - remainingWorkspaceContextSamples) start=\(ProcessInfo.processInfo.systemUptime)\n"
        state += "targetHit=NOT_READ referenceHit=NOT_READ; sequential observations, not atomic\n"
        state += "AUTInterfaceOrientation=NOT_READ; device orientation is physical, frame aspect is derived geometry\n"
        state += "soleWindowMainOrKeyStatus=NOT_READ; window uniqueness does not establish main/key status\n"
        state += detail + "\n"
        defer {
            state += "end=\(ProcessInfo.processInfo.systemUptime)\n"
            let attachment = XCTAttachment(string: state)
            attachment.name = name + "-state"; attachment.lifetime = .keepAlways; add(attachment)
            // These existing captures are sequential too; they do not freeze the sampled state.
            capture(app, name: name)
        }

        func valid(_ frame: CGRect) -> Bool {
            [frame.minX, frame.minY, frame.maxX, frame.maxY, frame.width, frame.height]
                .allSatisfy { $0.isFinite } && !frame.isEmpty
        }
        func aspect(_ frame: CGRect) -> String {
            guard valid(frame) else { return "invalid" }
            if frame.width == frame.height { return "square" }
            return frame.width > frame.height ? "wide" : "tall"
        }
        let appState = app.state
        let appFrame = app.frame
        let physicalOrientation = XCUIDevice.shared.orientation
        state += "appState=\(appState.rawValue) appFrame=\(appFrame) appAspect=\(aspect(appFrame)) physicalOrientation=\(physicalOrientation.rawValue)\n"

        // Materialize each query once and bind only a sole result; never choose by position or hit status.
        let targets = app.buttons.matching(identifier: "workspace-actions").allElementsBoundByAccessibilityElement
        let references = app.buttons.matching(identifier: "open-pro").allElementsBoundByAccessibilityElement
        let windows = app.windows.allElementsBoundByAccessibilityElement
        state += "targetCount=\(targets.count) referenceCount=\(references.count) windowCount=\(windows.count)\n"
        guard targets.count == 1, references.count == 1, windows.count == 1,
              let target = targets.first, let reference = references.first, let window = windows.first else {
            state += "result=INCONCLUSIVE reason=nonunique-or-missing-binding remaining=NOT_READ\n"
            return
        }
        let targetExists = target.exists
        let referenceExists = reference.exists
        let windowExists = window.exists
        state += "targetExists=\(targetExists) referenceExists=\(referenceExists) windowExists=\(windowExists)\n"
        guard targetExists, referenceExists, windowExists else {
            state += "result=INCONCLUSIVE reason=absent-after-binding remaining=NOT_READ\n"
            return
        }
        let targetEnabled = target.isEnabled
        let referenceEnabled = reference.isEnabled
        let targetFrame = target.frame
        let referenceFrame = reference.frame
        let windowFrame = window.frame
        let targetLabel = target.label
        let validFrames = valid(appFrame) && valid(windowFrame) && valid(targetFrame) && valid(referenceFrame)
        let targetInApp = appFrame.contains(targetFrame)
        let referenceInApp = appFrame.contains(referenceFrame)
        let targetInWindow = windowFrame.contains(targetFrame)
        let referenceInWindow = windowFrame.contains(referenceFrame)
        state += "targetEnabled=\(targetEnabled) targetFrame=\(targetFrame) targetLabel=\(String(reflecting: targetLabel))\n"
        state += "referenceEnabled=\(referenceEnabled) referenceFrame=\(referenceFrame) reference=open-pro observationOnly=true\n"
        state += "soleWindowFrame=\(windowFrame) windowAspect=\(aspect(windowFrame)) windowEqualsApp=\(windowFrame == appFrame)\n"
        state += "validFrames=\(validFrames) targetInApp=\(targetInApp) referenceInApp=\(referenceInApp) targetInWindow=\(targetInWindow) referenceInWindow=\(referenceInWindow)\n"
        guard appState == .runningForeground, targetEnabled, referenceEnabled, validFrames,
              targetInApp, referenceInApp, targetInWindow, referenceInWindow else {
            state += "result=INCONCLUSIVE reason=ineligible-state-or-geometry remaining=NOT_READ\n"
            return
        }
        let targetStart = ProcessInfo.processInfo.systemUptime
        let targetHit = target.isHittable
        let targetEnd = ProcessInfo.processInfo.systemUptime
        state += "targetHit=\(targetHit) start=\(targetStart) end=\(targetEnd)\n"
        let referenceStart = ProcessInfo.processInfo.systemUptime
        let referenceHit = reference.isHittable
        let referenceEnd = ProcessInfo.processInfo.systemUptime
        state += "referenceHit=\(referenceHit) start=\(referenceStart) end=\(referenceEnd)\n"
        state += "result=SEQUENTIAL_SAMPLES targetHit=\(targetHit) referenceHit=\(referenceHit)\n"
        state += "No stability, simultaneous-state, main-window, global-hit-testing, or cause claim. Original readiness and tap remain authoritative.\n"
    }

    @MainActor
    private func revealMenuEntry(_ entry: XCUIElement, in app: XCUIApplication) {
        guard !entry.isHittable else { return }
        capture(app, name: "privacy-menu-before-scroll")
        // At AX5 the system menu can scroll independently of the workspace.
        // Use an actual ancestor of this entry, never swipe the whole app.
        let queries = [app.scrollViews, app.collectionViews, app.menus].map {
            $0.containing(.button, identifier: entry.identifier)
        }
        guard let query = queries.first(where: { $0.count == 1 && $0.firstMatch.isHittable }) else {
            XCTFail("No unique visible menu container contains the privacy entry.")
            return
        }
        let menu = query.firstMatch
        for _ in 0..<4 {
            if entry.isHittable { break }
            menu.swipeUp(velocity: .slow)
        }
        capture(app, name: "privacy-menu-after-scroll")
    }

    @MainActor
    private func waitForInformation(in app: XCUIApplication, language: String) {
        XCTAssertTrue(informationList(in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.navigationBars[language == "ru" ? "Конфиденциальность и поддержка" : "Privacy and support"].exists)
        let close = app.buttons["close-privacy-support"]
        XCTAssertEqual(close.label, language == "ru" ? "Готово" : "Done")
        XCTAssertTrue(close.isHittable)
    }

    @MainActor
    private func readEverySectionAndFooter(in app: XCUIApplication, language: String) -> [String: String] {
        let list = informationList(in: app)
        let device = UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone"
        let size = UIApplication.shared.preferredContentSizeCategory.rawValue
        let prefix = "privacy-\(language)-\(device)-\(size)"
        let capturePoints = [
            "privacy-text-overview-0": "opening",
            "privacy-text-queue-1": "queue",
            "privacy-text-sharing-1": "sharing",
            "privacy-preview-notice": "footer"
        ]
        var read: [String: String] = [:]
        for identifier in paragraphIDs + ["privacy-preview-notice"] {
            let paragraph = app.staticTexts[identifier]
            reveal(paragraph, in: list, app: app)
            assertTranslated(paragraph, language: language)
            XCTAssertGreaterThan(paragraph.frame.width, 0)
            XCTAssertGreaterThanOrEqual(paragraph.frame.minX, list.frame.minX - 2)
            XCTAssertLessThanOrEqual(paragraph.frame.maxX, list.frame.maxX + 2,
                                     "Paragraphs must wrap within the information list.")
            read[identifier] = paragraph.label
            if let name = capturePoints[identifier] {
                waitForStableFrame(paragraph)
                capture(app, name: "\(prefix)-\(name)")
            }
        }
        for identifier in ["privacy-policy-link", "support-guide-link", "public-issues-link"] {
            let link = app.descendants(matching: .any)[identifier].firstMatch
            reveal(link, in: list, app: app, needsCenter: true)
            assertTranslated(link, language: language)
            XCTAssertTrue(link.isHittable)
            // Visibility is verified without following an external destination.
        }
        XCTAssertEqual(app.state, .runningForeground)
        XCTAssertTrue(app.buttons["close-privacy-support"].isHittable)
        return read
    }

    @MainActor
    private func assertTranslated(_ element: XCUIElement, language: String) {
        XCTAssertFalse(element.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        XCTAssertFalse(element.label.contains("privacy."), "A semantic resource key must not reach the UI.")
        if language == "ru" {
            XCTAssertNotNil(element.label.range(of: "[А-Яа-яЁё]", options: .regularExpression))
        }
    }

    @MainActor
    private func verifySameOpeningParagraph(in app: XCUIApplication, expected: String?) {
        let opening = app.staticTexts[paragraphIDs[0]]
        reveal(opening, in: informationList(in: app), app: app)
        guard let expected else {
            XCTFail("The first information read must capture its opening paragraph")
            return
        }
        XCTAssertEqual(opening.label, expected)
    }

    @MainActor
    private func dismissInformation(in app: XCUIApplication) {
        let close = app.buttons["close-privacy-support"]
        XCTAssertTrue(close.isHittable)
        close.tap()
        waitUntil("The information sheet must actually close") { !close.exists }
    }

    @MainActor
    private func informationList(in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)["privacy-support-list"].firstMatch
    }

    @MainActor
    private func reveal(_ element: XCUIElement, in scroll: XCUIElement, app: XCUIApplication, needsCenter: Bool = false) {
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        for _ in 0..<16 {
            var visible = scroll.frame.intersection(app.frame)
            for bar in app.navigationBars.allElementsBoundByIndex where bar.isHittable {
                let top = max(visible.minY, bar.frame.maxY)
                visible = CGRect(x: visible.minX, y: top, width: visible.width, height: max(0, visible.maxY - top))
            }
            visible = visible.insetBy(dx: 4, dy: 12)
            guard visible.width > 20 && visible.height > 40 else {
                XCTFail("No usable viewport for \(element.identifier)")
                return
            }
            let frame = element.exists ? element.frame : .zero
            let overlap = visible.intersection(frame)
            let ready = needsCenter ? visible.contains(CGPoint(x: frame.midX, y: frame.midY))
                : !overlap.isNull && overlap.height >= min(24, frame.height)
            if element.exists && element.isHittable && ready { return }
            guard remainingScrollGestures > 0 else {
                XCTFail("The bounded scrolling budget was exhausted at \(element.identifier)")
                return
            }
            remainingScrollGestures -= 1
            let upwards = !element.exists || frame.midY >= visible.midY
            let origin = app.coordinate(withNormalizedOffset: .zero)
            let x = visible.midX
            let from = CGPoint(x: x, y: visible.minY + visible.height * (upwards ? 0.8 : 0.2))
            let to = CGPoint(x: x, y: visible.minY + visible.height * (upwards ? 0.2 : 0.8))
            origin.withOffset(CGVector(dx: from.x, dy: from.y)).press(forDuration: 0.05,
                thenDragTo: origin.withOffset(CGVector(dx: to.x, dy: to.y)))
        }
        capture(app, name: "privacy-unreachable-\(element.identifier)")
        XCTFail("Could not reveal \(element.identifier) within the natural scroll viewport.")
    }

    @MainActor
    private func waitUntil(_ description: String, condition: @escaping () -> Bool) {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in condition() }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 6), .completed, description)
    }

    @MainActor
    private func waitForStableFrame(_ element: XCUIElement) {
        var previous = CGRect.null
        var stableSince = Date()
        waitUntil("The reading position must settle before capture") {
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
            return Date().timeIntervalSince(stableSince) >= 0.5
        }
    }

    @MainActor
    private func capture(_ app: XCUIApplication, name: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name; screenshot.lifetime = .keepAlways; add(screenshot)
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = name + "-hierarchy"; hierarchy.lifetime = .keepAlways; add(hierarchy)
    }
}

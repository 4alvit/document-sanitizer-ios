import Foundation
import LocalizationSupport
import SwiftUI
import UIKit
import XCTest
@testable import CleanSend

@MainActor
final class PrivacySupportTests: XCTestCase {
    func testBundledPrivacyCopyHasCompleteEnglishAndRussianEntries() throws {
        let sections = PrivacySupportContent.sections
        XCTAssertEqual(Set(sections.map(\.id)),
                       Set(["overview", "files", "queue", "presets", "sharing", "apple", "support"]),
                       "The offline information must cover every promised data-handling topic.")
        XCTAssertEqual(Set(sections.map(\.id)).count, sections.count)
        XCTAssertTrue(sections.allSatisfy { !$0.paragraphKeys.isEmpty })

        let keys = PrivacySupportContent.localizedKeys
        XCTAssertFalse(keys.isEmpty)
        XCTAssertEqual(Set(keys).count, keys.count)
        XCTAssertTrue(keys.allSatisfy { $0.hasPrefix("privacy.") })
        for section in sections {
            XCTAssertTrue(keys.contains(section.titleKey))
            XCTAssertTrue(section.paragraphKeys.allSatisfy(keys.contains))
        }

        for language in ["en", "ru"] {
            // Read this exact lproj directly: catalog fallback must not hide a
            // missing Russian entry or a resource omitted from the app target.
            let directory = try XCTUnwrap(Bundle.main.url(forResource: language, withExtension: "lproj"))
            let data = try Data(contentsOf: directory.appendingPathComponent("Localizable.strings"))
            let table = try XCTUnwrap(try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: String])
            let catalog = LocalizedCatalog(bundle: .main, preferredLanguages: [language])
            XCTAssertEqual(catalog.language, language)
            for key in keys {
                let value = try XCTUnwrap(table[key], "Missing actual \(language) resource: \(key)")
                XCTAssertFalse(value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, key)
                XCTAssertNotEqual(value, key, "Semantic keys must never be displayed as copy.")
                XCTAssertEqual(catalog.text(key), value, "The app must resolve the bundled \(language) copy.")
                if language == "ru" {
                    XCTAssertNotNil(value.range(of: "[А-Яа-яЁё]", options: .regularExpression),
                                    "Russian entry must contain translated text: \(key)")
                }
            }
            for key in ["Privacy and support", "Done"] {
                XCTAssertNotNil(table[key], "The information sheet's navigation must also be bundled.")
            }
        }
    }

    func testOnlineResourcesUseReviewedPinnedHTTPSDestinations() throws {
        // These documents exist at this reviewed commit; moving main is not
        // interchangeable with the published preview policy/support content.
        let revision = "d4976ab9a424fa1b3ef008b762fa668e8efb14b1"
        let expected = [
            (PrivacySupportContent.privacyPolicyURL,
             "https://github.com/4alvit/document-sanitizer-ios/blob/\(revision)/docs/PRIVACY.md"),
            (PrivacySupportContent.supportGuideURL,
             "https://github.com/4alvit/document-sanitizer-ios/blob/\(revision)/docs/SUPPORT.md"),
            (PrivacySupportContent.issuesURL,
             "https://github.com/4alvit/document-sanitizer-ios/issues")
        ]
        for (url, destination) in expected {
            XCTAssertEqual(url.absoluteString, destination)
            let components = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false))
            XCTAssertEqual(components.scheme, "https")
            XCTAssertEqual(components.host, "github.com")
            XCTAssertNil(components.user)
            XCTAssertNil(components.password)
            XCTAssertNil(components.port)
            XCTAssertNil(components.query)
            XCTAssertNil(components.fragment)
        }
    }

    func testInformationViewRendersWithoutPurchaseStateOrAutomaticURLOpening() async throws {
        let appeared = expectation(description: "Standalone offline information appeared")
        appeared.assertForOverFulfill = false
        var openedURLs: [URL] = []
        let content = InformationView()
            .environment(\.openURL, OpenURLAction { url in
                openedURLs.append(url)
                return .handled
            })
            .onAppear { appeared.fulfill() }
        // Deliberately supply no ProStore, Workspace or other environment object.
        let host = UIHostingController(rootView: content)
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let previousKeyWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            previousKeyWindow?.makeKey()
        }

        await fulfillment(of: [appeared], timeout: 3)
        host.view.layoutIfNeeded()
        await Task.yield()
        host.view.layoutIfNeeded()
        XCTAssertTrue(host.view.window === window)
        XCTAssertFalse(host.view.bounds.isEmpty)
        XCTAssertTrue(containsScrollView(host.view), "The information List must actually be mounted.")
        XCTAssertTrue(openedURLs.isEmpty, "Presenting bundled information must not open an external destination.")
        // This recorder covers SwiftUI openURL actions during initial rendering.
        // It is not a claim that every networking API or future action is blocked.
    }

    private func containsScrollView(_ view: UIView) -> Bool {
        view is UIScrollView || view.subviews.contains(where: containsScrollView)
    }
}

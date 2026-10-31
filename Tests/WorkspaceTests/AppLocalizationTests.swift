import Foundation
import LocalizationSupport
import SanitizerCore
import XCTest
@testable import CleanSend

@MainActor
final class AppLocalizationTests: XCTestCase {
    func testActualApplicationResourcesAndRussianRegionalPlurals() {
        let ru = LocalizedCatalog(bundle: .main, preferredLanguages: ["ru-RU"], formattingLocale: Locale(identifier: "en_US"))
        XCTAssertEqual(ru.language, "ru")
        XCTAssertEqual(ru.text("Cancel"), "Отмена")
        XCTAssertEqual(ru.text("Left"), "Слева")
        XCTAssertEqual([0, 1, 2, 5, 21].map { ru.count("count.files", $0) },
                       ["0 файлов", "1 файл", "2 файла", "5 файлов", "21 файл"])
        XCTAssertEqual([0, 1, 2, 5, 21].map { ru.count("count.pages", $0) },
                       ["0 страниц", "1 страница", "2 страницы", "5 страниц", "21 страница"])
        XCTAssertEqual(ru.number(1234.5), "1,234.5")
        let fallback = LocalizedCatalog(bundle: .main, preferredLanguages: ["fr-FR"])
        XCTAssertEqual(fallback.language, "en")
        XCTAssertEqual(fallback.text("Cancel"), "Cancel")
    }

    func testAllRussianPluralFamiliesUseUILanguageWithUSRegion() {
        let ru = LocalizedCatalog(bundle: .main, preferredLanguages: ["ru"], formattingLocale: Locale(identifier: "en_US"))
        let endings = [
            "count.hiddenAreas": ["скрытая область", "скрытые области", "скрытых областей"],
            "count.savedAreas": ["сохранённая область", "сохранённые области", "сохранённых областей"],
            "count.newAreas": ["новая область", "новые области", "новых областей"],
            "count.pageAreas": ["область с этой страницы", "области с этой страницы", "областей с этой страницы"],
            "count.suggestedLines": ["предложенная строка", "предложенные строки", "предложенных строк"],
            "count.hideLines": ["строку", "строки", "строк"]
        ]
        for (key, forms) in endings {
            for (count, form) in [(0, 2), (1, 0), (2, 1), (4, 1), (5, 2), (11, 2), (14, 2), (21, 0), (22, 1), (25, 2)] {
                XCTAssertTrue(ru.count(key, count).hasSuffix(forms[form]), "\(key) with \(count)")
            }
        }
    }

    func testEmbeddedExtensionHasItsOwnRussianResources() throws {
        let url = try XCTUnwrap(Bundle.main.builtInPlugInsURL).appendingPathComponent("CleanSendShare.appex")
        let bundle = try XCTUnwrap(Bundle(url: url))
        let ru = LocalizedCatalog(bundle: bundle, preferredLanguages: ["ru"])
        XCTAssertEqual(ru.text("Send to RedactLeaf"), "Отправить в RedactLeaf")
        XCTAssertEqual(ru.text("Done"), "Готово")
    }

    func testActualDemoRendersSearchableLocalizedTextAndLiteralUserData() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let workspace = Workspace(temporaryRoot: directory, sharedInbox: nil)
        workspace.loadDemo()
        let page = try XCTUnwrap(workspace.pages.first)
        let russian = Bundle.main.preferredLocalizations.first == "ru"
        XCTAssertEqual(page.sourceName, russian ? "Пример квитанции" : "Synthetic receipt")
        let latin = try await TextRecognizer.matches(in: page.image, query: "Alex Example")
        XCTAssertEqual(latin.count, 1)
        let localized = try await TextRecognizer.matches(in: page.image, query: russian ? "ремонт" : "Window")
        XCTAssertEqual(localized.count, 1)
        let amount = try await TextRecognizer.matches(in: page.image, query: "125")
        XCTAssertEqual(amount.count, 1)
    }

    func testPriceAndUserNamesAreLiteralFormattingArguments() {
        let ru = LocalizedCatalog(bundle: .main, preferredLanguages: ["ru"])
        let price = "19,99 €"
        XCTAssertTrue(ru.format("Unlock Pro · %@", price).hasSuffix(price))
        XCTAssertEqual(ru.format("Customer: %@", "Cancel % PDF"), "Клиент: Cancel % PDF")
    }

    func testAuthoredErrorMessagesFollowCurrentAppLanguage() {
        // No StoreKit request is made. These are ordinary error producers.
        if let expected = ProcessInfo.processInfo.environment["REDACTLEAF_EXPECTED_UI_LANGUAGE"] {
            XCTAssertEqual(Bundle.main.preferredLocalizations.first, expected, "Verify the test process actually selected the requested UI language")
        }
        let expectedRussian = Bundle.main.preferredLocalizations.first == "ru"
        XCTAssertEqual(SanitizerError.lockedPDF.errorDescription,
                       expectedRussian ? "Разблокируйте этот PDF перед импортом." : "Unlock this PDF before importing it.")
        XCTAssertEqual(L10n.text("Purchase cancelled."), expectedRussian ? "Покупка отменена." : "Purchase cancelled.")
    }
}

import Foundation
import XCTest
@testable import LocalizationSupport

final class LocalizationTests: XCTestCase {
    private func catalog(_ languages: [String], _ region: String = "en_US") -> LocalizedCatalog {
        LocalizedCatalog(bundle: .module, preferredLanguages: languages, formattingLocale: Locale(identifier: region))
    }

    func testPreferredSupportedLanguageAndDevelopmentFallback() {
        for (preferences, expected) in [(["ru-RU", "en-US"], "ru"),
                                         (["en-GB", "ru-RU"], "en"),
                                         (["fr-FR", "ru-RU", "en-US"], "ru"),
                                         (["fr-FR"], "en")] {
            let result = catalog(preferences)
            XCTAssertEqual(result.language, expected)
            XCTAssertEqual(result.text("Greeting"), expected == "ru" ? "Здравствуйте" : "Hello")
        }
    }

    func testMissingTranslationFallsBackToEnglishAndUnknownToSource() {
        let russian = catalog(["ru"])
        XCTAssertEqual(russian.text("English fallback"), "Only in English")
        XCTAssertEqual(russian.text("Unknown source"), "Unknown source")
    }

    func testRussianIntegerPluralsAreIndependentOfFormattingRegion() {
        let values = [0, 1, 2, 4, 5, 11, 14, 21, 22, 25, 101, 111]
        let expected = ["0 файлов", "1 файл", "2 файла", "4 файла", "5 файлов", "11 файлов",
                        "14 файлов", "21 файл", "22 файла", "25 файлов", "101 файл", "111 файлов"]
        for region in ["en_US", "ru_RU", "de_DE"] {
            let russian = catalog(["ru"], region)
            XCTAssertEqual(values.map { russian.count("count.files", $0) }, expected)
        }
        let english = catalog(["en"], "ru_RU")
        XCTAssertEqual([0, 1, 2, 5, 21].map { english.count("count.files", $0) },
                       ["0 files", "1 file", "2 files", "5 files", "21 files"])
    }

    func testRegionalNumbersPercentAndCurrencyKeepTheirMeaning() {
        let us = catalog(["ru"], "en_US")
        let de = catalog(["ru"], "de_DE")
        XCTAssertEqual(us.number(1234.5), "1,234.5")
        XCTAssertEqual(de.number(1234.5), "1.234,5")
        XCTAssertEqual(us.percent(0.25), "25%")
        XCTAssertEqual(de.percent(0.25).filter { !$0.isWhitespace }, "25%")
        XCTAssertTrue(us.currency(125, code: "USD").contains("125.00"))
        XCTAssertTrue(de.currency(125, code: "USD").contains("125,00"))
        XCTAssertFalse(de.currency(125, code: "USD").contains("€"))
    }

    func testPositionalInterpolationDoesNotTranslateUserContent() {
        let russian = catalog(["ru"])
        XCTAssertEqual(russian.format("File %@", "Greeting 100% 📄"), "Файл Greeting 100% 📄")
        XCTAssertEqual(russian.format("%@ then %@", "first", "second"), "second, затем first")
    }
}

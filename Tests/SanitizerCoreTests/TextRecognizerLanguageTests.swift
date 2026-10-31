import XCTest
import CoreGraphics
import CoreText
@testable import SanitizerCore

final class TextRecognizerLanguageTests: XCTestCase {
    // Real Vision recognition, not an injected observation or a configuration-only test.
    // Match the app's 900 x 1200 Russian sample and 30-point receipt body.
    func testRussianReceiptFindsCyrillicAndLatinWholeLines() async throws {
        let context = try RasterCanvas.make(width: 900, height: 1200)
        draw("СИНТЕТИЧЕСКИЙ ПРИМЕР", top: 80, size: 44, in: context)
        draw("Без настоящих персональных данных", top: 150, size: 30, in: context)
        let lines = [
            "КВИТАНЦИЯ ЗА УСЛУГУ",
            "Клиент: Alex Example",
            "Эл. почта: alex@example.invalid",
            "Адрес: 123 Example Street",
            "Номер: DEMO-2048",
            "Услуга: ремонт окна",
            "Итого: 125,00 $",
            "Попробуйте скрыть имя клиента и почту."
        ]
        for (index, line) in lines.enumerated() {
            draw(line, top: CGFloat(270 + index * 80), size: 30, in: context)
        }
        let image = try XCTUnwrap(context.makeImage())

        let latin = try await TextRecognizer.matches(in: image, query: "ALEX EXAMPLE")
        let customer = try XCTUnwrap(latin.first)
        XCTAssertEqual(latin.count, 1)
        XCTAssertTrue(customer.text.contains("Клиент:"), "A Latin query must return the entire mixed-script line")
        XCTAssertTrue(customer.text.contains("Alex Example"))
        XCTAssertGreaterThan(customer.rect.y, 0.25)
        XCTAssertLessThan(customer.rect.y, 0.35)
        XCTAssertTrue(customer.rect.isValid)
        XCTAssertNoThrow(try customer.rect.pixelRect(imageWidth: image.width, imageHeight: image.height))

        let cyrillic = try await TextRecognizer.matches(in: image, query: "  РЕМОНТ  ")
        let service = try XCTUnwrap(cyrillic.first)
        XCTAssertEqual(cyrillic.count, 1)
        XCTAssertTrue(service.text.contains("Услуга:"), "A Cyrillic query must return the whole line, not only the query")
        XCTAssertTrue(service.text.contains("окна"))
        XCTAssertGreaterThan(service.rect.y, 0.50)
        XCTAssertLessThan(service.rect.y, 0.62)
        XCTAssertTrue(service.rect.isValid)
        XCTAssertNoThrow(try service.rect.pixelRect(imageWidth: image.width, imageHeight: image.height))

        let email = try await TextRecognizer.matches(in: image, query: "alex@example.invalid")
        XCTAssertEqual(email.count, 1)
        XCTAssertTrue(try XCTUnwrap(email.first).text.contains("почта:"))
        let absent = try await TextRecognizer.matches(in: image, query: "НесуществующийПолучатель")
        XCTAssertTrue(absent.isEmpty)
    }

    private func draw(_ text: String, top: CGFloat, size: CGFloat, in context: CGContext) {
        let font = CTFontCreateUIFontForLanguage(.system, size, nil)!
        let string = NSAttributedString(string: text, attributes: [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0, alpha: 1)
        ])
        context.textPosition = CGPoint(x: 70, y: 1200 - top - size)
        CTLineDraw(CTLineCreateWithAttributedString(string), context)
    }
}

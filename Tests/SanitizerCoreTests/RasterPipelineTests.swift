import XCTest
import CoreGraphics
import CoreText
import ImageIO
import PDFKit
import UniformTypeIdentifiers
@testable import SanitizerCore

final class RasterPipelineTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("CleanSendTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws { try FileManager.default.removeItem(at: directory) }

    func testPDFCropAndAllQuarterTurnRotations() throws {
        let expected: [[RGB]] = [
            [.red, .green, .blue, .yellow],
            [.blue, .red, .yellow, .green],
            [.yellow, .blue, .green, .red],
            [.green, .yellow, .red, .blue]
        ]
        for (index, rotation) in [0, 90, 180, 270].enumerated() {
            let input = try fixturePDF(name: "crop-\(rotation).pdf", rotation: rotation)
            let original = try Data(contentsOf: input)
            let page = try XCTUnwrap(RasterImporter.load(url: input).first)
            XCTAssertEqual(page.image.width, rotation % 180 == 0 ? 200 : 120)
            XCTAssertEqual(page.image.height, rotation % 180 == 0 ? 120 : 200)
            let actual = try quadrantColors(page.image)
            for (a, e) in zip(actual, expected[index]) { assertColor(a, e) }
            XCTAssertEqual(try Data(contentsOf: input), original, "Import must not modify its input")
        }
    }

    func testPDFCropClippedToMediaBox() throws {
        let input = try fixturePDF(name: "oversized-crop.pdf", rotation: 0,
                                   crop: CGRect(x: -20, y: -10, width: 230, height: 200))
        let page = try XCTUnwrap(RasterImporter.load(url: input).first)
        XCTAssertEqual(page.image.width, 360)
        XCTAssertEqual(page.image.height, 320)
    }

    func testExistingOpaqueAnnotationNeverRevealsCoveredPixels() throws {
        for rotation in [0, 90, 180, 270] {
            let url = try fixturePDF(name: "covered-\(rotation).pdf", rotation: rotation, withText: true)
            let document = try XCTUnwrap(PDFDocument(url: url))
            let page = try XCTUnwrap(document.page(at: 0))
            let covering = PDFAnnotation(bounds: CGRect(x: 55, y: 55, width: 50, height: 30),
                                          forType: .square, withProperties: nil)
            covering.color = .black
            covering.interiorColor = .black
            page.addAnnotation(covering)
            XCTAssertTrue(document.write(to: url))
            let raster = try XCTUnwrap(RasterImporter.load(url: url).first)
            assertColor(try pixel(raster.image, x: raster.image.width / 2, y: raster.image.height / 2), .black)
            let output = try XCTUnwrap(RasterExporter.export(pages: [raster], format: .pdf, to: directory).first)
            let exported = try XCTUnwrap(PDFDocument(url: output)?.page(at: 0))
            XCTAssertTrue(exported.annotations.isEmpty)
            let roundtrip = try XCTUnwrap(RasterImporter.load(url: output).first)
            assertColor(try pixel(roundtrip.image, x: roundtrip.image.width / 2, y: roundtrip.image.height / 2), .black)
        }
    }

    func testTopLeftMaskAndFreshOpaquePixels() throws {
        var page = RasterPage(image: try solidImage(width: 100, height: 60), sourceName: "Synthetic", sourcePageNumber: 1)
        page.redactions = [Redaction(rect: NormalizedRect(x: 0, y: 0, width: 0.5, height: 0.5))]
        let rendered = try RasterSanitizer.render(page)
        assertColor(try pixel(rendered, x: 10, y: 10), .black)
        assertColor(try pixel(rendered, x: 10, y: 50), .white)
        assertColor(try pixel(rendered, x: 75, y: 10), .white)
        assertColor(try pixel(page.image, x: 10, y: 10), .white)
        XCTAssertEqual(rendered.alphaInfo, .noneSkipLast)
    }

    func testSubpixelMaskRoundsOutwards() throws {
        var page = RasterPage(image: try solidImage(width: 10, height: 10), sourceName: "Synthetic", sourcePageNumber: 1)
        page.redactions = [Redaction(rect: NormalizedRect(x: 0.11, y: 0.21, width: 0.001, height: 0.001))]
        let result = try RasterSanitizer.render(page)
        assertColor(try pixel(result, x: 1, y: 2), .black)
        assertColor(try pixel(result, x: 0, y: 2), .white)
        assertColor(try pixel(result, x: 1, y: 1), .white)
        assertColor(try pixel(result, x: 2, y: 2), .white)
    }

    func testInvalidMasksFailClosedBeforeCreatingFiles() throws {
        let invalid: [NormalizedRect] = [
            .init(x: .nan, y: 0, width: 0.1, height: 0.1),
            .init(x: 0, y: .infinity, width: 0.1, height: 0.1),
            .init(x: -0.01, y: 0, width: 0.1, height: 0.1),
            .init(x: 0, y: 0, width: 0, height: 0.1),
            .init(x: 0, y: 0, width: 0.1, height: -0.1),
            .init(x: 0.9, y: 0, width: 0.2, height: 0.1),
            .init(x: 0, y: 0.9, width: 0.1, height: 0.2),
            .init(x: 0, y: 0, width: .infinity, height: 0.1)
        ]
        for rectangle in invalid {
            var page = RasterPage(image: try solidImage(width: 10, height: 10), sourceName: "Synthetic", sourcePageNumber: 1)
            page.redactions = [Redaction(rect: rectangle)]
            XCTAssertThrowsError(try RasterSanitizer.render(page)) { XCTAssertEqual($0 as? SanitizerError, .invalidRedaction) }
            XCTAssertThrowsError(try RasterExporter.export(pages: [page], format: .pdf, to: directory))
        }
        XCTAssertEqual(try contents(), [])
    }

    func testImageAlphaFlattenedAndMetadataRemoved() throws {
        let space = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
        let context = try XCTUnwrap(CGContext(data: nil, width: 40, height: 20, bitsPerComponent: 8,
                                              bytesPerRow: 160, space: space,
                                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.setFillColor(red: 1, green: 0, blue: 0, alpha: 0.5)
        context.fill(CGRect(x: 0, y: 0, width: 40, height: 20))
        let input = directory.appendingPathComponent("alpha.png")
        try saveImage(try XCTUnwrap(context.makeImage()), url: input, type: UTType.png.identifier,
                      properties: [kCGImagePropertyPNGDictionary: [kCGImagePropertyPNGAuthor: "SYNTHETIC_AUTHOR"]])
        let page = try XCTUnwrap(RasterImporter.load(url: input).first)
        assertColor(try pixel(page.image, x: 10, y: 10), RGB(r: 255, g: 127, b: 127), tolerance: 2)
        let output = try XCTUnwrap(RasterExporter.export(pages: [page], format: .png, to: directory).first)
        let source = try XCTUnwrap(CGImageSourceCreateWithURL(output as CFURL, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        let png = properties[kCGImagePropertyPNGDictionary] as? [CFString: Any]
        XCTAssertNil(png?[kCGImagePropertyPNGAuthor])
        let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
        let generatedOnly: Set<CFString> = [kCGImagePropertyExifColorSpace,
                                           kCGImagePropertyExifPixelXDimension,
                                           kCGImagePropertyExifPixelYDimension]
        XCTAssertTrue(Set(exif.keys).isSubset(of: generatedOnly))
        if let value = exif[kCGImagePropertyExifColorSpace] as? NSNumber { XCTAssertEqual(value.intValue, 1) }
        if let value = exif[kCGImagePropertyExifPixelXDimension] as? NSNumber { XCTAssertEqual(value.intValue, 40) }
        if let value = exif[kCGImagePropertyExifPixelYDimension] as? NSNumber { XCTAssertEqual(value.intValue, 20) }
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        let exported = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertTrue([CGImageAlphaInfo.none, .noneSkipLast, .noneSkipFirst].contains(exported.alphaInfo))
    }

    func testExifOrientationIsApplied() throws {
        let context = try RasterCanvas.make(width: 40, height: 20)
        context.setFillColor(red: 1, green: 0, blue: 0, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: 20, height: 20))
        let input = directory.appendingPathComponent("orientation.jpg")
        try saveImage(try XCTUnwrap(context.makeImage()), url: input, type: UTType.jpeg.identifier,
                      properties: [kCGImagePropertyOrientation: 6,
                                   kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 12.345],
                                   kCGImageDestinationLossyCompressionQuality: 1])
        let page = try XCTUnwrap(RasterImporter.load(url: input).first)
        XCTAssertEqual(page.image.width, 20)
        XCTAssertEqual(page.image.height, 40)
        assertColor(try pixel(page.image, x: 10, y: 5), .red, tolerance: 5)
        assertColor(try pixel(page.image, x: 10, y: 35), .white, tolerance: 5)
        let output = try XCTUnwrap(RasterExporter.export(pages: [page], format: .jpeg, to: directory).first)
        let source = try XCTUnwrap(CGImageSourceCreateWithURL(output as CFURL, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        XCTAssertNil(properties[kCGImagePropertyOrientation])
    }

    func testPDFExportHasNoOriginalTextAnnotationsOrMetadataAndMatchesPreview() throws {
        let input = try fixturePDF(name: "original.pdf", rotation: 90, withText: true)
        let original = try Data(contentsOf: input)
        let sourcePDF = try XCTUnwrap(PDFDocument(url: input))
        XCTAssertTrue(sourcePDF.string?.contains("SYNTHETIC_SECRET_42") == true)
        var page = try XCTUnwrap(RasterImporter.load(url: input).first)
        page.redactions = [Redaction(rect: .init(x: 0.1, y: 0.1, width: 0.7, height: 0.8))]
        let preview = try RasterSanitizer.render(page)
        let url = try XCTUnwrap(RasterExporter.export(pages: [page, page], format: .pdf, to: directory).first)
        let pdf = try XCTUnwrap(PDFDocument(url: url))
        XCTAssertEqual(pdf.pageCount, 2)
        XCTAssertTrue((pdf.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        XCTAssertNil(pdf.documentAttributes?[PDFDocumentAttribute.authorAttribute])
        XCTAssertNil(pdf.documentAttributes?[PDFDocumentAttribute.titleAttribute])
        XCTAssertEqual(pdf.documentAttributes?[PDFDocumentAttribute.creatorAttribute] as? String, "RedactLeaf")
        for index in 0..<2 { XCTAssertEqual(pdf.page(at: index)?.annotations.count, 0) }
        let reloaded = try RasterImporter.load(url: url)
        XCTAssertEqual(reloaded.count, 2)
        for result in reloaded {
            XCTAssertEqual(result.image.width, preview.width)
            XCTAssertEqual(result.image.height, preview.height)
            for (x, y) in [(0, 0), (20, 40), (60, 100), (119, 199)] {
                assertColor(try pixel(result.image, x: x, y: y), try pixel(preview, x: x, y: y), tolerance: 2)
            }
        }
        XCTAssertEqual(try Data(contentsOf: input), original)
    }

    func testNameCollisionNeverOverwritesAndRollsBackEarlierFiles() throws {
        let pages = try ["first", "second"].map {
            RasterPage(image: try solidImage(width: 10, height: 10), sourceName: $0, sourcePageNumber: 1)
        }
        let existing = directory.appendingPathComponent("RedactLeaf-page-2-fixed.png")
        let sentinel = Data("DO NOT OVERWRITE".utf8)
        try sentinel.write(to: existing)
        XCTAssertThrowsError(try RasterExporter.export(pages: pages, format: .png, to: directory, identifier: "fixed"))
        XCTAssertEqual(try Data(contentsOf: existing), sentinel)
        XCTAssertEqual(try contents(), [existing.lastPathComponent])
    }

    func testFilenameCannotEscapeDestinationAndRepeatedExportsAreUnique() throws {
        let page = RasterPage(image: try solidImage(width: 10, height: 10), sourceName: "../../secret\n/test", sourcePageNumber: 1)
        let first = try RasterExporter.export(pages: [page], format: .png, to: directory)
        let second = try RasterExporter.export(pages: [page], format: .png, to: directory)
        XCTAssertNotEqual(first, second)
        for url in first + second {
            XCTAssertEqual(url.deletingLastPathComponent().standardizedFileURL, directory.standardizedFileURL)
            XCTAssertFalse(url.lastPathComponent.hasPrefix("."))
            XCTAssertFalse(url.lastPathComponent.contains("\n"))
            XCTAssertFalse(url.lastPathComponent.contains("secret"))
        }
    }

    func testCancellationBeforeExportCreatesNothing() async throws {
        let page = RasterPage(image: try solidImage(width: 10, height: 10), sourceName: "Synthetic", sourcePageNumber: 1)
        let destination = directory!
        let task = Task.detached {
            withUnsafeCurrentTask { $0?.cancel() }
            return try RasterExporter.export(pages: [page], format: .pdf, to: destination)
        }
        do { _ = try await task.value; XCTFail("Cancelled export succeeded") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(try contents(), [])
    }

    func testCancellationDuringExportCleansStagingAndOutputs() async throws {
        let page = RasterPage(image: try solidImage(width: 2_000, height: 2_000), sourceName: "Synthetic", sourcePageNumber: 1)
        let pages = Array(repeating: page, count: 6)
        let destination = directory!
        let task = Task.detached { try RasterExporter.export(pages: pages, format: .png, to: destination) }
        var stagingSeen = false
        for _ in 0..<2_000 {
            if try contents().contains(where: { $0.hasPrefix(".cleansend-stage-") }) {
                stagingSeen = true
                task.cancel()
                break
            }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        XCTAssertTrue(stagingSeen)
        do { _ = try await task.value; XCTFail("Cancelled export succeeded") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(try contents(), [])
    }

    func testAggregatePixelLimitAndEmptyExport() throws {
        let page = RasterPage(image: try solidImage(width: 2_400, height: 2_400), sourceName: "Synthetic", sourcePageNumber: 1)
        XCTAssertThrowsError(try RasterExporter.export(pages: Array(repeating: page, count: 5), format: .pdf, to: directory)) {
            XCTAssertEqual($0 as? SanitizerError, .pixelLimitExceeded)
        }
        XCTAssertThrowsError(try RasterExporter.export(pages: [], format: .pdf, to: directory)) {
            XCTAssertEqual($0 as? SanitizerError, .emptyDocument)
        }
        XCTAssertEqual(try contents(), [])
    }

    func testOCRCaseInsensitiveWholeLineAndEmptyQuery() async throws {
        let context = try RasterCanvas.make(width: 1_000, height: 180)
        drawText("SYNTHETIC Example 42", at: CGPoint(x: 30, y: 65), size: 56, in: context)
        let image = try XCTUnwrap(context.makeImage())
        let empty = try await TextRecognizer.matches(in: image, query: "  ")
        XCTAssertTrue(empty.isEmpty)
        let matches = try await TextRecognizer.matches(in: image, query: "synthetic")
        XCTAssertEqual(matches.count, 1)
        let match = try XCTUnwrap(matches.first)
        XCTAssertTrue(match.text.contains("42"), "The UI must disclose that a whole line is selected")
        XCTAssertGreaterThan(match.rect.width, 0.4)
        XCTAssertGreaterThan(match.rect.y, 0.2)
        XCTAssertLessThan(match.rect.y, 0.6)
        XCTAssertNoThrow(try match.rect.pixelRect(imageWidth: image.width, imageHeight: image.height))
    }

    private func contents() throws -> [String] { try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted() }

    private func solidImage(width: Int, height: Int) throws -> CGImage {
        try XCTUnwrap(RasterCanvas.make(width: width, height: height).makeImage())
    }

    private func saveImage(_ image: CGImage, url: URL, type: String, properties: [CFString: Any]) throws {
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type as CFString, 1, nil))
        CGImageDestinationAddImage(destination, image, properties as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
    }

    private func fixturePDF(name: String, rotation: Int,
                            crop: CGRect = CGRect(x: 30, y: 40, width: 100, height: 60),
                            withText: Bool = false) throws -> URL {
        let data = NSMutableData()
        let consumer = try XCTUnwrap(CGDataConsumer(data: data))
        var media = CGRect(x: 0, y: 0, width: 180, height: 160)
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &media, nil))
        context.beginPDFPage(nil)
        let box = CGRect(x: 30, y: 40, width: 100, height: 60)
        for (color, rectangle) in [
            (RGB.red, CGRect(x: box.minX, y: box.midY, width: 50, height: 30)),
            (RGB.green, CGRect(x: box.midX, y: box.midY, width: 50, height: 30)),
            (RGB.blue, CGRect(x: box.minX, y: box.minY, width: 50, height: 30)),
            (RGB.yellow, CGRect(x: box.midX, y: box.minY, width: 50, height: 30))
        ] {
            context.setFillColor(red: Double(color.r) / 255, green: Double(color.g) / 255,
                                 blue: Double(color.b) / 255, alpha: 1)
            context.fill(rectangle)
        }
        if withText { drawText("SYNTHETIC_SECRET_42", at: CGPoint(x: 33, y: 68), size: 6, in: context) }
        context.endPDFPage()
        context.closePDF()
        let document = try XCTUnwrap(PDFDocument(data: data as Data))
        let page = try XCTUnwrap(document.page(at: 0))
        page.rotation = rotation
        page.setBounds(crop, for: .cropBox)
        if withText {
            page.addAnnotation(PDFAnnotation(bounds: CGRect(x: 40, y: 50, width: 20, height: 10), forType: .text, withProperties: nil))
        }
        document.documentAttributes = [PDFDocumentAttribute.authorAttribute: "SYNTHETIC_AUTHOR",
                                       PDFDocumentAttribute.titleAttribute: "SYNTHETIC_TITLE"]
        let url = directory.appendingPathComponent(name)
        XCTAssertTrue(document.write(to: url))
        return url
    }

    private func drawText(_ text: String, at point: CGPoint, size: CGFloat, in context: CGContext) {
        let font = CTFontCreateWithName("Helvetica" as CFString, size, nil)
        let string = NSAttributedString(string: text, attributes: [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0, alpha: 1)
        ])
        context.textPosition = point
        CTLineDraw(CTLineCreateWithAttributedString(string), context)
    }

    private func quadrantColors(_ image: CGImage) throws -> [RGB] {
        try [(image.width / 8, image.height / 8), (image.width * 7 / 8, image.height / 8),
             (image.width / 8, image.height * 7 / 8), (image.width * 7 / 8, image.height * 7 / 8)]
            .map { try pixel(image, x: $0.0, y: $0.1) }
    }

    private func pixel(_ image: CGImage, x: Int, y: Int) throws -> RGB {
        let context = try RasterCanvas.make(width: image.width, height: image.height)
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        let bytes = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
        let offset = y * context.bytesPerRow + x * 4
        return RGB(r: Int(bytes[offset]), g: Int(bytes[offset + 1]), b: Int(bytes[offset + 2]))
    }

    private func assertColor(_ actual: RGB, _ expected: RGB, tolerance: Int = 1,
                             file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(Double(actual.r), Double(expected.r), accuracy: Double(tolerance), file: file, line: line)
        XCTAssertEqual(Double(actual.g), Double(expected.g), accuracy: Double(tolerance), file: file, line: line)
        XCTAssertEqual(Double(actual.b), Double(expected.b), accuracy: Double(tolerance), file: file, line: line)
    }

    private struct RGB {
        let r: Int
        let g: Int
        let b: Int
        static let red = RGB(r: 255, g: 0, b: 0)
        static let green = RGB(r: 0, g: 255, b: 0)
        static let blue = RGB(r: 0, g: 0, b: 255)
        static let yellow = RGB(r: 255, g: 255, b: 0)
        static let black = RGB(r: 0, g: 0, b: 0)
        static let white = RGB(r: 255, g: 255, b: 255)
    }
}

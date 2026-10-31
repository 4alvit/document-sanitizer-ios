import XCTest
import CoreGraphics
import ImageIO
import PDFKit
import UniformTypeIdentifiers
@testable import SanitizerCore

final class InputHardeningTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("InputHardening-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try FileManager.default.removeItem(at: directory)
    }

    func testPDFMarkerInsideImageMetadataDoesNotChangeDetectedFormat() throws {
        let url = directory.appendingPathComponent("synthetic.png")
        try saveImage(url, type: UTType.png.identifier, properties: [
            kCGImagePropertyPNGDictionary: [kCGImagePropertyPNGDescription: "Synthetic reference to %PDF-1.7"]
        ])
        XCTAssertNotNil(try Data(contentsOf: url).prefix(1_024).range(of: Data("%PDF-".utf8)))
        let pages = try RasterImporter.load(url: url)
        XCTAssertEqual(pages.count, 1)
        XCTAssertEqual(pages.first?.image.width, 32)
        XCTAssertEqual(pages.first?.image.height, 24)
    }

    func testRecognizedImageDoesNotDependOnFilenameExtension() throws {
        let url = directory.appendingPathComponent("misnamed.pdf")
        try saveImage(url, type: UTType.png.identifier)
        let page = try XCTUnwrap(RasterImporter.load(url: url).first)
        XCTAssertEqual(page.image.width, 32)
        XCTAssertEqual(page.image.height, 24)
    }

    func testEmptyUnrecognizedAndHeaderOnlyInputsAreRejected() throws {
        for (index, bytes) in [Data(), Data("not an image".utf8),
                               Data([0xff, 0xd8, 0xff, 0xe0]), Data("%PDF-1.7\n".utf8)].enumerated() {
            let url = directory.appendingPathComponent("malformed-\(index).bin")
            try bytes.write(to: url)
            XCTAssertThrowsError(try RasterImporter.load(url: url))
        }
    }

    func testNormalizedRectMustMakeRepresentableProgress() throws {
        let tooSmall = Double.leastNonzeroMagnitude
        for rect in [
            NormalizedRect(x: 1, y: 0, width: tooSmall, height: 0.25),
            NormalizedRect(x: 0, y: 1, width: 0.25, height: tooSmall),
            NormalizedRect(x: 0.5, y: 0, width: tooSmall, height: 0.25),
            NormalizedRect(x: 0, y: 0.5, width: 0.25, height: tooSmall)
        ] {
            XCTAssertFalse(rect.isValid)
            XCTAssertThrowsError(try rect.pixelRect(imageWidth: 32, imageHeight: 24))
        }
        // A representable subpixel selection at the origin is still valid and
        // must conservatively cover the touched pixel.
        let valid = NormalizedRect(x: 0, y: 0, width: tooSmall, height: tooSmall)
        XCTAssertTrue(valid.isValid)
        XCTAssertEqual(try valid.pixelRect(imageWidth: 32, imageHeight: 24), CGRect(x: 0, y: 23, width: 1, height: 1))
        let tinyInterior = NormalizedRect(x: 0.5, y: 0.5,
                                         width: 0.5.nextUp - 0.5, height: 0.5.nextUp - 0.5)
        XCTAssertTrue(tinyInterior.isValid)
        XCTAssertEqual(try tinyInterior.pixelRect(imageWidth: 32, imageHeight: 24),
                       CGRect(x: 16, y: 11, width: 1, height: 1))
    }

    func testInputFileAndPDFPageLimitsRejectBeforeRasterizing() throws {
        let oversized = directory.appendingPathComponent("oversized.pdf")
        try Data([0]).write(to: oversized)
        let handle = try FileHandle(forWritingTo: oversized)
        try handle.truncate(atOffset: UInt64(RasterLimits.maximumInputBytes + 1))
        try handle.close()
        XCTAssertThrowsError(try RasterImporter.load(url: oversized)) {
            XCTAssertEqual($0 as? SanitizerError, .inputTooLarge)
        }
        let tooMany = try pdfFixture(name: "too-many.bin", pages: 31,
                                    media: CGRect(x: 0, y: 0, width: 10, height: 10))
        XCTAssertThrowsError(try RasterImporter.load(url: tooMany)) {
            XCTAssertEqual($0 as? SanitizerError, .tooManyPages)
        }
    }

    func testLargePDFDownsamplesAndAggregateLimitRemainsEnforced() throws {
        let large = try pdfFixture(name: "large.bin", pages: 1,
                                  media: CGRect(x: 0, y: 0, width: 3_000, height: 1_500))
        let page = try XCTUnwrap(RasterImporter.load(url: large).first)
        XCTAssertEqual(page.image.width, 2_400)
        XCTAssertEqual(page.image.height, 1_200)
        let excessive = try pdfFixture(name: "aggregate.bin", pages: 5,
                                      media: CGRect(x: 0, y: 0, width: 1_200, height: 1_200))
        XCTAssertThrowsError(try RasterImporter.load(url: excessive)) {
            XCTAssertEqual($0 as? SanitizerError, .pixelLimitExceeded)
        }
    }

    func testNegativeOriginCropRotationAndMaskUseTheUprightRaster() throws {
        for rotation in [0, 90, 180, 270] {
            let url = try pdfFixture(name: "negative-\(rotation).bin", pages: 1,
                                     media: CGRect(x: -100, y: -80, width: 200, height: 160))
            let pdf = try XCTUnwrap(PDFDocument(url: url))
            let source = try XCTUnwrap(pdf.page(at: 0))
            source.setBounds(CGRect(x: -50, y: -30, width: 100, height: 60), for: .cropBox)
            source.rotation = rotation
            XCTAssertTrue(pdf.write(to: url))
            var page = try XCTUnwrap(RasterImporter.load(url: url).first)
            XCTAssertEqual(page.image.width, rotation % 180 == 0 ? 200 : 120)
            XCTAssertEqual(page.image.height, rotation % 180 == 0 ? 120 : 200)
            // This is deliberately in upright output coordinates, independent
            // of PDF origin/rotation and never copied from PDF space.
            page.redactions = [Redaction(rect: .init(x: 0, y: 0, width: 0.5, height: 0.5))]
            let image = try RasterSanitizer.render(page)
            let context = try RasterCanvas.make(width: image.width, height: image.height)
            context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            let pixels = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
            for y in 0..<image.height { for x in 0..<image.width {
                let offset = y * context.bytesPerRow + x * 4
                let expected: UInt8 = x < image.width / 2 && y < image.height / 2 ? 0 : 255
                XCTAssertEqual(pixels[offset], expected)
                XCTAssertEqual(pixels[offset + 1], expected)
                XCTAssertEqual(pixels[offset + 2], expected)
            }}
        }
    }

    private func pdfFixture(name: String, pages: Int, media: CGRect) throws -> URL {
        let data = NSMutableData()
        let consumer = try XCTUnwrap(CGDataConsumer(data: data))
        var box = media
        let context = try XCTUnwrap(CGContext(consumer: consumer, mediaBox: &box, nil))
        for _ in 0..<pages {
            context.beginPDFPage(nil)
            context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
            context.fill(media)
            context.endPDFPage()
        }
        context.closePDF()
        let url = directory.appendingPathComponent(name)
        try (data as Data).write(to: url)
        return url
    }

    private func saveImage(_ url: URL, type: String, properties: [CFString: Any] = [:]) throws {
        let context = try RasterCanvas.make(width: 32, height: 24)
        context.setFillColor(red: 1, green: 0, blue: 0, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: 16, height: 24))
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try XCTUnwrap(context.makeImage()), properties as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
    }
}

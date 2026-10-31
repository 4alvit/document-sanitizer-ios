import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Darwin

public enum RasterExporter {
    /// Writes fresh copies. A failure or cancellation removes all files created by this call.
    /// PDF contains only rendered images and a constant RedactLeaf creator value; no source metadata.
    /// ImageIO can generate PNG EXIF ColorSpace/PixelXDimension/PixelYDimension and
    /// an sRGB chunk from the output raster. Those are technical output properties,
    /// never copied source fields. JPEG may similarly describe the output color profile.
    public static func export(pages: [RasterPage], format: ExportFormat, to directory: URL) throws -> [URL] {
        try export(pages: pages, format: format, to: directory, identifier: UUID().uuidString.lowercased())
    }

    // The identifier seam permits deterministic collision tests without weakening the public API.
    static func export(pages: [RasterPage], format: ExportFormat, to directory: URL,
                       identifier: String) throws -> [URL] {
        try Task.checkCancellation()
        guard !pages.isEmpty else { throw SanitizerError.emptyDocument }
        guard pages.count <= RasterLimits.maximumPages else { throw SanitizerError.tooManyPages }
        var pixels = 0
        for page in pages {
            guard page.image.width <= RasterLimits.maximumDimension,
                  page.image.height <= RasterLimits.maximumDimension else {
                throw SanitizerError.pixelLimitExceeded
            }
            pixels += page.image.width * page.image.height
            guard pixels <= RasterLimits.maximumTotalPixels else { throw SanitizerError.pixelLimitExceeded }
            // Validate every selection before performing any disk writes.
            for mask in page.redactions {
                _ = try mask.rect.pixelRect(imageWidth: page.image.width, imageHeight: page.image.height)
            }
        }
        let manager = FileManager.default
        var isDirectory: ObjCBool = false
        guard directory.isFileURL,
              manager.fileExists(atPath: directory.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            throw SanitizerError.exportFailed
        }
        let staging = directory.appendingPathComponent(".cleansend-stage-\(UUID().uuidString)", isDirectory: true)
        do { try manager.createDirectory(at: staging, withIntermediateDirectories: false,
                                         attributes: [.posixPermissions: 0o700]) }
        catch { throw SanitizerError.exportFailed }
        defer { try? manager.removeItem(at: staging) }
        var committed: [URL] = []
        var completed = false
        defer {
            if !completed { for url in committed { try? manager.removeItem(at: url) } }
        }
        let names: [String]
        if format == .pdf {
            names = ["RedactLeaf-\(identifier).pdf"]
            try writePDF(pages: pages, to: staging.appendingPathComponent(names[0]))
        } else {
            names = pages.enumerated().map { index, _ in
                // Source filenames can themselves disclose personal information.
                "RedactLeaf-page-\(index + 1)-\(identifier).\(format.rawValue)"
            }
            for (index, page) in pages.enumerated() {
                try Task.checkCancellation()
                try autoreleasepool {
                    let rendered = try RasterSanitizer.render(page)
                    try writeImage(rendered, format: format, to: staging.appendingPathComponent(names[index]))
                }
            }
        }
        try Task.checkCancellation()
        do {
            for name in names {
                try Task.checkCancellation()
                let destination = directory.appendingPathComponent(name)
                // FileManager move rejects existing files. Never use replacingItem or overwrite.
                try manager.moveItem(at: staging.appendingPathComponent(name), to: destination)
                committed.append(destination)
            }
            try Task.checkCancellation()
        } catch is CancellationError { throw CancellationError() }
        catch { throw SanitizerError.exportFailed }
        completed = true
        return committed
    }

    private static func writeImage(_ image: CGImage, format: ExportFormat, to url: URL) throws {
        let type = format == .png ? UTType.png.identifier : UTType.jpeg.identifier
        let sink = try ExportSink(url: url)
        guard let consumer = sink.makeConsumer(),
              let destination = CGImageDestinationCreateWithDataConsumer(consumer, type as CFString, 1, nil) else {
            throw SanitizerError.exportFailed
        }
        // Do not attach source dictionaries, EXIF, GPS, comments, thumbnails or names.
        var properties: [CFString: Any] = [:]
        if format == .jpeg { properties[kCGImageDestinationLossyCompressionQuality] = 0.95 }
        CGImageDestinationAddImageAndMetadata(destination, image, nil, properties as CFDictionary)
        let finalized = CGImageDestinationFinalize(destination)
        try sink.finish()
        guard finalized else { throw SanitizerError.exportFailed }
    }

    private static func writePDF(pages: [RasterPage], to url: URL) throws {
        let sink = try ExportSink(url: url)
        guard let consumer = sink.makeConsumer() else { throw SanitizerError.exportFailed }
        var defaultBox = CGRect(x: 0, y: 0, width: Double(pages[0].image.width) / 2,
                                height: Double(pages[0].image.height) / 2)
        guard let pdf = CGContext(consumer: consumer, mediaBox: &defaultBox,
                                  [kCGPDFContextCreator: "RedactLeaf"] as CFDictionary) else {
            throw SanitizerError.exportFailed
        }
        for page in pages {
            try Task.checkCancellation()
            try autoreleasepool {
                let image = try RasterSanitizer.render(page)
                var bounds = CGRect(x: 0, y: 0, width: Double(image.width) / 2,
                                    height: Double(image.height) / 2)
                let data = Data(bytes: &bounds, count: MemoryLayout<CGRect>.size)
                pdf.beginPDFPage([kCGPDFContextMediaBox: data] as CFDictionary)
                pdf.draw(image, in: bounds)
                pdf.endPDFPage()
                try sink.check()
            }
        }
        pdf.closePDF()
        try sink.finish()
    }
}

/// CoreGraphics provides no throwing PDF writer. This consumer records short writes,
/// disk-full errors and output bounds, which are checked before an export can commit.
private final class ExportSink {
    private var descriptor: Int32
    private var failed = false
    private var byteCount = 0

    init(url: URL) throws {
        descriptor = Darwin.open(url.path, O_WRONLY | O_CREAT | O_EXCL, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw SanitizerError.exportFailed }
    }

    deinit { if descriptor >= 0 { Darwin.close(descriptor) } }

    func makeConsumer() -> CGDataConsumer? {
        var callbacks = CGDataConsumerCallbacks(putBytes: { info, buffer, count in
            guard let info else { return 0 }
            return Unmanaged<ExportSink>.fromOpaque(info).takeUnretainedValue().write(buffer, count: count)
        }, releaseConsumer: { info in
            if let info { Unmanaged<ExportSink>.fromOpaque(info).release() }
        })
        let info = Unmanaged.passRetained(self).toOpaque()
        guard let consumer = CGDataConsumer(info: info, cbks: &callbacks) else {
            Unmanaged<ExportSink>.fromOpaque(info).release()
            return nil
        }
        return consumer
    }

    private func write(_ buffer: UnsafeRawPointer, count: Int) -> Int {
        guard !failed, descriptor >= 0, count >= 0,
              count <= RasterLimits.maximumExportBytes - byteCount else {
            failed = true
            return 0
        }
        var offset = 0
        while offset < count {
            let written = Darwin.write(descriptor, buffer.advanced(by: offset), count - offset)
            if written < 0 && errno == EINTR { continue }
            guard written > 0 else { failed = true; return offset }
            offset += written
        }
        byteCount += offset
        return offset
    }

    func check() throws {
        guard !failed else { throw SanitizerError.exportFailed }
    }

    func finish() throws {
        guard descriptor >= 0 else { throw SanitizerError.exportFailed }
        let syncResult = Darwin.fsync(descriptor)
        let closeResult = Darwin.close(descriptor)
        descriptor = -1
        guard !failed, syncResult == 0, closeResult == 0, byteCount > 0 else {
            throw SanitizerError.exportFailed
        }
    }
}

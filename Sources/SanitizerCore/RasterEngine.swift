import Foundation
import CoreGraphics
import ImageIO
import PDFKit
import UniformTypeIdentifiers

enum RasterCanvas {
    static func make(width: Int, height: Int) throws -> CGContext {
        guard width > 0, height > 0,
              width <= RasterLimits.maximumDimension, height <= RasterLimits.maximumDimension,
              width * height <= RasterLimits.maximumPagePixels else {
            throw SanitizerError.pixelLimitExceeded
        }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: width, height: height,
                                      bitsPerComponent: 8, bytesPerRow: width * 4,
                                      space: space,
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue |
                                          CGBitmapInfo.byteOrder32Big.rawValue) else {
            throw SanitizerError.renderingFailed
        }
        context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return context
    }

    static func image(from context: CGContext) throws -> CGImage {
        guard let image = context.makeImage() else { throw SanitizerError.renderingFailed }
        return image
    }
}

public enum RasterImporter {
    /// Inputs are never changed. The returned pages contain only opaque upright pixels.
    public static func load(url: URL) throws -> [RasterPage] {
        try Task.checkCancellation()
        guard url.isFileURL else { throw SanitizerError.invalidInput }
        let values: URLResourceValues
        do { values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey]) }
        catch { throw SanitizerError.invalidInput }
        guard values.isRegularFile == true, let bytes = values.fileSize, bytes > 0 else {
            throw SanitizerError.invalidInput
        }
        guard bytes <= RasterLimits.maximumInputBytes else { throw SanitizerError.inputTooLarge }
        let handle: FileHandle
        do { handle = try FileHandle(forReadingFrom: url) }
        catch { throw SanitizerError.invalidInput }
        let prefix = (try? handle.read(upToCount: 1_024)) ?? Data()
        try? handle.close()
        // Image metadata can contain a PDF marker (or the filename can be
        // misleading). Prefer ImageIO's recognized container over either hint.
        if let source = CGImageSourceCreateWithURL(url as CFURL,
                [kCGImageSourceShouldCache: false] as CFDictionary),
           let type = CGImageSourceGetType(source),
           UTType(type as String)?.conforms(to: .image) == true {
            return try loadImage(url, source: source)
        }
        let looksLikePDF = prefix.range(of: Data("%PDF-".utf8)) != nil
        if looksLikePDF || url.pathExtension.lowercased() == "pdf" {
            return try loadPDF(url)
        }
        throw SanitizerError.unsupportedFile
    }

    private static func loadPDF(_ url: URL) throws -> [RasterPage] {
        guard let document = PDFDocument(url: url) else { throw SanitizerError.unsupportedFile }
        guard !document.isLocked else { throw SanitizerError.lockedPDF }
        guard document.pageCount > 0 else { throw SanitizerError.emptyDocument }
        guard document.pageCount <= RasterLimits.maximumPages else { throw SanitizerError.tooManyPages }
        var result: [RasterPage] = []
        var totalPixels = 0
        for number in 1...document.pageCount {
            try Task.checkCancellation()
            let raster: RasterPage = try autoreleasepool {
                guard let displayPage = document.page(at: number - 1),
                      let page = displayPage.pageRef else { throw SanitizerError.invalidPage }
                // CoreGraphics' drawing transform clips the requested box to MediaBox.
                let box = page.getBoxRect(.cropBox).intersection(page.getBoxRect(.mediaBox))
                guard !box.isNull, !box.isInfinite,
                      [box.origin.x, box.origin.y, box.width, box.height].allSatisfy({ $0.isFinite }),
                      box.width > 0, box.height > 0 else { throw SanitizerError.invalidPage }
                let rotation = ((page.rotationAngle % 360) + 360) % 360
                guard rotation % 90 == 0 else { throw SanitizerError.invalidPage }
                let viewWidth = rotation % 180 == 0 ? box.width : box.height
                let viewHeight = rotation % 180 == 0 ? box.height : box.width
                let scale = min(RasterLimits.pdfPixelsPerPoint,
                                Double(RasterLimits.maximumDimension) / max(viewWidth, viewHeight))
                let width = max(1, Int(ceil(viewWidth * scale)))
                let height = max(1, Int(ceil(viewHeight * scale)))
                guard totalPixels + width * height <= RasterLimits.maximumTotalPixels else {
                    throw SanitizerError.pixelLimitExceeded
                }
                let context = try RasterCanvas.make(width: width, height: height)
                let target = CGRect(x: 0, y: 0, width: width, height: height)
                context.clip(to: target)
                // PDFKit preserves visible annotations; CG drawPDFPage omits them,
                // which could reveal content under an existing opaque annotation.
                // Its draw method handles rotation and crop origin itself.
                context.scaleBy(x: scale, y: scale)
                displayPage.setBounds(box, for: .cropBox)
                displayPage.displaysAnnotations = true
                displayPage.draw(with: .cropBox, to: context)
                totalPixels += width * height
                return RasterPage(image: try RasterCanvas.image(from: context),
                                  sourceName: url.deletingPathExtension().lastPathComponent,
                                  sourcePageNumber: number)
            }
            result.append(raster)
        }
        try Task.checkCancellation()
        return result
    }

    private static func loadImage(_ url: URL, source: CGImageSource) throws -> [RasterPage] {
        guard CGImageSourceGetCount(source) > 0,
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.doubleValue,
              let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.doubleValue else {
            throw SanitizerError.unsupportedFile
        }
        guard width.isFinite, height.isFinite, width > 0, height > 0,
              width * height <= Double(RasterLimits.maximumSourceImagePixels) else {
            throw SanitizerError.pixelLimitExceeded
        }
        // A single, well-defined still frame is required: do not silently discard image pages.
        guard CGImageSourceGetCount(source) == 1 else { throw SanitizerError.unsupportedFile }
        try Task.checkCancellation()
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: RasterLimits.maximumDimension,
            kCGImageSourceShouldCacheImmediately: true
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            throw SanitizerError.renderingFailed
        }
        let context = try RasterCanvas.make(width: thumbnail.width, height: thumbnail.height)
        context.draw(thumbnail, in: CGRect(x: 0, y: 0, width: thumbnail.width, height: thumbnail.height))
        try Task.checkCancellation()
        return [RasterPage(image: try RasterCanvas.image(from: context),
                           sourceName: url.deletingPathExtension().lastPathComponent,
                           sourcePageNumber: 1)]
    }
}

public enum RasterSanitizer {
    /// The same raster is used for preview and export. Invalid masks fail the entire operation.
    public static func render(_ page: RasterPage) throws -> CGImage {
        try Task.checkCancellation()
        let rectangles = try page.redactions.map {
            try $0.rect.pixelRect(imageWidth: page.image.width, imageHeight: page.image.height)
        }
        let context = try RasterCanvas.make(width: page.image.width, height: page.image.height)
        context.interpolationQuality = .none
        context.draw(page.image, in: CGRect(x: 0, y: 0, width: page.image.width, height: page.image.height))
        context.setShouldAntialias(false)
        context.setFillColor(red: 0, green: 0, blue: 0, alpha: 1)
        for rect in rectangles { context.fill(rect) }
        try Task.checkCancellation()
        return try RasterCanvas.image(from: context)
    }
}

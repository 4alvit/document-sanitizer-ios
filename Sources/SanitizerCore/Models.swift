import Foundation
import CoreGraphics

/// Coordinates are fractions of the visually upright raster, starting at its top-left.
public struct NormalizedRect: Codable, Hashable, Sendable {
    public var x: Double
    public var y: Double
    public var width: Double
    public var height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }

    /// Strict normalized geometry shared by storage, application and rendering.
    /// Invalid values are rejected rather than clamped or silently dropped.
    public var isValid: Bool {
        [x, y, width, height].allSatisfy { $0.isFinite } &&
        x >= 0 && y >= 0 && width > 0 && height > 0 &&
        x <= 1 && y <= 1 && width <= 1 && height <= 1 &&
        x + width > x && y + height > y &&
        x + width <= 1 && y + height <= 1
    }

    /// Round outwards so even a subpixel selection hides the entire touched pixel.
    func pixelRect(imageWidth: Int, imageHeight: Int) throws -> CGRect {
        guard isValid else { throw SanitizerError.invalidRedaction }
        let left = max(0, floor(x * Double(imageWidth)))
        let right = min(Double(imageWidth), ceil((x + width) * Double(imageWidth)))
        let top = max(0, floor(y * Double(imageHeight)))
        let bottom = min(Double(imageHeight), ceil((y + height) * Double(imageHeight)))
        guard right > left, bottom > top else { throw SanitizerError.invalidRedaction }
        return CGRect(x: left, y: Double(imageHeight) - bottom,
                      width: right - left, height: bottom - top)
    }
}

public struct Redaction: Identifiable, Codable, Hashable, Sendable {
    public let id: UUID
    public var rect: NormalizedRect

    public init(id: UUID = UUID(), rect: NormalizedRect) {
        self.id = id
        self.rect = rect
    }
}

public struct RasterPage: Identifiable {
    public let id: UUID
    public let image: CGImage
    public var sourceName: String
    public let sourcePageNumber: Int
    public var redactions: [Redaction]

    public init(image: CGImage, sourceName: String, sourcePageNumber: Int) {
        self.id = UUID()
        self.image = image
        self.sourceName = sourceName
        self.sourcePageNumber = sourcePageNumber
        self.redactions = []
    }
}

public enum ExportFormat: String, CaseIterable, Sendable {
    case pdf, png, jpeg
}

public struct OCRMatch: Identifiable, Sendable {
    public let id: UUID
    public let text: String
    public let rect: NormalizedRect

    public init(id: UUID = UUID(), text: String, rect: NormalizedRect) {
        self.id = id
        self.text = text
        self.rect = rect
    }
}

public enum SanitizerError: Error, LocalizedError, Equatable {
    case invalidInput, inputTooLarge, unsupportedFile, lockedPDF, tooManyPages
    case pixelLimitExceeded, invalidPage, renderingFailed, invalidRedaction
    case emptyDocument, exportFailed

    public var errorDescription: String? {
        switch self {
        case .invalidInput: return CoreL10n.text("The selected file could not be read. Try a local copy.")
        case .inputTooLarge: return CoreL10n.text("This file exceeds the 50 MiB import limit.")
        case .unsupportedFile: return CoreL10n.text("This file is not a supported image or PDF.")
        case .lockedPDF: return CoreL10n.text("Unlock this PDF before importing it.")
        case .tooManyPages: return CoreL10n.text("A package can contain at most 30 pages.")
        case .pixelLimitExceeded: return CoreL10n.text("This package is too large to process safely. Import fewer pages.")
        case .invalidPage: return CoreL10n.text("A page has invalid dimensions and could not be safely imported.")
        case .renderingFailed: return CoreL10n.text("A page could not be rendered. No export was completed.")
        case .invalidRedaction: return CoreL10n.text("A redaction has invalid coordinates. Draw it again before exporting.")
        case .emptyDocument: return CoreL10n.text("Import at least one page before exporting.")
        case .exportFailed: return CoreL10n.text("The export could not be saved. Check available space and try again.")
        }
    }
}

public enum RasterLimits {
    public static let maximumInputBytes = 50 * 1_024 * 1_024
    public static let maximumPages = 30
    public static let maximumPagePixels = 6_000_000
    public static let maximumTotalPixels = 24_000_000
    public static let maximumDimension = 2_400
    public static let pdfPixelsPerPoint: Double = 2 // 144 dpi
    static let maximumSourceImagePixels = 100_000_000
    static let maximumExportBytes = 256 * 1_024 * 1_024
}

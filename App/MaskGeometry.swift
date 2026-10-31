import CoreGraphics
import SanitizerCore

/// Preview and masks share the same aspect-fit frame in top-left view coordinates.
enum MaskGeometry {
    static func fittedFrame(imageSize: CGSize, in size: CGSize) -> CGRect {
        guard imageSize.width > 0, imageSize.height > 0, size.width > 0, size.height > 0 else { return .zero }
        let scale = min(size.width / imageSize.width, size.height / imageSize.height)
        let width = imageSize.width * scale, height = imageSize.height * scale
        return CGRect(x: (size.width - width) / 2, y: (size.height - height) / 2, width: width, height: height)
    }

    static func normalizedRect(start: CGPoint, end: CGPoint, in frame: CGRect) -> NormalizedRect? {
        guard frame.width > 0, frame.height > 0, frame.contains(start), start.x.isFinite, start.y.isFinite, end.x.isFinite, end.y.isFinite else { return nil }
        let end = CGPoint(x: min(max(end.x, frame.minX), frame.maxX), y: min(max(end.y, frame.minY), frame.maxY))
        let width = abs(start.x - end.x), height = abs(start.y - end.y)
        guard width >= 3, height >= 3 else { return nil }
        let x = min(max((min(start.x, end.x) - frame.minX) / frame.width, 0), 1)
        let y = min(max((min(start.y, end.y) - frame.minY) / frame.height, 0), 1)
        // Clamp after division too: binary rounding can otherwise put x + width above 1.
        return NormalizedRect(x: x, y: y, width: min(width / frame.width, 1 - x), height: min(height / frame.height, 1 - y))
    }
}
